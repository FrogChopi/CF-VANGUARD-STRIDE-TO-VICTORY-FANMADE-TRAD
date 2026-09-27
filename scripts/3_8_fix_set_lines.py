"""Rewrite the set line (@42) of translated card blocks from the game's
Japanese text: the game's set code + official English name
(files/set_names.json). Avoids Italian names / foreign reprints coming from
the card database or older translations.

Usage: python scripts/3_8_fix_set_lines.py [extract.csv] [translated.csv]
"""
import csv
import json
import re
import sys
import unicodedata

sys.path.insert(0, "scripts")
from compare_cards import set_code  # noqa: E402
from update_csv import wrap_game_text  # noqa: E402

EXTRACT = sys.argv[1] if len(sys.argv) > 1 else "extracted_strings.csv"
TRANSLATED = sys.argv[2] if len(sys.argv) > 2 else "extracted_strings_updated.csv"
GENERIC = {"PR": "PR Promo Cards", "MB": "MB Monthly Bushiroad"}
SET_LINE = re.compile(r"(^|†)@42†(.*?)(?=†@4[0-9]|$)")


def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f, delimiter=";"))


def main():
    set_names = json.load(open("files/set_names.json", encoding="utf-8"))
    jp = {r[1]: r[3] for r in read(EXTRACT)[1:]}
    rows = read(TRANSLATED)
    changed, unknown = 0, set()
    for r in rows[1:]:
        m_en = SET_LINE.search(r[3])
        m_jp = SET_LINE.search(jp.get(r[1], ""))
        if not m_en or not m_jp:
            continue
        raw = unicodedata.normalize("NFKC", m_jp.group(2).replace("†", "")).strip()
        code = set_code(raw)
        if code:
            if code not in set_names and not code.startswith("PR"):
                unknown.add(code)
            line = code if code.startswith("PR") else f"{code} {set_names.get(code, '')}".strip()
        elif raw in GENERIC:          # "ＰＲ", "ＭＢ": promo card without a number
            line = GENERIC[raw]
        elif raw.isascii():           # already in Latin script ("Rise to Royalty", "VZ")
            line = raw
        else:
            continue
        line = wrap_game_text(line, 34).replace("\n", "†")
        new = r[3][:m_en.start(2)] + line + r[3][m_en.end(2):]
        if new != r[3]:
            r[3] = new
            changed += 1
    with open(TRANSLATED, "w", newline="", encoding="utf-8") as f:
        csv.writer(f, delimiter=";").writerows(rows)
    print(f"{changed} @42 lines rewritten")
    if unknown:
        print("codes without a name in set_names.json:", " ".join(sorted(unknown)))


if __name__ == "__main__":
    main()
