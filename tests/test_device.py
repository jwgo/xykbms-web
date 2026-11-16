import tempfile
import unittest
from pathlib import Path

from xykbms import config as C
from xykbms.config import XYConfig, XYError
from xykbms.device import ApplyRefused, XYDevice, apply, load_backup, save_backup
from xykbms.mock import MockKeyboard

from helpers import counting_config, stock, with_bytes, with_word

NULL = Path("/dev/null")


def no_backup(_cfg):
    return NULL


class Protocol(unittest.TestCase):
    def setUp(self):
        self.raw = bytes(counting_config())
        self.kb = MockKeyboard(self.raw)
        self.dev = XYDevice(self.kb, settle_delay=0)

    def test_queries(self):
        self.assertEqual(self.dev.version(), "2023.12.06")
        self.assertEqual(self.dev.battery_millivolts(), 3868)

    def test_read_config(self):
        self.assertEqual(self.dev.read_config().raw, self.raw)

    def test_write_with_resend(self):
        self.kb.resend_once = 1
        read = self.dev.read_config()
        e = read.copy()
        e.move_speed = 0x80
        self.dev.write_config(e, read)
        self.assertTrue(self.kb.cfg_written)
        self.assertEqual(bytes(self.kb.cfg_new), e.raw)

    def test_unsafe_write_is_refused_before_sending(self):
        read = self.dev.read_config()
        evil = with_bytes(read, {0x100: read.raw[0x100] ^ 1, 0x01: 99})
        with self.assertRaises(XYError):
            self.dev.write_config(evil, read)
        self.assertFalse(self.kb.cfg_written)

    def test_backup_restore_writes_bytes_as_is(self):
        base = XYConfig(self.raw)
        other = with_bytes(base, {0x100: base.raw[0x100] ^ 0x5A})
        kb = MockKeyboard(other.raw)
        XYDevice(kb, 0).write_backup(base)
        self.assertEqual(bytes(kb.cfg_new), base.raw)

    def test_backlight_and_no_boot(self):
        self.dev.set_backlight(100)
        self.assertEqual(self.kb.backlight, 100)
        self.dev.read_config()
        self.assertFalse(self.kb.saw_boot)


class Apply(unittest.TestCase):
    def test_write_reconnect_read_back(self):
        s = stock()
        target = s.copy()
        target.set_alt_win_swapped(True)
        target.set_fn(0x16, 0x00F3)
        target.set_macro_chord(2, 0x09, 0x14)
        kb = MockKeyboard(s.raw)
        out = apply(XYDevice(kb, 0), lambda: XYDevice(kb, 0), lambda fresh: fresh.with_editable_from(target), save=no_backup)
        self.assertTrue(out.wrote)
        self.assertEqual(out.after.raw, target.raw)

    def test_nothing_changed_writes_nothing(self):
        kb = MockKeyboard(stock().raw)
        d = XYDevice(kb, 0)
        out = apply(d, lambda: d, lambda c: c, save=no_backup)
        self.assertFalse(out.wrote)
        self.assertFalse(kb.cfg_written)

    def test_refused_without_sending(self):
        s = stock()
        kb = MockKeyboard(s.raw)
        d = XYDevice(kb, 0)
        with self.assertRaises(ApplyRefused):
            apply(d, lambda: d, lambda _: with_word(s, 0x80, 0x0004), save=no_backup)
        self.assertFalse(kb.cfg_written)


class Backups(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            import os
            os.environ["XYKBMS_BACKUP_DIR"] = td
            try:
                p = save_backup(stock(), "test")
                self.assertTrue(p.name.startswith("xykbms_config-") and p.name.endswith("-test.bin"))
                self.assertEqual(load_backup(p), stock())
            finally:
                del os.environ["XYKBMS_BACKUP_DIR"]


if __name__ == "__main__":
    unittest.main()
