#!/usr/bin/env python3
"""Offline regression tests for PanelComfort (no TV / HA instance required)."""
from __future__ import annotations

import ast
import json
import gzip
import io
import os
import pathlib
import re
import subprocess
import tarfile
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

BASE = pathlib.Path(__file__).resolve().parents[1]
APP = BASE / "src/com.webosbrew.panelcomfort"
SCRIPTS = APP / "scripts"
HA = BASE / "custom_components/panelcomfort"
VERSION = "0.3.20"


def run(cmd, *, env=None, cwd=None, input_text=None, check=True):
    result = subprocess.run(
        cmd, text=True, input=input_text, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env, cwd=cwd, timeout=20,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"Command failed ({result.returncode}): {cmd}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def write(path: pathlib.Path, content: str, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if executable:
        path.chmod(0o755)


def rebase_script(source: pathlib.Path, root: pathlib.Path, dest: pathlib.Path | None = None) -> pathlib.Path:
    dest = dest or root / source.name
    content = source.read_text().replace("/var/lib/webosbrew/panelcomfort", str(root))
    write(dest, content, executable=True)
    return dest


class ProjectStaticTests(unittest.TestCase):
    def test_all_javascript_parses_on_node(self):
        for file in (APP / "app.js", APP / "web-ui/panelcomfort.js"):
            with self.subTest(file=file.name):
                run(["node", "--check", str(file)])

    def test_posix_shell_scripts_parse(self):
        files = list(SCRIPTS.glob("*.sh")) + list(SCRIPTS.glob("*.cgi")) + [BASE / "build-ipk.sh"]
        for file in files:
            with self.subTest(file=file.name):
                run(["sh", "-n", str(file)])

    def test_json_and_python_sources_are_valid(self):
        for file in BASE.rglob("*.json"):
            with self.subTest(file=str(file.relative_to(BASE))):
                json.loads(file.read_text())
        for file in HA.glob("*.py"):
            with self.subTest(file=file.name):
                ast.parse(file.read_text(), filename=str(file))

    def test_html_ids_and_click_bindings(self):
        html = (APP / "index.html").read_text()
        js = (APP / "app.js").read_text()
        ids = re.findall(r'\bid="([^"]+)"', html)
        duplicates = sorted({x for x in ids if ids.count(x) > 1})
        self.assertEqual([], duplicates, f"duplicate HTML ids: {duplicates}")
        idset = set(ids)
        refs = set(re.findall(r"\$\('([^']+)'\)", js))
        # This node is created dynamically before use in testHaEndpoint.
        self.assertEqual({"haEndpointTestDetails"}, refs - idset)
        self.assertIn("createElement('pre')", js)
        click_ids = re.findall(r"bindClick\('([^']+)'", js)
        self.assertTrue(click_ids)
        for node in click_ids:
            self.assertIn(node, idset, f"button binding references missing id {node}")
        tabs = set(re.findall(r'data-tab="([^"]+)"', html))
        panels = set(re.findall(r'data-panel="([^"]+)"', html))
        self.assertEqual(tabs, panels, "each tab must have exactly a matching panel")
        self.assertGreaterEqual(len(tabs), 7)

    def test_legacy_webkit_compatible_syntax(self):
        for file in (APP / "app.js", APP / "web-ui/panelcomfort.js"):
            source = file.read_text()
            for pattern, name in [
                (r"\?\?", "nullish coalescing"),
                (r"\?\.", "optional chaining"),
                (r"\.replaceAll\s*\(", "replaceAll"),
                (r"\.flatMap\s*\(", "flatMap"),
                (r"\.at\s*\(", "Array/String.at"),
            ]:
                self.assertIsNone(re.search(pattern, source), f"{file.name} uses unsupported {name}")

    def test_versions_are_consistent(self):
        appinfo = json.loads((APP / "appinfo.json").read_text())
        self.assertEqual(VERSION, appinfo["version"])
        self.assertIn("APP_VERSION='" + VERSION + "'", (APP / "app.js").read_text())
        self.assertIn("VERSION=" + VERSION, (BASE / "build-ipk.sh").read_text())
        for file in (SCRIPTS / "install-root.sh", SCRIPTS / "update-root.sh", SCRIPTS / "panelcomfort-health.cgi", SCRIPTS / "panelcomfort-discovery.cgi", SCRIPTS / "ssdp-broadcast.sh"):
            self.assertIn(VERSION, file.read_text(), f"stale version in {file.name}")

    def test_dashboard_is_opt_in_for_fresh_install(self):
        self.assertRegex((SCRIPTS / "default.env").read_text(), r"(?m)^WEB_UI_ENABLED=0$")
        self.assertRegex((SCRIPTS / "install-root.sh").read_text(), r"(?m)^ensure_line WEB_UI_ENABLED 0$")
        self.assertRegex((SCRIPTS / "update-root.sh").read_text(), r"(?m)^ensure_line WEB_UI_ENABLED 0$")
        self.assertIn("webEnabled=$('webUiEnabled').checked", (APP / "app.js").read_text())

    def test_picture_watcher_queries_fields_it_reads(self):
        source = (SCRIPTS / "picture-watch.sh").read_text()
        query = re.search(r"^QUERY='([^']+)'$", source, re.M).group(1)
        obj = json.loads(query)
        for key in ("backlight", "eyeComfortMode", "input", "pictureMode"):
            self.assertIn(key, obj["keys"])

    def test_ssdp_identity_is_uuid_shaped(self):
        source = (SCRIPTS / "ha-server.sh").read_text()
        match = re.search(r"make_udn\(\)\s*\{(.*?)\n  \}", source, re.S)
        self.assertIsNotNone(match, "missing stable SSDP UUID formatter")
        func = "make_udn() {" + match.group(1) + "\n} ; make_udn 0123456789abcdef01234567"
        output = run(["sh", "-c", func]).stdout.strip()
        self.assertRegex(output, r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$")

    def test_duration_helpers_and_preview_curves(self):
        source = (APP / "app.js").read_text()
        helpers = []
        for name, pattern in [
            ("parseDuration", r"function parseDuration\(raw,allowNegative=false\)\{.*?\n  \}"),
            ("formatDuration", r"function formatDuration\(minutes,allowNegative=false\)\{.*?\n  \}"),
            ("curveProgress", r"function curveProgress\(t,curve\)\{[^\n]*\}"),
        ]:
            match = re.search(pattern, source, re.S)
            self.assertIsNotNone(match, f"could not extract {name}")
            helpers.append(match.group(0).rstrip())
        program = "\n".join(helpers) + "\n" + '''console.log(JSON.stringify({
 good:parseDuration('1:05'), zero:parseDuration('0:00'), max:parseDuration('12:00'),
 tooLong:parseDuration('12:01'), badMinutes:parseDuration('1:60'),
 negativeAllowed:parseDuration('-1:05',true), negativeDenied:parseDuration('-1:05'),
 formatted:formatDuration(-65,true),
 curves:['linear','easein','easeout','smooth','smootherstep','twilight','rolloff-soft','rolloff','rolloff-strong','exponential','gamma-late','gamma-early'].map(c=>[c,[0,.25,.5,.75,1].map(x=>curveProgress(x,c))])
}));'''
        payload = json.loads(run(["node", "-e", program]).stdout)
        self.assertEqual(65, payload["good"])
        self.assertEqual(0, payload["zero"])
        self.assertEqual(720, payload["max"])
        self.assertIsNone(payload["tooLong"])
        self.assertIsNone(payload["badMinutes"])
        self.assertEqual(-65, payload["negativeAllowed"])
        self.assertIsNone(payload["negativeDenied"])
        self.assertEqual("-1:05", payload["formatted"])
        for name, values in payload["curves"]:
            with self.subTest(curve=name):
                self.assertEqual(0, values[0])
                self.assertEqual(1, values[-1])
                self.assertEqual(values, sorted(values))

    def test_ipk_builder_creates_valid_non_epoch_archive(self):
        with tempfile.TemporaryDirectory(prefix="panelcomfort-build-") as td:
            output_name = "panelcomfort-test.ipk"  # relative path exercises path normalization
            run(["sh", str(BASE / "build-ipk.sh"), output_name], cwd=td)
            ipk = pathlib.Path(td) / output_name
            self.assertTrue(ipk.is_file())
            archive = ipk.read_bytes()
            self.assertTrue(archive.startswith(b"!<arch>\n"))
            members = {}
            position = 8
            while position < len(archive):
                header = archive[position:position + 60]
                self.assertEqual(60, len(header), "truncated ar header")
                self.assertEqual(b"`\n", header[58:60], "invalid ar member trailer")
                name = header[:16].decode("ascii").strip().rstrip("/")
                timestamp = int(header[16:28].decode("ascii").strip())
                owner = int(header[28:34].decode("ascii").strip())
                group = int(header[34:40].decode("ascii").strip())
                size = int(header[48:58].decode("ascii").strip())
                self.assertGreater(timestamp, 0, f"{name} has an epoch timestamp")
                self.assertEqual((0, 1001), (owner, group))
                start = position + 60
                members[name] = archive[start:start + size]
                self.assertEqual(size, len(members[name]), f"truncated {name}")
                position = start + size + (size % 2)
            self.assertEqual({"debian-binary", "control.tar.gz", "data.tar.gz"}, set(members))
            with tarfile.open(fileobj=io.BytesIO(gzip.decompress(members["data.tar.gz"])), mode="r:") as payload:
                entries = {member.name: member for member in payload.getmembers()}
            self.assertIn("./usr/palm/applications/com.webosbrew.panelcomfort/app.js", entries)
            self.assertIn("./usr/palm/applications/com.webosbrew.panelcomfort/scripts/daemon.sh", entries)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="panelcomfort-test-")
        self.root = pathlib.Path(self.tmp.name) / "root"
        self.root.mkdir()
        self.bin = pathlib.Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        write(self.bin / "date", r'''#!/bin/sh
case "${1:-}" in
  +%H:%M) echo "${PC_FAKE_TIME:-20:00}" ;;
  +%j) echo 120 ;;
  +%z) echo +0200 ;;
  +%s) echo "${PC_FAKE_EPOCH:-1770000000}" ;;
  *) echo '2026-04-30 20:00:00' ;;
esac
''', executable=True)
        self.daemon = rebase_script(SCRIPTS / "daemon.sh", self.root)
        self.config = {
            "ENABLED": "1", "DIM_MODE": "fixed", "DIM_START": "19:00", "DIM_DURATION": "120",
            "UP_MODE": "fixed", "UNDIM_START": "06:30", "UNDIM_DURATION": "45",
            "MIN_BRIGHTNESS": "18", "MAX_BRIGHTNESS": "80", "FADE_METHOD": "duration", "FADE_CURVE": "linear",
            "EYE_ENABLED": "1", "EYE_TIMING": "linked", "EYE_START": "21:30", "EYE_END": "06:30",
            "EYE_START_OFFSET": "15", "EYE_END_OFFSET": "0", "SUNSET_LAT": "", "SUNSET_LON": "",
            "SUNSET_OFFSET": "-20", "SUNRISE_OFFSET": "0", "HYPERHDR_ENABLED": "1",
            "HYPERHDR_MIN_BRIGHTNESS": "12", "HYPERHDR_MAX_BRIGHTNESS": "60", "HA_BRIGHTNESS_OFFSET": "0",
        }
        self.save_config()

    def tearDown(self):
        self.tmp.cleanup()

    def save_config(self):
        write(self.root / "config.env", "".join(f"{k}={v}\n" for k, v in self.config.items()))

    def calculate(self, clock, **overrides):
        self.config.update(overrides)
        self.save_config()
        env = os.environ.copy()
        env.update({"PATH": str(self.bin) + os.pathsep + env.get("PATH", ""), "PC_FAKE_TIME": clock, "TZ": "Europe/Amsterdam"})
        return run(["sh", str(self.daemon), "--calculate"], env=env).stdout.strip().split()

    def test_evening_fade_is_not_restarted_when_tv_starts_late(self):
        # 19:00 -> 21:00. At 20:00 the TV is exactly halfway into the schedule.
        brightness, eye, phase, hdr = self.calculate("20:00")
        self.assertEqual(["49", "on", "evening-fade", "36"], [brightness, eye, phase, hdr])

    def test_fade_end_night_morning_and_day(self):
        self.assertEqual(["18", "on", "night", "12"], self.calculate("21:00"))
        self.assertEqual(["48", "off", "morning-fade", "35"], self.calculate("06:52"))
        self.assertEqual(["80", "off", "day", "60"], self.calculate("08:00"))

    def test_movie_override_forces_day_target_and_eye_comfort_off(self):
        (self.root / "override.flag").touch()
        self.assertEqual(["80", "off", "movie-override", "60"], self.calculate("02:00"))

    def test_each_fade_curve_is_bounded_and_monotonic_during_sunset(self):
        curves = ["linear", "easein", "easeout", "smooth", "smootherstep", "twilight", "rolloff-soft", "rolloff", "rolloff-strong", "exponential", "gamma-late", "gamma-early"]
        for curve in curves:
            values = []
            for clock in ("19:00", "19:15", "19:30", "19:45", "20:00", "20:15", "20:30", "20:45"):
                row = self.calculate(clock, FADE_CURVE=curve)
                value = int(row[0]); self.assertGreaterEqual(value, 18); self.assertLessEqual(value, 80)
                values.append(value)
            with self.subTest(curve=curve):
                self.assertEqual(values, sorted(values, reverse=True), f"brightness should fall monotonically for {curve}: {values}")

    def test_wraps_midnight_correctly(self):
        self.config.update({"DIM_START": "23:00", "DIM_DURATION": "120", "UNDIM_START": "06:30", "UNDIM_DURATION": "45", "FADE_CURVE": "linear"})
        self.assertEqual(["49", "on", "evening-fade", "36"], self.calculate("00:00"))

    def test_stale_ambient_sample_falls_back_to_clock(self):
        epoch = 1770000000
        row = self.calculate("20:00", FADE_METHOD="ambient", HA_AMBIENT_LUX="800", HA_AMBIENT_LUX_UPDATED=str(epoch-240))
        self.assertEqual("evening-fade", row[2])

    def test_recent_ambient_sample_drives_ambient_phase(self):
        epoch = 1770000000
        row = self.calculate("20:00", FADE_METHOD="ambient", HA_AMBIENT_LUX="100", HA_AMBIENT_LUX_UPDATED=str(epoch-30))
        self.assertEqual("ambient-response", row[2])
        self.assertGreaterEqual(int(row[0]), 18); self.assertLessEqual(int(row[0]), 80)

    def test_solar_mode_outputs_bounded_target(self):
        row = self.calculate("12:00", FADE_METHOD="solar", SUNSET_LAT="52.7000", SUNSET_LON="5.2000")
        self.assertIn(row[2], ("day", "solar-fade", "night"))
        self.assertGreaterEqual(int(row[0]), 18); self.assertLessEqual(int(row[0]), 80)


class CgiAndHyperHdrTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="panelcomfort-cgi-")
        self.root = pathlib.Path(self.tmp.name) / "root"
        self.root.mkdir()
        write(self.root / "service.log", "")
        write(self.root / "apply-queue.sh", '#!/bin/sh\n: > "$(dirname "$0")/apply-queue.pending"\n', executable=True)
        write(self.root / "daemon.sh", '''#!/bin/sh
if [ "${1:-}" = "--calculate" ]; then echo "39 off night 20"; else echo applied >> "$(dirname "$0")/apply.log"; fi
''', executable=True)

    def tearDown(self):
        self.tmp.cleanup()

    def cgi(self, name, query, config, remote="192.168.0.22", body=None, extra_env=None):
        write(self.root / "config.env", config)
        script = rebase_script(SCRIPTS / name, self.root)
        env = os.environ.copy()
        env.update({"QUERY_STRING": query, "REMOTE_ADDR": remote, "REQUEST_METHOD": "GET", "CONTENT_LENGTH": "0"})
        if extra_env: env.update(extra_env)
        if body is not None:
            env["REQUEST_METHOD"] = "POST"; env["CONTENT_LENGTH"] = str(len(body))
        return run(["sh", str(script)], env=env, input_text=body, check=False)

    def test_webhook_updates_movie_flag_and_lux(self):
        conf = "WEBHOOK_ENABLED=1\nWEBHOOK_TOKEN=0123abcd\nHA_DEVICE_ID=0123456789abcdef01234567\nENABLED=1\nEYE_ENABLED=1\nHA_API_PORT=8765\n"
        res = self.cgi("panelcomfort.cgi", "movie=on", conf)
        self.assertIn('"ok":true', res.stdout)
        self.assertTrue((self.root / "override.flag").exists())
        res = self.cgi("panelcomfort.cgi", "ambient_lux=125", conf)
        self.assertIn('"ok":true', res.stdout)
        newcfg = (self.root / "config.env").read_text()
        self.assertRegex(newcfg, r"(?m)^HA_AMBIENT_LUX=125$")
        self.assertRegex(newcfg, r"(?m)^HA_AMBIENT_LUX_UPDATED=\d+$")
        self.assertEqual(0o600, (self.root / "config.env").stat().st_mode & 0o777)

    def test_webhook_rejects_invalid_lux_and_public_client(self):
        conf = "WEBHOOK_ENABLED=1\nWEBHOOK_TOKEN=0123abcd\nHA_DEVICE_ID=0123456789abcdef01234567\nENABLED=1\n"
        res = self.cgi("panelcomfort.cgi", "ambient_lux=200001", conf)
        self.assertIn("Status: 400 Bad Request", res.stdout)
        res = self.cgi("panelcomfort.cgi", "movie=on", conf, remote="8.8.8.8")
        self.assertIn("Status: 403 Forbidden", res.stdout)
        self.assertFalse((self.root / "override.flag").exists())

    def test_ha_api_status_and_validates_offset(self):
        conf = "HA_API_ENABLED=1\nHA_DEVICE_ID=0123456789abcdef01234567\nENABLED=1\nEYE_ENABLED=1\nHYPERHDR_ENABLED=1\nFADE_METHOD=duration\nHA_BRIGHTNESS_OFFSET=0\n"
        res = self.cgi("panelcomfort-ha.cgi", "action=status", conf)
        self.assertIn('"domain"', res.stdout) if '"domain"' in res.stdout else self.assertIn('"ok":true', res.stdout)
        res = self.cgi("panelcomfort-ha.cgi", "brightness_offset=31", conf)
        self.assertIn("Status: 400 Bad Request", res.stdout)
        self.assertNotRegex((self.root / "config.env").read_text(), r"(?m)^HA_BRIGHTNESS_OFFSET=31$")

    def test_discovery_returns_expected_stable_identity(self):
        conf = "HA_API_ENABLED=1\nHA_API_PORT=8765\nHA_DEVICE_ID=0123456789abcdef01234567\n"
        res = self.cgi("panelcomfort-discovery.cgi", "", conf)
        payload_text = re.split(r"\r?\n\r?\n", res.stdout, maxsplit=1)[1]
        payload = json.loads(payload_text)
        self.assertTrue(payload["ok"])
        self.assertEqual("panelcomfort", payload["domain"])
        self.assertEqual("0123456789abcdef01234567", payload["device_id"])

    def test_dashboard_is_off_by_default_and_same_origin_guarded(self):
        conf = "WEB_UI_ENABLED=0\nHA_API_ENABLED=0\n"
        res = self.cgi("panelcomfort-web.cgi", "action=status", conf)
        self.assertIn("Status: 404 Not Found", res.stdout)
        conf = "WEB_UI_ENABLED=1\nHA_API_ENABLED=0\nENABLED=1\nEYE_ENABLED=1\n"
        res = self.cgi("panelcomfort-web.cgi", "", conf, body="action=movie_on", extra_env={"HTTP_ORIGIN":"http://attacker.invalid", "HTTP_HOST":"192.0.2.186:8765"})
        self.assertIn("Status: 403 Forbidden", res.stdout)
        self.assertFalse((self.root / "override.flag").exists())

    def test_dashboard_save_preserves_eye_timing_and_secures_config(self):
        conf = "WEB_UI_ENABLED=1\nHA_API_ENABLED=0\nENABLED=1\nEYE_ENABLED=1\nEYE_TIMING=linked\n"
        body = "action=save&enabled=1&dim_mode=fixed&dim_start=21%3A00&dim_duration=60&up_mode=fixed&undim_start=06%3A30&undim_duration=45&curve=smooth&method=duration&min_brightness=18&max_brightness=80&movie_brightness_enabled=0&movie_brightness=80&eye_enabled=1&eye_mode=dynamic&eye_lux_threshold=50&eye_timing=linked&eye_start=21%3A30&eye_end=06%3A30&eye_start_offset=15&eye_end_offset=0&latitude=&longitude=&sunset_offset=-20&sunrise_offset=0&ambient_lux_min=5&ambient_lux_max=500&lux_stability=10&ambient_brightness_offset=0&hyperhdr_enabled=0&hyperhdr_min_brightness=12&hyperhdr_max_brightness=60&profile_protection=1"
        res = self.cgi("panelcomfort-web.cgi", "", conf, body=body)
        self.assertEqual(0, res.returncode, res.stderr)
        payload_text = re.split(r"\r?\n\r?\n", res.stdout, maxsplit=1)[1]
        payload = json.loads(payload_text)
        self.assertEqual("linked", payload["eye_timing"])
        self.assertRegex((self.root / "config.env").read_text(), r"(?m)^EYE_TIMING=linked$")
        self.assertEqual(0o600, (self.root / "config.env").stat().st_mode & 0o777)
        custom_body = body.replace("eye_timing=linked", "eye_timing=custom")
        custom_res = self.cgi("panelcomfort-web.cgi", "", conf, body=custom_body)
        custom_payload = json.loads(re.split(r"\r?\n\r?\n", custom_res.stdout, maxsplit=1)[1])
        self.assertEqual("custom", custom_payload["eye_timing"])
        self.assertRegex((self.root / "config.env").read_text(), r"(?m)^EYE_TIMING=custom$")
        self.assertEqual(0o600, (self.root / "config.env").stat().st_mode & 0o777)

    def test_hyperhdr_detects_and_applies_both_instances(self):
        bin_dir = pathlib.Path(self.tmp.name) / "bin"; bin_dir.mkdir()
        api_log = pathlib.Path(self.tmp.name) / "api.log"
        write(bin_dir / "curl", r'''#!/bin/sh
body=''; url=''
while [ "$#" -gt 0 ]; do
 case "$1" in --data|--data-binary) body=$2; shift 2;; -H) shift 2;; http://*) url=$1; shift;; *) shift;; esac
done
printf 'BODY=%s\nURL=%s\n' "$body" "$url" >> "$API_LOG"
case "$body" in
  *serverinfo*) echo '{"success":true,"info":{"instances":[{"instance":0,"running":true},{"instance":3,"running":true}]}}' ;;
  *) echo '{"success":true,"tan":0}' ;;
esac
''', executable=True)
        conf = "HYPERHDR_ENABLED=1\nHYPERHDR_HOST=127.0.0.1\nHYPERHDR_PORT=8090\nHYPERHDR_TOKEN=\nHYPERHDR_INSTANCE_IDS=all\n"
        write(self.root / "config.env", conf)
        hdr = rebase_script(SCRIPTS / "hyperhdr.sh", self.root)
        env = os.environ.copy(); env.update({"PATH":str(bin_dir)+os.pathsep+env.get("PATH",""),"API_LOG":str(api_log)})
        tested = run(["sh", str(hdr), "test"], env=env).stdout
        self.assertIn("HYPERHDR_INSTANCE_IDS=0,3", tested)
        applied = run(["sh", str(hdr), "apply", "32"], env=env).stdout
        self.assertIn("HYPERHDR_TARGETED_INSTANCES=0,3", applied)
        lines = api_log.read_text().splitlines()
        urls = [line[4:] for line in lines if line.startswith("URL=")]
        requests = []
        for url in urls:
            requests.extend(json.loads(item) for item in parse_qs(urlparse(url).query).get("request", []))
        switches = [x for x in requests if x.get("command") == "instance"]
        adjustments = [x for x in requests if x.get("command") == "adjustment"]
        self.assertEqual([0, 3], [x["instance"] for x in switches])
        self.assertEqual(["switchTo", "switchTo"], [x["subcommand"] for x in switches])
        self.assertEqual(2, len(adjustments))
        self.assertAlmostEqual(0.32, adjustments[0]["adjustment"]["scaleOutput"])
        self.assertNotIn("instance", adjustments[0])
        self.assertAlmostEqual(0.32, adjustments[1]["adjustment"]["scaleOutput"])
        multi_request_urls = [url for url in urls if "?request=" in url]
        self.assertEqual(2, len(multi_request_urls))
        self.assertTrue(all(len(parse_qs(urlparse(url).query).get("request", [])) == 2 for url in multi_request_urls))

    def test_hyperhdr_all_fails_closed_if_ids_cannot_be_detected(self):
        bin_dir = pathlib.Path(self.tmp.name) / "bin"; bin_dir.mkdir()
        write(bin_dir / "curl", r'''#!/bin/sh
body=''
while [ "$#" -gt 0 ]; do if [ "$1" = --data ]; then body=$2; shift 2; else shift; fi; done
case "$body" in *serverinfo*) echo '{"success":true,"info":{"instances":[]}}';; *) echo '{"success":true}';; esac
''', executable=True)
        write(self.root / "config.env", "HYPERHDR_HOST=127.0.0.1\nHYPERHDR_PORT=8090\nHYPERHDR_INSTANCE_IDS=all\n")
        hdr = rebase_script(SCRIPTS / "hyperhdr.sh", self.root)
        env = os.environ.copy(); env["PATH"] = str(bin_dir)+os.pathsep+env.get("PATH","")
        res = run(["sh", str(hdr), "apply", "30"], env=env, check=False)
        self.assertNotEqual(0, res.returncode)
        self.assertIn("could not read its running instance ids", res.stdout.lower())



if __name__ == "__main__":
    unittest.main(verbosity=2)
