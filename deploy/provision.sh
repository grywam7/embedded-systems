#!/usr/bin/env bash
# Base provisioning for the embedded-music HUB75 appliance on Debian 12 minimal.
# Idempotent-ish; safe to re-run. Run as root (sudo). Edit CONFIG first.
# WiFi onboarding is separate -> deploy/wifi-onboarding.sh (run after check-hardware.sh).
set -euo pipefail

### CONFIG ##############################################################
APP_USER="music"
APP_DIR="/opt/embedded-systems"     # repo root: git clone your repo here first
RUBY_VERSION="3.0.7"                 # match Gemfile.lock / the dev machine
WEB_PORT="4567"
#########################################################################

[ "$(id -u)" -eq 0 ] || { echo "run as root: sudo $0"; exit 1; }
SERWER_DIR="$APP_DIR/serwer"
[ -d "$SERWER_DIR" ] || { echo "repo not found at $APP_DIR -- 'git clone <repo> $APP_DIR' first"; exit 1; }

echo "== apt: build deps, native libs (vips/taglib/sqlite), audio, downloads, NetworkManager =="
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  git curl ca-certificates build-essential pkg-config autoconf bison \
  libssl-dev libreadline-dev zlib1g-dev libyaml-dev libffi-dev libgdbm-dev \
  libvips-dev libtag1-dev libsqlite3-dev sqlite3 \
  mpg123 alsa-utils \
  network-manager dnsmasq-base iw \
  python3 python3-venv python3-pip ffmpeg

echo "== service user '$APP_USER' (groups: audio, dialout) =="
id "$APP_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$APP_USER"
usermod -aG audio,dialout "$APP_USER"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "== rbenv + Ruby $RUBY_VERSION (compiles Ruby; can take 10-20 min on a Celeron) =="
sudo -u "$APP_USER" bash -c '
  set -e
  RB="$HOME/.rbenv"
  [ -d "$RB" ] || git clone --depth 1 https://github.com/rbenv/rbenv.git "$RB"
  [ -d "$RB/plugins/ruby-build" ] || git clone --depth 1 https://github.com/rbenv/ruby-build.git "$RB/plugins/ruby-build"
  grep -q "rbenv/shims" "$HOME/.bashrc" 2>/dev/null || {
    echo "export PATH=\"\$HOME/.rbenv/bin:\$HOME/.rbenv/shims:\$PATH\"" >> "$HOME/.bashrc"
    echo "eval \"\$(rbenv init - bash)\"" >> "$HOME/.bashrc"
  }
  export PATH="$RB/bin:$RB/shims:$PATH"
  rbenv install -s '"$RUBY_VERSION"'
  rbenv global '"$RUBY_VERSION"'
  gem install bundler --no-document
'

echo "== bundle install =="
sudo -u "$APP_USER" bash -c "export PATH=\$HOME/.rbenv/shims:\$HOME/.rbenv/bin:\$PATH; cd '$SERWER_DIR' && bundle install"

echo "== python venv with spotdl + yt-dlp (downloader does 'source venv/bin/activate') =="
sudo -u "$APP_USER" bash -c "
  cd '$SERWER_DIR'
  [ -d venv ] || python3 -m venv venv
  ./venv/bin/pip install -q --upgrade pip
  ./venv/bin/pip install -q spotdl yt-dlp
"

echo "== udev rule: stable /dev/pico + dialout access =="
install -m0644 "$APP_DIR/deploy/udev/99-pico-hub75.rules" /etc/udev/rules.d/99-pico-hub75.rules
udevadm control --reload-rules && udevadm trigger || true

echo "== systemd service =="
sed -e "s#@APP_USER@#$APP_USER#g" -e "s#@SERWER_DIR@#$SERWER_DIR#g" -e "s#@WEB_PORT@#$WEB_PORT#g" \
  "$APP_DIR/deploy/systemd/embedded-music.service" > /etc/systemd/system/embedded-music.service
systemctl daemon-reload
systemctl enable embedded-music.service
systemctl enable --now NetworkManager

cat <<EOF

== base provisioning DONE ==
Verify, in order:
  1) AUDIO (plays from this box):
        sudo -u $APP_USER mpg123 -o alsa "$SERWER_DIR/music_data/"*.mp3
     If silent: 'aplay -l' to find the card, then set it in /etc/asound.conf.
     NOTE: the app runs 'mpg123 -R --fifo ...' (no -o). If default output is wrong,
     add '-o alsa' to MusicPlayerService#initialize, or set default_output in ~/.mpg123rc.
  2) WIFI ONBOARDING (only after check-hardware.sh shows AP mode):
        sudo $APP_DIR/deploy/wifi-onboarding.sh
  3) START THE APP:
        sudo systemctl start embedded-music
        journalctl -u embedded-music -f
     Reach the UI from another device at  http://<box-ip>:$WEB_PORT/
EOF
