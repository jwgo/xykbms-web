"""HTTP API against the mock board: edits, apply, and request filtering."""

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from xykbms.mock import sample_config
from xykbms.server import App, make_handler


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["XYKBMS_BACKUP_DIR"] = cls.tmp.name
        cls.app = App(sample_config())
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = cls.srv.server_address[1]
        cls.srv.RequestHandlerClass = make_handler(cls.app, port)
        cls.base = f"http://127.0.0.1:{port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.app.connect()
        cls.wait_idle()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        del os.environ["XYKBMS_BACKUP_DIR"]
        cls.tmp.cleanup()

    @classmethod
    def wait_idle(cls):
        for _ in range(100):
            if not cls.app.busy:
                return
            time.sleep(0.02)
        raise AssertionError("still busy")

    def post(self, path, body, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), h, method="POST")
        with urllib.request.urlopen(req) as r:
            return json.load(r)

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return json.load(r)

    def edit(self, op, **kw):
        return self.post("/api/edit", {"op": op, **kw})

    def setUp(self):
        self.edit("discard")

    def test_state_and_meta(self):
        s = self.get("/api/state")
        self.assertEqual(s["link"], "connected")
        self.assertFalse(s["dirty"])
        self.assertEqual(len(s["base"]), 128)
        m = self.get("/api/meta")
        self.assertGreater(len(m["caps"]), 90)

    def test_every_edit_op(self):
        ops = [("set_key", {"idx": 16, "word": 5}), ("reset_key", {"idx": 16, "layer": "base"}),
               ("set_fn", {"scan": 22, "word": 242}), ("reset_key", {"idx": 22, "layer": "fn"}),
               ("clear_fn", {"scan": 0x77}), ("macbook_fn_row", {}), ("reset_all_keys", {}), ("mac_preset", {}),
               ("set_alt_win", {"on": False}), ("set_ralt_cmd", {"on": True}),
               ("set_field", {"name": "moveSpeed", "value": 180}), ("set_flag", {"group": "a", "bit": 64, "on": True}),
               ("set_macro", {"n": 2, "mods": 9, "key": 20}), ("bind_macro", {"n": 2, "idx": 103}),
               ("clear_macro_trigger", {"n": 0}), ("backup_now", {})]
        for op, kw in ops:
            r = self.edit(op, **kw)
            self.assertTrue(r["ok"], (op, r.get("error")))
        self.assertTrue(r["state"]["dirty"])
        name = r["state"]["backups"][0]
        self.assertTrue(self.edit("load_backup", name=name)["ok"])

    def test_refusals(self):
        for op, kw in [("set_key", {"idx": 128, "word": 4}), ("set_key", {"idx": 16, "word": 0x66}),
                       ("load_backup", {"name": "../../etc/passwd"}), ("set_flag", {"group": "b", "bit": 128, "on": True}),
                       ("clear_macro_trigger", {"n": 9}), ("reset_key", {"idx": 500}), ("nope", {})]:
            r = self.edit(op, **kw)
            self.assertFalse(r["ok"], op)
            self.assertTrue(r["error"])
        self.assertFalse(self.get("/api/state")["dirty"])

    def test_apply(self):
        self.edit("set_field", name="scrollSpeed", value=3)
        self.edit("set_fn", scan=22, word=242)
        self.post("/api/apply", {})
        self.wait_idle()
        s = self.get("/api/state")
        self.assertFalse(s["dirty"])
        self.assertEqual(s["header"]["scrollSpeed"], 3)
        self.assertEqual(s["fn"]["22"]["w"], 242)
        self.assertFalse(s["event"]["error"])
        self.assertTrue(any(b.endswith("-before-write.bin") for b in s["backups"]))

    def test_foreign_requests_are_rejected(self):
        for headers in ({"Origin": "http://evil.example"}, {"Content-Type": "text/plain"}, {"Host": "evil.example"}):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.post("/api/edit", {"op": "discard"}, headers)
            self.assertEqual(cm.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
