#!/usr/bin/env bash
# Install balena wifi-connect (captive-portal WiFi onboarding) + its systemd unit.
# Run as root AFTER check-hardware.sh confirms the adapter supports AP mode.
#
# Flow it gives you: boot with no known WiFi -> open AP "Embedded-Music-Setup" ->
# user connects -> portal page -> pick home SSID + password -> box connects ->
# AP torn down -> embedded-music.service starts.
#
# Idempotent & self-verifying: re-running fixes a partial install (e.g. binary
# present but the UI assets missing -> the captive portal 404s).
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root: sudo $0"; exit 1; }
APP_DIR="/opt/embedded-systems"
UI_DIR="/usr/local/share/wifi-connect/ui"   # must match --ui-directory in the unit

command -v NetworkManager >/dev/null || { echo "NetworkManager missing -- run provision.sh first"; exit 1; }

# --- pick the asset for this architecture (balena names them by Rust target) ---
case "$(dpkg --print-architecture)" in
  amd64) TARGET="x86_64-unknown-linux-gnu" ;;
  arm64) TARGET="aarch64-unknown-linux-gnu" ;;
  armhf) TARGET="armv7-unknown-linux-gnueabihf" ;;
  *) echo "unsupported arch $(dpkg --print-architecture) -- set WC_ASSET manually"; exit 1 ;;
esac
WC_ASSET="${WC_ASSET:-wifi-connect-${TARGET}.tar.gz}"

# --- resolve a version: latest from the GitHub API, with a pinned fallback ---
WC_VERSION="${WC_VERSION:-$(curl -fsSL https://api.github.com/repos/balena-os/wifi-connect/releases/latest 2>/dev/null \
  | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1)}"
WC_VERSION="${WC_VERSION:-v4.11.1}"

# Install only if the binary OR the UI is missing (so a half-done install heals).
if ! command -v wifi-connect >/dev/null || [ ! -f "$UI_DIR/index.html" ]; then
  echo "== fetching balena wifi-connect $WC_VERSION ($WC_ASSET) =="
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  url="https://github.com/balena-os/wifi-connect/releases/download/$WC_VERSION/$WC_ASSET"
  if ! curl -fSL "$url" -o "$tmp/wc.tgz"; then
    echo "DOWNLOAD FAILED: $url"
    echo "-> check the releases page and set WC_VERSION / WC_ASSET, then re-run:"
    echo "   sudo WC_VERSION=vX.Y.Z WC_ASSET=wifi-connect-${TARGET}.tar.gz $0"
    exit 1
  fi
  tar -xzf "$tmp/wc.tgz" -C "$tmp"

  # Find the binary and the UI dir at ANY depth (tarball layout varies by release).
  bin="$(find "$tmp" -type f -name wifi-connect | head -1)"
  ui="$(find "$tmp" -type d -name ui | head -1)"
  [ -n "$bin" ] || { echo "ERROR: no 'wifi-connect' binary inside $WC_ASSET"; exit 1; }
  if [ -z "$ui" ]; then
    echo "ERROR: no 'ui/' directory inside $WC_ASSET -- the captive portal needs it."
    echo "Tarball contents were:"; find "$tmp" -maxdepth 3 | sed 's/^/   /'
    echo "-> wrong asset? balena ships the binary + ui/ together; verify the asset name."
    exit 1
  fi

  install -m0755 "$bin" /usr/local/sbin/wifi-connect
  rm -rf "$UI_DIR"
  mkdir -p "$(dirname "$UI_DIR")"
  cp -r "$ui" "$UI_DIR"
fi

# Hard verification: the portal cannot work without index.html under --ui-directory.
[ -f "$UI_DIR/index.html" ] || { echo "ERROR: UI still missing at $UI_DIR (no index.html)"; exit 1; }

install -m0644 "$APP_DIR/deploy/systemd/wifi-connect.service" /etc/systemd/system/wifi-connect.service
systemctl daemon-reload
systemctl enable wifi-connect.service

echo
echo "== wifi-connect installed =="
echo "binary: $(command -v wifi-connect)   UI: $UI_DIR ($(ls "$UI_DIR" | wc -l) entries)"
cat <<'EOF'
Test (only raises the AP when NOT on a known WiFi):
  sudo systemctl start wifi-connect
Then from a phone join "Embedded-Music-Setup" -> the portal should load (no 404).
If the AP never appears: the adapter likely can't do AP mode (re-check with
check-hardware.sh) -> use an AP-capable USB dongle and re-run this script.
EOF
