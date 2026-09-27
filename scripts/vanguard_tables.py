# -*- coding: utf-8 -*-
"""code.bin tables identified by decompilation (IDA), shared by
3_extract_from_pointer.py, 4_inject_from_file.py and 3_6_keywords.py."""

BASE_ADDR = 0x100000

# Card table (unk_D42E68): 3890 records of 0x34 bytes, followed by its sorted
# index {u16 id, u16 record} (unk_D74490). +0x00 = card number (key of the
# binary search sub_20DD0C), +0x08 = displayed name, +0x0C = kana reading,
# +0x2C = set.
CARD_TABLE_START    = 0xD42E68
CARD_COUNT          = 3890
CARD_STRIDE         = 0x34
CARD_AREA_END       = 0xD74490 + 3889 * 4
CARD_POINTER_FIELDS = {0x08, 0x0C, 0x2C}
CARD_NAME_FIELD     = 0x08

# Confirmed text columns: (base, record size, record count,
# text pointer fields, function that reads the table).
TEXT_COLUMNS = [
    (0xDA3730, 0x08, 5159, (0x04,),                   "sub_21CC7C"),
    (0xD9FE90, 0x08, 1412, (0x04,),                   "sub_39D244 (name keywords)"),
    (0xDA2BC8, 0x0C,  233, (0x08,),                   "sub_20DD60"),
    (0xD96990, 0x114, 138, (0x08, 0x0C),              "sub_1C2B68"),
    (0xD96490, 0x18,   51, (0x08, 0x0C, 0x10, 0x14),  "sub_39C098"),
    (0xD781F8, 0x28,   90, (0x04, 0x24),              "sub_1E09C0"),
]

# Card name keywords (sub_72EAC0): records {u32 key|flag, u32 word}.
# Bit 31 of the first word = "name CONTAINS the word", otherwise "name EQUALS the word".
# The comparison uses the displayed name (+0x08) without furigana.
KEYWORD_TABLE = 0xD9FE90
KEYWORD_COUNT = 1412


def card_field(off: int):
    """Field (offset within the record) if off is in the card table,
    -1 in the sorted index, None elsewhere."""
    rel = off - CARD_TABLE_START
    if 0 <= rel < CARD_COUNT * CARD_STRIDE:
        return rel % CARD_STRIDE
    if CARD_TABLE_START <= off < CARD_AREA_END:
        return -1
    return None


def text_column_locations() -> set:
    locs = set()
    for base, stride, count, fields, _ in TEXT_COLUMNS:
        for i in range(count):
            for f in fields:
                locs.add(base + i * stride + f)
    return locs


def confirmed_pointer_locations() -> set:
    """Every location proven to be a text pointer by the structure:
    text columns + pointer fields of the card table."""
    locs = text_column_locations()
    for i in range(CARD_COUNT):
        for f in CARD_POINTER_FIELDS:
            locs.add(CARD_TABLE_START + i * CARD_STRIDE + f)
    return locs


def u32(data, addr: int) -> int:
    off = addr - BASE_ADDR
    return int.from_bytes(data[off:off + 4], 'little')


def read_utf16(data, addr: int) -> str:
    """UTF-16 string at addr, up to the aligned 00 00 terminator."""
    start = end = addr - BASE_ADDR
    while data[end:end + 2] != b'\x00\x00':
        end += 2
    return bytes(data[start:end]).decode('utf-16le', errors='replace')
