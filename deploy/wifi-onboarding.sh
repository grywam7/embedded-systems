#!/usr/bin/env bash
# Install balena wifi-connect (captive-portal WiFi onboarding) + its systemd unit.
# Run as root AFTER check-hardware.sh confirms the adapter supports AP mode.
#
# Flow it gives you: boot with no known WiFi -> open AP "Embedded-Music-Setup" ->
# user connects -> portal page -> pick home SSID + password -> box connects ->
# AP torn down -> embedded-music.service starts.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root: sudo $0"; exit 1; }
APP_DIR="/opt/embedded-systems"

# !!! VERIFY this against https://github.com/balena-os/wifi-connect/releases
#     The version tag AND the asset filename have changed across releases.
#     Set these two to match a current release for your arch (amd64 -> x86_64).
WC_VERSION="v4.11.82"
WC_ASSET="wifi-connect-x86_64-unknown-linux-gnu.tar.gz"

command -v NetworkManager >/dev/null || { echo "NetworkManager missing -- run provision.sh first"; exit 1; }

if ! command -v wifi-connect >/dev/null; then
  echo "== fetching balena wifi-connect $WC_VERSION ($WC_ASSET) =="
  tmp="$(mktemp -d)"
  url="https://github.com/balena-os/wifi-connect/releases/download/$WC_VERSION/$WC_ASSET"
  if ! curl -fsSL "$url" -o "$tmp/wc.tgz"; then
    echo "DOWNLOAD FAILED: $url"
    echo "-> open the releases page, copy the current Linux x86_64 asset name into WC_ASSET/WC_VERSION, re-run."
    exit 1
  fi
  tar -xzf "$tmp/wc.tgz" -C "$tmp"
  install -m0755 "$(find "$tmp" -maxdepth 2 -name wifi-connect -type f | head -1)" /usr/local/sbin/wifi-connect
  mkdir -p /usr/local/share/wifi-connect
  # copy bundled UI assets if present
  uidir="$(find "$tmp" -maxdepth 2 -type d -name ui | head -1)"
  [ -n "${uidir:-}" ] && cp -r "$uidir" /usr/local/share/wifi-connect/ || true
  rm -rf "$tmp"
fi

install -m0644 "$APP_DIR/deploy/systemd/wifi-connect.service" /etc/systemd/system/wifi-connect.service
systemctl daemon-reload
systemctl enable wifi-connect.service

cat <<'EOF'

== wifi onboarding installed ==
Test it:  sudo systemctl start wifi-connect   (if not already on a known WiFi)
Then from a phone, join "Embedded-Music-Setup" and the portal should pop up.
If the AP never appears: the adapter likely can't do AP mode (re-check with
check-hardware.sh) -> use an AP-capable USB dongle and re-run this script.
EOF
