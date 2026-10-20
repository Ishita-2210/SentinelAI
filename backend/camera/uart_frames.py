"""Proposed SNC1 transport contract. No device I/O or camera pin assumptions.

Current UART probe/telemetry firmware does NOT emit this protocol.
"""
from dataclasses import dataclass
import struct
import time
import zlib

MAGIC = b"SNC1"
VERSION = 1
STATUS, JPEG = 1, 2
HEADER = struct.Struct("<4sBBHIIQII")
MAX_PAYLOAD = 128 * 1024


@dataclass(frozen=True)
class Packet:
    kind: int
    session: int
    sequence: int
    capture_us: int
    payload: bytes


def encode(packet):
    limit = 2048 if packet.kind == STATUS else MAX_PAYLOAD
    if packet.kind not in (STATUS, JPEG) or not 0 < len(packet.payload) <= limit:
        raise ValueError("Invalid packet kind/length")
    header = HEADER.pack(MAGIC, VERSION, packet.kind, 0, packet.session,
                         packet.sequence, packet.capture_us, len(packet.payload), 0)
    crc = zlib.crc32(header[:-4] + packet.payload) & 0xFFFFFFFF
    return header[:-4] + struct.pack("<I", crc) + packet.payload


class Parser:
    def __init__(self, timeout_s=15, clock=time.monotonic):
        self.timeout_s, self.clock = timeout_s, clock
        self.buffer = bytearray()
        self.pending_at = None
        self.corrupt = self.timeouts = self.noise_bytes = 0

    def feed(self, data):
        packets = []
        # Bound memory even when the caller provides a very large input chunk.
        for offset in range(0, max(1, len(data)), 4096):
            self.buffer.extend(data[offset:offset+4096])
            self._drain(packets)
        return packets

    def _drain(self, packets):
        while self.buffer:
            start = self.buffer.find(MAGIC)
            if start < 0:
                keep = min(3, len(self.buffer))
                self.noise_bytes += len(self.buffer)-keep
                del self.buffer[:len(self.buffer)-keep]
                self.pending_at = None
                return
            if start:
                self.noise_bytes += start
                del self.buffer[:start]
                self.pending_at = None
            now = self.clock()
            if self.pending_at is None:
                self.pending_at = now
            if now-self.pending_at >= self.timeout_s:
                self.timeouts += 1
                del self.buffer[0]
                self.pending_at = None
                continue
            if len(self.buffer) < HEADER.size:
                return
            _, version, kind, flags, session, seq, captured, length, crc = HEADER.unpack_from(self.buffer)
            limit = 2048 if kind == STATUS else MAX_PAYLOAD
            if version != VERSION or kind not in (STATUS, JPEG) or flags != 0 or not 0 < length <= limit:
                self.corrupt += 1
                del self.buffer[0]
                self.pending_at = None
                continue
            total = HEADER.size+length
            if len(self.buffer) < total:
                return
            payload = bytes(self.buffer[HEADER.size:total])
            actual = zlib.crc32(bytes(self.buffer[:HEADER.size-4])+payload) & 0xFFFFFFFF
            if actual != crc:
                self.corrupt += 1
                del self.buffer[0]
                self.pending_at = None
                continue
            packets.append(Packet(kind, session, seq, captured, payload))
            del self.buffer[:total]
            self.pending_at = None


def jpeg_dimensions(data, max_pixels=1024*1024):
    """Check SOF dimensions before allocating decoded image memory."""
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ValueError("JPEG SOI/EOI missing")
    index = 2
    while index+4 <= len(data):
        if data[index] != 255:
            raise ValueError("Invalid JPEG marker")
        while index < len(data) and data[index] == 255:
            index += 1
        if index >= len(data):break
        marker = data[index];index += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        if index+2 > len(data):break
        length = int.from_bytes(data[index:index+2], "big")
        if length < 2 or index+length > len(data):
            raise ValueError("Truncated JPEG segment")
        if marker in (0xC0, 0xC1, 0xC2):
            if length < 8:raise ValueError("Short JPEG SOF")
            height = int.from_bytes(data[index+3:index+5], "big")
            width = int.from_bytes(data[index+5:index+7], "big")
            if not width or not height or width*height > max_pixels:
                raise ValueError("JPEG exceeds decoded pixel budget")
            return width, height
        if marker == 0xDA:break
        index += length
    raise ValueError("JPEG dimensions unavailable")
