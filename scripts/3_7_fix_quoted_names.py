# -*- coding: utf-8 -*-
"""Align the card names quoted in effects with the in-game names.

    python scripts/3_7_fix_quoted_names.py [--check]

English effects (official database) quote cards between double quotes
("Blaster Blade"); the game's Japanese text quotes them between 「…」. For each
effect line (table 0xDA3730), the quotes of both languages are aligned in
order; if the Japanese 「…」 is the name of a card in the game, the English
quote is replaced by the exact name of that card (as translated in
extracted_strings_updated.csv), then the line is re-wrapped to the screen
width. Writes the list of changes to files/quoted_names_fixes.csv.

No replacement if: different number of quotes, expected name already there
as-is, or quote too far from the expected name (flagged).
Run after update_csv.py --cards (official effects) and before 3_6_keywords.py.
"""
import csv
import re
import shutil
import sys
from difflib import SequenceMatcher
from pathlib import Path

from update_csv import wrap_game_text
from vanguard_tables import (BASE_ADDR, CARD_COUNT, CARD_STRIDE, CARD_TABLE_START,
                             read_utf16, u32)

csv.field_size_limit(2**31 - 1)

BIN_PATH       = Path("full_padded.bin")
TRANSLATED_CSV = Path("extracted_strings_updated.csv")
REPORT_CSV     = Path("files/quoted_names_fixes.csv")
EFFECT_TABLE, EFFECT_COUNT = 0xDA3730, 5159
WRAP = 34
MIN_SIMILARITY = 0.6

QUOTE_EN = re.compile(r'"\s*([^"\n]+?)\s*"')
QUOTE_JP = re.compile(r'「([^」]+)」')
JAPANESE = re.compile(r'[぀-ヿ一-鿿]')


def clean(s: str) -> str:
    """Remove furigana <|A|B|> and color codes {$…}."""
    s = re.sub(r'<\|([^|]*)\|[^|]*\|>', r'\1', s)
    return re.sub(r'\{\$[0-9a-fA-F]*\}', '', s)


def similar(a: str, b: str) -> bool:
    if SequenceMatcher(None, a.lower(), b.lower()).ratio() >= MIN_SIMILARITY:
        return True
    last = lambda s: re.split(r'[ ,]+', s.strip())[-1].lower()
    return last(a) == last(b)


def main():
    check_only = '--check' in sys.argv
    data = BIN_PATH.read_bytes()
    with TRANSLATED_CSV.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f, delimiter=';'))
    by_addr = {int(r['pointer_value'], 16): r for r in rows}

    # JP name of each card (without furigana) -> in-game EN name
    jp_to_en = {}
    for i in range(CARD_COUNT):
        rec = CARD_TABLE_START + i * CARD_STRIDE
        if not int.from_bytes(data[rec + 4 - BASE_ADDR:rec + 6 - BASE_ADDR], 'little'):
            continue
        addr = u32(data, rec + 0x08)
        jp = clean(read_utf16(data, addr))
        en = clean(by_addr[addr]['extract']) if addr in by_addr else ''
        if en and not JAPANESE.search(en):
            jp_to_en.setdefault(jp, en)

    fixes, flagged, seen = [], [], set()
    for i in range(EFFECT_COUNT):
        addr = u32(data, EFFECT_TABLE + i * 8 + 4)
        if addr in seen or addr not in by_addr:
            continue
        seen.add(addr)
        row = by_addr[addr]
        text = row['extract'].replace('†', '\n')
        flat = ' '.join(text.split('\n'))
        if JAPANESE.search(flat.replace('『', '').replace('』', '')) or '"' not in flat:
            continue
        jp_quotes = QUOTE_JP.findall(clean(read_utf16(data, addr)).replace('\n', ''))
        en_quotes = list(QUOTE_EN.finditer(flat))
        if not jp_quotes or len(jp_quotes) != len(en_quotes):
            continue

        new, changed = flat, False
        for jq, m in reversed(list(zip(jp_quotes, en_quotes))):
            expected, quoted = jp_to_en.get(jq), m.group(1)
            if not expected or expected == quoted or expected in flat:
                continue
            if not similar(quoted, expected):
                flagged.append((row['pointer_value'], quoted, expected, jq))
                continue
            new = new[:m.start(1)] + expected + new[m.end(1):]
            fixes.append((row['pointer_value'], quoted, expected, jq))
            changed = True
        if changed:
            row['extract'] = wrap_game_text(new, WRAP).replace('\n', '†')

    with REPORT_CSV.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['pointer_value', 'quoted_before', 'game_name', 'quoted_jp', 'action'])
        w.writerows([(*x, 'replaced') for x in fixes] + [(*x, 'flagged (too different)') for x in flagged])

    print(f"{len(fixes)} quote(s) replaced, {len(flagged)} flagged → {REPORT_CSV}")
    for p, a, b, _ in fixes[:30]:
        print(f"  {a!r} -> {b!r}")
    for p, a, b, _ in flagged:
        print(f"  ⚠ not replaced: {a!r} (game: {b!r}) @ {p}")

    if not check_only and fixes:
        shutil.copyfile(TRANSLATED_CSV, TRANSLATED_CSV.with_suffix('.csv.bak'))
        with TRANSLATED_CSV.open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow(['pointer_offsets', 'pointer_value', 'separators', 'extract'])
            for r in rows:
                w.writerow([r['pointer_offsets'], r['pointer_value'], r['separators'], r['extract']])
        print(f"✔ {TRANSLATED_CSV} updated")


if __name__ == "__main__":
    main()
