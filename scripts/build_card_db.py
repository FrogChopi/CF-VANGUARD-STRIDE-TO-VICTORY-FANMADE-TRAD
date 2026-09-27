# -*- coding: utf-8 -*-
"""Convert the English card database to the game's text format (@xx tags).

    python scripts/build_card_db.py [vanguard_cards_enriched.json] [files/vanguard_cards_balise.json]

For each card:
  name, effet, effet_modified, flavor, flavor_modified
  (+ clan, kanji, kana, set_id, flavor_variants to link it to the game).

effet / effet_modified: lists, one entry per ability (the game stores one
string per ability); split on [AUTO]/[CONT]/[ACT], except inside an ability
given between quotes ("[CONT]…").
effet_modified: with the game's icon tags and their spaces. Only confirmed
tags (game/database alignment over ~3400 cards) are converted; the rest stays
as text. No wrapping to the screen width here.
flavor_modified: block of the +0x2C field of a card record:
  @42 set / @40 flavor / @41 illustrator.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "vanguard_cards_enriched.json")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "files/vanguard_cards_balise.json")

CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳'

# Tag + the spaces that follow it in the game (width reserved for the icon).
ABILITY = {'AUTO': '@0E', 'CONT': '@0F', 'ACT': '@0D'}
HEADER_ZONE = {'(VC)': '@05   ', '(RC)': '@03   ', '(VC/RC)': '@06       ',
               '(GC)': '@01 ', '(VC/RC/GC)': '@28             '}
INLINE_ZONE = {'(VC)': '@02 ', '(RC)': '@00 ', '(GC)': '@01 '}
ONE_PER_TURN = '@27     '
LIMIT_BREAK = {'4': '@12  ', '5': '@1E  '}
GENERATION_BREAK = {'1': '@25   ', '2': '@26   '}
COSTS = {'Counter Blast': '@15 ', 'Soul Blast': '@14 ', 'Soul Charge': '@13 ', 'Counter Charge': '@2A '}
ICONS = {'[Power]': '@07', '[Critical]': '@09', '[Shield]': '@08', '[Stand]': '@11', '[Rest]': '@10',
         '[ Stride ]': '@23    ', '[Stride]': '@23    '}

ABILITY_START = re.compile(r'\[(AUTO|CONT|ACT)\]')
HEADER = re.compile(
    r'^\[(?P<type>AUTO|CONT|ACT)\]\s*'
    r'(?P<zone>\((?:VC/RC/GC|VC/RC|VC|RC|GC)\))?\s*'
    r'(?P<turn>\[?1/Turn\]?)?\s*'
    r'(?:Limit Break (?P<lb>\d)|Generation Break (?P<gb>\d))?')


def circled(n: str) -> str:
    i = int(n)
    return CIRCLED[i - 1] if 1 <= i <= len(CIRCLED) else f'({n})'


def quote_given_abilities(effect: str) -> str:
    """Abilities given between quotes ("[CONT]…") -> 『[CONT]…』 like the game,
    so they stay in the line of the ability that grants them."""
    return re.sub(r'"\s*(\[(?:AUTO|CONT|ACT)\][^"]*?)\s*"', r'『\1』', effect)


def split_abilities(effect: str) -> list:
    """One entry per ability, without splitting inside a given ability 『…』."""
    depth, starts = 0, []
    for i, ch in enumerate(effect):
        depth += (ch == '『') - (ch == '』')
        if depth == 0 and ABILITY_START.match(effect, i):
            starts.append(i)
    if not starts:
        return [effect.strip()] if effect.strip() else []
    head = effect[:starts[0]].strip()
    parts = [effect[a:b].strip() for a, b in zip(starts, starts[1:] + [len(effect)])]
    if head:  # text before the first ability (e.g. "Sentinel" without a tag)
        parts.insert(0, head)
    return parts


def convert_header(text: str) -> str:
    """"[AUTO](VC) 1/Turn Generation Break 1 (...):" -> "@0E@05   @27     @25   (...):" """
    m = HEADER.match(text)
    if not m:
        return text
    lb, gb = m.group('lb'), m.group('gb')
    header = ABILITY[m.group('type')]
    if m.group('zone'):
        header += HEADER_ZONE[m.group('zone')]
    if m.group('turn'):
        header += ONE_PER_TURN
    rest = text[m.end():]
    if lb:
        header += LIMIT_BREAK.get(lb, f'Limit Break {lb} ')
    if gb:
        header += GENERATION_BREAK.get(gb, f'Generation Break {gb} ')
    rest = rest.lstrip() if (lb or gb) else rest
    # the game glues the header ':' to the text: "(…) : Lord" -> "(…):Lord"
    if header and not rest.startswith('('):
        rest = re.sub(r'^\s*:\s*', ':', rest)
    else:
        rest = re.sub(r'^(\([^()]*(?:\([^()]*\)[^()]*)*\))\s*:\s*', r'\1:', rest)
    return header + rest


def convert_ability(text: str) -> str:
    out = convert_header(text)
    # given abilities 『[CONT](VC):…』: same header as normal abilities
    out = re.sub(r'『([^』]*)』', lambda mm: '『' + convert_header(mm.group(1)) + '』', out)

    # costs and numbered actions: "Counter Blast (2)", "Counter Blast(2)", "Counter-Blast 2"
    for word, code in COSTS.items():
        pat = word.replace(' ', r'[ -]?')
        out = re.sub(pat + r'\s*\(?\s*(\d+)\s*\)?', lambda mm: code + circled(mm.group(1)), out)
    # Legion: "Legion 20000" header and verb ("When this unit Legion")
    out = re.sub(r'\bLegion \d{5}\b\s*', '@1F       ', out)
    out = re.sub(r'(?<=unit )Legion\b|(?<=is )Legion\b', '@22  ', out)
    for tok, code in ICONS.items():
        out = out.replace(tok, code)
    # remaining zones = zones in the text (header ones are already codes):
    # the game puts exactly one space after the icon ("@02 か@00 に")
    for tok, code in INLINE_ZONE.items():
        out = re.sub(re.escape(tok) + ' ?', code, out)
    # multiple costs: "[@15 ③ & @14 ③ & Choose…]" -> "[@15 ③,@14 ③,Choose…]" like the game
    out = re.sub(r'\[[^\]]*\]', lambda mm: re.sub(r'\s*&\s*', ',', mm.group(0))
                 if re.search(r'@1[345]|@2A', mm.group(0)) else mm.group(0), out)
    # game punctuation
    out = out.replace('«', '《').replace('»', '》')
    out = re.sub(r'《\s*([^》]*?)\s*》', r'《\1》', out)   # "« Granblue »" -> "《Granblue》"
    return sanitize(out)


CARD_CODE = re.compile(r'[A-Z][A-Z0-9-]*/[A-Z]*\d+[A-Z]*(?: \([A-Z]+\))?(?: \d{4})?')


def parse_sets(card_sets: str) -> list:
    """"Card Set(s) Name - CODE/NNN (R) - CODE/Sxx (SP) CODE/NNNEN Name2 - CODE2/NNN"
    -> [(code, name)]: the free text between two card codes is the set name of
    the codes that follow (names may contain '-' or ':')."""
    s = re.sub(r'^Card Set\(s\)\s*', '', card_sets or '')
    found, name, pos = [], '', 0
    for m in CARD_CODE.finditer(s):
        chunk = s[pos:m.start()].strip().strip('-').strip()
        if chunk:
            name = chunk
        code = m.group(0).split('/')[0]
        if name and code not in dict(found):
            found.append((code, name))
        pos = m.end()
    return found


def flavor_variants(flavor: str) -> list:
    """"(EB01 RRR): a (SP): b" -> [("EB01 RRR", "a"), ("SP", "b")]; otherwise [("", flavor)]."""
    parts = re.split(r'\(([A-Z0-9/ -]{1,20})\):\s*', flavor or '')
    if len(parts) < 3:
        return [('', (flavor or '').strip())] if flavor else []
    return [(label, text.strip()) for label, text in zip(parts[1::2], parts[2::2])]


def flavor_block(set_line: str, text: str, illust: str) -> str:
    block = f"@42\n{set_line}\n@40\n{text}"
    if illust:
        block += f"\n@41\n{illust}"
    return sanitize(block)


# Characters missing from / risky for the game font -> safe equivalents
SAFE_CHARS = str.maketrans({'‎': None, '‏': None, '\xa0': ' ', '’': "'", '‘': "'",
                            '“': '"', '”': '"', '…': '...', '𝄞': '♪', 'ō': 'o', 'Ō': 'O'})


def sanitize(text: str) -> str:
    return text.translate(SAFE_CHARS)


def main():
    db = json.load(SRC.open(encoding='utf-8'))
    out, leftovers = [], Counter()
    for clan, cards in db.items():
        for c in cards:
            effect = c.get('card_effect') or ''
            abilities = split_abilities(quote_given_abilities(effect))
            converted = [convert_ability(a) for a in abilities]
            for a in converted:
                for tok in re.findall(r'\[(?:AUTO|CONT|ACT|Power|Critical|Shield|Stand|Rest)\]|\((?:VC|RC|GC)\)', a):
                    leftovers[tok] += 1

            sets = parse_sets(c.get('card_sets', ''))
            main_code = (c.get('set_id') or '').split('/')[0] or (sets[0][0] if sets else '')
            set_names = dict(sets)
            illust = c.get('Illust') or c.get('Design /Illust') or ''
            variants = []
            for label, text in flavor_variants(c.get('card_flavor')):
                # "(G-BT04/V-SS09)" -> G-BT04 ; "(PR/0185)" -> PR ; "(EB01 RRR)" -> EB01
                word = next((w for w in label.split() if re.match(r'[A-Z].*\d', w)), '')
                code = word.split('/')[0] if word else main_code
                set_line = f"{code} {set_names.get(code, '')}".strip()
                variants.append({'print': label, 'flavor': text,
                                 'flavor_modified': flavor_block(set_line, text, illust)})

            out.append({
                'name': c.get('name', ''),
                # one entry per ability; given abilities (『…』) keep
                # their original quotes in 'effet'
                'effet': [a.replace('『', '"').replace('』', '"') for a in abilities],
                'effet_modified': converted,
                'flavor': c.get('card_flavor') or '',
                'flavor_modified': variants[0]['flavor_modified'] if variants else '',
                'clan': clan,
                'kanji': c.get('Kanji', ''),
                'kana': c.get('Kana', ''),
                'set_id': c.get('set_id', ''),
                'flavor_variants': variants if len(variants) > 1 else [],
            })

    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f"✔ {DST}: {len(out)} cards")
    print(f"  with effect: {sum(1 for x in out if x['effet'])}, with flavor: {sum(1 for x in out if x['flavor'])}")
    if leftovers:
        print("  tags left as text (zones/context without a known code):", dict(leftovers.most_common(10)))


if __name__ == "__main__":
    main()
