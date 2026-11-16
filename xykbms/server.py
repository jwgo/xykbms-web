"""Local web UI server. Holds the device connection, the config read from the board (`device`) and the edited
copy (`draft`). The browser only sends edit operations; every check and every byte decision stays here.

Only listens on 127.0.0.1. POSTs need a JSON body and a matching Host/Origin, so other web pages
cannot drive the board.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from . import config as C
from .config import XYConfig, XYError
from .mock import sample_config
from .device import (ApplyInterrupted, ApplyMismatch, ApplyReconnectFailed, XYDevice, apply, backup_dir,
                     list_backups, load_backup, save_backup)
from .keynames import (CAPS, EXTRA_BUTTON_NAMES, GROUPS, HEIGHT, MACBOOK_FN_ROW, NUB, PRESETS, WIDTH, chord,
                       key_name, label, macro_summary)
from .stock import X220_TABLE

STATIC = Path(__file__).with_name("static")


def lab(w: int) -> dict:
    m, s = label(w)
    return {"w": w, "main": m, "sub": s}


def hardware_rows(c: XYConfig) -> list[list[str]]:
    """What the board's own config says about the hardware (read-only)."""
    r = c.raw

    def u16(o):
        return r[o] | r[o + 1] << 8

    def pin(b):
        return "없음" if b == 0xFF else f"{b}번"

    used = sum(1 for i in range(C.MATRIX_KEYS) if c.key_word(i) != 0xFFFF)
    out = [
        ["보드 종류", c.board_title],
        ["키 매트릭스", f"{r[0x3A]} × {r[0x4F]} = {r[0x3A] * r[0x4F]}자리, 키 {used}개 사용"],
        ["Caps Lock LED 핀", pin(r[0x35])],
        ["Num/Scroll LED 핀", f"{pin(r[0x34])} / {pin(r[0x36])}"],
        ["백라이트 PWM 핀", "없음 (백라이트 불가)" if r[0x39] == 0xFF else pin(r[0x39])],
        ["충전·저전압 감지", "없음 (유선)" if r[0x38] == 0xFF and r[0x37] == 0xFF else "있음"],
    ]
    fnk = {0x00: f"전용 IO 핀 {r[0x1E5]}번", 0x01: f"매트릭스 스캔 0x{r[0x1E5]:02X}"}.get(r[0x1E4], "없음")
    out.append(["Fn 키", fnk])
    lines = []
    for i in range(C.FN_SLOTS):
        scan = r[0x1E6 + i]
        if scan == 0xFF:
            continue
        frm = key_name(scan) if scan < C.MATRIX_KEYS else f"0x{scan:02X}"
        lines.append(f"Fn+{frm} → {label(u16(0x1F8 + 2 * i))[0]}")
    out.append(["Fn 레이어", ", ".join(lines) or "없음"])
    out.append(["프로그램(매크로) 키", f"{sum(1 for n in range(5) if r[0x26B + 4 * n] != 0xFF)}/5개 직접 트리거"])
    free = [n for n, o in (("트랙포인트 on/off 키", 0x25A), ("키보드 절전 키", 0x25C), ("Win 키 비활성 키", 0x258)) if r[o] == 0xFF]
    out.append(["지정 안 된 기능 슬롯", ", ".join(free) or "없음"])
    out.append(["플래그 B 미확인 비트", f"0x{r[0x00B] & 0xE0:02X} (그대로 유지)"])
    return out


class App:
    def __init__(self, mock_cfg: XYConfig | None = None):
        self.lock = threading.RLock()  # model state
        self.io = threading.Lock()     # every HID transfer; apply holds it from fresh read to read-back
        self.mock = None
        if mock_cfg is not None:
            from .mock import MockKeyboard
            self.mock = MockKeyboard(mock_cfg.raw)
        self.transport = None
        self.device: XYDevice | None = None
        self.link = "searching"
        self.link_error = ""
        self.version = ""
        self.battery_mv = 0
        self.dev_cfg: XYConfig | None = None
        self.draft: XYConfig | None = None
        self.busy = False
        self.progress = 0.0
        self._event_ids = itertools.count(1)
        self.event = None
        self._last_present = None

    # helpers
    def notify(self, text: str, error: bool = False) -> None:
        with self.lock:
            self.event = {"id": next(self._event_ids), "text": text, "error": error}

    def _open(self):
        if self.mock:
            return self.mock, XYDevice(self.mock, settle_delay=0)
        from .hidtransport import HIDTransport
        t = HIDTransport()
        return t, XYDevice(t)

    def _close(self) -> None:
        if self.transport is not None:
            try:
                self.transport.close()
            except Exception:
                pass
        self.transport = None
        self.device = None

    def _bg(self, fn) -> None:
        def run():
            try:
                fn()
            except Exception as e:  # pragma: no cover
                traceback.print_exc()
                with self.lock:
                    self.busy = False
                    self.progress = 0
                self.notify(str(e), True)
        threading.Thread(target=run, daemon=True).start()

    def _start(self) -> bool:
        with self.lock:
            if self.busy:
                return False
            self.busy = True
            return True

    # connection
    def connect(self) -> None:
        if not self._start():
            return
        with self.lock:
            self.link = "searching"

        def work():
            with self.io:
                self._close()
                try:
                    t, d = self._open()
                    self.transport, self.device = t, d
                    v, mv, cfg = d.version(), d.battery_millivolts(), d.read_config()
                    with self.lock:
                        self.version, self.battery_mv = v, mv
                        self.dev_cfg, self.draft = cfg, cfg.copy()
                        self.link, self.link_error = "connected", ""
                except Exception as e:
                    self._close()
                    with self.lock:
                        self.link, self.link_error = "failed", str(e)
                finally:
                    with self.lock:
                        self.busy = False
        self._bg(work)

    def tick(self) -> None:
        """Only reacts to plug/unplug; a failed link is retried by the user, not automatically."""
        if self.mock:
            return
        from .hidtransport import is_present
        with self.lock:
            if self.busy:
                return
            link = self.link
        # never enumerate while another thread talks to hidapi (e.g. apply's reconnect after the board reset)
        if not self.io.acquire(blocking=False):
            return
        try:
            present = is_present()
        finally:
            self.io.release()
        appeared = present and self._last_present is False
        self._last_present = present
        if link == "connected" and not present:
            with self.io:
                self._close()
            with self.lock:
                self.link, self.link_error = "failed", "키보드 연결이 끊겼어요"
        elif link != "connected" and appeared:
            self.connect()

    def reload(self) -> None:
        if self.link != "connected" or not self._start():
            return

        def work():
            try:
                with self.io:
                    d = self.device
                    if d is None:
                        raise C.XYNotFound("연결되지 않았어요")
                    v, mv, cfg = d.version(), d.battery_millivolts(), d.read_config()
                with self.lock:
                    self.version, self.battery_mv = v, mv
                    self.dev_cfg, self.draft = cfg, cfg.copy()
                self.notify("키보드에서 다시 읽었어요")
            except Exception as e:
                self.notify(str(e), True)
            finally:
                with self.lock:
                    self.busy = False
        self._bg(work)

    def apply(self) -> None:
        with self.lock:
            if self.link != "connected" or self.busy or self.draft is None:
                return
            draft = self.draft.copy()
            self.busy, self.progress = True, 0.0

        def set_progress(p):
            with self.lock:
                self.progress = p

        def reconnect():
            if self.mock:
                return XYDevice(self.mock, settle_delay=0)
            from .hidtransport import HIDTransport
            t2 = HIDTransport.reconnect_after_reset(self.transport)
            self.transport, self.device = t2, XYDevice(t2)
            return self.device

        def work():
            try:
                with self.io:
                    if self.device is None:
                        raise C.XYNotFound("연결되지 않았어요")
                    out = apply(self.device, reconnect, lambda fresh: fresh.with_editable_from(draft), progress=set_progress)
                    self.device = out.device
                with self.lock:
                    self.dev_cfg, self.draft = out.after, out.after.copy()
                self.notify("적용 완료. 쓴 값을 다시 읽어 확인했어요" if out.wrote else "바꿀 내용이 없어요")
            except (ApplyInterrupted, ApplyReconnectFailed) as e:
                with self.io:
                    self._close()
                with self.lock:
                    self.link, self.link_error = "failed", str(e)
            except ApplyMismatch as e:
                with self.lock:
                    self.dev_cfg, self.draft = e.after, e.after.copy()
                self.notify(str(e), True)
            except Exception as e:
                self.notify(str(e), True)
            finally:
                with self.lock:
                    self.busy, self.progress = False, 0.0
        self._bg(work)

    def backlight(self, percent: int) -> None:
        if self.link != "connected" or self.busy:
            return
        with self.io:
            if self.device:
                self.device.set_backlight(percent)

    # edits (draft only; nothing is sent until apply)
    def edit(self, op: str, a: dict) -> str | None:
        """Returns a message to show, raises XYError on refusal."""
        with self.lock:
            if self.busy:
                raise XYError("작업 중이에요. 끝난 뒤 다시 해 주세요")
            if self.draft is None or self.dev_cfg is None:
                raise XYError("키보드가 연결되지 않았어요")
            d = self.draft.copy()
            msg = None
            if op == "set_key":
                if not d.set_key_word(int(a["idx"]), int(a["word"])):
                    raise XYError("이 자리에는 그 값을 넣을 수 없어요")
            elif op == "set_fn":
                if not d.set_fn(int(a["scan"]), int(a["word"])):
                    raise XYError(f"Fn 조합 {C.FN_SLOTS}칸이 모두 찼거나 넣을 수 없는 값이에요")
            elif op == "reset_key":
                i = int(a["idx"])
                if not 0 <= i < C.MATRIX_KEYS:
                    raise XYError("키 번호가 잘못됐어요")
                if a.get("layer") == "fn":
                    w = self.dev_cfg.fn_word(i)
                    d.set_fn(i, 0xFFFF if w is None else w)
                else:
                    d.set_key_word(i, X220_TABLE[i] if X220_TABLE[i] != 0xFFFF else 0xFFFF)
            elif op == "clear_fn":
                d.set_fn(int(a["scan"]), 0xFFFF)
            elif op == "macbook_fn_row":
                failed = sum(0 if d.set_fn(X220_TABLE.index(0x3A + n), w) else 1 for n, w in enumerate(MACBOOK_FN_ROW))
                msg = (f"Fn 칸이 부족해서 {failed}개는 못 넣었어요" if failed
                       else "Fn+F1~F12를 맥북 배열로 채웠어요. '적용'을 눌러야 키보드에 써져요")
            elif op == "reset_all_keys":
                for i, w in enumerate(X220_TABLE):
                    if w != 0xFFFF:
                        d.set_key_word(i, w)
            elif op == "mac_preset":
                if d.alt_win_swapped is None:
                    raise XYError("이 키보드의 키맵이 기본형과 달라서 프리셋을 쓸 수 없어요")
                d.set_alt_win_swapped(True)
                if d.right_alt_is_command is not None:
                    d.set_right_alt_is_command(True)
            elif op == "set_alt_win":
                d.set_alt_win_swapped(bool(a["on"]))
            elif op == "set_ralt_cmd":
                d.set_right_alt_is_command(bool(a["on"]))
            elif op == "set_field":
                name, v = a["name"], a["value"]
                if name == "moveSpeed": d.move_speed = int(v)
                elif name == "scrollSpeed": d.scroll_speed = int(v)
                elif name == "autoOff": d.auto_off_minutes = int(v)
                elif name == "tpAutoOff": d.tp_auto_off_minutes = int(v)
                elif name == "rfChannel": d.rf_channel = int(v)
                elif name == "rfMode": d.set_rf_mode(int(v))
                elif name == "btName": d.set_bluetooth_name(str(v))
                else: raise XYError("알 수 없는 항목")
            elif op == "set_flag":
                bit = int(a["bit"])
                known = {b for b, _, _ in (C.FLAG_NAMES_A if a["group"] == "a" else C.FLAG_NAMES_B)}
                if bit not in known:
                    raise XYError("알 수 없는 플래그")
                d.set_flag("a" if a["group"] == "a" else "b", bit, bool(a["on"]))
            elif op == "set_macro":
                if not d.set_macro_chord(int(a["n"]), int(a["mods"]), int(a["key"])):
                    raise XYError("매크로에 넣을 수 없는 키예요")
            elif op == "clear_macro_trigger":
                if not 0 <= int(a["n"]) < C.MACRO_SLOTS:
                    raise XYError("매크로 번호가 잘못됐어요")
                d.clear_macro_trigger(int(a["n"]))
            elif op == "bind_macro":
                n, idx = int(a["n"]), int(a["idx"])
                if not d.set_key_word(idx, 0xF1 + n):
                    raise XYError("그 키에는 매크로를 지정할 수 없어요")
                # a direct trigger on the same key (e.g. factory macro 1 on ThinkVantage) would fire as well
                for s in range(C.MACRO_SLOTS):
                    mc = d.macro(s)
                    if mc.scan1 == idx and mc.scan2 == 0xFD:
                        d.clear_macro_trigger(s)
            elif op == "discard":
                d = self.dev_cfg.copy()
            elif op == "load_backup":
                names = {p.name: p for p in list_backups()}
                p = names.get(str(a["name"]))
                if p is None:
                    raise XYError("그런 백업 파일이 없어요")
                d = self.dev_cfg.with_editable_from(load_backup(p))
                msg = "백업 값을 불러왔어요. 적용을 눌러야 키보드에 써져요"
            elif op == "backup_now":
                p = save_backup(self.dev_cfg, "manual")
                msg = f"백업 저장: {p.name}"
            else:
                raise XYError(f"알 수 없는 동작: {op}")
            self.draft = d
            return msg

    # views
    def changes(self) -> list[str]:
        a, b = self.dev_cfg, self.draft
        if a is None or b is None or a == b:
            return []
        out = []
        for name, fa, fb in (("트랙포인트 이동 속도", a.move_speed, b.move_speed), ("스크롤 속도", a.scroll_speed, b.scroll_speed),
                             ("키보드 자동 꺼짐(분)", a.auto_off_minutes, b.auto_off_minutes),
                             ("트랙포인트 자동 꺼짐(분)", a.tp_auto_off_minutes, b.tp_auto_off_minutes),
                             ("블루투스 이름", a.bluetooth_name, b.bluetooth_name),
                             ("연결 방식", C.RF_MODES.get(a.rf_mode, "?"), C.RF_MODES.get(b.rf_mode, "?")),
                             ("채널", a.rf_channel, b.rf_channel)):
            if fa != fb:
                out.append(f"{name} {fa} → {fb}")
        kd = [f"‘{key_name(i)}’ 자리: {label(a.key_word(i))[0]} → {label(b.key_word(i))[0]}"
              for i in range(C.MATRIX_KEYS) if a.key_word(i) != b.key_word(i)]
        out += kd[:10]
        if len(kd) > 10:
            out.append(f"… 외 {len(kd) - 10}개 키")
        for i in range(C.MATRIX_KEYS):
            fa, fb = a.fn_word(i), b.fn_word(i)
            if fa != fb:
                out.append(f"Fn+{key_name(i)}: {'없음' if fa is None else label(fa)[0]} → {'없음' if fb is None else label(fb)[0]}")
        for n in range(C.MACRO_SLOTS):
            ma, mb = a.macro(n), b.macro(n)
            if ma != mb:
                out.append(f"매크로 {n + 1}: {macro_summary(ma)} → {macro_summary(mb)}"
                           + (" (직접 트리거 변경)" if ma.scan1 != mb.scan1 else ""))
        for flags, fa, fb in ((C.FLAG_NAMES_A, a.flags_a, b.flags_a), (C.FLAG_NAMES_B, a.flags_b, b.flags_b)):
            for bit, _, name in flags:
                if (fa ^ fb) & bit:
                    out.append(f"{name}: {'켬' if fb & bit else '끔'}")
        return out

    def macro_triggers(self, d: XYConfig, n: int) -> list[str]:
        w = 0xF1 + n
        out = [key_name(i) for i in range(C.MATRIX_KEYS) if d.key_word(i) == w]
        out += ["Fn+" + key_name(i) for i in range(C.MATRIX_KEYS) if d.fn_word(i) == w]
        mc = d.macro(n)
        if mc.scan1 != 0xFF and C.is_physical_scan(mc.scan1):
            first = key_name(mc.scan1)
            if mc.scan2 == 0xFD:
                out.append(f"{first} 단독 (직접 트리거)")
            elif mc.scan2 == 0xFE:
                out.append(f"Fn+{first} (직접 트리거)")
            else:
                out.append(f"{first}+{key_name(mc.scan2) if C.is_physical_scan(mc.scan2) else '?'} (직접 트리거)")
        return out

    def state(self) -> dict:
        with self.lock:
            s = {"link": self.link, "linkError": self.link_error, "busy": self.busy, "progress": self.progress,
                 "version": self.version, "batteryMV": self.battery_mv, "mock": self.mock is not None,
                 "event": self.event, "backupDir": str(backup_dir()),
                 "backups": [p.name for p in list_backups()[:30]]}
            d, dev = self.draft, self.dev_cfg
            if d is None or dev is None:
                return s
            caps = C.capabilities(dev.board)
            macros = []
            for n in range(C.MACRO_SLOTS):
                mc = d.macro(n)
                simple = len(mc.rows) <= 1
                r0 = mc.rows[0] if mc.rows else None
                macros.append({"summary": macro_summary(mc), "empty": mc.is_empty, "simple": simple,
                               "mods": r0.mods if r0 else 0, "key": next((k for k in r0.keys if k), 0) if r0 else 0,
                               "hasTrigger": mc.scan1 != 0xFF, "triggers": self.macro_triggers(d, n)})
            s.update({
                "dirty": d != dev, "changes": self.changes(), "caps": caps, "hasX220Pins": d.has_x220_pins,
                "board": dev.board_title, "wired": dev.board == C.WIRED_USB,
                "base": [lab(d.key_word(i)) for i in range(C.MATRIX_KEYS)],
                "fn": {str(i): lab(w) for i in range(C.MATRIX_KEYS) if (w := d.fn_word(i)) is not None},
                "devFn": {str(i): w for i in range(C.MATRIX_KEYS) if (w := dev.fn_word(i)) is not None},
                "fnUsed": d.fn_slots_used,
                "header": {"moveSpeed": d.move_speed, "scrollSpeed": d.scroll_speed, "autoOff": d.auto_off_minutes,
                           "tpAutoOff": d.tp_auto_off_minutes, "btName": d.bluetooth_name, "rfMode": d.rf_mode,
                           "rfChannel": d.rf_channel, "flagsA": d.flags_a, "flagsB": d.flags_b},
                "altWin": d.alt_win_swapped, "ralt": d.right_alt_is_command,
                "macros": macros, "hardware": hardware_rows(dev),
            })
            return s


def meta() -> dict:
    return {
        "width": WIDTH, "height": HEIGHT, "nub": NUB, "caps": CAPS,
        "stock": [lab(w) for w in X220_TABLE], "extraButtons": {str(k): v for k, v in EXTRA_BUTTON_NAMES.items()},
        "groups": [{"title": t, "experimental": e, "words": [lab(w) for w in ws]} for t, ws, e in GROUPS],
        "presets": [{"title": t, "mods": m, "key": k, "chord": chord(m, k)} for t, m, k in PRESETS],
        "macroKeys": [lab(k) for k in range(0x04, 0x66)],
        "flagsA": [{"bit": b, "id": i, "title": t} for b, i, t in C.FLAG_NAMES_A],
        "flagsB": [{"bit": b, "id": i, "title": t} for b, i, t in C.FLAG_NAMES_B],
        "rfModes": C.RF_MODES, "fnSlots": C.FN_SLOTS,
    }


def make_handler(app: App, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    meta_json = json.dumps(meta(), ensure_ascii=False).encode()

    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if os.environ.get("XYKBMS_VERBOSE"):
                super().log_message(fmt, *args)

        def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode())

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in allowed_hosts

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/api/meta":
                return self._send(200, meta_json)
            if path == "/api/state":
                return self._json(app.state())
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            origin = self.headers.get("Origin")
            if (not self._host_ok() or (origin and origin.split("://", 1)[-1] not in allowed_hosts)
                    or not self.headers.get("Content-Type", "").startswith("application/json")):
                return self._send(403, b"forbidden", "text/plain")
            try:
                n = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except (ValueError, json.JSONDecodeError):
                return self._json({"error": "잘못된 요청"}, 400)
            path = self.path
            try:
                msg = None
                if path == "/api/connect": app.connect()
                elif path == "/api/reload": app.reload()
                elif path == "/api/apply": app.apply()
                elif path == "/api/backlight": app.backlight(int(body.get("percent", 0)))
                elif path == "/api/edit": msg = app.edit(str(body.get("op")), body)
                else: return self._json({"error": "not found"}, 404)
                self._json({"ok": True, "message": msg, "state": app.state()})
            except (XYError, KeyError, ValueError, TypeError) as e:
                self._json({"ok": False, "error": str(e) or type(e).__name__, "state": app.state()})
            except Exception as e:
                traceback.print_exc()
                self._json({"ok": False, "error": f"내부 오류: {e}", "state": app.state()}, 500)

    return H


def main(argv=None):
    ap = argparse.ArgumentParser(prog="xykbms-web", description="XYKBMS 키보드 컨트롤러 웹 설정 도구")
    ap.add_argument("--port", type=int, default=8765, help="포트 (기본 8765)")
    ap.add_argument("--mock", nargs="?", const="", metavar="CONFIG.bin",
                    help="키보드 없이 목업 보드로 실행. 설정 파일을 주면 그 내용으로, 없으면 공장 기본형 X220 설정으로")
    ap.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = ap.parse_args(argv)

    mock_cfg = None
    if args.mock is not None:
        mock_cfg = load_backup(Path(args.mock)) if args.mock else sample_config()
        # never mix mock backups into the real backup folder
        os.environ.setdefault("XYKBMS_BACKUP_DIR", tempfile.mkdtemp(prefix="xykbms-mock-"))

    app = App(mock_cfg)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app, args.port))
    srv.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}/"
    print(f"XYKBMS 웹 UI: {url}" + ("  (목업 보드)" if app.mock else ""), flush=True)
    print(f"백업 폴더: {backup_dir()}", flush=True)
    app.connect()

    def ticker():
        while True:
            time.sleep(2)
            try:
                app.tick()
            except Exception:
                pass
    threading.Thread(target=ticker, daemon=True).start()
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with app.io:
            app._close()


if __name__ == "__main__":
    main()
