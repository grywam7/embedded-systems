# Deploying the embedded-music appliance (Dell Wyse + Debian 12)

Turns a Dell Wyse (x86_64, 4 GB) into a headless appliance: it hosts the Sinatra
web UI, drives the Pico/HUB75 over USB, plays music through its own audio out, and
onboards onto your home WiFi via a captive portal.

> These scripts are a **v1 written without a test box** — run them on the Wyse and
> we'll iterate. Run order matters.

## 0. Install Debian 12 (minimal, CLI-only)

1. Flash the **Debian 12 netinst amd64** ISO to a USB stick, boot the Wyse from it.
2. In the installer's *Software selection*, **uncheck every desktop**; keep only
   **SSH server** + **standard system utilities**.
3. After first boot, log in and `sudo apt update`. Note the box's IP (`ip -br a`).
4. Put the repo on the box at `/opt/embedded-systems`:
   ```
   sudo apt install -y git
   sudo git clone <your-repo-url> /opt/embedded-systems
   ```

## 1. Hardware check (do this first)

```
sudo /opt/embedded-systems/deploy/check-hardware.sh
```
Confirms arch, the **WiFi chipset + AP-mode support**, the audio output device, and
the Pico serial port. **AP mode is the gate for the captive portal** — Intel cards
(common in Wyse) often can't do it. If it says "AP mode: NOT detected", grab a cheap
**RTL8188EUS** USB WiFi dongle for onboarding. Send me the AP-mode / chipset / audio
lines and I'll tune the rest.

## 2. Base provisioning

```
sudo /opt/embedded-systems/deploy/provision.sh
```
Installs native libs (libvips/taglib/sqlite), **rbenv + Ruby 3.0.7** (matches the
lockfile — compiles, slow), `bundle install`, a Python venv with **spotdl + yt-dlp**
(+ ffmpeg), a `music` service user (in `audio`/`dialout`), the udev rule, and the
`embedded-music` systemd service. Edit the CONFIG block at the top first if needed.

Then **verify audio** (it plays from the Wyse, not your laptop):
```
sudo -u music mpg123 -o alsa /opt/embedded-systems/serwer/music_data/*.mp3
```

## 3. WiFi onboarding (after the AP-mode check passes)

```
sudo /opt/embedded-systems/deploy/wifi-onboarding.sh
```
Installs **balena wifi-connect**. ⚠️ Verify the release version/asset URL inside the
script first (balena's asset names drift between releases). On a boot with no known
WiFi it raises the `Embedded-Music-Setup` AP + portal; enter your home WiFi and it
connects, then the app starts.

## 4. Run it

```
sudo systemctl start embedded-music
journalctl -u embedded-music -f
```
From a phone/laptop on the same network: **http://<box-ip>:4567/**

## Boot flow (how it hangs together)

```
NetworkManager ──> wifi-connect.service ──(connected)──> network-online.target
                     (AP + portal if no                          │
                      known WiFi)                                 ▼
                                                       embedded-music.service
                                                       (bundle exec ruby web_serwer.rb -o 0.0.0.0)
```
The Pico is found at `/dev/ttyACM0` (and `/dev/pico`); the udev rule grants the
`music` user access.

## Known tweaks / gotchas (likely to need on the box)

- **App was localhost-only on the Mac.** The systemd unit passes `-o 0.0.0.0` so the
  UI is reachable over the network. Good.
- **mpg123 output module.** `MusicPlayerService` runs `mpg123 -R --fifo` with no
  `-o`. If audio is silent under systemd, either add `-o alsa` to that command in
  `serwer/services/music_player_service.rb`, or set `default_output alsa` in
  `/home/music/.mpg123rc`.
- **Headless audio = ALSA, not PulseAudio.** A systemd service has no user session,
  so we rely on ALSA (session-less). Make sure nothing pulls in Pulse/PipeWire.
- **DataMapper is ancient** — that's why we pin Ruby 3.0.7. If `bundle install`
  fights you on a newer Ruby, stay on 3.0.7.
- **spotdl needs internet** and occasionally breaks with YouTube changes; `yt-dlp`
  in the venv is the fallback the downloader can use.
- **Port 80 instead of :4567?** Change `WEB_PORT` and add
  `AmbientCapabilities=CAP_NET_BIND_SERVICE` to the unit (binding <1024 as non-root).
