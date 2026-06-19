#!/usr/bin/env bash
# WiFi onboarding via comitup (https://davesteele.github.io/comitup/).
# comitup is built for headless Linux: when there's no known WiFi it raises an AP
# and serves its OWN web UI to pick/enter the home network, then connects. Unlike
# balena wifi-connect, it's an apt package that ships the UI -> no UI sourcing.
#
# Run as root. First cut for x86_64/Debian -- ends with diagnostics so we can
# tune comitup.conf / services on the box.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root: sudo $0"; exit 1; }

AP_NAME="${AP_NAME:-embedded-music-<nnn>}"   # comitup replaces <nnn> with a hash

echo "== removing old balena wifi-connect leftovers =="
systemctl disable --now wifi-connect 2>/dev/null || true
rm -f /etc/systemd/system/wifi-connect.service /usr/local/sbin/wifi-connect
rm -rf /usr/local/share/wifi-connect
systemctl daemon-reload || true

echo "== installing comitup =="
export DEBIAN_FRONTEND=noninteractive
if ! apt-cache policy comitup 2>/dev/null | grep -qE 'Candidate: +[0-9]'; then
  # comitup isn't in Debian's repos; add David Steele's repo via his apt-source .deb
  apt-get install -y ca-certificates curl
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  SRC_URL="https://davesteele.github.io/comitup/deb/davesteele-comitup-apt-source_1.2_all.deb"
  if ! curl -fSL "$SRC_URL" -o "$tmp/src.deb"; then
    echo "FAILED to fetch comitup apt-source: $SRC_URL"
    echo "-> sprawdź aktualny plik na https://davesteele.github.io/comitup/ i ustaw:"
    echo "   sudo SRC_URL=<url> $0   (albo dodaj repo ręcznie)"
    exit 1
  fi
  dpkg -i "$tmp/src.deb" || apt-get -f install -y
  apt-get update
fi
apt-get install -y comitup

echo "== configuring /etc/comitup.conf =="
# Keep a backup of whatever the package shipped, then set our AP name.
[ -f /etc/comitup.conf ] && cp -n /etc/comitup.conf /etc/comitup.conf.orig || true
cat > /etc/comitup.conf <<EOF
# managed by deploy/wifi-onboarding.sh
ap_name: $AP_NAME
# web_service: embedded-music.service   # uncomment to (re)start the app after connect
EOF

systemctl enable comitup 2>/dev/null || true

echo
echo "===================== DIAGNOSTYKA (wklej mi to) ====================="
echo "--- wersja ---"; comitup --version 2>/dev/null || dpkg -l comitup | tail -1
echo "--- usługi comitup* ---"; systemctl list-unit-files | grep -i comitup || echo "(brak unitów comitup?)"
echo "--- interfejs wlan + NM ---"; nmcli device status 2>/dev/null | grep -iE 'wifi|wlan' || true
echo "--- zależności (dnsmasq?) ---"; command -v dnsmasq >/dev/null && echo "dnsmasq: jest" || echo "dnsmasq: BRAK"
echo "====================================================================="
echo
echo "Po sprawdzeniu diagnostyki uruchomimy/przetestujemy:"
echo "  sudo systemctl restart comitup        # (potem) rozłącz znane WiFi, żeby podniósł AP"
echo "  -> z telefonu połącz z '$AP_NAME-xxxx' i otwórz stronę wyboru sieci"
