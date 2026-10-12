# MMM-DekcoBridge

Live video from a stock Dekco/Tuya IP camera for MagicMirror², with a local RTSP stream and a browser-compatible MJPEG feed. The bridge runs on the Raspberry Pi, independently of a desktop PC.

Tested with a **Dekco DC5L2DA11, firmware 2.6.7**, on a **Raspberry Pi 3 Model B**, Raspberry Pi OS Trixie arm64, Python 3.13 and MagicMirror² 2.38.0. The SD preview measured approximately **10 fps at 640×360**. Other camera models, firmware versions and account regions have not been validated.

## What it does

- Keeps the camera's stock firmware and existing Dekco pairing.
- Uses the Tuya session belonging to the Dekco OEM account for signaling and video relay.
- Reassembles the camera's H.264 packets and publishes them to MediaMTX as RTSP.
- Provides an MJPEG preview, JPEG snapshot and health endpoint for the mirror.
- Requests SD by default for the Pi 3; HD is available with `--clarity 4`.
- Disables FFmpeg autorotation to keep the displayed image orientation fixed.
- Reconnects failed video sessions, with a delay between attempts.

**This is a working experimental bridge, not a one-click account integration.** It requires your own Dekco OEM signing configuration and Tuya account identifier. The repository does not contain account credentials, app signing secrets, saved sessions, camera IDs or an APK/firmware extraction toolkit. Smart Life account credentials are not a substitute for the Dekco OEM configuration.

It still relies on Tuya cloud signaling/relay. It is not an offline/LAN-only camera modification. Audio is not implemented.

## Requirements

- Linux with Python **3.13 or later**; the pinned SDK uses Python 3.13 syntax.
- FFmpeg on `PATH`.
- MediaMTX, installed by the checksum-verifying helper below.
- A private OEM configuration and an account authorized to access the camera.

## Install the bridge

Run these commands as the normal account that will run the bridge:

```bash
sudo apt update
sudo apt install ffmpeg python3-venv git
sudo mkdir -p /opt/dekco-rtsp-bridge
sudo chown "$USER":"$(id -gn)" /opt/dekco-rtsp-bridge
git clone https://github.com/Krisalexroberts/MMM-DekcoBridge.git /opt/dekco-rtsp-bridge
cd /opt/dekco-rtsp-bridge
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python install-mediamtx.py
```

MediaMTX is downloaded from its official release and checked against the published SHA256 checksum. Binaries are not committed to this repository.

## Private configuration

Keep the account file **outside the Git checkout**:

```bash
umask 077
mkdir -p ~/.config/dekco
cp credentials.example.json ~/.config/dekco/credentials.json
chmod 600 ~/.config/dekco/credentials.json
```

Fill in the placeholders locally. Do not commit the completed file or paste its contents into issues.

| Field | Purpose |
| --- | --- |
| `cfg.package_name` | Android package name associated with your OEM signing configuration. |
| `cfg.client_id` | Dekco OEM Tuya app/client identifier. |
| `cfg.composite_key` | Matching package/certificate/derived-key/app-secret composite. |
| `cfg.ch_key` | Matching OEM channel key. |
| `cfg.app_version` | App version associated with that configuration. |
| `account.region` | Tuya region; only `eu` has been tested here. |
| `account.countryCode` | Country calling code for your account. |
| `account.tuyaUsername` | The Tuya username returned by Dekco's account login, not the Dekco email address. |
| `settings.device_id` | Camera's Tuya device ID. |

The signing values must match each other and the app build. They are not provided here. If you already have a working private configuration, also retain its saved `session` and `devices` entries; the renewal script can create these otherwise.

To log in or renew an expired session:

```bash
cd /opt/dekco-rtsp-bridge
.venv/bin/python renew-session.py
```

The password is entered at a hidden prompt and is not saved. The resulting session and device local keys are written to the private account file with permission `600`. There is no automatic password-based reauthentication. After renewing, restart the service.

`DEKCO_CONFIG` can override the private-file path. The bridge also accepts `--config /path/to/private.json`; use `DEKCO_CONFIG` for the renewal script.

## Run and verify

```bash
cd /opt/dekco-rtsp-bridge
.venv/bin/python dekco-bridge.py --clarity 2
```

The endpoints listen on **localhost only**:

| Endpoint | Output |
| --- | --- |
| `http://127.0.0.1:8089/` | Browser preview |
| `http://127.0.0.1:8089/stream.mjpg` | MJPEG feed, target 10 fps |
| `http://127.0.0.1:8089/snapshot.jpg` | Latest JPEG frame |
| `http://127.0.0.1:8089/status` | Frame count, state and last-frame age |
| `rtsp://127.0.0.1:8554/dekco` | H.264 RTSP stream; use TCP |

To test briefly, add `--duration 60`. To request HD, use `--clarity 4`; this requires more decoding resources. MJPEG preview stays 640 pixels wide. RTSP preserves the selected camera stream's resolution.

For viewing from another machine, use an authenticated tunnel or deliberately configure access controls. The supplied configuration does not expose video to the LAN or internet.

## Start automatically on the Pi

```bash
cd /opt/dekco-rtsp-bridge
sudo cp dekco-bridge@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now "dekco-bridge@$USER.service"
```

The template runs as the selected user and reads that user's private configuration. The installation directory must be writable by that user for local logs and the stop-control token.

```bash
systemctl status "dekco-bridge@$USER.service"
journalctl -u "dekco-bridge@$USER.service" -n 30 --no-pager
sudo systemctl restart "dekco-bridge@$USER.service"
```

## MagicMirror module

Copy the two frontend files into the mirror's module directory:

```bash
mkdir -p ~/MagicMirror/modules/MMM-DekcoBridge
cp /opt/dekco-rtsp-bridge/MMM-DekcoBridge.{js,css} ~/MagicMirror/modules/MMM-DekcoBridge/
```

Add this entry to the existing `modules` array in `config/config.js`:

```js
{
  module: "MMM-DekcoBridge",
  position: "top_right",
  config: {
    streamUrl: "http://127.0.0.1:8089/stream.mjpg",
    width: "500px",
    retrySeconds: 5
  }
},
```

Restart or reload your mirror using its existing startup method. Disable an older camera module if it occupies the same display area. This project does not rewrite your other module configuration.

## Troubleshooting and limitations

- **No image:** check the service log and `/status`. Another live viewer can leave the camera busy temporarily.
- **Expired account session:** stop the bridge, run `renew-session.py` interactively, then restart it.
- **Malformed H.264 or very few frames:** this implementation handles the observed Tuya frame-header flags instead of treating them as standard RTP CSRC counts. Future firmware can change the packet layout.
- **Slow preview:** use SD (`--clarity 2`) and check Pi CPU load. H.264 decoding and MJPEG encoding are performed by FFmpeg.
- **Orientation:** FFmpeg autorotation is disabled; camera firmware image-flip settings are independent.
- **A timestamp warning in FFmpeg:** raw H.264 is currently assigned a fixed 20-fps input timebase rather than its original packet timestamps. Playback worked in the tested deployment, but RTSP timing can be improved.
- **Session refresh and long-term resilience:** video reconnects are implemented, but the login session still requires manual renewal. This is not presented as a production-supported camera SDK.

Do not share credentials, APK signing material, packet captures, camera footage or full private configuration in bug reports. A redacted health summary and error type are generally sufficient.

## Development

```bash
python3 -m unittest discover -s tests -v
```

The regression tests cover the observed nonstandard header flags, H.264 fragmentation and fragment loss. They use synthetic packets and require no camera account.

Upstream references: [Tuya IPC SDK preview/clarity modes](https://developer.tuya.com/en/docs/app-development/android-ipc-sdk-tutorial?id=Kavqw6037lhs4), [MediaMTX](https://mediamtx.org/), [Tuya IPC P2P SDK](https://github.com/roquerodrigo/tuya-ipc-p2p-sdk).
