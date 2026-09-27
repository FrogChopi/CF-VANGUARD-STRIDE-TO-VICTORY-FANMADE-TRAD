import argparse
import csv
import json
import os
import re
import unicodedata

# 1. Small kana -> full-size kana
KANA_SIZE_MAP = str.maketrans(
    "ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ",
    "あいうえおつやゆよわアイウエオツヤユヨワカケ",
)

# 2. Katakana (U+30A1..U+30F6) -> Hiragana (U+3041..U+3096)
KATAKANA_TO_HIRAGANA = {i: i - 0x60 for i in range(0x30A1, 0x30F7)}
KATAKANA_TO_HIRAGANA[0x30F4] = 0x3094  # ヴ -> ゔ


def clean_base_text(text: str) -> str:
    """Normalize quotes, dashes and Unicode, and remove ALL whitespace."""
    if not text:
        return ""

    # Unicode normalization (NFKC handles half-width chars and full-width spaces)
    text = unicodedata.normalize("NFKC", text)

    # Remove quotes and all whitespace (including inner)
    text = re.sub(r'[“”"«»\s]', "", text)

    # Small kana -> full-size kana
    text = text.translate(KANA_SIZE_MAP)

    # Katakana -> Hiragana
    text = text.translate(KATAKANA_TO_HIRAGANA)

    # Unify dashes and long-vowel marks
    text = re.sub(r"[―—–‐-]", "ー", text)

    return text


def extract_variants(raw_text: str) -> tuple[str, str]:
    """Return two normalized variants: (left Kanji part, right Furigana part)."""
    # 1. Main variant: keep the left part A of <|A|B|>
    kanji_text = re.sub(r"<\|([^|]+)\|[^>]*\|>", r"\1", raw_text)

    # 2. Phonetic variant: keep the right part B of <|A|B|>
    furigana_text = re.sub(r"<\|[^|]+\|([^>]*)\|>", r"\1", raw_text)

    return clean_base_text(kanji_text), clean_base_text(furigana_text)


def load_mapping(json_path: str) -> dict:
    """Load the JSON dictionary and normalize all its keys."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_mapping = {}

    if all(isinstance(v, str) for v in data.values()):
        raw_mapping = data
    else:
        for clan_cards in data.values():
            if isinstance(clan_cards, list):
                for card in clan_cards:
                    name = card.get("name") or card.get("Name")
                    if not name:
                        continue
                    if card.get("Kana"):
                        raw_mapping[card["Kana"]] = name
                    if card.get("Kanji"):
                        raw_mapping[card["Kanji"]] = name

    # Normalize keys (no whitespace)
    normalized_mapping = {}
    for k, v in raw_mapping.items():
        normalized_mapping[clean_base_text(k)] = v

    return normalized_mapping


JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
HEADER_SIG = re.compile(r"^((?:@0[DEF]|@23)(?:@[0-9A-F]{2}| )*)")  # @23 = Stride (G units)


def display_width(text: str) -> int:
    """On-screen width: full-width = 2, half-width = 1, @xx tags /
    {$…} colors = 0 (the icon is drawn over the spaces that follow it)."""
    text = re.sub(r"@[0-9A-F]{2}|\{\$[0-9a-fA-F]*\}", "", text)
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def wrap_game_text(text: str, width: int) -> str:
    """Wrap each line at `width` units (game lines are 32 to 34), between
    words. An ability header (up to the first ':') and tag lines
    (@40, @42…) are never split."""
    if width <= 0:
        return text
    out = []
    for line in text.split("\n"):
        if re.fullmatch(r"@4[0-9]", line) or display_width(line) <= width:
            out.append(line)
            continue
        head = ""
        m = HEADER_SIG.match(line)
        if m:
            colon = line.find(":", m.end() - 1)
            if colon != -1 and display_width(line[:colon + 1]) <= width:
                head, line = line[:colon + 1], line[colon + 1:]
        current = head
        # a cost code and its number ("@15 ③") stay on the same line
        line = re.sub(r"(@(?:1[345]|2A)) (?=[①-⑳])", "\\1\x00", line)
        for word in (w.replace("\x00", " ") for w in line.split(" ")):
            candidate = f"{current} {word}" if current and not current.endswith(":") else current + word
            if current and display_width(candidate) > width:
                out.append(current)
                current = word
            else:
                current = candidate
        out.append(current)
    return "\n".join(out)


def header_signature(line: str) -> str:
    """"@0D@05   @12  (…)" -> "@0D@05@12": ability type, zone, LB/GB, 1/turn."""
    m = HEADER_SIG.match(line)
    return m.group(1).replace(" ", "") if m else ""


def align_abilities(jp_lines: list, en_lines: list) -> dict:
    """Match the game's effect lines (table order) with the database
    abilities, by groups with the same header signature, in order. A group is
    only matched if it has the same number of lines on both sides.
    -> {index_jp: index_en}"""
    groups_jp, groups_en = {}, {}
    for i, line in enumerate(jp_lines):
        groups_jp.setdefault(header_signature(line), []).append(i)
    for i, line in enumerate(en_lines):
        groups_en.setdefault(header_signature(line), []).append(i)
    pairs = {}
    for sig, idx_jp in groups_jp.items():
        idx_en = groups_en.get(sig, [])
        if sig and len(idx_jp) == len(idx_en):
            pairs.update(zip(idx_jp, idx_en))
    return pairs


def card_texts_by_address(cards_json: str, bin_path: str, translations: dict) -> tuple[dict, dict]:
    """Official translations (files/vanguard_cards_balise.json) by game string
    address: effect lines (table 0xDA3730) and flavor blocks (+0x2C).
    translations: {name address: current text} to link by English name."""
    from compare_cards import (EFFECT_COUNT, EFFECT_TABLE, norm_name,
                               parse_card_block, set_code)
    from vanguard_tables import (BASE_ADDR, CARD_COUNT, CARD_STRIDE,
                                 CARD_TABLE_START, read_utf16, u32)

    data = open(bin_path, "rb").read()
    entries = json.load(open(cards_json, encoding="utf-8"))
    set_names = {}
    if os.path.exists("files/set_names.json"):
        set_names = json.load(open("files/set_names.json", encoding="utf-8"))
    index = {"kanji": {}, "kana": {}, "en": {}}
    for e in entries:
        for key, field in (("kanji", "kanji"), ("kana", "kana"), ("en", "name")):
            if e.get(field):
                index[key].setdefault(norm_name(e[field]), []).append(e)

    effect_lines = {}
    for i in range(EFFECT_COUNT):
        num = u32(data, EFFECT_TABLE + i * 8)
        effect_lines.setdefault(num, []).append(u32(data, EFFECT_TABLE + i * 8 + 4))

    effects, flavors = {}, {}
    stats = {"cards linked": 0, "cards without entry": 0,
             "effect lines aligned": 0, "effect lines not aligned": 0}
    for i in range(CARD_COUNT):
        rec = CARD_TABLE_START + i * CARD_STRIDE
        if not int.from_bytes(data[rec + 4 - BASE_ADDR:rec + 6 - BASE_ADDR], "little"):
            continue
        num = u32(data, rec)
        name_addr = u32(data, rec + 0x08)
        jp_name = read_utf16(data, name_addr)
        kana = read_utf16(data, u32(data, rec + 0x0C))
        block_addr = u32(data, rec + 0x2C)
        code = set_code(parse_card_block(read_utf16(data, block_addr)).get("@42", ""))

        found = []
        for key, value in (("kanji", jp_name), ("kana", kana), ("en", translations.get(name_addr, ""))):
            found = index[key].get(norm_name(value), [])
            if found:
                break
        if not found:
            stats["cards without entry"] += 1
            continue
        stats["cards linked"] += 1

        # several entries (reprints, "(No Ability)", "(Stride Bonus)" variants…):
        # the one whose abilities align best, then the one from the same set
        addrs = effect_lines.get(num, [])
        jp_lines = [read_utf16(data, a) for a in addrs]
        def score(e):
            same_set = (e.get("set_id") or "").split("/")[0].replace("V-", "") == code
            return (len(align_abilities(jp_lines, e.get("effet_modified", []))),
                    len(e.get("effet_modified", [])) == len(jp_lines), same_set)
        entry = max(found, key=score)

        # effects: alignment by header signature
        pairs = align_abilities(jp_lines, entry.get("effet_modified", []))
        for j, addr in enumerate(addrs):
            if j in pairs:
                effects.setdefault(addr, entry["effet_modified"][pairs[j]])
                stats["effect lines aligned"] += 1
            else:
                stats["effect lines not aligned"] += 1

        # flavor: the print of the game's set if the database has several;
        # the @42 line ALWAYS shows the game's set (code + English name from
        # files/set_names.json), not the set of a reprint from the database
        flavor = entry.get("flavor_modified", "")
        for v in entry.get("flavor_variants", []):
            if v["flavor_modified"].split("\n")[1].split(" ")[0].replace("V-", "") == code:
                flavor = v["flavor_modified"]
                break
        if flavor and code:
            set_line = code if code == "PR" else f"{code} {set_names.get(code, '')}".strip()
            flavor = re.sub(r"^@42\n[^\n]*", "@42\n" + set_line.replace("\\", "\\\\"), flavor)
        if flavor:
            flavors.setdefault(block_addr, flavor)

    for k, v in stats.items():
        print(f"  {k:28}: {v}")
    return effects, flavors


def update_csv(
    json_path: str,
    input_csv_path: str,
    output_csv_path: str,
    text_column: str = "extract",
    cards_json: str = None,
    bin_path: str = "full_padded.bin",
    overwrite: bool = False,
    wrap: int = 34,
):
    mapping = load_mapping(json_path)
    count = 0

    with open(input_csv_path, "r", encoding="utf-8") as f_in:
        reader = csv.DictReader(f_in, delimiter=";")
        fieldnames = reader.fieldnames
        rows = list(reader)

    for row in rows:
        raw_cell = row.get(text_column, "")
        norm_kanji, norm_furi = extract_variants(raw_cell)

        # Try the Kanji spelling first, then the Furigana reading
        if norm_kanji in mapping:
            row[text_column] = mapping[norm_kanji]
            count += 1
        elif norm_furi in mapping:
            row[text_column] = mapping[norm_furi]
            count += 1

    # Official effects and flavors (code.bin CSV only: pointer_value column)
    card_count = 0
    if cards_json and "pointer_value" in (fieldnames or []):
        translations = {int(r["pointer_value"], 16): r[text_column] for r in rows}
        effects, flavors = card_texts_by_address(cards_json, bin_path, translations)
        for row in rows:
            addr = int(row["pointer_value"], 16)
            text = effects.get(addr) or flavors.get(addr)
            if text and (overwrite or JAPANESE.search(row[text_column])):
                row[text_column] = wrap_game_text(text, wrap).replace("\n", "†")
                card_count += 1

    # csv.writer: automatic quoting if a text contains ';' or '"'
    with open(output_csv_path, "w", encoding="utf-8", newline="") as f_out:
        writer = csv.writer(f_out, delimiter=";", lineterminator="\n")
        writer.writerow(fieldnames)
        for row in rows:
            writer.writerow([row.get(col, "") for col in fieldnames])

    print(f"Done: {count} name(s) replaced, {card_count} card effect(s)/flavor(s).")
    print(f"Saved to: {output_csv_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Replace a CSV text column using a JSON mapping (furigana, spaces and kana normalized)."
    )
    parser.add_argument(
        "json_file", help="Path to the JSON mapping file"
    )
    parser.add_argument("input_csv", help="Path to the source CSV")
    parser.add_argument("output_csv", help="Path to the output CSV")
    parser.add_argument(
        "--column",
        default="extract",
        help="Target column name (default: extract)",
    )

    parser.add_argument(
        "--cards",
        help="Tagged card database (files/vanguard_cards_balise.json): also replaces "
             "the code.bin effect lines and flavors",
    )
    parser.add_argument("--bin", default="full_padded.bin", help="code.bin binary (default: full_padded.bin)")
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Also replace effects/flavors already translated (default: only those still in Japanese)",
    )

    parser.add_argument("--wrap", type=int, default=34,
                        help="Line width for effects/flavors (half-width units, 0 = no wrapping)")

    args = parser.parse_args()
    update_csv(args.json_file, args.input_csv, args.output_csv, args.column,
               args.cards, args.bin, args.overwrite, args.wrap)