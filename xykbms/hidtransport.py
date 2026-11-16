"""hidapi transport for the vendor collection (Usage Page 0xFF00, Report ID 2).

The vendor collection shares its USB interface with the consumer-control collection (report ID 1, the media
keys), so the device must be opened WITHOUT seizing it. hidapi opens devices exclusively on macOS by default;
that is switched off through hid_darwin_set_open_exclusive(0), and nothing is opened if that is not possible.
On Linux the hidraw backend is preferred, because the libusb backend detaches the kernel driver.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time

from .config import XYIOError, XYNotFound, XYPermission, XYTimeout
from .device import PACKET_SIZE, REPORT_ID

VENDOR_ID = 0x5859
USAGE_PAGE = 0xFF00

hid = None
try:  # pip package "hidapi" (cython-hidapi)
    if sys.platform.startswith("linux"):
        try:
            import hidraw as hid
        except ImportError:
            import hid
    else:
        import hid
except ImportError:  # pragma: no cover
    pass

_VERBOSE = bool(os.environ.get("XYKBMS_VERBOSE"))
_exclusive_off = False


def _need_hid():
    if hid is None or not hasattr(hid, "device"):
        raise XYIOError("hidapi 모듈이 없어요. `pip install hidapi` 를 먼저 실행해 주세요")


def _ensure_non_exclusive() -> None:
    global _exclusive_off
    if _exclusive_off or sys.platform != "darwin":
        return
    lib = ctypes.CDLL(hid.__file__)
    try:
        setter, getter = lib.hid_darwin_set_open_exclusive, lib.hid_darwin_get_open_exclusive
    except AttributeError:
        raise XYIOError("이 hidapi 빌드에서 비독점 열기를 설정할 수 없어요. 미디어 키를 막지 않도록 열지 않았어요 (hidapi >= 0.12 필요)")
    setter.argtypes, setter.restype = [ctypes.c_int], None
    getter.argtypes, getter.restype = [], ctypes.c_int
    setter(0)
    if getter() != 0:
        raise XYIOError("hidapi 비독점 열기 설정에 실패했어요")
    _exclusive_off = True


def find() -> list[dict]:
    """Vendor-collection entries of XY boards (one per board)."""
    _need_hid()
    return [d for d in hid.enumerate(VENDOR_ID, 0) if d.get("usage_page") == USAGE_PAGE]


def is_present() -> bool:
    try:
        return bool(find())
    except Exception:
        return False


def _trace(arrow: str, p: bytes) -> None:
    if _VERBOSE:
        print(arrow, p.hex(" "), file=sys.stderr, flush=True)


class HIDTransport:
    def __init__(self):
        _need_hid()
        _ensure_non_exclusive()
        entries = find()
        if not entries:
            if hid.enumerate(VENDOR_ID, 0):
                raise XYNotFound("XY 키보드는 보이지만 설정용(0xFF00) 인터페이스를 찾지 못했어요")
            raise XYNotFound("XY 키보드(수신기)를 찾지 못했어요. USB 연결을 확인해 주세요")
        self._dev = hid.device()
        try:
            self._dev.open_path(entries[0]["path"])
        except (OSError, IOError) as e:
            if sys.platform == "darwin":
                raise XYPermission("HID 열기에 실패했어요. 시스템 설정 → 개인정보 보호 및 보안 → 입력 모니터링에서 "
                                   f"이 터미널(또는 Python)을 허용한 뒤 다시 시도해 주세요 ({e})")
            if sys.platform.startswith("linux"):
                raise XYPermission(f"HID 열기에 실패했어요. README의 udev 규칙을 설치했는지 확인해 주세요 ({e})")
            raise XYIOError(f"HID 열기 실패: {e}")
        self._open = True

    def send(self, p: bytes) -> None:
        assert len(p) == PACKET_SIZE and p[0] == REPORT_ID
        _trace("→", p)
        try:
            n = self._dev.write(bytes(p))
        except (OSError, IOError, ValueError) as e:
            raise XYIOError(f"쓰기 실패 ({e})")
        if n < 0:
            raise XYIOError("쓰기 실패")

    def receive(self, timeout_ms: int) -> bytes:
        """Waits for one 19-byte report 0x02. hidapi puts the report ID first for numbered reports;
        other report IDs (1 = consumer control) are dropped."""
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            left = int((deadline - time.monotonic()) * 1000)
            if left <= 0:
                raise XYTimeout()
            try:
                d = self._dev.read(64, left)
            except (OSError, IOError, ValueError) as e:
                raise XYIOError(f"읽기 실패 ({e})")
            if not d:
                raise XYTimeout()
            if d[0] != REPORT_ID:
                _trace("· (다른 리포트, 무시)", bytes(d))
                continue
            p = bytes(d[:PACKET_SIZE]).ljust(PACKET_SIZE, b"\0")
            _trace("←", p)
            return p

    def flush(self) -> None:
        try:
            self._dev.set_nonblocking(1)
            while self._dev.read(64):
                pass
        except (OSError, IOError, ValueError):
            pass
        finally:
            try:
                self._dev.set_nonblocking(0)
            except Exception:
                pass

    def close(self) -> None:
        if self._open:
            self._open = False
            try:
                self._dev.close()
            except Exception:
                pass

    @staticmethod
    def reconnect_after_reset(old: "HIDTransport | None", timeout: float = 12) -> "HIDTransport":
        """After a config write the board resets itself and re-enumerates. Close the dead handle, wait for the
        device to leave and come back, then open a fresh transport. The timings were found on real hardware."""
        if old:
            old.close()
        start = time.monotonic()
        saw_absent = False
        while time.monotonic() - start < timeout:
            if is_present():
                if saw_absent or time.monotonic() - start > 3:
                    break
            else:
                saw_absent = True
            time.sleep(0.2)
        # give the board time to finish booting: a read right after re-enumeration once left key input dead
        time.sleep(2.5)
        last: Exception = XYNotFound("쓰기 후 키보드가 다시 나타나지 않았어요. USB를 뽑았다 다시 꽂아 주세요")
        for _ in range(12):
            try:
                return HIDTransport()
            except Exception as e:
                last = e
                time.sleep(0.5)
        raise last
