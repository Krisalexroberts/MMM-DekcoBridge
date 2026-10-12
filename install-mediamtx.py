"""Fetch a checksum-verified official MediaMTX binary; do not commit it."""

from pathlib import Path
import hashlib, io, platform, tarfile, urllib.request

VERSION = "v1.21.2"
ARCH = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "armv7l": "armv7"}


def main():
    if platform.system() != "Linux":
        raise RuntimeError("This installer supports Linux only")
    arch = ARCH.get(platform.machine().lower())
    if not arch:
        raise RuntimeError("Unsupported CPU architecture")
    name = f"mediamtx_{VERSION}_linux_{arch}.tar.gz"
    root = f"https://github.com/bluenviron/mediamtx/releases/download/{VERSION}/"
    data = urllib.request.urlopen(root + name, timeout=60).read()
    checks = (
        urllib.request.urlopen(root + "checksums.sha256", timeout=30).read().decode()
    )
    expected = next(
        line.split()[0] for line in checks.splitlines() if line.endswith(name)
    )
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError("MediaMTX checksum mismatch")
    destination = Path(__file__).resolve().parent / "bridge-tools"
    destination.mkdir(exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        binary = archive.extractfile("mediamtx")
        if binary is None:
            raise RuntimeError("Missing server binary")
        target = destination / "mediamtx"
        target.write_bytes(binary.read())
        target.chmod(0o755)
    print(f"MediaMTX {VERSION} installed; official SHA256 verified.")


if __name__ == "__main__":
    main()
