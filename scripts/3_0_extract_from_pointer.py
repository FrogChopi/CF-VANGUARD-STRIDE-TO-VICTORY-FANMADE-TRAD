# -*- coding: utf-8 -*-
import csv
from collections import Counter
from pathlib import Path

# --- Config ---
BASE_ADDR   = 0x100000
PATCH_START = 0x949720
PATCH_END   = 0xB51CD0
TERMINATOR  = b'\x00\x00'
SEP_BYTES   = {b'\x00\x00', b'\xff\xff'}

# Control characters accepted at the start of a string (on top of printable ones).
# '　' (full-width space) isn't "printable" for Python but is legit text;
# same for '\n' ('†' once escaped).
ALLOWED_START = {'\n', '\t', '　'}

# Recovery of "tail-shared" pointers (step 2 of extract_strings).
# DISABLED: it adds ~2200 entries, most of them fake pointers (numeric values
# from other tables that happen to fall in PATCH_START..PATCH_END, in the
# middle of a string). Rewriting them corrupts code.bin and crashes the game
# at boot.
RECOVER_TAIL_SHARED = False

# Fake pointers found with the debugger: data whose 32-bit value happens to
# fall in PATCH_START..PATCH_END. They are never repatched.
IMPOSTOR_OFFSETS = {
    # End-of-fight bonus table (byte_DADBF8, 38 x 12 bytes), entry 3:
    # bytes "04 09 96 00" (id, type, value) = 0x00960904. Once repatched, the id
    # becomes 0xD4 and onWinLose (sub_6F7698) loops ~1e9 times → SIGSEGV.
    0xDADC1C,
    # Thumb code in zlib gen_bitlen (sub_1050C8): "STR R4,[SP] ; LSLS R4,R4,#2"
    # = 00 94 A4 00 = 0x00A49400. Once repatched, the code is corrupted and the
    # save after the results screen crashes (SIGSEGV @ 0x10522E).
    0x10512C,
}

# Card table (see vanguard_tables.py): only +0x08 (name), +0x0C (reading) and
# +0x2C (set) are pointers. Field +0x00 is the card number, key of the binary
# search sub_20DD0C: 25 numbers fall in PATCH_START..PATCH_END, and once
# repatched some cards showed up as "Perfect Raizer".
from vanguard_tables import (CARD_POINTER_FIELDS, card_field,
                             confirmed_pointer_locations)

def is_card_non_pointer_field(off: int) -> bool:
    field = card_field(off)
    return field is not None and field not in CARD_POINTER_FIELDS

# "Tail-shared" pointers from IDA-confirmed text columns: they target the end
# of another string (e.g. "撃退者" at the end of "…・撃退者") and are extracted
# as strings of their own. Unlike RECOVER_TAIL_SHARED, no fake pointer is
# possible: the column is proven.
RECOVER_CONFIRMED_TAILS = True

BIN_PATH       = Path("full_padded.bin")
CSV_INPUT      = Path("fresh_rodata_pointers.csv")
OUTPUT_CSV     = Path("extracted_strings.csv")

NO_SEPARATOR = "not preceded by a separator"


def is_separator(pair: bytes) -> bool:
    return bytes(pair) in SEP_BYTES

def escape_newlines(text: str) -> str:
    return text.replace('\n', '†')

def load_and_group_pointers(csv_file: Path):
    ptr_map = {}
    with csv_file.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        for row in reader:
            if len(row) < 2 or row[0].lower() == 'offset':
                continue
            off_s, val_s = row[0].rstrip("Ll"), row[1].rstrip("Ll")
            try:
                off = int(off_s, 16)
                val = int(val_s, 16)
            except ValueError:
                continue
            if off in IMPOSTOR_OFFSETS or is_card_non_pointer_field(off):
                continue
            if PATCH_START <= val < PATCH_END:
                ptr_map.setdefault(val, []).append(off)
    return {k: sorted(v) for k, v in sorted(ptr_map.items())}

def find_terminator(data, start, limit):
    """First 2-byte-aligned 00 00 from start (end of the UTF-16 string)."""
    for i in range(start, limit - 1, 2):
        if data[i] == 0 and data[i + 1] == 0:
            return i
    return limit

def valid_start_reason(data, fo):
    """None if fo is a plausible string start, otherwise the rejection reason."""
    if fo % 2:
        return "odd address"
    if fo < 2 or not is_separator(data[fo - 2:fo]):
        return NO_SEPARATOR
    pair = bytes(data[fo:fo + 2])
    if pair == TERMINATOR:
        return "empty string (points to 00 00)"
    if pair == b'\xff\xff':
        return "points to FF FF"
    try:
        ch = pair.decode('utf-16le')
    except UnicodeDecodeError:
        return "first character not decodable"
    if not (ch.isprintable() or ch in ALLOWED_START):
        return "first character not printable"
    return None

def build_entry(val, start, data, ptr_map, limit):
    """Build one CSV row for the string starting at start (ended by 00 00)."""
    end = find_terminator(data, start, limit)
    try:
        text = bytes(data[start:end]).decode('utf-16le')
    except UnicodeDecodeError:
        return None
    if not text:
        return None

    # Separators: the terminator + the padding (00 00 / FF FF) after it,
    # without spilling into the next string.
    sep_end = end
    while sep_end + 2 <= limit and is_separator(data[sep_end:sep_end + 2]):
        sep_end += 2
    sep_bytes = bytes(data[end:sep_end])

    pointers = ",".join(f"0x{off:06X}" for off in ptr_map[val])
    sep_str  = " ".join(f"{b:02X}" for b in sep_bytes)
    return {
        'pointer_offsets': pointers,
        'pointer_value'  : f"0x{val:08X}",
        'separators'     : sep_str,
        'extract'        : escape_newlines(text),
    }

def extract_strings():
    data = bytearray(BIN_PATH.read_bytes())
    ptr_map = load_and_group_pointers(CSV_INPUT)
    region_end = PATCH_END - BASE_ADDR

    # 1) Real string starts: preceded by a separator (00 00 / FF FF).
    valid_vals = []
    rejected = {}
    for val in ptr_map:
        reason = valid_start_reason(data, val - BASE_ADDR)
        if reason:
            rejected[val] = reason
        else:
            valid_vals.append(val)
    valid_vals.sort()
    valid_starts = [v - BASE_ADDR for v in valid_vals]

    results = []
    for idx, val in enumerate(valid_vals):
        start = valid_starts[idx]
        limit = valid_starts[idx + 1] if idx + 1 < len(valid_starts) else region_end
        entry = build_entry(val, start, data, ptr_map, limit)
        if entry:
            results.append(entry)
        else:
            rejected[val] = "string not decodable"

    # 2) "Tail-shared" pointers: the target isn't preceded by a separator
    #    because it points into the middle of another string whose tail the
    #    game reuses (e.g. "...のコストを選んで下さい" also serves as
    #    "コストを選んで下さい"). See RECOVER_TAIL_SHARED.
    recovered = 0
    if RECOVER_TAIL_SHARED:
        for val, reason in list(rejected.items()):
            if reason != NO_SEPARATOR:
                continue
            fo = val - BASE_ADDR
            if fo % 2:
                continue
            ch = bytes(data[fo:fo + 2])
            if ch in SEP_BYTES:
                continue
            entry = build_entry(val, fo, data, ptr_map, region_end)
            if entry:
                results.append(entry)
                recovered += 1
                del rejected[val]

    # 3) Shared tails targeted by a confirmed text column: only the locations
    #    of those columns are kept as pointers.
    confirmed_tails = 0
    if RECOVER_CONFIRMED_TAILS:
        columns = confirmed_pointer_locations()
        for val, reason in list(rejected.items()):
            if reason != NO_SEPARATOR:
                continue
            offs = [o for o in ptr_map[val] if o in columns]
            if not offs:
                continue
            entry = build_entry(val, val - BASE_ADDR, data, {val: offs}, region_end)
            if entry:
                results.append(entry)
                confirmed_tails += 1
                del rejected[val]
        recovered += confirmed_tails

    results.sort(key=lambda r: int(r['pointer_value'], 16))

    with OUTPUT_CSV.open("w", newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['pointer_offsets','pointer_value','separators','extract'])
        for r in results:
            writer.writerow([r['pointer_offsets'],
                             r['pointer_value'],
                             r['separators'],
                             r['extract']])

    print(f"✔ Extraction done → {OUTPUT_CSV}")
    print(f"  {len(results)} strings extracted ({recovered} tail-shared)")
    print(f"  {len(rejected)} pointer values rejected:")
    for reason, n in Counter(rejected.values()).most_common():
        print(f"    - {reason}: {n}")

if __name__ == "__main__":
    extract_strings()
