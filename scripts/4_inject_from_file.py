# -*- coding: utf-8 -*-
"""Inject the translations into code.bin.

    python scripts/4_inject_from_file.py [output code.bin]

Default output: full_patched.bin. Point it straight at an Azahar mod folder
(.../load/mods/<title id>/exefs/code.bin) to test without rebuilding the .3ds.
"""
import csv
import sys
from pathlib import Path

# --- Config ---
BASE_ADDR     = 0x0100000  # Base virtual address of code.bin
INPUT_BIN     = Path("full_padded.bin")
POINTER_CSV   = Path("extracted_strings_updated.csv")
OUTPUT_BIN    = Path(sys.argv[1] if len(sys.argv) > 1 else "full_patched.bin")

# --- Raise the CSV field size limit ---
try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(2**31 - 1)

# Max number of rows injected (to bisect a problem); None = all.
MAX_CHAINES = None

# --- Injection: full translation, verified pointers ---
# Each translated string is relocated IN FULL at the end of the file (the JP
# originals stay intact). Only locations proven to be real pointers are
# repatched; fake pointers (data that looks like a string address) are never
# touched. Rule order (classify_location):
#   1. card table: only +0x08 name, +0x0C reading, +0x2C set;
#   2. manual review (files/pointer_review.csv): forced verdict;
#   3. text column confirmed by decompilation (vanguard_tables) -> pointer;
#   4. value = card number -> impostor (deck tables, card links...);
#   5. offset typed by IDA (files/ida_trusted_offsets.txt) -> pointer;
#   6. .text not typed by IDA -> impostor (code);
#   7. structure column whose field is a string pointer in
#      >= FIELD_RATIO of the records with the same layout -> pointer;
#   8. otherwise: UNPROVEN -> not patched + warning, add it to the review.
IDA_TRUSTED_FILE = Path("files/ida_trusted_offsets.txt")
REVIEW_FILE      = Path("files/pointer_review.csv")
REPORT_CSV       = Path("injection_report.csv")
FIELD_MAX_STRIDE = 0x400
FIELD_RATIO      = 0.9
TEXT_END         = 0x8D3000              # end of .text
DATA_END         = 0xFBD000              # end of .data/.bss in full_padded.bin
PTR_RANGE        = (0x100000, 0x1000000)

# Card table and confirmed text columns: see vanguard_tables.py.
from vanguard_tables import (CARD_COUNT, CARD_POINTER_FIELDS, CARD_STRIDE,
                             CARD_TABLE_START, card_field,
                             text_column_locations)

def load_ida_trusted() -> set:
    if not IDA_TRUSTED_FILE.exists():
        print(f"⚠ {IDA_TRUSTED_FILE} missing")
        return set()
    return {int(l, 16) for l in IDA_TRUSTED_FILE.read_text(encoding="utf-8").split() if l}

def load_review() -> dict:
    review = {}
    if REVIEW_FILE.exists():
        with REVIEW_FILE.open(newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f, delimiter=';'):
                # verdict: "pointeur"/"pointer" or "imposteur"/"impostor"
                review[int(row['offset'], 16)] = row['verdict'].strip() in ('pointeur', 'pointer')
    return review

def make_classifier(orig: bytes, all_locs: set):
    ida_trusted = load_ida_trusted()
    review = load_review()

    def u32(addr):
        off = addr - BASE_ADDR
        return int.from_bytes(orig[off:off + 4], 'little')

    card_numbers = {u32(CARD_TABLE_START + i * CARD_STRIDE) for i in range(CARD_COUNT)}
    text_columns = text_column_locations()

    def kind(addr):
        v = u32(addr)
        if v == 0:
            return '0'
        return 'P' if PTR_RANGE[0] <= v < PTR_RANGE[1] else 'n'

    def layout(addr):
        return tuple(kind(addr + 4 * k) for k in (-3, -2, -1, 1, 2, 3))

    def field_is_pointer(off):
        base = layout(off)
        for stride in range(4, FIELD_MAX_STRIDE + 4, 4):
            if off + stride not in all_locs and off - stride not in all_locs:
                continue
            column = [off]
            for direction in (1, -1):
                a = off + direction * stride
                while TEXT_END <= a < DATA_END - 16 and len(column) < 5000 and layout(a) == base:
                    column.append(a)
                    a += direction * stride
            nonnull = [a for a in column if u32(a) != 0]
            good = sum(a in all_locs for a in nonnull)
            if len(column) >= 2 and good >= 2 and good >= FIELD_RATIO * len(nonnull):
                return True
        return False

    def classify_location(off):
        """-> (is_pointer: bool | None if unproven, reason)"""
        field = card_field(off)
        if field is not None:
            return field in CARD_POINTER_FIELDS, 'card table'
        if off in review:
            return review[off], 'manual review'
        if off in text_columns:
            return True, 'confirmed text column'
        if u32(off) in card_numbers:
            return False, 'card number'
        if off in ida_trusted:
            return True, 'IDA'
        if off < TEXT_END:
            return False, 'code'
        if field_is_pointer(off):
            return True, 'structure'
        return None, 'unproven'
    return classify_location

OUTSIDE_CSV = Path("extracted_outside_updated.csv")


def inject_outside(data: bytearray, orig: bytes, cursor: int, relocated: dict) -> int:
    """Strings OUTSIDE the range (extracted_outside_updated.csv, scripts 1_7 + 3b):
    .text literals loaded by a PC-relative ADR, .rodata strings loaded by LDR
    from a pool. For each translation that differs from the Japanese:
      - the English string is relocated at the end of the file, or reused if
        the same text was already relocated for the range (relocated: text -> address);
      - "A:ea": "ADR Rd, lit" -> "LDR Rd, [PC, #±off]" (same condition, same
        register) and the address of the translation is written into the
        literal's slot (the JP text isn't read from there anymore);
      - "P:ea": pool dword -> address of the translation.
    Every reference is checked again against the original binary before patching.
    Returns the new end-of-file cursor."""
    if not OUTSIDE_CSV.exists():
        return cursor
    u32o = lambda a: int.from_bytes(orig[a - BASE_ADDR:a - BASE_ADDR + 4], 'little')
    put = lambda a, v: data.__setitem__(slice(a - BASE_ADDR, a - BASE_ADDR + 4), v.to_bytes(4, 'little'))
    ror = lambda v, r: ((v >> r) | (v << (32 - r))) & 0xFFFFFFFF

    with OUTSIDE_CSV.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f, delimiter=';'))

    stats = {'untranslated': 0, 'redirected': 0, 'invalid reference': 0}
    for row in rows:
        lit = int(row['pointer_value'], 16)
        txt = row['extract'].replace('†', '\n')
        utf16 = txt.encode('utf-16le')
        if utf16 == original_utf16(orig, lit):
            stats['untranslated'] += 1
            continue

        refs = [r.split(':') for r in row['pointer_offsets'].split(',') if r]
        # check every reference before patching anything
        valid = True
        for kind, ea_s in refs:
            ea, w = int(ea_s, 16), u32o(int(ea_s, 16))
            if kind == 'A':
                imm = ror(w & 0xFF, 2 * ((w >> 8) & 0xF))
                tgt = ea + 8 + imm if (w & 0x0FEF0000) == 0x028F0000 else ea + 8 - imm
                valid &= (w & 0x0FEF0000) in (0x028F0000, 0x024F0000) and tgt == lit and lit % 4 == 0 \
                    and abs(lit - (ea + 8)) <= 0xFFF
            elif kind == 'P':
                valid &= w == lit
            else:
                valid = False
        if not valid:
            stats['invalid reference'] += 1
            print(f"⚠ Out-of-range string 0x{lit:08X} skipped: invalid reference ({row['pointer_offsets']})")
            continue

        new_addr = relocated.get(txt)
        if new_addr is None:
            block = (len(utf16) // 2).to_bytes(4, 'little') + utf16 + b'\x00\x00'
            new_addr = BASE_ADDR + cursor + 4
            data.extend(block)
            cursor += len(block)
            relocated[txt] = new_addr

        for kind, ea_s in refs:
            ea = int(ea_s, 16)
            if kind == 'A':
                w, off = u32o(ea), lit - (ea + 8)
                put(ea, (w & 0xF0000000) | 0x051F0000 | ((off >= 0) << 23) | (w & 0x0000F000) | abs(off))
            else:
                put(ea, new_addr)
        if any(kind == 'A' for kind, _ in refs):
            put(lit, new_addr)
        stats['redirected'] += 1

    print(f"✔ Out-of-range strings ({OUTSIDE_CSV}): " + ", ".join(f"{k} {v}" for k, v in stats.items()))
    return cursor


def original_utf16(data, addr):
    """UTF-16 bytes of the original string (without the 00 00 terminator)."""
    start = addr - BASE_ADDR
    end = start
    while data[end:end + 2] != b'\x00\x00':
        end += 2
    return bytes(data[start:end])

def parse_separators(sep_field: str) -> bytes:
    if sep_field.strip() in ("(none)", "(aucun)"):  # "(aucun)" = older CSVs
        return b""
    parts = sep_field.split()
    return bytes(int(p, 16) for p in parts)

def main():
    data = bytearray(INPUT_BIN.read_bytes())
    orig = bytes(data)
    orig_len = len(data)
    print(f"⚙ code.bin loaded: {orig_len} bytes")

    with POINTER_CSV.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=';')
        rows = list(reader)

    all_locs = {int(o, 16) for r in rows for o in r['pointer_offsets'].split(',') if o}
    classify_location = make_classifier(orig, all_locs)

    stats = {'untranslated': 0, 'relocated': 0, 'no valid pointer': 0}
    unproven = {}
    report = []
    relocated = {}   # translated text -> relocated address (reused by out-of-range strings)
    cursor = orig_len
    for idx, row in enumerate(rows):
        if MAX_CHAINES is not None and idx >= MAX_CHAINES:
            print(f"⚠ Stopped after {MAX_CHAINES} strings.")
            break

        offs = [int(o, 16) for o in row['pointer_offsets'].split(',') if o]
        addr = int(row['pointer_value'], 16)
        txt = row['extract'].replace('†', '\n')
        utf16_bytes = txt.encode('utf-16le')
        jp_bytes = original_utf16(orig, addr)

        # 1. Nothing to do
        if utf16_bytes == jp_bytes:
            stats['untranslated'] += 1
            continue

        # 2. Full relocation, repatch real pointers only
        patchable, rejected = [], []
        for o in offs:
            is_ptr, reason = classify_location(o)
            if is_ptr:
                patchable.append(o)
            else:
                rejected.append(f"0x{o:06X}:{reason}")
                if is_ptr is None:
                    unproven[o] = txt[:40]
        if not patchable:
            stats['no valid pointer'] += 1
            report.append((row['pointer_value'], 'no valid pointer', ' '.join(rejected), txt[:60]))
            continue

        sep_bytes = parse_separators(row['separators'])
        length_prefix = (len(utf16_bytes) // 2).to_bytes(4, 'little')
        block = length_prefix + utf16_bytes + sep_bytes
        new_addr = BASE_ADDR + cursor + 4  # the pointer targets the text, after the length header

        for addr_virt in patchable:
            off = addr_virt - BASE_ADDR
            data[off:off + 4] = new_addr.to_bytes(4, 'little')

        data.extend(block)
        cursor += len(block)
        relocated.setdefault(txt, new_addr)
        stats['relocated'] += 1
        report.append((row['pointer_value'], 'relocated', ' '.join(rejected), txt[:60]))

    cursor = inject_outside(data, orig, cursor, relocated)
    OUTPUT_BIN.write_bytes(data)
    with REPORT_CSV.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['pointer_value', 'mode', 'unpatched_locations', 'text'])
        w.writerows(report)

    print(f"✔ '{OUTPUT_BIN}' written ({len(data)} bytes total).")
    for k, v in stats.items():
        print(f"  {k:22} : {v}")
    print(f"  details → {REPORT_CSV}")
    if unproven:
        print(f"⚠ {len(unproven)} UNPROVEN location(s), not patched: check them, then "
              f"add them to {REVIEW_FILE} (verdict 'pointeur' or 'imposteur')")
        for o, t in sorted(unproven.items())[:50]:
            print(f"    0x{o:06X}  {t!r}")

if __name__ == "__main__":
    main()
