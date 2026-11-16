"""In-memory fake board for the tests and `--mock` mode."""

from __future__ import annotations

from . import config as C
from .config import SIZE, XYConfig, XYTimeout
from .device import PACKET_SIZE
from .stock import X220_PINS, X220_TABLE


def sample_config() -> XYConfig:
    """A factory-like X220 wired-board config: stock key table, Fn+arrows as media keys,
    macro 1 = ⌘E on the ThinkVantage button. Used by `--mock` and the tests."""
    r = bytearray(SIZE)
    r[0], r[1] = C.VERSION, C.WIRED_USB
    r[0x004:0x006] = (0xFFFF).to_bytes(2, "little")
    r[0x008], r[0x009], r[0x00A], r[0x00B] = 7, 155, 0x27, 0xE0
    r[0x34:0x64] = X220_PINS
    for i, w in enumerate(X220_TABLE):
        r[C.KEY_TABLE_OFFSET + 2 * i:C.KEY_TABLE_OFFSET + 2 * i + 2] = w.to_bytes(2, "little")
    for i in range(C.KEY_TABLE_OFFSET + 2 * C.MATRIX_KEYS, C.OFF_FN_SCAN):
        r[i] = 0xFF
    r[0x1E4], r[0x1E5] = 0, 5  # Fn on its own IO pin 5
    r[C.OFF_FN_SCAN:C.FN_END] = b"\xff" * (C.FN_END - C.OFF_FN_SCAN)
    for slot, (key, media) in enumerate([(0x51, 0x80CD), (0x52, 0x80B7), (0x50, 0x80B6), (0x4F, 0x80B5)]):
        r[C.OFF_FN_SCAN + slot] = X220_TABLE.index(key)
        r[C.OFF_FN_WORD + 2 * slot:C.OFF_FN_WORD + 2 * slot + 2] = media.to_bytes(2, "little")
    r[0x258:0x25E] = b"\xff" * 6
    for n in range(C.MACRO_SLOTS):
        e = C.OFF_PROG_KEYS + 4 * n
        r[e:e + 4] = bytes([0xFF, 0xFF, 0, 0])
    e = C.OFF_PROG_KEYS
    r[e:e + 4] = bytes([0x07, 0xFD, 0, 1])  # ThinkVantage alone -> macro 1
    o = C.OFF_PROG_ROWS
    r[o:o + 9] = bytes([0x08, 0, 0x08, 0, 0, 0, 0, 0, 5])  # GUI + E
    r[C.OFF_CRC:C.OFF_CRC + 4] = C.crc32(r[:C.CRC_LENGTH]).to_bytes(4, "little")
    return XYConfig(r)


class MockKeyboard:
    def __init__(self, cfg: bytes):
        self.cfg = bytearray(cfg)
        self.cfg_new = bytearray(SIZE)
        self.cfg_written = False
        self.resend_once = 0
        self.backlight: int | None = None
        self.saw_boot = False
        self._last_ctrl = 0
        self._replies: list[bytes] = []

    def flush(self) -> None:
        self._replies.clear()

    def close(self) -> None:
        pass

    def _reply(self, payload) -> None:
        p = bytearray(PACKET_SIZE)
        p[0] = 0x02
        payload = bytes(payload)[:18]
        p[1:1 + len(payload)] = payload
        self._replies.append(bytes(p))

    def send(self, r: bytes) -> None:
        assert len(r) == PACKET_SIZE and r[0] == 0x02
        idx = r[1] | (r[2] & 0x3F) << 8
        if self._last_ctrl == 0 and r[1] == 0x3F:
            self._last_ctrl = r[2]
            self._reply([0x3F, r[2]])
            return
        if self._last_ctrl == 0 and r[1] == 0x3E:
            res = bytearray(18)
            res[0] = r[2]
            if r[2] == 0x6B:
                v = b"2023.12.06"
                res[:len(v)] = v
            if r[2] == 0x6A:
                res[0], res[1] = 0x1C, 0x0F
            if r[2] == 0x66:
                self.backlight = r[3]
            if r[2] in (0xCC, 0xCD):
                self.saw_boot = True
            self._reply(res)
            return
        if self._last_ctrl == 0x22:
            if r[1] == 0xFF and r[2] == 0xFF:
                self._last_ctrl = 0
                return
            self._reply(bytes([r[1], r[2]]) + bytes(self.cfg[idx * 8:idx * 8 + 8]))
            return
        if self._last_ctrl == 0x11:
            assert r[2] & 0x80 == 0
            if idx == SIZE // 16:
                self.cfg_written = True
                self.cfg = bytearray(self.cfg_new)
                self._last_ctrl = 0
                return
            self.cfg_new[idx * 16:idx * 16 + 16] = r[3:19]
            if idx == 4 and self.resend_once > 0:
                self.resend_once -= 1
                self._reply([3, 0])
            else:
                self._reply([0x11, 0x22])

    def receive(self, timeout_ms: int) -> bytes:
        if not self._replies:
            raise XYTimeout()
        return self._replies.pop(0)
