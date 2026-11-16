import unittest

from xykbms import config as C
from xykbms.config import MacroRow, XYConfig, XYError, crc32, is_safe_edit
from xykbms.keynames import CAPS, MACBOOK_FN_ROW, unplaced
from xykbms.stock import X220_TABLE

from helpers import counting_config, stock, with_bytes, with_word


class Validation(unittest.TestCase):
    def test_crc32_vector(self):
        self.assertEqual(crc32(b"123456789"), 0xCBF43926)

    def test_valid_config(self):
        XYConfig(counting_config())

    def test_rejects_bad_crc_length_version(self):
        r = counting_config()
        r[0x10] ^= 0xFF
        with self.assertRaises(XYError):
            XYConfig(r)
        with self.assertRaises(XYError):
            XYConfig(counting_config()[:-1])
        r = counting_config()
        r[0] = 3
        with self.assertRaises(XYError):
            XYConfig(r)

    def test_stock_table(self):
        self.assertEqual(len(X220_TABLE), C.MATRIX_KEYS)
        self.assertEqual(sum(w != 0xFFFF for w in X220_TABLE), 91)
        self.assertTrue(stock().has_x220_pins)
        self.assertFalse(XYConfig(counting_config()).has_x220_pins)

    def test_keyboard_picture(self):
        idx = [c["index"] for c in CAPS if c["index"] is not None]
        self.assertEqual(unplaced(), [])
        self.assertEqual(len(idx), len(set(idx)))


class SafeEdit(unittest.TestCase):
    def setUp(self):
        self.s = stock()

    def test_header_edit_is_safe(self):
        e = self.s.copy()
        e.move_speed = 0x80
        e.set_flag("b", C.SWAP_FN_LCTRL, True)
        self.assertTrue(is_safe_edit(self.s, e))

    def test_pin_map_and_board_type_are_unsafe(self):
        self.assertFalse(is_safe_edit(self.s, with_bytes(self.s, {0x40: self.s.raw[0x40] ^ 1})))
        self.assertFalse(is_safe_edit(self.s, with_bytes(self.s, {0x01: 99})))
        self.assertFalse(is_safe_edit(self.s, with_bytes(self.s, {0x258: 0x10})), "special function slots")

    def test_mac_preset(self):
        self.assertIs(self.s.alt_win_swapped, False)
        self.assertIs(self.s.right_alt_is_command, False)
        m = self.s.copy()
        m.set_alt_win_swapped(True)
        m.set_right_alt_is_command(True)
        self.assertEqual(m.key_word(C.IDX_LEFT_ALT), C.MOD_LGUI)
        self.assertEqual(m.key_word(C.IDX_LEFT_WIN), C.MOD_LALT)
        self.assertEqual(m.key_word(C.IDX_RIGHT_ALT), C.MOD_RGUI)
        self.assertTrue(is_safe_edit(self.s, m))
        self.assertEqual(m.with_editable_from(self.s), self.s)

    def test_key_values(self):
        self.assertTrue(is_safe_edit(self.s, with_word(self.s, 0x10, 0x0004)))
        self.assertTrue(is_safe_edit(self.s, with_word(self.s, C.IDX_RIGHT_ALT, 0x4007)))
        self.assertTrue(is_safe_edit(self.s, with_word(self.s, C.IDX_LEFT_ALT, C.MOD_LGUI)), "same value twice")
        for bad in (0x4008, 0x0066, 0xC000, 0x4010, 0x80FF, 0x0001):
            self.assertFalse(is_safe_edit(self.s, with_word(self.s, 0x10, bad)), hex(bad))
        self.assertFalse(is_safe_edit(self.s, with_word(self.s, 0x80, 0x0004)), "Pn area")

    def test_set_key_word(self):
        k = self.s.copy()
        self.assertTrue(k.set_key_word(0x10, 0x0005))
        self.assertFalse(k.set_key_word(0x80, 0x0005))
        self.assertFalse(k.set_key_word(0x10, 0x0066))
        self.assertEqual(k.key_word(0x10), 0x0005)


class FnLayer(unittest.TestCase):
    def setUp(self):
        self.s = stock()
        self.clean = self.s.copy()
        for i in range(C.MATRIX_KEYS):
            if C.is_physical_scan(i):
                self.clean.set_fn(i, 0xFFFF)

    def test_set_and_clear(self):
        f = self.clean.copy()
        self.assertEqual(f.fn_slots_used, 0)
        self.assertTrue(f.set_fn(0x77, 0x80CD))
        self.assertEqual(f.fn_word(0x77), 0x80CD)
        self.assertTrue(is_safe_edit(self.clean, f))
        self.assertFalse(f.set_fn(0x03, 0x0004), "no key at that scan index")
        self.assertTrue(f.set_fn(0x67, 0x8192), "mic-mute button")
        self.assertTrue(f.set_fn(0x77, 0xFFFF))
        self.assertIsNone(f.fn_word(0x77))
        self.assertEqual(f.fn_slots_used, 1)

    def test_eighteen_slots(self):
        f = self.clean.copy()
        keys = [i for i in range(C.MATRIX_KEYS) if X220_TABLE[i] != 0xFFFF]
        for k in keys[:18]:
            f.set_fn(k, 0x0004)
        self.assertEqual(f.fn_slots_used, 18)
        self.assertFalse(f.set_fn(keys[18], 0x0004))

    def test_macbook_row(self):
        f = self.clean.copy()
        scans = [X220_TABLE.index(0x3A + n) for n in range(12)]
        self.assertTrue(all(f.set_fn(s, w) for s, w in zip(scans, MACBOOK_FN_ROW)))
        self.assertTrue(is_safe_edit(self.clean, f))

    def test_unsafe_fn_area(self):
        bad = with_bytes(self.clean, {C.OFF_FN_SCAN: 0x03, C.OFF_FN_WORD: 0x04, C.OFF_FN_WORD + 1: 0})
        self.assertFalse(is_safe_edit(self.clean, bad))


class Macros(unittest.TestCase):
    def setUp(self):
        self.s = stock()

    def test_chord(self):
        m = self.s.copy()
        self.assertTrue(m.set_macro_chord(1, 0x0A, 0x21))
        self.assertEqual(m.macro(1).rows[0], MacroRow(0x0A, (0x21, 0, 0, 0, 0, 0), 5))
        self.assertTrue(is_safe_edit(self.s, m))
        self.assertFalse(m.set_macro_chord(2, 0, 0xE0))
        self.assertTrue(m.set_key_word(0x07, 0x00F2))
        self.assertTrue(is_safe_edit(self.s, m))
        self.assertTrue(m.set_macro_chord(1, 0, 0))
        self.assertTrue(m.macro(1).is_empty)

    def test_merge_keeps_fn_and_macros(self):
        d = self.s.copy()
        d.set_fn(0x16, 0x00F3)
        d.set_macro_chord(2, 0x09, 0x14)
        d.clear_macro_trigger(0)
        merged = self.s.with_editable_from(d)
        self.assertEqual(merged.fn_word(0x16), 0x00F3)
        self.assertEqual(merged.macro(2), d.macro(2))
        self.assertEqual(merged.macro(0), d.macro(0))

    def test_unsafe_macro_area(self):
        self.assertFalse(is_safe_edit(self.s, with_bytes(self.s, {C.OFF_PROG_KEYS + 2: 39, C.OFF_PROG_KEYS + 3: 5})))
        self.assertFalse(is_safe_edit(self.s, with_bytes(self.s, {C.OFF_PROG_ROWS + 9 * 9 + 2: 0xE3})))


if __name__ == "__main__":
    unittest.main()
