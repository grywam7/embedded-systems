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
if ! command -v comitup >/dev/null; then
  apt-get install -y ca-certificates curl gnupg dirmngr
  # David Steele's repo signing key. Debian 13's apt (sqv) verifies via signed-by,
  # not the legacy trusted.gpg.d that the apt-source .deb uses (and that .deb often
  # ships an older key than the one the repo is currently signed with). So fetch the
  # exact key into a dedicated keyring and point the repo at it.
  install -d /etc/apt/keyrings
  KEY_FPR="${KEY_FPR:-4E1609F5CDFE5F2036961B66B5E293D64E192FDE}"
  if ! gpg --no-default-keyring --keyring /tmp/cmt-key.gpg \
        --keyserver hkps://keyserver.ubuntu.com --recv-keys "$KEY_FPR"; then
    echo "FAILED to fetch comitup signing key $KEY_FPR from keyserver."
    echo "-> sprawdź sieć, albo: sudo KEY_FPR=<fpr> $0  (lub inny keyserver)"
    exit 1
  fi
  gpg --no-default-keyring --keyring /tmp/cmt-key.gpg --export \
    > /etc/apt/keyrings/davesteele-comitup.gpg
  rm -f /tmp/cmt-key.gpg
  # replace any legacy comitup repo entry with a signed-by one
  rm -f /etc/apt/sources.list.d/*comitup*.list
  echo "deb [signed-by=/etc/apt/keyrings/davesteele-comitup.gpg] http://davesteele.github.io/comitup/repo comitup main" \
    > /etc/apt/sources.list.d/comitup.list
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
