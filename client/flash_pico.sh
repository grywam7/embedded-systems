#!/usr/bin/env bash
# Flash client/main.py onto the Pico, catching the boot recovery window.
#
# The running firmware sleeps 2s before disabling Ctrl-C, so a reset gives a
# few-second window where mpremote can break in. This script waits (no time
# limit pressure) for you to unplug + replug, then grabs that window.
#
# Usage:   bash client/flash_pico.sh            # flash main.py
#          bash client/flash_pico.sh --all      # flash hub75.py + main.py
#          bash client/flash_pico.sh --all /dev/cu.usbmodemXXXX
set -u

ALL=0
PORT=""
for a in "$@"; do
  case "$a" in
    --all) ALL=1 ;;
    /dev/*) PORT="$a" ;;
  esac
done
PORT="${PORT:-/dev/cu.usbmodem14201}"
HERE="$(cd "$(dirname "$0")" && pwd)"

mpc() { perl -e 'alarm shift; exec @ARGV' "$@"; }   # timeout wrapper

echo "Flasher targeting $PORT"
echo ">>> UNPLUG the Pico's USB cable now (waiting up to 3 min)..."
for _ in $(seq 1 3600); do [ -e "$PORT" ] || break; perl -e 'select(undef,undef,undef,0.05)'; done
if [ -e "$PORT" ]; then echo "!!! never saw it disconnect - is the right cable being pulled?"; exit 1; fi

echo ">>> Good, it's gone. Now PLUG it back in..."
for _ in $(seq 1 3600); do [ -e "$PORT" ] && break; perl -e 'select(undef,undef,undef,0.03)'; done
echo ">>> Reconnected. Catching the boot window..."

for j in $(seq 1 40); do
  if mpc 3 mpremote connect "$PORT" cp "$HERE/main.py" :main.py 2>/dev/null; then
    # We caught the window: board is now held at the REPL, no time pressure.
    echo ">>> flashed main.py on try $j"
    if [ "$ALL" = 1 ]; then
      mpc 15 mpremote connect "$PORT" cp "$HERE/hub75.py" :hub75.py 2>/dev/null && echo ">>> pushed hub75.py"
    fi
    mpc 10 mpremote connect "$PORT" exec "import os; print('FILES', os.listdir())" 2>&1 || true
    mpc 12 mpremote connect "$PORT" reset 2>/dev/null || true
    echo ">>> done - Pico reset into new firmware."
    exit 0
  fi
  perl -e 'select(undef,undef,undef,0.05)'
done
echo "!!! missed the window - just run the script again."
exit 1
