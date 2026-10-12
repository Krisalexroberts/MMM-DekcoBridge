import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "media", Path(__file__).resolve().parents[1] / "h264-media.py"
)
media = importlib.util.module_from_spec(spec)
spec.loader.exec_module(media)


def packet(payload, sequence=1, flag=0x80, extra=b""):
    header = bytearray(12)
    header[0] = flag
    header[1] = 96
    header[2:4] = sequence.to_bytes(2, "big")
    header[4:8] = (12345).to_bytes(4, "big")
    rtp = bytes(header) + payload
    return (
        b"\x03\0\x01\0"
        + bytes(12)
        + len(extra).to_bytes(4, "little")
        + bytes(4)
        + extra
        + len(rtp).to_bytes(4, "little")
        + rtp
    )


class ParserTests(unittest.TestCase):
    def test_tuya_flags_do_not_skip_video_payload(self):
        for flag in [0x80, 0x90, 0xA8]:
            with self.subTest(flag=flag):
                output = []
                parser = media.H264Media(output.append)
                parser.push(packet(b"\x41example", flag=flag))
                self.assertEqual(output, [b"\0\0\0\1\x41example"])

    def test_outer_metadata_is_skipped(self):
        output = []
        parser = media.H264Media(output.append)
        parser.push(packet(b"\x67sps", extra=bytes(8)))
        self.assertEqual(output, [b"\0\0\0\1\x67sps"])

    def test_fragment_reassembly_and_sequence_wrap(self):
        output = []
        parser = media.H264Media(output.append)
        parser.push(packet(b"\x7c\x85first", sequence=65535))
        parser.push(packet(b"\x7c\x45last", sequence=0))
        self.assertEqual(output, [b"\0\0\0\1\x65firstlast"])

    def test_lost_fragment_is_discarded(self):
        output = []
        parser = media.H264Media(output.append)
        parser.push(packet(b"\x7c\x85first", sequence=1))
        parser.push(packet(b"\x7c\x45last", sequence=3))
        self.assertEqual(output, [])
        self.assertEqual(parser.dropped, 1)

    def test_truncated_packet_does_not_emit(self):
        output = []
        parser = media.H264Media(output.append)
        parser.push(packet(b"\x41example")[:-2])
        self.assertEqual(output, [])


if __name__ == "__main__":
    unittest.main()
