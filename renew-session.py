"""Renew the Pi's Tuya login using a hidden interactive password prompt."""

from pathlib import Path
import asyncio, dataclasses, getpass, importlib.util, warnings

base = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("oem", base / "oem-settings.py")
oem = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oem)
from tuya_ipc_p2p_sdk.models import AccountSession
from tuya_ipc_p2p_sdk.crypto import md5_hex


async def main():
    warnings.simplefilter("error", getpass.GetPassWarning)
    password = getpass.getpass("Dekco password (hidden): ")
    if not password:
        return
    digest = md5_hex(password)
    del password
    country = str(oem.account["countryCode"])
    username = oem.account["tuyaUsername"]
    async with oem.SafeGateway(
        region=oem.account["region"], composite_key=oem.cfg["composite_key"]
    ) as api:
        token = await api.async_call(
            "smartlife.m.user.username.token.get",
            "2.0",
            {"countryCode": country, "username": username, "isUid": True},
        )
        encrypted = oem.gateway._encrypt_password(
            token["publicKey"], token["exponent"], digest
        )
        del digest
        result = await api.async_call(
            "thing.m.user.uid.password.login",
            "1.0",
            {
                "countryCode": country,
                "uid": username,
                "passwd": encrypted,
                "token": token["token"],
                "ifencrypt": 1,
                "options": '{"group": 1}',
            },
        )
        del encrypted
        session = AccountSession(
            sid=result["sid"],
            ecode=result["ecode"],
            uid=result["uid"],
            device_fingerprint=api._device_fingerprint,
        )
        oem.login.save("session", dataclasses.asdict(session))
        devices = await api.async_list_devices(session)
        oem.login.save("devices", [dataclasses.asdict(d) for d in devices])
        print("Tuya session renewed on the Pi. Password was not saved.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except getpass.GetPassWarning:
        print("Run renewal in an interactive terminal so password entry stays hidden.")
    except Exception as error:
        print("Renewal stopped:", type(error).__name__)
