# -*- coding: utf-8 -*-
"""Compare the game's card texts (flavor @42 and effect lines) with an
official card database (vanguard_cards_enriched.json).

    python scripts/compare_cards.py [database.json] [output.csv]

In code.bin:
  - card record (vanguard_tables): +0x08 name, +0x0C kana reading,
    +0x2C block "@42 set / @40 flavor / @43 author / @41 illustrator";
  - effects: table 0xDA3730 {card number, text}, one line per ability.
A game card is linked to the database by its kanji name, then its kana
reading, then its English name; the set code (ＴＤ０１ → TD01) breaks ties
between reprints.
Also provides set_code(), norm_name()... used by update_csv.py and 3_8.
"""
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from vanguard_tables import (BASE_ADDR, CARD_COUNT, CARD_STRIDE, CARD_TABLE_START,
                             read_utf16, u32)

csv.field_size_limit(2**31 - 1)

BIN_PATH       = Path("full_padded.bin")
TRANSLATED_CSV = Path("extracted_strings_updated.csv")
DB_PATH        = Path(sys.argv[1] if len(sys.argv) > 1 else "vanguard_cards_enriched.json")
OUTPUT_CSV     = Path(sys.argv[2] if len(sys.argv) > 2 else "cards_compare.csv")

EFFECT_TABLE, EFFECT_COUNT = 0xDA3730, 5159

FURIGANA = re.compile(r'<\|([^|]*)\|[^|]*\|>')
DB_ABILITY = re.compile(r'\[(?:AUTO|CONT|ACT)\]')
SET_CODE = re.compile(r'^[A-Z]+(?:-[A-Z]+)*\d+')


# Icon codes of effect lines, deduced by aligning ~3400 game cards with the
# database (co-occurrence >= 95 %). Rare/ambiguous codes are left raw.
ICON_CODES = {
    '@0E': '[AUTO]', '@0F': '[CONT]', '@0D': '[ACT]',
    '@05': '(VC)', '@02': '(VC)', '@03': '(RC)', '@00': '(RC)', '@06': '(VC/RC)', '@01': '(GC)',
    '@07': '[Power]', '@09': '[Critical]',
    '@15': '[Counter Blast]', '@14': '[Soul Blast]', '@13': '[Soul Charge]', '@2A': '[Counter Charge]',
    '@12': '[Limit Break]', '@25': '[Generation Break]', '@11': '[Stand]', '@10': '[Rest]',
}


def decode_icons(line: str) -> str:
    line = re.sub(r'@[0-9A-F]{2}', lambda m: ICON_CODES.get(m.group(0), m.group(0)), line)
    return re.sub(r' {2,}', ' ', line.replace('\n', ''))


def flavor_for_set(flavor: str, code: str) -> str:
    """The database concatenates the flavors of every print:
    "(EB01 RRR): ... (EB04 SP): ..." -> keep the one of the game's set."""
    segments = re.split(r'\(([A-Z0-9-]+)(?: [A-Z]+)?\):\s*', flavor)
    if len(segments) < 3 or not code:
        return flavor
    pairs = list(zip(segments[1::2], segments[2::2]))
    for seg_code, text in pairs:
        if seg_code.replace('V-', '') == code:
            return text.strip()
    return flavor


def split_db_abilities(effect: str) -> list:
    """Split the database effect into abilities ([AUTO]/[CONT]/[ACT]), like the game."""
    starts = [m.start() for m in DB_ABILITY.finditer(effect)]
    if not starts:
        return [effect] if effect else []
    return [effect[a:b].strip() for a, b in zip(starts, starts[1:] + [len(effect)])]


def strip_furigana(s: str) -> str:
    return FURIGANA.sub(r'\1', s or '')


def norm_name(s: str) -> str:
    s = unicodedata.normalize('NFKC', strip_furigana(s))
    s = ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ヶ' else c for c in s)   # katakana -> hiragana
    s = s.translate(str.maketrans('ぁぃぅぇぉっゃゅょゎ', 'あいうえおつやゆよわ'))
    return re.sub(r'[\s・･·“”"\'「」『』\-ー―]', '', s).lower()


def parse_card_block(text: str) -> dict:
    """Split the +0x2C block into {'@42': set, '@40': flavor, ...}."""
    parts, key = {}, None
    for line in text.split('\n'):
        if re.fullmatch(r'@4[0-9]', line):
            key = line
            parts[key] = []
        elif key:
            parts[key].append(line)
    return {k: '\n'.join(v) for k, v in parts.items()}


def set_code(ext: str) -> str:
    m = SET_CODE.match(unicodedata.normalize('NFKC', strip_furigana(ext)).replace(' ', ''))
    return m.group(0) if m else ''


def main():
    data = BIN_PATH.read_bytes()
    translated = {}
    if TRANSLATED_CSV.exists():
        with TRANSLATED_CSV.open(newline='', encoding='utf-8') as f:
            translated = {int(r['pointer_value'], 16): r['extract'].replace('†', '\n')
                          for r in csv.DictReader(f, delimiter=';')}

    db_cards = [c for clan in json.load(DB_PATH.open(encoding='utf-8')).values() for c in clan]
    index = {'kanji': defaultdict(list), 'kana': defaultdict(list), 'en': defaultdict(list)}
    for c in db_cards:
        if c.get('Kanji'):
            index['kanji'][norm_name(c['Kanji'])].append(c)
        if c.get('Kana'):
            index['kana'][norm_name(c['Kana'])].append(c)
        index['en'][norm_name(c.get('name', ''))].append(c)

    effects = defaultdict(list)
    for i in range(EFFECT_COUNT):
        effects[u32(data, EFFECT_TABLE + i * 8)].append(u32(data, EFFECT_TABLE + i * 8 + 4))

    stats = defaultdict(int)
    out = []
    for i in range(CARD_COUNT):
        rec = CARD_TABLE_START + i * CARD_STRIDE
        if not int.from_bytes(data[rec + 4 - BASE_ADDR:rec + 6 - BASE_ADDR], 'little'):
            continue
        num = u32(data, rec)
        name_addr = u32(data, rec + 0x08)
        jp_name = read_utf16(data, name_addr)
        kana = read_utf16(data, u32(data, rec + 0x0C))
        en_name = translated.get(name_addr, jp_name)
        block = parse_card_block(read_utf16(data, u32(data, rec + 0x2C)))
        ext = block.get('@42', '')
        code = set_code(ext)

        candidates, how = [], ''
        for how, key in (('kanji', norm_name(jp_name)), ('kana', norm_name(kana)), ('en', norm_name(en_name))):
            candidates = index[how].get(key, [])
            if candidates:
                break
        if len(candidates) > 1 and code:
            same_set = [c for c in candidates if (c.get('set_id') or '').split('/')[0].replace('V-', '') == code
                        or code in (c.get('card_sets') or '')]
            if same_set:
                candidates, how = same_set, how + '+extension'
        # identical duplicate entries (same card listed under several clans)
        uniq = {(c.get('name'), c.get('card_effect'), c.get('card_flavor')): c for c in candidates}
        candidates = list(uniq.values())
        match = candidates[0] if candidates else None
        status = 'none' if not candidates else ('unique' if len(candidates) == 1 else 'ambiguous')
        stats[status] += 1

        jp_lines = [strip_furigana(read_utf16(data, a)) for a in effects.get(num, [])]
        db_effect = (match or {}).get('card_effect', '') or ''
        out.append({
            'card_num': f"0x{num:08X}",
            'name_jp': strip_furigana(jp_name),
            'name_en_game': en_name,
            'name_db': (match or {}).get('name', ''),
            'match': f"{status} ({how})" if candidates else status,
            'set_game': strip_furigana(ext).replace('\n', ' '),
            'set_db': (match or {}).get('set_id', ''),
            'flavor_jp': strip_furigana(block.get('@40', '')),
            'flavor_db': flavor_for_set((match or {}).get('card_flavor', '') or '', code),
            'effect_lines_jp': len(jp_lines),
            'abilities_db': len(DB_ABILITY.findall(db_effect)),
            'effects_jp': '\n‖ '.join(jp_lines),
            'effects_jp_decoded': '\n‖ '.join(decode_icons(l) for l in jp_lines),
            'effect_db': '\n‖ '.join(split_db_abilities(db_effect)),
        })

    with OUTPUT_CSV.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]), delimiter=';')
        w.writeheader()
        w.writerows(out)

    total = len(out)
    print(f"✔ {OUTPUT_CSV}: {total} cards")
    for k in ('unique', 'ambiguous', 'none'):
        print(f"  match {k:9}: {stats[k]}")
    same = sum(1 for r in out if r['name_db'] and r['effect_lines_jp'] == r['abilities_db'])
    print(f"  same number of abilities (game / db): {same}/{total - stats['none']}")


if __name__ == "__main__":
    main()
