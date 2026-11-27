"""PanelComfort against a simulated TV: one poll per cycle, shared by all entities."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import aiohttp
import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    async_fire_time_changed,
    mock_integration,
)

from custom_components.panelcomfort.const import DOMAIN

HOST, PORT, DEVICE = "192.168.0.50", 8765, "pc-0123456789abcdef"
BASE = f"http://{HOST}:{PORT}/cgi-bin/panelcomfort-ha.cgi"
STATUS = {
    "ok": True, "device_id": DEVICE, "phase": "evening", "backlight": 42,
    "hyperhdr_brightness": 30, "ambient_lux": 120, "screen_apply_status": "applied",
    "movie_override": False, "service_enabled": True, "eye_comfort": "off",
    "eye_comfort_mode": "time", "fade_method": "duration", "backlight_offset": 0,
    "dim_start": "21:30", "eye_lux_threshold": 40, "lux_stability": 10,
    "ambient_lux_min": 5, "ambient_lux_max": 500,
}


@pytest.fixture(autouse=True)
def _offline_ssdp(hass):
    """SSDP is only needed for discovery; a stand-in keeps the tests off the network."""
    mock_integration(hass, MockModule("ssdp"))


def _entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN, version=3, unique_id=DEVICE, title="PanelComfort TV",
        data={"host": HOST, "port": PORT, "device_id": DEVICE, "entity_key": "bedroom"},
        options=options,
    )


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    # Keep tests offline: never sweep the LAN for the TV.
    with patch("custom_components.panelcomfort.coordinator.async_find_device", return_value=None):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _status_calls(aioclient_mock) -> int:
    return sum(1 for _m, url, *_ in aioclient_mock.mock_calls if url.query.get("action") == "status")


async def test_tv_off_creates_unavailable_entities_with_one_request(hass, aioclient_mock):
    aioclient_mock.get(BASE, exc=aiohttp.ClientConnectionError())
    entry = _entry()
    await _setup(hass, entry)
    assert entry.state.name == "LOADED"
    assert hass.states.get("switch.panelcomfort_tv_movie_mode").state == STATE_UNAVAILABLE
    assert _status_calls(aioclient_mock) == 1

    with patch("custom_components.panelcomfort.coordinator.async_find_device", return_value=None):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
        await hass.async_block_till_done()
    # The next cycle is again a single request for every entity together.
    assert _status_calls(aioclient_mock) == 2


async def test_status_fills_every_entity_and_keeps_unique_ids(hass, aioclient_mock):
    aioclient_mock.get(BASE, json=STATUS)
    entry = _entry()
    await _setup(hass, entry)
    assert hass.states.get("sensor.panelcomfort_tv_backlight_target").state == "42"
    assert hass.states.get("switch.panelcomfort_tv_brightness_schedule").state == "on"
    assert hass.states.get("time.panelcomfort_tv_evening_start").state == "21:30:00"
    assert hass.states.get("select.panelcomfort_tv_eye_comfort_mode").state == "Time"
    assert _status_calls(aioclient_mock) == 1

    registry = er.async_get(hass)
    unique_ids = {e.unique_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}
    # Same IDs as releases before the coordinator, so entity IDs and history stay.
    assert {"bedroom_movie_mode", "bedroom_brightness_offset", "bedroom_eye_comfort_active",
            "bedroom_backlight", "bedroom_dim_start", "bedroom_fade_method"} <= unique_ids
    hidden = {e.unique_id for e in er.async_entries_for_config_entry(registry, entry.entry_id) if e.disabled_by}
    assert {"bedroom_sunset_lat", "bedroom_fade_curve", "bedroom_lux_stability"} <= hidden
    assert "bedroom_movie_brightness" not in hidden


async def test_changes_send_the_setting_and_publish_the_confirmed_state(hass, aioclient_mock):
    aioclient_mock.get(BASE, json=STATUS)
    entry = _entry()
    await _setup(hass, entry)
    aioclient_mock.clear_requests()
    aioclient_mock.get(BASE, json={**STATUS, "movie_override": True, "backlight_offset": 5})

    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.panelcomfort_tv_movie_mode"}, blocking=True)
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.panelcomfort_tv_brightness_offset", "value": 5}, blocking=True
    )
    queries = [dict(url.query) for _m, url, *_ in aioclient_mock.mock_calls]
    assert {"movie": "on"} in queries
    assert {"brightness_offset": "5"} in queries
    assert hass.states.get("switch.panelcomfort_tv_movie_mode").state == "on"
    assert hass.states.get("number.panelcomfort_tv_brightness_offset").state == "5"


async def test_unconfirmed_choice_is_reported(hass, aioclient_mock):
    aioclient_mock.get(BASE, json=STATUS)
    await _setup(hass, _entry())
    with pytest.raises(HomeAssistantError, match="did not confirm"):
        await hass.services.async_call(
            "select", "select_option",
            {"entity_id": "select.panelcomfort_tv_eye_comfort_mode", "option": "Dynamic"},
            blocking=True,
        )


async def test_lux_is_forwarded_only_when_the_tv_uses_it(hass, aioclient_mock):
    hass.states.async_set("sensor.room_lux", "250")
    # The TV echoes the lux value it accepted.
    aioclient_mock.get(BASE, json={**STATUS, "fade_method": "ambient", "ambient_lux": 250})
    await _setup(hass, _entry(ambient_lux_entity="sensor.room_lux"))
    lux_queries = [url.query.get("ambient_lux") for _m, url, *_ in aioclient_mock.mock_calls if "ambient_lux" in url.query]
    assert lux_queries == ["250"]

    # A change inside the stability band is not sent again within a minute.
    hass.states.async_set("sensor.room_lux", "255")
    await hass.async_block_till_done()
    assert sum("ambient_lux" in url.query for _m, url, *_ in aioclient_mock.mock_calls) == 1


async def test_no_lux_is_sent_for_time_based_brightness(hass, aioclient_mock):
    hass.states.async_set("sensor.room_lux", "250")
    aioclient_mock.get(BASE, json=STATUS)
    await _setup(hass, _entry(ambient_lux_entity="sensor.room_lux"))
    assert not any("ambient_lux" in url.query for _m, url, *_ in aioclient_mock.mock_calls)


async def test_tv_found_at_a_new_address_after_dhcp_change(hass, aioclient_mock):
    new_host = "192.168.0.77"
    aioclient_mock.get(BASE, exc=aiohttp.ClientConnectionError())
    aioclient_mock.get(f"http://{new_host}:{PORT}/cgi-bin/panelcomfort-ha.cgi", json=STATUS)
    entry = _entry()
    entry.add_to_hass(hass)
    found = {"host": new_host, "port": PORT, "device_id": DEVICE}
    with patch("custom_components.panelcomfort.coordinator.async_find_device", return_value=found):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.data["host"] == new_host
    assert hass.states.get("sensor.panelcomfort_tv_backlight_target").state == "42"


async def test_lux_is_resent_at_once_when_the_tv_fell_back_to_its_clock(hass, aioclient_mock):
    """A TV that just booted ignores older lux and runs on its clock until a new reading arrives."""
    hass.states.async_set("sensor.room_lux", "4")
    aioclient_mock.get(BASE, json={**STATUS, "fade_method": "ambient", "ambient_lux": 4, "phase": "day"})
    entry = _entry(ambient_lux_entity="sensor.room_lux")
    await _setup(hass, entry)
    assert sum("ambient_lux" in url.query for _m, url, *_ in aioclient_mock.mock_calls) == 1

    # The next poll still sees the clock fallback, so the unchanged reading goes out again
    # instead of waiting for the one-minute refresh.
    await entry.runtime_data.async_refresh()
    assert sum("ambient_lux" in url.query for _m, url, *_ in aioclient_mock.mock_calls) == 2


async def test_led_dark_room_curve_switch(hass, aioclient_mock):
    aioclient_mock.get(BASE, json={**STATUS, "hyperhdr_dark_curve": False})
    await _setup(hass, _entry())
    assert hass.states.get("switch.panelcomfort_tv_led_dark_room_curve").state == "off"

    aioclient_mock.clear_requests()
    aioclient_mock.get(BASE, json={**STATUS, "hyperhdr_dark_curve": True})
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.panelcomfort_tv_led_dark_room_curve"}, blocking=True
    )
    assert any(url.query.get("hyperhdr_dark_curve") == "on" for _m, url, *_ in aioclient_mock.mock_calls)
    assert hass.states.get("switch.panelcomfort_tv_led_dark_room_curve").state == "on"
