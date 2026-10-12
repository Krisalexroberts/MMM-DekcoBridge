class H264Media:
    def __init__(self, on_nal):
        self.on_nal = on_nal
        self.pending = None
        self.sequence = None
        self.timestamp = None
        self.packets = 0
        self.nals = 0
        self.dropped = 0

    def emit(self, data):
        if data:
            self.nals += 1
            self.on_nal(b"\0\0\0\1" + data)

    def push(self, plain):
        if len(plain) < 40 or plain[:4] != b"\x03\0\x01\0":
            return
        extra = int.from_bytes(plain[16:20], "little")
        offset = 28 + extra
        if extra > 256 or offset + 12 > len(plain):
            return
        size = int.from_bytes(plain[offset - 4 : offset], "little")
        if size < 13 or offset + size > len(plain):
            return
        rtp = plain[offset : offset + size]
        if rtp[0] >> 6 != 2:
            return
        # This Tuya transport uses bits in the first byte as frame flags.
        # Captured video has 0x80/0x90/0xa8 headers, all with 12-byte headers;
        # treating its low nibble as an RTP CSRC count discards video bytes.
        if rtp[1] & 127 != 96:
            return
        start = 12
        payload = rtp[start:]
        if not payload:
            return
        sequence = int.from_bytes(rtp[2:4], "big")
        stamp = rtp[4:8]
        self.packets += 1
        kind = payload[0] & 31
        if 1 <= kind <= 23:
            self.emit(payload)
        elif kind == 24:
            cursor = 1
            while cursor + 2 <= len(payload):
                length = int.from_bytes(payload[cursor : cursor + 2], "big")
                cursor += 2
                if not length or cursor + length > len(payload):
                    break
                self.emit(payload[cursor : cursor + length])
                cursor += length
        elif kind == 28 and len(payload) > 2:
            flags = payload[1]
            if flags & 128:
                self.pending = bytearray([(payload[0] & 224) | (flags & 31)])
                self.timestamp = stamp
                self.sequence = (sequence - 1) & 65535
            if self.pending is None:
                return
            if stamp != self.timestamp or sequence != ((self.sequence + 1) & 65535):
                self.pending = None
                self.dropped += 1
                return
            self.pending.extend(payload[2:])
            self.sequence = sequence
            if flags & 64:
                self.emit(bytes(self.pending))
                self.pending = None


if __name__ == "__main__":
    from pathlib import Path

    base = Path(__file__).resolve().parent
    raw = (base / "media-sample.bin").read_bytes()
    cursor = 0
    with (base / "camera-sample.h264").open("wb") as output:
        parser = H264Media(output.write)
        while cursor + 4 <= len(raw):
            size = int.from_bytes(raw[cursor : cursor + 4], "little")
            cursor += 4
            parser.push(raw[cursor : cursor + size])
            cursor += size
    print(
        "H.264 RTP packets:",
        parser.packets,
        "NAL units:",
        parser.nals,
        "discarded incomplete fragments:",
        parser.dropped,
    )
