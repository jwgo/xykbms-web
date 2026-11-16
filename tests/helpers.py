from xykbms import config as C
from xykbms.config import XYConfig, crc32
from xykbms.mock import sample_config


def fix_crc(r: bytearray) -> bytearray:
    r[C.OFF_CRC:C.OFF_CRC + 4] = crc32(r[:C.CRC_LENGTH]).to_bytes(4, "little")
    return r


def counting_config() -> bytearray:
    """Valid config whose bytes are 0, 1, 2, ... (only version and CRC fixed up)."""
    r = bytearray(i & 0xFF for i in range(C.SIZE))
    r[0] = C.VERSION
    return fix_crc(r)


def with_word(cfg: XYConfig, idx: int, word: int) -> XYConfig:
    r = bytearray(cfg.raw)
    o = C.KEY_TABLE_OFFSET + idx * 2
    r[o:o + 2] = word.to_bytes(2, "little")
    return XYConfig(fix_crc(r))


def with_bytes(cfg: XYConfig, changes: dict[int, int]) -> XYConfig:
    r = bytearray(cfg.raw)
    for o, b in changes.items():
        r[o] = b
    return XYConfig(fix_crc(r))


def stock() -> XYConfig:
    return sample_config()
