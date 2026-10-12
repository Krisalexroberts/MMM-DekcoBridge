"""Stock Dekco/Tuya camera to local RTSP and browser MJPEG."""

from pathlib import Path
import argparse, asyncio, contextlib, importlib.util, json, logging, os, queue, secrets, shutil, subprocess, sys, threading, time

base = Path(__file__).resolve().parent
ffmpeg_path = shutil.which("ffmpeg")
from aiohttp import web

spec = importlib.util.spec_from_file_location("h264", base / "h264-media.py")
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)
from tuya_ipc_p2p_sdk.models import AccountSession, MqttIdentity
from tuya_ipc_p2p_sdk.gateway import identity as ident
from tuya_ipc_p2p_sdk.stream_session import StreamSession
from tuya_ipc_p2p_sdk.crypto import decrypt_record

logging.getLogger("tuya_ipc_p2p_sdk").setLevel(logging.CRITICAL)


class Bridge:
    def __init__(self):
        self.latest = None
        self.frames = 0
        self.nals = 0
        self.last_frame = 0
        self.status = "Connecting"
        self.process = None
        self.stopped = threading.Event()
        self.input = queue.Queue(maxsize=128)
        self.shutdown_event = asyncio.Event()
        self.stop_token = secrets.token_hex(32)
        (base / "bridge-stop-token.local").write_text(self.stop_token)

    def start_encoder(self):
        self.input = queue.Queue(maxsize=128)
        self.stopped = threading.Event()
        error = (base / "bridge-ffmpeg.log").open("wb")
        command = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-fflags",
            "+genpts",
            "-noautorotate",
            "-r",
            "20",
            "-f",
            "h264",
            "-i",
            "pipe:0",
            "-map",
            "0:v:0",
            "-c:v",
            "copy",
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            "rtsp://127.0.0.1:8554/dekco",
            "-map",
            "0:v:0",
            "-vf",
            "scale=640:-2,fps=10",
            "-q:v",
            "5",
            "-f",
            "image2pipe",
            "pipe:1",
        ]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=error,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        error.close()

        def write():
            try:
                while not self.stopped.is_set():
                    try:
                        data = self.input.get(timeout=1)
                    except queue.Empty:
                        continue
                    if data is None:
                        break
                    self.process.stdin.write(data)
                    self.process.stdin.flush()
            except (OSError, ValueError):
                pass

        def read():
            buffer = bytearray()
            try:
                while not self.stopped.is_set():
                    data = self.process.stdout.read1(16384)
                    if not data:
                        break
                    buffer.extend(data)
                    while True:
                        begin = buffer.find(b"\xff\xd8")
                        end = buffer.find(b"\xff\xd9", max(0, begin))
                        if begin < 0 or end < 0:
                            break
                        self.latest = bytes(buffer[begin : end + 2])
                        del buffer[: end + 2]
                        self.frames += 1
                        self.last_frame = time.monotonic()
                        self.status = "Live"
                    if len(buffer) > 4 * 1024 * 1024:
                        buffer.clear()
            except (OSError, ValueError):
                pass

        self.threads = [
            threading.Thread(target=write, daemon=True),
            threading.Thread(target=read, daemon=True),
        ]
        for thread in self.threads:
            thread.start()

    def nal(self, data):
        self.nals += 1
        try:
            self.input.put_nowait(data)
        except queue.Full:
            raise RuntimeError("Video encoder cannot keep up")

    def stop_encoder(self):
        self.stopped.set()
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            for thread in self.threads:
                thread.join(timeout=2)
            self.process.stdin.close()
            self.process.stdout.close()
            self.process = None

    async def home(self, request):
        return web.Response(
            text='<!doctype html><meta name="viewport" content="width=device-width"><title>Dekco camera</title><style>html,body{margin:0;background:#000;color:#fff;font-family:sans-serif}img{display:block;width:100%;height:auto}p{padding:12px}</style><img src="/stream.mjpg" alt="Connecting to camera"><script>document.querySelector("img").onerror=()=>setTimeout(()=>location.reload(),3000)</script>',
            content_type="text/html",
        )

    async def status_response(self, request):
        return web.json_response(
            {
                "status": self.status,
                "frames": self.frames,
                "h264_nals": self.nals,
                "last_frame_seconds_ago": (
                    round(time.monotonic() - self.last_frame, 1)
                    if self.last_frame
                    else None
                ),
            }
        )

    async def shutdown(self, request):
        if not secrets.compare_digest(
            request.headers.get("X-Dekco-Stop", ""), self.stop_token
        ):
            raise web.HTTPForbidden()
        self.shutdown_event.set()
        return web.Response(text="Stopping camera bridge")

    async def snapshot(self, request):
        if not self.latest:
            return web.Response(status=503, text="Camera connecting")
        return web.Response(
            body=self.latest,
            content_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    async def stream(self, request):
        response = web.StreamResponse(
            headers={
                "Content-Type": "multipart/x-mixed-replace; boundary=frame",
                "Cache-Control": "no-store",
            }
        )
        await response.prepare(request)
        last = None
        try:
            while not self.shutdown_event.is_set():
                frame = self.latest
                if frame and frame is not last:
                    await response.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(frame)).encode()
                        + b"\r\n\r\n"
                        + frame
                        + b"\r\n"
                    )
                    last = frame
                await asyncio.sleep(0.1)
        except (ConnectionError, asyncio.CancelledError):
            pass
        return response

    async def camera(self):
        account = AccountSession(
            **oem.login.unprotect_local(base / "tuya-session.dpapi")
        )
        devices = oem.login.unprotect_local(base / "tuya-devices.dpapi")
        target = next(
            (d for d in devices if d["device_id"] == oem.settings["device_id"]), None
        )
        if target is None:
            raise RuntimeError(
                "Configured camera missing from saved devices; run renew-session.py"
            )
        region = oem.account.get("region", "eu")
        identity = MqttIdentity(
            host=ident.broker_host(region),
            port=ident.BROKER_PORT,
            client_id=ident.mqtt_client_id(account.device_fingerprint, account.uid),
            username=ident.mqtt_username(
                account.sid, account.ecode, oem.cfg["client_id"]
            ),
            password=ident.mqtt_password(account.ecode, oem.cfg["composite_key"]),
        )
        owner = self
        capture = (
            (base / "media-sample.bin").open("wb")
            if "--capture-sample" in sys.argv
            else None
        )
        captured = 0

        class Video(StreamSession):
            def _on_media_record(self, record):
                nonlocal capture, captured
                try:
                    plain = decrypt_record(self._answer_key, record)
                except Exception:
                    return
                if capture:
                    capture.write(len(plain).to_bytes(4, "little") + plain)
                    captured += len(plain)
                    capture.flush()
                    if captured >= 2 * 1024 * 1024:
                        capture.close()
                        capture = None
                parser.push(plain)

        async with oem.SafeGateway(
            region=region, composite_key=oem.cfg["composite_key"]
        ) as api:
            while True:
                video = None
                try:
                    self.status = "Connecting"
                    self.latest = None
                    self.start_encoder()
                    started = False

                    def accept(data):
                        nonlocal started
                        if not started:
                            if data[4] & 31 != 7:
                                return
                            started = True
                        owner.nal(data)

                    parser = media.H264Media(accept)
                    config = await api.async_stream_config(
                        account, target["device_id"], target["local_key"]
                    )
                    video = Video(config, identity, account.uid, lambda frame: None)
                    await asyncio.wait_for(video.async_start(), 60)
                    print("Camera video connection opened.", flush=True)
                    previous = self.nals
                    missed = 0
                    while True:
                        await asyncio.sleep(5)
                        if self.process.poll() is not None:
                            raise RuntimeError("Encoder exited")
                        missed = missed + 1 if previous == self.nals else 0
                        previous = self.nals
                        if missed >= 3:
                            raise RuntimeError("Video stalled")
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self.status = "Reconnecting"
                    print("Reconnecting after:", type(error).__name__, flush=True)
                    if getattr(error, "session_expired", False):
                        self.status = "Login required"
                        print(
                            "Session expired; run renew-session.py again.", flush=True
                        )
                        return
                finally:
                    if video:
                        await video.async_close()
                    self.stop_encoder()
                await asyncio.sleep(20)


async def main(duration, clarity):
    global oem
    spec = importlib.util.spec_from_file_location("oem", base / "oem-settings.py")
    oem = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oem)
    ident.PACKAGE_NAME = oem.cfg["package_name"]
    ident.CH_KEY = oem.cfg["ch_key"]
    if not ffmpeg_path:
        raise RuntimeError("FFmpeg was not found on PATH")
    from tuya_ipc_p2p_sdk import stream_session as session_module
    from tuya_ipc_p2p_sdk.control import start_sequence

    def selected_sequence(credential, username="admin"):
        result = []
        for packet in start_sequence(credential, username):
            packet_type = int.from_bytes(packet[4:8], "little")
            sub_command = int.from_bytes(packet[12:16], "little")
            if (packet_type, sub_command) in [(0x10004, 9), (0x10005, 0x40006)]:
                packet = packet[:-4] + clarity.to_bytes(4, "little")
            result.append(packet)
        return tuple(result)

    session_module.start_sequence = selected_sequence
    server_log = (base / "bridge-mediamtx.log").open("wb")
    server_binary = base / (
        "bridge-tools/mediamtx.exe"
        if sys.platform == "win32"
        else "bridge-tools/mediamtx"
    )
    server = subprocess.Popen(
        [str(server_binary), str(base / "mediamtx.yml")],
        stdout=server_log,
        stderr=server_log,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    server_log.close()
    bridge = Bridge()
    app = web.Application()
    app.add_routes(
        [
            web.get("/", bridge.home),
            web.get("/status", bridge.status_response),
            web.get("/snapshot.jpg", bridge.snapshot),
            web.get("/stream.mjpg", bridge.stream),
            web.post("/shutdown", bridge.shutdown),
        ]
    )
    runner = web.AppRunner(app)
    task = None
    try:
        await asyncio.sleep(1)
        if server.poll() is not None:
            raise RuntimeError("RTSP server did not start; see bridge-mediamtx.log")
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 8089).start()
        print(
            "Browser: http://127.0.0.1:8089/  RTSP: rtsp://127.0.0.1:8554/dekco",
            flush=True,
        )
        task = asyncio.create_task(bridge.camera())
        stop = asyncio.create_task(bridge.shutdown_event.wait())
        try:
            await asyncio.wait(
                [task, stop],
                timeout=duration or None,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            stop.cancel()
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await runner.cleanup()
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=int, default=0)
    parser.add_argument("--clarity", type=int, choices=[2, 4], default=2)
    parser.add_argument("--capture-sample", action="store_true")
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.config:
        os.environ["DEKCO_CONFIG"] = str(args.config.expanduser().resolve())
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main(args.duration, args.clarity))
    except KeyboardInterrupt:
        pass
