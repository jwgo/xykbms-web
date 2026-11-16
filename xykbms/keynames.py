"""Keycap text, palette groups, macro presets and the X220 keyboard picture."""

from __future__ import annotations

from .config import PROG_KEYS
from .stock import X220_TABLE

_PUNCT = {0x2D: "-", 0x2E: "=", 0x2F: "[", 0x30: "]", 0x31: "\\", 0x33: ";", 0x34: "'", 0x35: "`", 0x36: ",",
          0x37: ".", 0x38: "/"}
_NAMED = {
    0x28: "Enter", 0x29: "Esc", 0x2A: "⌫", 0x2B: "Tab", 0x2C: "Space", 0x39: "Caps", 0x46: "PrtSc", 0x47: "ScrLk",
    0x48: "Pause", 0x49: "Ins", 0x4A: "Home", 0x4B: "PgUp", 0x4C: "Del", 0x4D: "End", 0x4E: "PgDn", 0x4F: "→",
    0x50: "←", 0x51: "↓", 0x52: "↑", 0x53: "NumLk", 0x65: "Menu", 0x90: "한/영", 0x91: "한자", 0x92: "Lang3",
}
_MODS = {
    0x4000: ("Ctrl", "⌃"), 0x4001: ("Shift", "⇧"), 0x4002: ("Alt", "⌥"), 0x4003: ("Win", "⌘"),
    0x4004: ("Ctrl", "⌃"), 0x4005: ("Shift", "⇧"), 0x4006: ("Alt", "⌥"), 0x4007: ("RWin", "⌘"),
}
_MOUSE = {
    0x5001: ("좌클릭", "🖱"), 0x5002: ("우클릭", "🖱"), 0x5004: ("가운데", "🖱"),
    0x51FE: ("◀︎", "마우스"), 0x5102: ("▶︎", "마우스"), 0x5202: ("▲", "마우스"), 0x52FE: ("▼", "마우스"),
    0x5301: ("휠 ▲", None), 0x53FF: ("휠 ▼", None),
}
_MEDIA = {
    0x80E2: ("Mute", "🔇"), 0x80E9: ("Vol +", "🔊"), 0x80EA: ("Vol −", "🔉"), 0x80CD: ("▶︎❚❚", None),
    0x80B5: ("⏭", "다음"), 0x80B6: ("⏮", "이전"), 0x80B7: ("⏹", "정지"), 0x8224: ("Back", "뒤로"),
    0x8225: ("Fwd", "앞으로"), 0x8192: ("계산기", None),
    0x8070: ("☀︎−", "밝기"), 0x806F: ("☀︎+", "밝기"), 0x829F: ("MC", "Mission Ctrl"), 0x82A0: ("LP", "Launchpad"),
    0x8221: ("🔍", "Spotlight"), 0x80CF: ("🎤", "받아쓰기"), 0x809B: ("🌙", "방해금지"),
}

# MacBook top row for Fn+F1..F12
MACBOOK_FN_ROW = [0x8070, 0x806F, 0x829F, 0x8221, 0x80CF, 0x809B, 0x80B6, 0x80CD, 0x80B5, 0x80E2, 0x80EA, 0x80E9]

EXTRA_BUTTON_NAMES = {0x67: "마이크 음소거 버튼", 0x07: "ThinkVantage 버튼"}


def label(w: int) -> tuple[str, str | None]:
    if w == 0xFFFF:
        return ("—", None)
    for table in (_MODS, _MEDIA, _MOUSE):
        if w in table:
            return table[w]
    if w in PROG_KEYS:
        return (f"M{w - 0xF0}", "매크로")
    if w >> 14 == 0:
        u = w & 0x3FFF
        if 0x04 <= u <= 0x1D:
            return (chr(0x41 + u - 4), None)
        if 0x1E <= u <= 0x26:
            return (str(u - 0x1D), None)
        if u == 0x27:
            return ("0", None)
        if 0x3A <= u <= 0x45:
            return (f"F{u - 0x39}", None)
        if 0x68 <= u <= 0x73:
            return (f"F{u - 0x68 + 13}", None)
        if u in _PUNCT:
            return (_PUNCT[u], None)
        if u in _NAMED:
            return (_NAMED[u], None)
    return (f"{w:04X}", None)


def key_name(idx: int) -> str:
    """Name of the physical key at a scan index (its factory legend)."""
    if idx in EXTRA_BUTTON_NAMES:
        return EXTRA_BUTTON_NAMES[idx].replace(" 버튼", "")
    return label(X220_TABLE[idx])[0]


def chord(mods: int, key: int) -> str:
    """⌃⌥⇧⌘ + key. Modifier bits: Ctrl, Shift, Alt, GUI (left, then right)."""
    s = ""
    if mods & 0x11: s += "⌃"
    if mods & 0x44: s += "⌥"
    if mods & 0x22: s += "⇧"
    if mods & 0x88: s += "⌘"
    if key:
        s += label(key)[0]
    return s or "비어 있음"


def macro_summary(m) -> str:
    if m.is_empty:
        return "비어 있음"
    def first(r):
        return next((k for k in r.keys if k), 0)
    if len(m.rows) == 1 and sum(1 for k in m.rows[0].keys if k) <= 1:
        return chord(m.rows[0].mods, first(m.rows[0]))
    s = " ".join(chord(r.mods, first(r)) for r in m.rows[:4])
    return s + (" …" if len(m.rows) > 4 else "") + f" ({len(m.rows)}줄)"


PRESETS = [
    ("영역 스크린샷 ⌘⇧4", 0x0A, 0x21), ("스크린샷 도구 ⌘⇧5", 0x0A, 0x22), ("화면 잠금 ⌃⌘Q", 0x09, 0x14),
    ("Spotlight ⌘Space", 0x08, 0x2C), ("입력 소스 전환 ⌃Space", 0x01, 0x2C), ("이모지 ⌃⌘Space", 0x09, 0x2C),
    ("Mission Control ⌃↑", 0x01, 0x52), ("강제 종료 창 ⌥⌘Esc", 0x0C, 0x29), ("Zoom 마이크 ⌘⇧A", 0x0A, 0x04),
    ("Google Meet 마이크 ⌘D", 0x08, 0x07), ("Teams/Discord 마이크 ⌘⇧M", 0x0A, 0x10),
]

GROUPS = [
    ("문자", list(range(0x04, 0x1E)), False),
    ("숫자·기호", list(range(0x1E, 0x28)) + [0x2D, 0x2E, 0x2F, 0x30, 0x31, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38], False),
    ("편집·이동", [0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x39, 0x49, 0x4C, 0x4A, 0x4D, 0x4B, 0x4E, 0x50, 0x52, 0x51, 0x4F], False),
    ("펑션", list(range(0x3A, 0x46)), False),
    ("수정키", list(range(0x4000, 0x4008)), False),
    ("미디어", [0x80E2, 0x80EA, 0x80E9, 0x80CD, 0x80B6, 0x80B5, 0x80B7, 0x8224, 0x8225, 0x8192], False),
    ("맥 기능", [0x8070, 0x806F, 0x829F, 0x82A0, 0x8221, 0x80CF, 0x809B], True),
    ("매크로", list(range(0xF1, 0xF6)), False),
    ("마우스", [0x5001, 0x5002, 0x5004, 0x51FE, 0x5102, 0x5202, 0x52FE, 0x5301, 0x53FF], False),
    ("시스템", [0x46, 0x47, 0x48, 0x65, 0x53], False),
    ("실험적", [0x90, 0x91] + list(range(0x68, 0x74)), True),
    ("비활성", [0xFFFF], False),
]

# --- keyboard picture (ThinkPad X220, key units) -------------------------------------------------

WIDTH, HEIGHT = 16.75, 6.55
NUB = (6.75, 4.45)


def _build_caps() -> list[dict]:
    stock_index = {}
    for i, w in enumerate(X220_TABLE):
        if w != 0xFFFF:
            stock_index[w] = i
    out: list[dict] = []

    def k(word, x, y, w=1.0, h=1.0, fn=None, kind="key", enter=False):
        i = stock_index.get(word)
        if i is None:
            return
        out.append(dict(index=i, x=x, y=y, w=w, h=h, kind=kind, fn=fn, enter=enter))

    ra, rb, sh = 0.0, 0.68, 0.6
    k(0x80E2, 1.15, ra, 0.7, sh, kind="bezel")
    k(0x80EA, 2.0, ra, 0.75, sh, kind="bezel")
    k(0x80E9, 2.75, ra, 0.75, sh, kind="bezel")
    # not in the factory table, scan indexes from the ZMK X220 matrix
    out.append(dict(index=0x67, x=3.7, y=ra, w=0.7, h=sh, kind="bezel", label="Mic", fn=None, enter=False))
    out.append(dict(index=0x07, x=4.6, y=ra, w=1.3, h=sh, kind="bezel", label="ThinkVantage", fn=None, enter=False))
    k(0x46, 8.25, ra, 0.88, sh, fn="SysRq")
    k(0x47, 9.13, ra, 0.88, sh, fn="NmLk")
    k(0x48, 10.01, ra, 0.88, sh, fn="Break")
    k(0x49, 10.89, ra, 0.88, sh)
    k(0x4C, 12.3, 0, 1.0, rb + sh)  # tall Delete
    k(0x4A, 13.4, ra, 0.85, sh, fn="☀")
    k(0x4B, 14.25, ra, 0.85, sh, fn="💡")
    k(0x4D, 13.4, rb, 0.85, sh, fn="☼")
    k(0x4E, 14.25, rb, 0.85, sh)

    k(0x29, 0, rb, 1.0, sh)  # Esc
    f_legends = {2: "🔒", 3: "🔋", 4: "☾", 5: "📶", 6: "📷", 7: "🖥", 8: "TP", 12: "💤"}
    for n in range(1, 13):
        group = (n - 1) // 4
        k(0x39 + n, 1.15 + (n - 1) * 0.88 + group * 0.25, rb, 0.88, sh, fn=f_legends.get(n))

    y1, y2, y3, y4, y5 = 1.45, 2.45, 3.45, 4.45, 5.45
    k(0x35, 0, y1)
    for d in range(10):
        k(0x1E + d, 1 + d, y1)
    k(0x2D, 11, y1); k(0x2E, 12, y1); k(0x2A, 13, y1, 2)

    k(0x2B, 0, y2, 1.5)
    for n, w in enumerate([0x14, 0x1A, 0x08, 0x15, 0x17, 0x1C, 0x18, 0x0C, 0x12, 0x13]):
        k(w, 1.5 + n, y2)
    k(0x2F, 11.5, y2); k(0x30, 12.5, y2); k(0x31, 13.5, y2, 1.5)

    k(0x39, 0, y3, 1.75)
    for n, w in enumerate([0x04, 0x16, 0x07, 0x09, 0x0A, 0x0B, 0x0D, 0x0E, 0x0F]):
        k(w, 1.75 + n, y3)
    k(0x33, 10.75, y3); k(0x34, 11.75, y3); k(0x28, 12.75, y3, 2.25, enter=True)

    k(0x4001, 0, y4, 2.25)
    for n, w in enumerate([0x1D, 0x1B, 0x06, 0x19, 0x05, 0x11, 0x10, 0x36, 0x37, 0x38]):
        k(w, 2.25 + n, y4)
    k(0x4005, 12.25, y4, 1.6)
    k(0x8224, 13.95, y4 + 0.1, 0.9, 0.9)
    k(0x52, 14.85, y4 + 0.1, 0.9, 0.9, fn="■")
    k(0x8225, 15.75, y4 + 0.1, 0.9, 0.9)

    out.append(dict(index=None, x=0, y=y5, w=1.25, h=1, kind="fixedFn", label="Fn", fn=None, enter=False))
    k(0x4000, 1.25, y5, 1.25)
    k(0x4003, 2.5, y5, 1.0)
    k(0x4002, 3.5, y5, 1.25)
    k(0x2C, 4.75, y5, 6.0, fn="🔍")
    k(0x4006, 10.75, y5)
    k(0x65, 11.75, y5)
    k(0x4004, 12.75, y5)
    k(0x50, 13.95, y5 + 0.1, 0.9, 0.9, fn="⏮")
    k(0x51, 14.85, y5 + 0.1, 0.9, 0.9, fn="⏯")
    k(0x4F, 15.75, y5 + 0.1, 0.9, 0.9, fn="⏭")
    return out


CAPS = _build_caps()


def unplaced() -> list[int]:
    placed = {c["index"] for c in CAPS if c["index"] is not None}
    return [i for i, w in enumerate(X220_TABLE) if w != 0xFFFF and i not in placed]
