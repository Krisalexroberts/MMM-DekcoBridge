"""Load private account material from outside the repository."""

from pathlib import Path
import json, os, stat, sys
from tuya_ipc_p2p_sdk.gateway import client as gateway

os.umask(0o077)
credentials_path = Path(
    os.environ.get("DEKCO_CONFIG", str(Path.home() / ".config/dekco/credentials.json"))
).expanduser()
if not credentials_path.is_file():
    raise RuntimeError("Private configuration missing. See README.md for setup.")
if sys.platform != "win32" and stat.S_IMODE(credentials_path.stat().st_mode) & 0o077:
    raise RuntimeError("Private configuration must have permission 600")
private = json.loads(credentials_path.read_text())
cfg = private["cfg"]
account = private["account"]
settings = private["settings"]
for key in ["client_id", "composite_key", "ch_key", "package_name"]:
    if not cfg.get(key) or str(cfg[key]).startswith("YOUR_"):
        raise RuntimeError("Complete the private OEM configuration first")
if not settings.get("device_id") or settings["device_id"].startswith("YOUR_"):
    raise RuntimeError("Set your camera device ID in private configuration")


class PrivateStore:
    def unprotect_local(self, path):
        key = {"tuya-session.dpapi": "session", "tuya-devices.dpapi": "devices"}[
            Path(path).name
        ]
        if key not in private:
            raise RuntimeError("No saved Tuya session; run renew-session.py first")
        return private[key]

    def save(self, key, value):
        private[key] = value
        temporary = credentials_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(private))
        temporary.chmod(0o600)
        temporary.replace(credentials_path)


login = PrivateStore()
gateway.CLIENT_ID = cfg["client_id"]
gateway.APP_VERSION = cfg.get("app_version", "5.1.51")
gateway.TTID = "sdk_international@" + cfg["client_id"]
gateway.CH_KEY = cfg["ch_key"]
SafeGateway = gateway.GatewayClient
