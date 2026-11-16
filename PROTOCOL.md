# XYKBMS HID protocol and config layout

This page covers the parts of the protocol this tool uses. The full reverse-engineered description,
including BOOT mode and firmware upload, is in
[hughsie/xykbms-gtk PROTOCOL.md](https://github.com/hughsie/xykbms-gtk/blob/main/PROTOCOL.md).
All multi-byte values are little-endian.

## Transport

The board exposes a vendor-defined HID collection (Usage Page `0xFF00`, Report ID 2, 18 data bytes in and out).
Every transfer is a 19-byte report `[0x02, b1 … b18]`.

The same USB interface also carries a consumer-control collection (Report ID 1, the media keys).

* Reports that do not start with `0x02` are ignored.
* The device must not be opened exclusively, or the media keys stop working.

Each read waits up to 2000 ms. Command packets are retried 3 times, bulk-transfer packets 6 times.
A reply byte of `0xFD` (the board's fill byte) means "try again".

## Commands

| Kind | Request | Success reply |
|---|---|---|
| control | `02 3f <cmd>` | `02 3f <cmd>` |
| data | `02 3e <cmd> <payload ≤ 16>` | `02 <cmd> …` or a payload |

| cmd | Kind | Meaning |
|---|---|---|
| `0x22` | control | begin config read |
| `0x11` | control | begin config write |
| `0x6b` | data | firmware version, up to 18 ASCII bytes |
| `0x6a` | data | battery voltage, u32 in mV |
| `0x66` | data | set backlight to `<percent>` (runtime only, not stored) |
| `0x44` / `0x45` | data | start / stop scancode reporting |

## Reading the config

1. Send control `0x22`.
2. For block `n` = 0 … 127, send `02 <n lo> <n hi>`. The reply is `02 <n lo> <n hi> <8 bytes>`.
   Continue from the block number in the reply.
3. Always finish with `02 ff ff`, even after an error.

## Writing the config

1. Send control `0x11`.
2. For block `n` = 0 … 63, send `02 <n lo> <n hi> <16 bytes>`.
   * `02 11 22` acknowledges the block.
   * Any other reply `02 <lo> <hi>` asks to resend from block `(lo | hi << 8) & 0x3FFF`.
3. End with block 64 filled with `0xFF`: `02 40 00 ff…`.

The board then commits the config, resets itself and re-enumerates on USB, so the open handle is dead.
Wait for the device to disappear and come back, give it about 2.5 s to boot, and then open it again.

## Config block (1024 bytes)

The CRC-32 (standard, reflected `0xEDB88320`) covers bytes `0x000`–`0x07F` and is stored at `0x3FC`.
Byte 0 is the config version and must be 4.

| Offset | Size | Field |
|---|---|---|
| `0x000` | 1 | config version (4) |
| `0x001` | 1 | board type: 1 ThinkPad wireless, 2 mechanical wireless, 3/4/6 TrackPoint mechanical, 5/7 ThinkPad wireless 2/3, 10 wired USB |
| `0x002` | 2 | keyboard auto-off, minutes |
| `0x004` | 2 | TrackPoint auto-off, minutes |
| `0x008` | 1 | scroll speed, 1–15 |
| `0x009` | 1 | TrackPoint speed, 80–255 |
| `0x00A` | 1 | flags A (below) |
| `0x00B` | 1 | flags B (below) |
| `0x00C` | 16 | Bluetooth name, UTF-8, NUL-terminated, at most 14 bytes |
| `0x01C` | 1 | radio mode: 1 Bluetooth 4.0, 2 USB receiver, 3 URT |
| `0x01D` | 1 | radio channel, 0–3 |
| `0x034` | 3 | LED pins: Num, Caps, Scroll (`0xFF` = none) |
| `0x037` | 3 | further pin bytes; read here as charge sense, low-voltage sense and backlight PWM |
| `0x03A` | 1 + 20 | drive (row) count and pins |
| `0x04F` | 1 + 20 | sense (column) count and pins |
| `0x064` | 192 × 2 | key table, one key word per scan index; `0x00`–`0x7F` matrix keys, `0x80` and up the Pn area |
| `0x1E4` | 2 | Fn key: `00 <pin>` dedicated IO pin, `01 <scan>` matrix key |
| `0x1E6` | 18 | Fn layer scan indexes (`0xFF` = free slot) |
| `0x1F8` | 18 × 2 | Fn layer key words |
| `0x258` | 2 × 3 | function keys for Win-disable, TrackPoint on/off and sleep (`0xFF` = unassigned) |
| `0x26B` | 5 × 4 | programmable keys: `scan1, scan2, first row, row count` |
| `0x27F` | 40 × 9 | macro rows: `modifiers, 0, key × 6, delay (10 ms)` |
| `0x3FC` | 4 | CRC-32 |

Bytes not listed are kept as they are.

### Flags

| Bit | Flags A (`0x00A`) | Flags B (`0x00B`) |
|---|---|---|
| 0 | middle button + move = scroll | disable status-LED blinking |
| 1 | double-tap middle button = Backspace | status LED off |
| 2 | mouse middle button = Backspace | swap Fn and left Ctrl |
| 3 | keep LEDs on in low power | Bluetooth passkey |
| 4 | disable Win key | wake only on specific keys |
| 5 | TrackPoint on at power-up | unknown |
| 6 | invert TrackPoint X/Y | unknown |
| 7 | allow low power in USB mode | unknown |

Some boards ship with the unknown bits 5–7 of flags B set. This tool keeps them unchanged.

### Key words

A key word is 16 bits. The top two bits select the category:

| Value | Meaning |
|---|---|
| `0x0004`–`0x0065` | HID keyboard usage (letters, digits, F1–F12, navigation, …) |
| `0x0068`–`0x0073` | F13–F24 |
| `0x0087`–`0x008B`, `0x0090`–`0x0092` | international keys, Hangul/Hanja |
| `0x00E0`–`0x00F0` | layer keys (not used by this tool) |
| `0x00F1`–`0x00F5` | send programmable key (macro) 1–5 |
| `0x4000`–`0x4007` | modifiers: left Ctrl, Shift, Alt, GUI, then right Ctrl, Shift, Alt, GUI |
| `0x5001`–`0x53FF` | mouse emulation: buttons `0x5001/0x5002/0x5004`, X `0x51xx`, Y `0x52xx`, wheel `0x53xx` (signed step in the low byte) |
| `0x8000` + usage | consumer control (media), e.g. `0x80E2` mute, `0x80E9`/`0x80EA` volume, `0x80CD` play/pause, `0x8224`/`0x8225` back/forward |
| `0xFFFF` | key disabled |

### Programmable keys

Each of the five entries has four bytes:

* `scan1`: the key that triggers it directly, or `0xFF` for none.
* `scan2`: `0xFD` means `scan1` alone, `0xFE` means Fn + `scan1`, and anything else is a second key.
* `first row` and `row count`: which rows of the 40-row macro table belong to this entry.

A macro can also be sent from any key whose key word is `0x00F1`–`0x00F5`.

Each row is played as one chord:

* Byte 0 is the modifier bits: bit 0–3 left Ctrl, Shift, Alt, GUI; bit 4–7 the right-hand ones.
* Bytes 2–7 are up to six HID key codes.
* Byte 8 is a delay in units of 10 ms.

## ThinkPad X220 notes

* 91 keys sit on a 16 × 9 matrix. Fn is on its own IO pin and cannot be remapped.
* The mic-mute button is scan `0x67` and the ThinkVantage button is scan `0x07`. Neither has a key word in the
  factory table. Boards may ship with programmable key 1 bound directly to ThinkVantage (`07 fd`).
