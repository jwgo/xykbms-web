"""The 1 KiB configuration block of xy_3dg12 (XYKBMS) boards.

Field layout, CRC, the key values this tool is willing to write, and the write-safety check.
The layout follows hughsie/xykbms-gtk PROTOCOL.md (LGPL-2.1-or-later); see PROTOCOL.md in this repository.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field

from .stock import EXTRA_BUTTONS, X220_PINS, X220_TABLE


class XYError(Exception):
    """Base error; the message is shown to the user as is."""


class XYTimeout(XYError):
    def __init__(self, msg: str = "키보드가 응답하지 않아요"):
        super().__init__(msg)


class XYNotFound(XYError):
    pass


class XYPermission(XYError):
    pass


class XYIOError(XYError):
    pass


class XYBadState(XYError):
    def __init__(self, msg: str = "키보드 상태가 이상해요. 수신기를 뽑았다 다시 꽂고 시도해 주세요"):
        super().__init__(msg)


class XYInvalidConfig(XYError):
    pass


class XYUnsafeWrite(XYError):
    def __init__(self, why: str):
        super().__init__(f"쓰기를 막았어요: {why}")
        self.why = why


def crc32(data: bytes) -> int:
    # zlib.crc32 is the standard reflected CRC-32 (polynomial 0xEDB88320) the board uses.
    return zlib.crc32(bytes(data)) & 0xFFFFFFFF


# --- board types / flags -----------------------------------------------------------------------

BOARD_TITLES = {
    0: "디버그 보드", 1: "ThinkPad 무선 개조 보드", 2: "기계식 키보드 무선 개조 보드",
    3: "트랙포인트 기계식 키보드 보드", 4: "트랙포인트 60% 기계식 키보드 보드",
    5: "ThinkPad 무선 개조 보드 2", 6: "트랙포인트 60% 기계식 키보드 보드 2",
    7: "ThinkPad 무선 개조 보드 3", 10: "유선 USB 보드",
}
WIRED_USB = 10
RF_MODES = {1: "블루투스 4.0", 2: "USB 수신기", 3: "URT"}

# flags A (0x00A)
TP_MIDDLE_SCROLL = 1 << 0
TP_DOUBLE_MIDDLE_BACKSPACE = 1 << 1
MIDDLE_BACKSPACE = 1 << 2
LOW_POWER_KEEP_LED = 1 << 3
DISABLE_WIN = 1 << 4
TP_ON_AT_POWER_UP = 1 << 5
TP_INVERT_XY = 1 << 6
USB_LOW_POWER = 1 << 7
# flags B (0x00B)
DISABLE_STA_BLINK = 1 << 0
STA_OFF = 1 << 1
SWAP_FN_LCTRL = 1 << 2
BT_PASSKEY = 1 << 3
SPECIFIC_WAKE = 1 << 4

FLAG_NAMES_A = [
    (TP_MIDDLE_SCROLL, "tpMiddleScroll", "트랙포인트 가운데 버튼 스크롤"),
    (TP_DOUBLE_MIDDLE_BACKSPACE, "tpDoubleMiddleBackspace", "트랙포인트 가운데 두 번 탭 = 백스페이스"),
    (MIDDLE_BACKSPACE, "middleBackspace", "마우스 가운데 버튼 = 백스페이스"),
    (LOW_POWER_KEEP_LED, "lowPowerKeepLED", "절전 중 LED 유지"),
    (DISABLE_WIN, "disableWin", "Win 키 비활성화"),
    (TP_ON_AT_POWER_UP, "tpOnAtPowerUp", "전원 켤 때 트랙포인트 켜기"),
    (TP_INVERT_XY, "tpInvertXY", "트랙포인트 X/Y 반전"),
    (USB_LOW_POWER, "usbLowPower", "USB 모드 절전 허용"),
]
FLAG_NAMES_B = [
    (SWAP_FN_LCTRL, "swapFnLCtrl", "Fn ↔ 왼쪽 Ctrl 교체"),
    (BT_PASSKEY, "btPasskey", "블루투스 패스키"),
    (SPECIFIC_WAKE, "specificWake", "특정 키로만 깨우기"),
    (DISABLE_STA_BLINK, "disableSTABlink", "상태 LED 깜빡임 끄기"),
    (STA_OFF, "staOff", "상태 LED 끄기"),
]


def capabilities(board: int | None) -> dict[str, bool]:
    """Which controls make sense for a board type; mirrors what the vendor tool enables."""
    names = ["btName", "autoOff", "rfMode", "rfChannel", "tpAutoOff", "moveSpeed", "scrollSpeed",
             "tpMiddleScroll", "tpDoubleMiddleBackspace", "middleBackspace", "lowPowerKeepLED", "disableWin",
             "tpOnAtPowerUp", "tpInvertXY", "usbLowPower", "swapFnLCtrl", "btPasskey", "backlight"]
    c = dict.fromkeys(names, False)
    if board not in BOARD_TITLES:
        return c  # unknown board: everything stays disabled
    b = board
    wired = b == WIRED_USB
    tp_wireless = b == 1
    mech_wireless = b == 2
    tp_mech = b in (3, 4, 6)
    c.update(
        btName=not wired, autoOff=not wired, rfMode=not wired, rfChannel=not wired,
        tpAutoOff=not wired and not mech_wireless,
        moveSpeed=not mech_wireless, scrollSpeed=not mech_wireless,
        tpMiddleScroll=not mech_wireless, tpDoubleMiddleBackspace=not mech_wireless,
        middleBackspace=not wired and not mech_wireless and not tp_mech,
        lowPowerKeepLED=not wired, disableWin=True,
        tpOnAtPowerUp=not wired and not mech_wireless and not tp_mech,
        tpInvertXY=not tp_wireless and not mech_wireless,
        usbLowPower=not wired,
        swapFnLCtrl=not mech_wireless and not tp_mech,
        btPasskey=not wired,
        backlight=not tp_wireless and b not in (3, 4),
    )
    return c


# --- key codes ---------------------------------------------------------------------------------

# Media words listed in the vendor .cfg appendix 3.
KNOWN_MEDIA = frozenset({0x80B5, 0x80B6, 0x80B7, 0x80CD, 0x80E2, 0x80E9, 0x80EA, 0x8224, 0x8225, 0x8192})
# macOS consumer functions NOT in the vendor tables (experimental).
MAC_CONSUMER = frozenset({0x8070, 0x806F, 0x829F, 0x82A0, 0x8221, 0x80CF, 0x809B})
# Mouse emulation words from the vendor .cfg appendix 4.
MOUSE = frozenset({0x5001, 0x5002, 0x5004, 0x51FE, 0x5102, 0x5202, 0x52FE, 0x5301, 0x53FF})
# "Send programmable key n" (vendor appendix 1).
PROG_KEYS = range(0x00F1, 0x00F6)


def is_macro_key(k: int) -> bool:
    """Keys allowed inside a macro row (plain HID keyboard usages; modifiers go in the modifier byte)."""
    return 0x04 <= k <= 0x65


def is_allowed(w: int) -> bool:
    """Key words this app is willing to write. Top two bits: 00 HID usage, 01 modifier/mouse, 10 consumer."""
    if w == 0xFFFF:
        return True  # key disabled
    cat = w >> 14
    if cat == 0:
        u = w & 0x3FFF
        if 0x04 <= u <= 0x65:
            return True
        if 0x68 <= u <= 0x73:
            return True  # F13-F24
        if 0x87 <= u <= 0x8B or 0x90 <= u <= 0x92:
            return True  # international, 한/영·한자 (not verified on the board)
        return w in PROG_KEYS  # macro 1..5
    if cat == 1:
        return 0x4000 <= w <= 0x4007 or w in MOUSE
    if cat == 2:
        return w in KNOWN_MEDIA or w in MAC_CONSUMER
    return False


# --- config ------------------------------------------------------------------------------------

SIZE = 0x400
VERSION = 4
CRC_LENGTH = 0x80
OFF_CRC = 0x3FC
PIN_OFFSET = 0x34

KEY_TABLE_OFFSET = 0x64
MATRIX_KEYS = 0x80
IDX_LEFT_ALT, IDX_LEFT_WIN, IDX_RIGHT_ALT = 0x0F, 0x29, 0x7F
MOD_LALT, MOD_LGUI, MOD_RALT, MOD_RGUI = 0x4002, 0x4003, 0x4006, 0x4007

FN_SLOTS = 18
OFF_FN_SCAN, OFF_FN_WORD = 0x1E6, 0x1F8
FN_END = OFF_FN_WORD + 2 * FN_SLOTS  # 0x21C

MACRO_SLOTS, MACRO_ROW_COUNT, ROWS_PER_SLOT = 5, 40, 8
OFF_PROG_KEYS, OFF_PROG_ROWS = 0x26B, 0x27F
PROG_END = OFF_PROG_ROWS + 9 * MACRO_ROW_COUNT  # 0x3E7


def is_physical_scan(s: int) -> bool:
    """Scan indexes that are real keys on this keyboard (factory keys plus mic-mute and ThinkVantage)."""
    return 0 <= s < MATRIX_KEYS and (X220_TABLE[s] != 0xFFFF or s in EXTRA_BUTTONS)


def validate(raw: bytes) -> None:
    """Validates length, CRC and version like the vendor tool."""
    if len(raw) != SIZE:
        raise XYInvalidConfig(f"설정 길이가 맞지 않아요 ({len(raw)} 바이트, 기대값 {SIZE})")
    stored = int.from_bytes(raw[OFF_CRC:OFF_CRC + 4], "little")
    calc = crc32(raw[:CRC_LENGTH])
    if calc != stored:
        raise XYInvalidConfig(f"체크섬이 맞지 않아요 (저장 0x{stored:08x}, 계산 0x{calc:08x}). 다시 읽어 주세요")
    if raw[0] != VERSION:
        raise XYInvalidConfig(f"지원하지 않는 설정 버전이에요: {raw[0]}")


@dataclass(frozen=True)
class MacroRow:
    mods: int
    keys: tuple[int, ...]
    delay: int


@dataclass(frozen=True)
class Macro:
    scan1: int  # direct trigger (0xFF = none)
    scan2: int  # 0xFD alone, 0xFE with Fn, else a second key
    start: int
    count: int
    rows: tuple[MacroRow, ...] = field(default_factory=tuple)

    @property
    def is_empty(self) -> bool:
        return self.count == 0 or all(r.mods == 0 and all(k == 0 for k in r.keys) for r in self.rows)


class XYConfig:
    """The 1 KiB config. Value-like: copy() before editing, compare with ==."""

    __slots__ = ("_raw",)

    def __init__(self, raw: bytes | bytearray):
        validate(bytes(raw))
        self._raw = bytearray(raw)

    @property
    def raw(self) -> bytes:
        return bytes(self._raw)

    def copy(self) -> "XYConfig":
        c = XYConfig.__new__(XYConfig)
        c._raw = bytearray(self._raw)
        return c

    def __eq__(self, other) -> bool:
        return isinstance(other, XYConfig) and self._raw == other._raw

    def __hash__(self):
        return hash(bytes(self._raw))

    def _update_crc(self) -> None:
        self._raw[OFF_CRC:OFF_CRC + 4] = crc32(self._raw[:CRC_LENGTH]).to_bytes(4, "little")

    def _u16(self, o: int) -> int:
        return self._raw[o] | self._raw[o + 1] << 8

    def _set_u16(self, o: int, v: int) -> None:
        self._raw[o] = v & 0xFF
        self._raw[o + 1] = (v >> 8) & 0xFF

    # read-only
    @property
    def board(self) -> int:
        return self._raw[0x001]

    @property
    def board_title(self) -> str:
        return BOARD_TITLES.get(self.board, f"알 수 없는 보드 ({self.board})")

    # editable header fields (all below PIN_OFFSET)
    @property
    def auto_off_minutes(self) -> int:
        return self._u16(0x002)

    @auto_off_minutes.setter
    def auto_off_minutes(self, v: int) -> None:
        self._set_u16(0x002, min(max(int(v), 0), 0xFFFF)); self._update_crc()

    @property
    def tp_auto_off_minutes(self) -> int:
        return self._u16(0x004)

    @tp_auto_off_minutes.setter
    def tp_auto_off_minutes(self, v: int) -> None:
        self._set_u16(0x004, min(max(int(v), 0), 0xFFFF)); self._update_crc()

    @property
    def scroll_speed(self) -> int:
        return self._raw[0x008]

    @scroll_speed.setter
    def scroll_speed(self, v: int) -> None:
        self._raw[0x008] = min(max(int(v), 1), 15); self._update_crc()

    @property
    def move_speed(self) -> int:
        return self._raw[0x009]

    @move_speed.setter
    def move_speed(self, v: int) -> None:
        self._raw[0x009] = min(max(int(v), 80), 255); self._update_crc()

    @property
    def flags_a(self) -> int:
        return self._raw[0x00A]

    @flags_a.setter
    def flags_a(self, v: int) -> None:
        self._raw[0x00A] = v & 0xFF; self._update_crc()

    @property
    def flags_b(self) -> int:
        return self._raw[0x00B]

    @flags_b.setter
    def flags_b(self, v: int) -> None:
        self._raw[0x00B] = v & 0xFF; self._update_crc()

    def set_flag(self, group: str, bit: int, on: bool) -> None:
        if group == "a":
            self.flags_a = (self.flags_a | bit) if on else (self.flags_a & ~bit)
        else:
            self.flags_b = (self.flags_b | bit) if on else (self.flags_b & ~bit)

    @property
    def bluetooth_name(self) -> str:
        b = bytes(self._raw[0x00C:0x01C]).split(b"\0", 1)[0]
        return b.decode("utf-8", "replace")

    def set_bluetooth_name(self, name: str) -> None:
        b = name.encode("utf-8")
        if not 1 <= len(b) <= 14:
            raise XYInvalidConfig("블루투스 이름은 1~14바이트여야 해요 (한글은 글자당 3바이트)")
        self._raw[0x00C:0x00C + len(b)] = b
        self._raw[0x00C + len(b)] = 0  # NUL terminator only, same as the vendor tool
        self._update_crc()

    @property
    def rf_mode(self) -> int:
        return self._raw[0x01C]

    def set_rf_mode(self, m: int) -> None:
        if m in RF_MODES:
            self._raw[0x01C] = m; self._update_crc()

    @property
    def rf_channel(self) -> int:
        return self._raw[0x01D]

    @rf_channel.setter
    def rf_channel(self, v: int) -> None:
        self._raw[0x01D] = min(max(int(v), 0), 3); self._update_crc()

    # merge
    def with_editable_from(self, other: "XYConfig") -> "XYConfig":
        """Copies only the editable header fields, matrix key table, Fn layer and macros from `other`.
        Everything else (version, board, pins, Pn rows, unknown bytes) stays as it is in self."""
        c = self.copy()
        r, o = c._raw, other._raw
        r[0x002:0x006] = o[0x002:0x006]
        r[0x008:0x01E] = o[0x008:0x01E]
        kt = KEY_TABLE_OFFSET
        r[kt:kt + MATRIX_KEYS * 2] = o[kt:kt + MATRIX_KEYS * 2]
        r[OFF_FN_SCAN:FN_END] = o[OFF_FN_SCAN:FN_END]
        r[OFF_PROG_KEYS:PROG_END] = o[OFF_PROG_KEYS:PROG_END]
        c._update_crc()
        return c

    # key table
    def key_word(self, idx: int) -> int:
        return self._u16(KEY_TABLE_OFFSET + idx * 2)

    def set_key_word(self, idx: int, word: int) -> bool:
        """Sets one matrix key. False (nothing changed) for the Pn area or a value not allowed."""
        if not (0 <= idx < MATRIX_KEYS and is_allowed(word)):
            return False
        self._set_u16(KEY_TABLE_OFFSET + idx * 2, word)
        self._update_crc()
        return True

    @property
    def has_x220_pins(self) -> bool:
        return bytes(self._raw[0x34:0x64]) == X220_PINS

    @property
    def alt_win_swapped(self) -> bool | None:
        a, w = self.key_word(IDX_LEFT_ALT), self.key_word(IDX_LEFT_WIN)
        if a == MOD_LALT and w == MOD_LGUI:
            return False
        if a == MOD_LGUI and w == MOD_LALT:
            return True
        return None

    @property
    def right_alt_is_command(self) -> bool | None:
        w = self.key_word(IDX_RIGHT_ALT)
        if w == MOD_RALT:
            return False
        if w in (MOD_LGUI, MOD_RGUI):
            return True
        return None

    def set_alt_win_swapped(self, on: bool) -> None:
        if self.alt_win_swapped is None:
            return
        self._set_u16(KEY_TABLE_OFFSET + IDX_LEFT_ALT * 2, MOD_LGUI if on else MOD_LALT)
        self._set_u16(KEY_TABLE_OFFSET + IDX_LEFT_WIN * 2, MOD_LALT if on else MOD_LGUI)
        self._update_crc()

    def set_right_alt_is_command(self, on: bool) -> None:
        if self.right_alt_is_command is None:
            return
        self._set_u16(KEY_TABLE_OFFSET + IDX_RIGHT_ALT * 2, MOD_RGUI if on else MOD_RALT)
        self._update_crc()

    # Fn layer
    def fn_slot(self, i: int) -> tuple[int, int]:
        return self._raw[OFF_FN_SCAN + i], self._u16(OFF_FN_WORD + 2 * i)

    @property
    def fn_slots_used(self) -> int:
        return sum(1 for i in range(FN_SLOTS) if self._raw[OFF_FN_SCAN + i] != 0xFF)

    def fn_word(self, scan: int) -> int | None:
        for i in range(FN_SLOTS):
            if self._raw[OFF_FN_SCAN + i] == scan:
                return self._u16(OFF_FN_WORD + 2 * i)
        return None

    def set_fn(self, scan: int, word: int) -> bool:
        """Defines Fn+scan -> word; 0xFFFF removes it. False when no slot is free or the value is not allowed."""
        if not (is_physical_scan(scan) and is_allowed(word)):
            return False
        for i in range(FN_SLOTS):
            if self._raw[OFF_FN_SCAN + i] == scan:
                if word == 0xFFFF:
                    self._raw[OFF_FN_SCAN + i] = 0xFF
                self._set_u16(OFF_FN_WORD + 2 * i, word)
                self._update_crc()
                return True
        if word == 0xFFFF:
            return True
        for i in range(FN_SLOTS):
            if self._raw[OFF_FN_SCAN + i] == 0xFF:
                self._raw[OFF_FN_SCAN + i] = scan
                self._set_u16(OFF_FN_WORD + 2 * i, word)
                self._update_crc()
                return True
        return False

    # macros: 5 entries of [scan1, scan2, start row, row count] at 0x26B,
    # 40 rows of [modifier bits, 0, key x6, delay(10 ms)] at 0x27F
    def macro(self, n: int) -> Macro:
        r = self._raw
        e = OFF_PROG_KEYS + 4 * n
        start, count = r[e + 2], r[e + 3]
        rows = []
        if start + count <= MACRO_ROW_COUNT:
            for i in range(start, start + count):
                o = OFF_PROG_ROWS + 9 * i
                rows.append(MacroRow(r[o], tuple(r[o + 2:o + 8]), r[o + 8]))
        return Macro(r[e], r[e + 1], start, count, tuple(rows))

    def set_macro_chord(self, n: int, mods: int, key: int) -> bool:
        """Makes macro n a single key chord in its own row block. mods 0 and key 0 clears it."""
        if not (0 <= n < MACRO_SLOTS) or not (key == 0 or is_macro_key(key)) or not (0 <= mods <= 0xFF):
            return False
        r = self._raw
        e = OFF_PROG_KEYS + 4 * n
        if mods == 0 and key == 0:
            r[e + 2] = 0
            r[e + 3] = 0
        else:
            row = n * ROWS_PER_SLOT
            o = OFF_PROG_ROWS + 9 * row
            r[o:o + 9] = bytes([mods, 0, key, 0, 0, 0, 0, 0, 5])  # 50 ms, then the board sends "all keys up"
            r[e + 2] = row
            r[e + 3] = 1
        self._update_crc()
        return True

    def clear_macro_trigger(self, n: int) -> None:
        e = OFF_PROG_KEYS + 4 * n
        self._raw[e] = 0xFF
        self._raw[e + 1] = 0xFF
        self._update_crc()


def is_safe_edit(old: XYConfig, new: XYConfig) -> bool:
    """A write is only allowed when nothing but editable header fields, matrix key words, the Fn layer,
    macros and the CRC changed, and every changed value is allowed."""
    o, n = old.raw, new.raw
    if len(o) != SIZE or len(n) != SIZE:
        return False

    def same(a: int, b: int) -> bool:
        return o[a:b] == n[a:b]

    if not (same(0x000, 0x002) and same(0x006, 0x008)):
        return False
    kt, kt_end = KEY_TABLE_OFFSET, KEY_TABLE_OFFSET + MATRIX_KEYS * 2
    if not (same(0x01E, kt) and same(kt_end, OFF_FN_SCAN) and same(FN_END, OFF_PROG_KEYS) and same(PROG_END, OFF_CRC)):
        return False
    for idx in range(MATRIX_KEYS):
        if old.key_word(idx) != new.key_word(idx) and not is_allowed(new.key_word(idx)):
            return False
    if not same(OFF_FN_SCAN, FN_END):
        seen = set()
        for i in range(FN_SLOTS):
            scan, word = new.fn_slot(i)
            if scan == 0xFF:
                continue
            if not (is_physical_scan(scan) and is_allowed(word) and word != 0xFFFF and scan not in seen):
                return False
            seen.add(scan)
    if not same(OFF_PROG_KEYS, PROG_END):
        for m in range(MACRO_SLOTS):
            e = OFF_PROG_KEYS + 4 * m
            s1, s2, start, count = n[e], n[e + 1], n[e + 2], n[e + 3]
            if s1 != 0xFF:
                if not (is_physical_scan(s1) and (s2 in (0xFD, 0xFE) or is_physical_scan(s2))):
                    return False
            elif s2 != 0xFF:
                return False
            if start + count > MACRO_ROW_COUNT:
                return False
        for r in range(MACRO_ROW_COUNT):
            ro = OFF_PROG_ROWS + 9 * r
            if o[ro:ro + 9] == n[ro:ro + 9]:
                continue
            if n[ro + 1] != 0 or not all(k == 0 or is_macro_key(k) for k in n[ro + 2:ro + 8]):
                return False
    try:
        validate(n)
    except XYError:
        return False
    return True
