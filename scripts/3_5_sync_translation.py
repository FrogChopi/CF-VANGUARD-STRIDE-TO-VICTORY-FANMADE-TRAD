# -*- coding: utf-8 -*-
"""Sync the translated CSV with a fresh extraction, without losing anything.

    python scripts/3_5_sync_translation.py [extract.csv] [translated.csv] [name_table.json]
    python scripts/3_5_sync_translation.py extracted_outside.csv extracted_outside_updated.csv

For each row of the extraction (pointer_offsets / separators always come from
the extraction):
  1. the JP text matches a name in name_table.json -> English name (the name
     table is authoritative, to stay identical to the .rtz);
  2. the JP text is exactly a card name -> translation of that name
     (record +0x08, in the range CSV);
  3. [out-of-range CSV] same JP text as a translated string of the range ->
     same translation (name keywords, clans...: abilities compare the text);
  4. otherwise the existing translation (same pointer_value) is kept;
  5. otherwise the JP text is kept as-is (new row to translate).
The previous translated file is backed up as .bak.
"""
import csv
import shutil
import sys
from pathlib import Path

from update_csv import extract_variants, load_mapping

csv.field_size_limit(2**31 - 1)

EXTRACT_CSV    = Path(sys.argv[1] if len(sys.argv) > 1 else "extracted_strings.csv")
TRANSLATED_CSV = Path(sys.argv[2] if len(sys.argv) > 2 else "extracted_strings_updated.csv")
NAME_TABLE     = Path(sys.argv[3] if len(sys.argv) > 3 else "files/name_table.json")
RANGE_JP_CSV   = Path("extracted_strings.csv")            # known range: reference
RANGE_TR_CSV   = Path("extracted_strings_updated.csv")


def card_name_strings():
    """(address, JP text) of each card name (record +0x08) in full_padded.bin."""
    from vanguard_tables import CARD_COUNT, CARD_STRIDE, CARD_TABLE_START, read_utf16, u32
    bin_path = Path("full_padded.bin")
    if not bin_path.exists():
        return []
    data = bin_path.read_bytes()
    result = []
    for i in range(CARD_COUNT):
        addr = u32(data, CARD_TABLE_START + i * CARD_STRIDE + 0x08)
        result.append((addr, read_utf16(data, addr)))
    return result


def read_rows(path: Path):
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f, delimiter=';'))


def main():
    fresh = read_rows(EXTRACT_CSV)
    old = {r['pointer_value']: r['extract'] for r in read_rows(TRANSLATED_CSV)} if TRANSLATED_CSV.exists() else {}
    mapping = load_mapping(str(NAME_TABLE))

    # Range CSV (reference): translation by address
    is_range = TRANSLATED_CSV.resolve() == RANGE_TR_CSV.resolve()
    range_tr = {}
    if not is_range and RANGE_TR_CSV.exists():
        range_tr = {r['pointer_value']: r['extract'] for r in read_rows(RANGE_TR_CSV)}

    # Name of each card (record +0x08, without furigana) -> translation of that name:
    # a copy of the name elsewhere (ability conditions, code literals...)
    # gets the same translation, even if name_table.json doesn't know that spelling.
    by_addr = {r['pointer_value']: r for r in fresh}
    card_names = {}
    for addr, jp_name in card_name_strings():
        kanji, furi = extract_variants(jp_name)
        en = mapping.get(kanji) or mapping.get(furi) or range_tr.get(f"0x{addr:08X}")
        if en and en != jp_name:
            card_names.setdefault(kanji, en)

    # [out of range] same JP text as a translated string of the range -> same translation
    same_text = {}
    if range_tr and RANGE_JP_CSV.exists():
        for r in read_rows(RANGE_JP_CSV):
            tr = range_tr.get(r['pointer_value'])
            if tr and tr != r['extract']:
                same_text.setdefault(extract_variants(r['extract'])[0], tr)

    stats = {'name (name_table)': 0, 'name (card copy)': 0, 'same text as range': 0,
             'translation kept': 0, 'new (JP)': 0}
    out = []
    for row in fresh:
        kanji, furi = extract_variants(row['extract'])
        if kanji in mapping or furi in mapping:
            text = mapping.get(kanji) or mapping[furi]
            stats['name (name_table)'] += 1
        elif kanji in card_names:
            text = card_names[kanji]
            stats['name (card copy)'] += 1
        elif kanji in same_text:
            text = same_text[kanji]
            stats['same text as range'] += 1
        elif row['pointer_value'] in old:
            text = old[row['pointer_value']]
            stats['translation kept'] += 1
        else:
            text = row['extract']
            stats['new (JP)'] += 1
        out.append([row['pointer_offsets'], row['pointer_value'], row['separators'], text])

    lost = set(old) - {r['pointer_value'] for r in fresh}
    if TRANSLATED_CSV.exists():
        shutil.copyfile(TRANSLATED_CSV, TRANSLATED_CSV.with_suffix('.csv.bak'))
    with TRANSLATED_CSV.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['pointer_offsets', 'pointer_value', 'separators', 'extract'])
        w.writerows(out)

    print(f"✔ {TRANSLATED_CSV} synced ({len(out)} rows)")
    for k, v in stats.items():
        print(f"  {k:22} : {v}")
    if lost:
        print(f"⚠ {len(lost)} row(s) of the old file missing from the extraction "
              f"(kept in {TRANSLATED_CSV.with_suffix('.csv.bak')}): {sorted(lost)[:10]}")


if __name__ == "__main__":
    main()
