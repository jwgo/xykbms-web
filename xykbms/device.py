"""xy_3dg12 vendor-channel protocol: HID Usage Page 0xFF00, Report ID 2, 19-byte packets.

Deliberately NOT implemented: BOOT mode (0xCC/0xCD), firmware upload, layer and pin writes.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from .config import (SIZE, XYBadState, XYConfig, XYError, XYInvalidConfig, XYIOError, XYNotFound, XYTimeout,
                     XYUnsafeWrite, is_safe_edit, validate)

PACKET_SIZE = 19
REPORT_ID = 0x02
FILL = 0xFD
KIND_CTRL = 0x3F
KIND_DATA = 0x3E
TIMEOUT_MS = 2000
RETRIES_CMD = 3
RETRIES_BULK = 6

Progress = Callable[[float], None] | None


class Transport(Protocol):
    def send(self, packet: bytes) -> None: ...
    def receive(self, timeout_ms: int) -> bytes: ...  # raises XYTimeout
    def flush(self) -> None: ...
    def close(self) -> None: ...


def packet(*parts) -> bytes:
    b = bytearray()
    for p in parts:
        b += bytes([p]) if isinstance(p, int) else bytes(p)
    b = b[:PACKET_SIZE]
    return bytes(b + bytes(PACKET_SIZE - len(b)))


def _not_found() -> XYNotFound:
    return XYNotFound("키보드를 찾지 못했어요. 절전 모드(트랙포인트 꺼짐)라면 Fn을 누른 채 다시 시도해 주세요")


class XYDevice:
    def __init__(self, transport: Transport, settle_delay: float = 0.3):
        self.transport = transport
        self.settle_delay = settle_delay  # pause after a config write; tests set 0

    # low level
    def _transfer(self, req: bytes, retries: int) -> bytes:
        i = 0
        while True:
            self.transport.flush()
            self.transport.send(req)
            try:
                return self.transport.receive(TIMEOUT_MS)
            except XYTimeout:
                i += 1
                if i >= retries:
                    raise

    def _ctrl(self, cmd: int) -> None:
        """'02 3f <cmd>' -> '02 3f <cmd>'"""
        req = packet(REPORT_ID, KIND_CTRL, cmd)
        for i in range(RETRIES_CMD):
            try:
                res = self._transfer(req, 1)
            except XYTimeout:
                if i + 1 < RETRIES_CMD:
                    continue
                raise _not_found()
            if res[1] == KIND_CTRL and res[2] == cmd:
                return
            if res[1] != FILL and res[2] != FILL:
                break
        raise XYBadState()

    def _data(self, cmd: int, payload: bytes = b"", want_reply: bool = False) -> bytes:
        """'02 3e <cmd> <data>'. With want_reply the reply payload (bytes 1..) is returned, else it must echo cmd."""
        assert len(payload) <= 16
        req = packet(REPORT_ID, KIND_DATA, cmd, payload)
        for i in range(RETRIES_CMD):
            try:
                res = self._transfer(req, 1)
            except XYTimeout:
                if i + 1 < RETRIES_CMD:
                    continue
                raise _not_found()
            if want_reply:
                return bytes(res[1:])
            if res[1] == cmd:
                return b""
            if res[1] != FILL or res[2] != FILL:
                break
        raise XYBadState()

    # queries (read-only)
    def version(self) -> str:
        r = self._data(0x6B, want_reply=True)
        out = bytearray()
        for b in r[:18]:
            if b in (0, FILL):
                break
            out.append(b)
        if not out or not all(0x20 <= b < 0x7F for b in out):
            raise XYInvalidConfig(f"버전 응답이 ASCII가 아니에요 ({r[:18].hex(' ')}). 이 보드는 다른 방언일 수 있어요")
        return out.decode("ascii")

    def battery_millivolts(self) -> int:
        r = self._data(0x6A, want_reply=True)
        return int.from_bytes(r[0:4], "little")

    def read_config(self, progress: Progress = None) -> XYConfig:
        """Reads and validates the 1 KiB config. The '02 ff ff' terminator is always sent, also on failure."""
        self._ctrl(0x22)
        tmp = bytearray(b"\xff" * SIZE)
        idx = 0
        blocks = SIZE // 8

        def terminate():
            try:
                self.transport.send(packet(REPORT_ID, 0xFF, 0xFF))
            except Exception:
                pass

        try:
            while idx < blocks:
                if progress:
                    progress(idx / blocks)
                res = self._transfer(packet(REPORT_ID, idx & 0xFF, idx >> 8), RETRIES_BULK)
                ridx = res[1] | res[2] << 8
                if ridx * 8 > SIZE - 8:
                    raise XYIOError(f"잘못된 패킷 번호 0x{ridx:04x}")
                tmp[ridx * 8:ridx * 8 + 8] = res[3:11]
                idx = ridx + 1
        except BaseException:
            terminate()
            raise
        terminate()
        if progress:
            progress(1)
        return XYConfig(tmp)

    # writes
    def set_backlight(self, percent: int) -> None:
        """Runtime command; nothing is stored in the config."""
        self._data(0x66, bytes([min(max(int(percent), 0), 100)]))

    def write_config(self, new: XYConfig, original: XYConfig, progress: Progress = None) -> None:
        """`original` is the config read fresh from the device; only editable areas may differ."""
        if not is_safe_edit(original, new):
            raise XYUnsafeWrite("편집 가능한 항목 밖의 바이트가 달라요")
        self._write_blocks(new, progress)

    def write_backup(self, backup: XYConfig, progress: Progress = None) -> None:
        """Recovery: writes a byte-exact validated backup with the normal config-write stream (never BOOT mode)."""
        validate(backup.raw)
        self._write_blocks(backup, progress)

    def _write_blocks(self, cfg: XYConfig, progress: Progress) -> None:
        self._ctrl(0x11)
        buf = cfg.raw
        nblocks = len(buf) // 16
        idx = 0
        while True:
            if progress:
                progress(min(idx, nblocks) / nblocks)
            if idx >= nblocks:
                # end marker: block 64, no 0x80 flag. The board then commits and resets itself (USB re-enumerates);
                # this handle must not be used again, callers reconnect.
                self.transport.send(packet(REPORT_ID, idx & 0xFF, idx >> 8, b"\xff" * 16))
                time.sleep(self.settle_delay)
                self.transport.flush()
                break
            req = packet(REPORT_ID, idx & 0xFF, idx >> 8, buf[idx * 16:idx * 16 + 16])
            res = self._transfer(req, RETRIES_BULK)
            if res[1] == 0x11 and res[2] == 0x22:
                idx += 1
            else:
                idx = (res[1] | res[2] << 8) & 0x3FFF
        if progress:
            progress(1)


# --- backups -----------------------------------------------------------------------------------

def backup_dir() -> Path:
    """Per-user backup folder; XYKBMS_BACKUP_DIR overrides it."""
    env = os.environ.get("XYKBMS_BACKUP_DIR")
    if env:
        return Path(env)
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/XYKBMS/backups"
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "XYKBMS/backups"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "xykbms/backups"


def save_backup(cfg: XYConfig, note: str = "") -> Path:
    d = backup_dir()
    d.mkdir(parents=True, exist_ok=True)
    name = f"xykbms_config-{datetime.now():%Y%m%d-%H%M%S}{'-' + note if note else ''}.bin"
    p = d / name
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(cfg.raw)
    os.replace(tmp, p)
    return p


def list_backups() -> list[Path]:
    d = backup_dir()
    if not d.is_dir():
        return []
    return sorted((p for p in d.iterdir() if p.suffix == ".bin"), key=lambda p: p.name, reverse=True)


def load_backup(p: Path) -> XYConfig:
    return XYConfig(p.read_bytes())


# --- apply: fresh read -> backup -> build target -> guard -> write -> reconnect -> byte-exact read back --

class ApplyRefused(XYError):
    """Nothing was sent to the board."""


class ApplyInterrupted(XYError):
    def __init__(self, why: str, backup: Path):
        super().__init__(f"쓰는 도중 문제가 생겼어요 ({why}). 수신기를 뽑았다 다시 꽂은 뒤 다시 시도해 주세요. "
                         f"직전 설정 백업: {backup.name}")
        self.backup = backup


class ApplyReconnectFailed(XYError):
    def __init__(self, why: str, backup: Path):
        super().__init__(f"설정은 썼지만 키보드에 다시 연결하지 못했어요 ({why}). USB를 뽑았다 다시 꽂고 다시 시도해 주세요. "
                         f"직전 설정 백업: {backup.name}")
        self.backup = backup


class ApplyMismatch(XYError):
    def __init__(self, after: XYConfig, backup: Path, device: "XYDevice"):
        super().__init__(f"쓴 뒤 다시 읽은 값이 달라요. 키보드에 실제로 있는 값을 보여 주고 있어요. 직전 설정 백업: {backup.name}")
        self.after = after
        self.backup = backup
        self.device = device


@dataclass
class ApplyOutcome:
    wrote: bool
    before: XYConfig
    after: XYConfig
    backup: Path | None
    device: XYDevice  # a new connection when wrote is True


def apply(device: XYDevice, reconnect: Callable[[], XYDevice], edit: Callable[[XYConfig], XYConfig],
          save: Callable[[XYConfig], Path] = lambda c: save_backup(c, "before-write"),
          progress: Progress = None) -> ApplyOutcome:
    fresh = device.read_config()
    target = edit(fresh)
    if target == fresh:
        return ApplyOutcome(False, fresh, fresh, None, device)
    if not is_safe_edit(fresh, target):
        raise ApplyRefused("허용된 항목 밖의 바이트가 달라서 쓰기를 막았어요. 보드에는 아무것도 보내지 않았어요")
    backup = save(fresh)
    try:
        device.write_config(target, fresh, progress)
    except XYUnsafeWrite as e:
        raise ApplyRefused(e.why)
    except Exception as e:
        raise ApplyInterrupted(str(e), backup)
    try:
        new_device = reconnect()
        after = new_device.read_config()
    except Exception as e:
        raise ApplyReconnectFailed(str(e), backup)
    if after.raw != target.raw:
        raise ApplyMismatch(after, backup, new_device)
    return ApplyOutcome(True, fresh, after, backup, new_device)
