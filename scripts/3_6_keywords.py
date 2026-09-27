# -*- coding: utf-8 -*-
"""Card name keyword consistency (gameplay).

    python scripts/3_6_keywords.py [--check] [--verbose]

Abilities like "if you have a card whose name contains / is X" are evaluated
by sub_72EAC0: for each card, the game compares the DISPLAYED NAME (record
+0x08, without furigana) with the keywords of table 0xD9FE90, by content
("contains" if bit 31 is set, otherwise "equals"). After translation, each
keyword must therefore match EXACTLY the same cards as in Japanese.

For each keyword, the translation picked is, in order:
  1. the decision from files/keyword_map.csv (keyword_jp;keyword_en;note);
  2. the current translation, if it already gives the same set of cards;
  3. "equals": the English name of the targeted card;
     "contains": the shortest whole word (or group of words) shared by the
     English names of the targeted cards that selects no other card.
The script writes the translation into extracted_strings_updated.csv (.bak
copy) and fails (exit code 1) if a keyword is left without a solution or a
decision, or if two different Japanese cards share the same English name.
--check: writes nothing, only checks.
"""
import csv
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from vanguard_tables import (BASE_ADDR, CARD_COUNT, CARD_NAME_FIELD, CARD_STRIDE,
                             CARD_TABLE_START, KEYWORD_COUNT, KEYWORD_TABLE,
                             read_utf16, u32)

csv.field_size_limit(2**31 - 1)

BIN_PATH       = Path("full_padded.bin")
TRANSLATED_CSV = Path("extracted_strings_updated.csv")
KEYWORD_MAP    = Path("files/keyword_map.csv")

FURIGANA = re.compile(r'<\|([^|]*)\|[^|]*\|>')


def strip_furigana(s: str) -> str:
    return FURIGANA.sub(r'\1', s)


def load_translations():
    with TRANSLATED_CSV.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f, delimiter=';'))
    return rows, {int(r['pointer_value'], 16): r for r in rows}


def load_decisions():
    decisions = {}
    if KEYWORD_MAP.exists():
        with KEYWORD_MAP.open(newline='', encoding='utf-8') as f:
            for r in csv.DictReader(f, delimiter=';'):
                decisions[r['keyword_jp']] = (r['keyword_en'], r.get('note', ''))
    return decisions


def is_whole_words(sub: str, name: str) -> bool:
    """sub appears in name as whole word(s) (not in the middle of a word)."""
    i = name.find(sub)
    while i != -1:
        before = name[i - 1] if i > 0 else ' '
        after = name[i + len(sub)] if i + len(sub) < len(name) else ' '
        if not before.isalnum() and not after.isalnum():
            return True
        i = name.find(sub, i + 1)
    return False


_KANA = dict(zip(
    "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン"
    "ガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポヴ",
    "a i u e o ka ki ku ke ko sa shi su se so ta chi tsu te to na ni nu ne no ha hi fu he ho "
    "ma mi mu me mo ya yu yo ra ri ru re ro wa wo n ga gi gu ge go za ji zu ze zo da ji zu de do "
    "ba bi bu be bo pa pi pu pe po vu".split()))
_SMALL = {'ァ': 'a', 'ィ': 'i', 'ゥ': 'u', 'ェ': 'e', 'ォ': 'o', 'ャ': 'ya', 'ュ': 'yu', 'ョ': 'yo'}


def romanize(katakana: str) -> str:
    """Rough romanization of a katakana word (to compare with the English)."""
    out = ''
    for i, ch in enumerate(katakana):
        if ch in _KANA:
            out += _KANA[ch]
        elif ch in _SMALL:
            out = (out[:-1] if out and out[-1] in 'aiueo' else out) + _SMALL[ch]
        elif ch == 'ッ' and i + 1 < len(katakana) and katakana[i + 1] in _KANA:
            out += _KANA[katakana[i + 1]][0]
        elif ch == 'ー' and out:
            out += out[-1]
    return out


def best_candidate(kw_jp: str, cands: list) -> str:
    """Katakana: the candidate closest to the romanization (proper noun).
    Kanji/hiragana: the longest group of words (full descriptive term)."""
    from difflib import SequenceMatcher
    if all('゠' <= ch <= 'ヿ' for ch in kw_jp):
        roma = romanize(kw_jp)
        return max(cands, key=lambda c: (SequenceMatcher(None, roma, c.lower().replace(' ', '')).ratio(), -len(c)))
    return max(cands, key=len)


def matches(keyword, name, contains):
    return keyword in name if contains else keyword == name


def main():
    check_only = '--check' in sys.argv
    data = BIN_PATH.read_bytes()
    rows, by_addr = load_translations()
    decisions = load_decisions()

    def translated(addr):
        row = by_addr.get(addr)
        return (row['extract'] if row else read_utf16(data, addr)).replace('†', '\n')

    # Cards: number -> (JP name, EN name), without furigana
    cards = {}
    for i in range(CARD_COUNT):
        rec = CARD_TABLE_START + i * CARD_STRIDE
        if not int.from_bytes(data[rec + 4 - BASE_ADDR:rec + 6 - BASE_ADDR], 'little'):
            continue
        name_addr = u32(data, rec + CARD_NAME_FIELD)
        cards[u32(data, rec)] = (strip_furigana(read_utf16(data, name_addr)),
                                 strip_furigana(translated(name_addr)))

    errors = []
    by_en = defaultdict(set)
    for jp, en in cards.values():
        by_en[en].add(jp)
    for en, jps in by_en.items():
        if len(jps) > 1:
            errors.append(f"English name shared by different cards: {en!r} <- {sorted(jps)}")

    # Keywords: (contains?, string address)
    keywords = {}
    for i in range(KEYWORD_COUNT):
        flag = u32(data, KEYWORD_TABLE + i * 8)
        addr = u32(data, KEYWORD_TABLE + i * 8 + 4)
        if addr:
            keywords[(bool(flag >> 31), addr)] = None

    def card_set(keyword, contains, lang):
        return {c for c, names in cards.items() if matches(keyword, names[lang], contains)}

    new_text = {}      # address -> chosen translation
    deviations = []
    for contains, addr in sorted(keywords):
        kw_jp = strip_furigana(read_utf16(data, addr))
        target = card_set(kw_jp, contains, 0)
        current = strip_furigana(translated(addr))

        if kw_jp in decisions:
            chosen, note = decisions[kw_jp]
            got = card_set(chosen, contains, 1)
            if got != target:
                extra = sorted(cards[c][1] for c in got - target)
                missing = sorted(cards[c][1] for c in target - got)
                deviations.append(f"{kw_jp} -> {chosen!r} ({note}): extra {extra}, missing {missing}")
        elif card_set(current, contains, 1) == target:
            chosen = current
        elif not contains:
            ens = {cards[c][1] for c in target}
            chosen = ens.pop() if len(ens) == 1 else None
        else:
            chosen = None
            names = [cards[c][1] for c in target]
            if names:
                base = min(names, key=len)
                cands = {base[i:j] for i in range(len(base)) for j in range(i + 1, len(base) + 1)}
                cands = [c for c in cands
                         if c.strip() == c and c[0].isalnum() and c[-1].isalnum() and ',' not in c
                         and all(is_whole_words(c, n) for n in names)
                         and card_set(c, contains, 1) == target]
                if cands:
                    chosen = best_candidate(kw_jp, cands)

        if chosen is None:
            errors.append(f"keyword without a solution: {'contains' if contains else 'equals'} {kw_jp!r} "
                          f"({len(target)} cards) -> add a decision to {KEYWORD_MAP}")
            continue
        if chosen != current:
            if addr in new_text and new_text[addr] != chosen:
                errors.append(f"string 0x{addr:08X} shared by two incompatible keywords: "
                              f"{new_text[addr]!r} / {chosen!r}")
            new_text[addr] = chosen

    for addr, text in new_text.items():
        if addr not in by_addr:
            errors.append(f"keyword 0x{addr:08X} missing from {TRANSLATED_CSV} (run the extraction again)")

    print(f"{len(keywords)} keywords, {len(cards)} cards: {len(new_text)} keyword translation(s) to write")
    if "--verbose" in sys.argv:
        for addr, text in sorted(new_text.items()):
            print(f"  0x{addr:08X} {strip_furigana(read_utf16(data, addr))!r} -> {text!r}")
    for d in deviations:
        print(f"  accepted deviation: {d}")
    for e in errors:
        print(f"✘ {e}")

    if not check_only and new_text:
        shutil.copyfile(TRANSLATED_CSV, TRANSLATED_CSV.with_suffix('.csv.bak'))
        for addr, text in new_text.items():
            if addr in by_addr:
                by_addr[addr]['extract'] = text.replace('\n', '†')
        with TRANSLATED_CSV.open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow(['pointer_offsets', 'pointer_value', 'separators', 'extract'])
            for r in rows:
                w.writerow([r['pointer_offsets'], r['pointer_value'], r['separators'], r['extract']])
        print(f"✔ {TRANSLATED_CSV} updated")
    elif check_only and new_text:
        errors.append(f"{len(new_text)} inconsistent keyword(s) (run without --check to fix)")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
