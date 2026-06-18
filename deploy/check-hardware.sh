#!/usr/bin/env bash
# Run FIRST, as root, on the freshly-installed Debian 12 (with the Pico plugged in).
# Confirms the facts the rest of the setup depends on -- especially WiFi AP support,
# which gates the captive-portal onboarding.
set -uo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root: sudo $0"; exit 1; }

# tiny tools needed to inspect hardware (safe, ~few MB)
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -q iw pciutils usbutils alsa-utils >/dev/null 2>&1 || true

line() { printf '\n== %s ==\n' "$1"; }

line "CPU / arch"; uname -m; grep -m1 'model name' /proc/cpuinfo | cut -d: -f2
line "RAM";        free -h | awk '/Mem/{print $2" total"}'
line "Storage";   lsblk -o NAME,SIZE,TYPE,MOUNTPOINT 2>/dev/null | grep -v loop

line "Network interfaces"; ip -br link
line "WiFi chipset"
lspci -nn 2>/dev/null | grep -iE 'network|wireless' || true
lsusb 2>/dev/null | grep -iE 'wireless|wlan|wi-?fi|802\.11' || true

line "AP / hotspot mode  (GATES the captive portal)"
if iw list >/dev/null 2>&1; then
  if iw list | sed -n '/Supported interface modes/,/valid interface combinations/p' | grep -q '\* AP$'; then
    echo "  AP mode: SUPPORTED  -> built-in card can run the setup hotspot"
  else
    echo "  AP mode: NOT detected  -> Intel cards often can't AP reliably."
    echo "     Use an AP-capable USB dongle (RTL8188EUS / RTL8812AU / AR9271) for onboarding."
  fi
  echo "  --- supported interface modes ---"
  iw list | sed -n '/Supported interface modes/,/valid interface combinations/p' | sed '$d'
else
  echo "  no wifi PHY found by 'iw' (driver not loaded / no card?)"
fi

line "Audio outputs  (music plays from THIS box; connect speakers)"
aplay -l 2>/dev/null || echo "  none / alsa-utils missing"

line "Serial / Pico  (plug the Pico in first)"
ls -l /dev/ttyACM* /dev/ttyUSB* 2>/dev/null || echo "  no ttyACM*/ttyUSB* -- is the Pico plugged in?"
echo
echo "Report the 'AP mode', 'WiFi chipset', and 'Audio outputs' lines back and we tune the rest."
