# Run in IDA (File > Script file) on the analyzed extract/exefs/code.bin.
# Writes files/code_literals.json: the Japanese strings OUTSIDE the known
# range (0x949720..0xB51CD0) that the code loads directly:
#   - UTF-16 literals in .text (after the functions) loaded by a PC-relative
#     ADR (e.g. Wingal: "ADR R1, L"ブラスター・ブレード"");
#   - out-of-range .rodata strings loaded by LDR from a literal pool.
# Every reference is confirmed by IDA; a string with a reference that isn't a
# plain address load (LDRH, LDRD, MOV...) is excluded.
# Next: scripts/3b_extract_outside.py -> extracted_outside.csv.
import json
import os
import re
import struct

import idautils

PROJECT = os.path.abspath(os.path.join(os.path.dirname(idc.get_idb_path()), "..", ".."))
BIN = os.path.join(PROJECT, "full_padded.bin")
OUT = os.path.join(PROJECT, "files", "code_literals.json")

BASE, TEXT_END, RODATA_END = 0x100000, 0x8D3000, 0xC1F000
RANGE = (0x949720, 0xB51CD0)

data = open(BIN, "rb").read()
u32 = lambda a: struct.unpack_from("<I", data, a - BASE)[0]
ror = lambda v, r: ((v >> r) | (v << (32 - r))) & 0xFFFFFFFF

KANA = re.compile(r"[぀-ヿ]")
JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
ALLOWED = re.compile(r"^[ -~ -ÿ‐-‧‰-⋿①-⓿"
                     r"─-⟿　-ヿ一-鿿＀-￯\n]+$")
ISOLATED = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9](?![A-Za-z0-9])")
strip_furigana = lambda s: re.sub(r"<\|([^|]*)\|[^|]*\|>", r"\1", s)

# JP texts of the range: used to validate strings without kana (e.g. "神器")
import csv
csv.field_size_limit(2**31 - 1)
with open(os.path.join(PROJECT, "extracted_strings.csv"), encoding="utf-8") as f:
    CORPUS = "\n".join(strip_furigana(r["extract"].replace("†", "")) for r in csv.DictReader(f, delimiter=";"))


def ascii_bytes(c):
    """Both bytes of the character are printable ASCII (ASCII read as UTF-16)."""
    return 0x20 <= (ord(c) & 0xFF) <= 0x7E and 0x20 <= (ord(c) >> 8) <= 0x7E


def real_text(s):
    """Reject ASCII read as UTF-16 ("cost_..." -> "潣瑳...") and value tables."""
    t = strip_furigana(s)
    kana = len(KANA.findall(t))
    kanji = [c for c in t if "一" <= c <= "鿿"]
    if kana == 0:                                   # kanji only: must exist in the range
        return len(t) >= 2 and t in CORPUS
    if len(ISOLATED.findall(t)) >= 2:               # "ヘTむT": dwords read as text
        return False
    if kana <= 1 and kanji and sum(map(ascii_bytes, kanji)) > len(kanji) / 2 and t not in CORPUS:
        return False                                # "敔呸き" = "Text..."
    return True


def japanese_string(a):
    """Text if a is the start of a plausible out-of-range UTF-16 Japanese string."""
    if a % 2 or not (BASE <= a < RODATA_END) or RANGE[0] <= a < RANGE[1]:
        return None
    o = e = a - BASE
    while data[e:e + 2] != b"\0\0" and e - o < 600:
        e += 2
    if e - o < 2 or data[e:e + 2] != b"\0\0":
        return None
    s = data[o:e].decode("utf-16le", "replace")
    if not JAPANESE.search(s) or not ALLOWED.match(s):
        return None
    return s if real_text(s) else None


# 1. targets of .text ADR / LDR instructions that point to a Japanese string
targets = {}
for i in range(0, TEXT_END - BASE, 4):
    w, ea = struct.unpack_from("<I", data, i)[0], BASE + i
    if (w & 0x0FEF0000) in (0x028F0000, 0x024F0000):
        imm = ror(w & 0xFF, 2 * ((w >> 8) & 0xF))
        t = ea + 8 + imm if (w & 0x0FEF0000) == 0x028F0000 else ea + 8 - imm
    elif (w & 0x0F7F0000) == 0x051F0000:
        pool = ea + 8 + (w & 0xFFF) if w & (1 << 23) else ea + 8 - (w & 0xFFF)
        if not (BASE <= pool < BASE + len(data) - 4):
            continue
        t = u32(pool)
    else:
        continue
    if t not in targets:
        s = japanese_string(t)
        if s:
            targets[t] = s

# 2. references confirmed by IDA
out, excluded = [], 0
for lit, jp in sorted(targets.items()):
    entry, ok = {"literal": lit, "jp": jp, "adr": [], "pool": []}, True
    refs = list(idautils.XrefsTo(lit))
    if not refs:
        continue
    for x in refs:
        ea, w = x.frm, u32(x.frm)
        if not ida_bytes.is_code(ida_bytes.get_flags(ea)):
            ok &= w == lit
            entry["pool"].append(ea)
        elif (w & 0x0FEF0000) in (0x028F0000, 0x024F0000):
            imm = ror(w & 0xFF, 2 * ((w >> 8) & 0xF))
            ok &= lit % 4 == 0 and (ea + 8 + imm if (w & 0x0FEF0000) == 0x028F0000 else ea + 8 - imm) == lit
            entry["adr"].append(ea)
        elif (w & 0x0F7F0000) == 0x051F0000:
            pool = ea + 8 + (w & 0xFFF) if w & (1 << 23) else ea + 8 - (w & 0xFFF)
            ok &= u32(pool) == lit
            entry["pool"].append(pool)
        else:
            ok = False      # reads the content (LDRH, LDRD, MOV...): can't be redirected
    entry["pool"] = sorted(set(entry["pool"]))
    if ok:
        out.append(entry)
    else:
        excluded += 1

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(f"✅ {len(out)} out-of-range strings written to {OUT} ({excluded} excluded)")
