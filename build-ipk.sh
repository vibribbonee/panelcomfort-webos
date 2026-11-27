#!/bin/sh
# Build a webOS IPK with non-zero archive member timestamps. webOS' verifier
# rejects deterministic ar archives whose member timestamp is 0 (1970-01-01).
set -eu
BASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SRC="$BASE/src/com.webosbrew.panelcomfort"
VERSION=0.3.23
OUT=${1:-"$BASE/com.webosbrew.panelcomfort_${VERSION}_all.ipk"}
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM
mkdir -p "$TMP/root/usr/palm/applications/com.webosbrew.panelcomfort" "$TMP/root/usr/palm/packages/com.webosbrew.panelcomfort" "$TMP/control" "$TMP/ipk"
cp -a "$SRC/." "$TMP/root/usr/palm/applications/com.webosbrew.panelcomfort/"
cat > "$TMP/root/usr/palm/packages/com.webosbrew.panelcomfort/packageinfo.json" <<JSON
{
  "app": "com.webosbrew.panelcomfort",
  "id": "com.webosbrew.panelcomfort",
  "loc_name": "PanelComfort",
  "package_format_version": 2,
  "vendor": "PanelComfort",
  "version": "$VERSION",
  "services": []
}
JSON
cat > "$TMP/control/control" <<CONTROL
Package: com.webosbrew.panelcomfort
Version: $VERSION
Architecture: all
Section: webosbrew
Priority: optional
Maintainer: PanelComfort
Description: Scheduled LG webOS panel, solar-following fades, Eye Comfort and HyperHDR brightness for rooted TVs.
CONTROL
printf '2.0\n' > "$TMP/ipk/debian-binary"
(cd "$TMP/control" && COPYFILE_DISABLE=1 tar --format=ustar --owner=0 --group=0 --numeric-owner -cf "$TMP/ipk/control.tar" control)
(cd "$TMP/root" && COPYFILE_DISABLE=1 tar --format=ustar --owner=0 --group=0 --numeric-owner -cf "$TMP/ipk/data.tar" ./usr)
gzip -n -c "$TMP/ipk/control.tar" > "$TMP/ipk/control.tar.gz"
gzip -n -c "$TMP/ipk/data.tar" > "$TMP/ipk/data.tar.gz"
mkdir -p "$(dirname -- "$OUT")"
# Write the simple ar container directly. This avoids requiring root chown or
# Apple's Xcode-provided ar, while keeping nonzero timestamps and the archive
# ownership metadata used by accepted webOS packages. The inner payloads use
# USTAR headers and gzip -n to avoid macOS PAX provenance fields and timestamps.
write_member(){
  name=$1; file=$2; size=$(wc -c < "$file" | tr -d '[:space:]'); stamp=$(date +%s)
  printf '%-16s%-12s%-6s%-6s%-8s%-10s`\n' "$name/" "$stamp" 0 1001 100644 "$size"
  cat "$file"
  if [ $((size % 2)) -ne 0 ]; then printf '\n'; fi
}
{
  printf '!<arch>\n'
  write_member debian-binary "$TMP/ipk/debian-binary"
  write_member control.tar.gz "$TMP/ipk/control.tar.gz"
  write_member data.tar.gz "$TMP/ipk/data.tar.gz"
} > "$OUT"
echo "$OUT"
