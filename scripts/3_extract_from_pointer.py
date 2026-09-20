# Updated extraction script without cleaning (only newline escaping)

# -*- coding: utf-8 -*-
import bisect
import csv
from pathlib import Path

# --- Constantes de config ---
BASE_ADDR   = 0x100000
PATCH_START = 0x949720
PATCH_END   = 0xB51CD0
SEP_BYTES   = {b'\x00\x00', b'\xff\xff'}

BIN_PATH       = Path("full_padded.bin")
CSV_INPUT      = Path("rodata_pointers.csv")
OUTPUT_CSV     = Path("extracted_strings.csv")


def is_separator(pair: bytes) -> bool:
    return bytes(pair) in SEP_BYTES

def strip_trailing_separators(chunk: bytes):
    sep = bytearray()
    while len(chunk) >= 2 and is_separator(chunk[-2:]):
        tail = bytes(chunk[-2:])
        sep[:0] = tail
        chunk = chunk[:-2]
    return chunk, bytes(sep)

def escape_newlines(text: str) -> str:
    return text.replace('\n', '†')

def load_and_group_pointers(csv_file: Path):
    ptr_map = {}
    with csv_file.open(newline='', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        for row in reader:
            if len(row) < 2 or row[0].lower() == 'offset':
                continue
            off_s, val_s = row[0].rstrip("Ll"), row[1].rstrip("Ll")
            try:
                off = int(off_s, 16)
                val = int(val_s, 16)
            except ValueError:
                continue
            if PATCH_START <= val < PATCH_END:
                ptr_map.setdefault(val, []).append(off)
    return {k: sorted(v) for k, v in sorted(ptr_map.items())}

def build_entry(val, start, end, data, ptr_map):
    """Build one CSV row for a string living in data[start:end], targeted by ptr_map[val]."""
    raw = data[start:end]
    main_chunk, sep_bytes = strip_trailing_separators(raw)

    try:
        text = main_chunk.decode('utf-16le', errors='ignore').rstrip('\x00')
    except Exception:
        return None

    pointers = ",".join(f"0x{off:06X}" for off in ptr_map[val])
    sep_str  = " ".join(f"{b:02X}" for b in sep_bytes) or "(aucun)"
    return {
        'pointer_offsets': pointers,
        'pointer_value'  : f"0x{val:08X}",
        'separators'     : sep_str,
        'extract'        : escape_newlines(text),
    }

def extract_strings():
    data = bytearray(BIN_PATH.read_bytes())
    ptr_map = load_and_group_pointers(CSV_INPUT)

    def is_printable_start(fo):
        try:
            ch = data[fo:fo + 2].decode('utf-16le')
            return ch.isprintable()
        except Exception:
            return False

    # 1) "Real" string starts: preceded by a separator (00 00 / FF FF), so we
    #    know unambiguously where the string begins.
    valid_vals = []
    for val in ptr_map:
        fo = val - BASE_ADDR
        if fo < 2 or not is_separator(data[fo - 2:fo]):
            continue
        if not is_printable_start(fo):
            continue
        valid_vals.append(val)
    valid_vals.sort()
    valid_starts = [v - BASE_ADDR for v in valid_vals]

    results = []
    for idx, val in enumerate(valid_vals):
        start = valid_starts[idx]
        end = valid_starts[idx + 1] if idx + 1 < len(valid_vals) else PATCH_END - BASE_ADDR
        entry = build_entry(val, start, end, data, ptr_map)
        if entry:
            results.append(entry)

    # 2) "Tail-shared" pointers: the target isn't preceded by a separator
    #    because it points into the middle of *another* (longer) string's
    #    bytes — the game reuses the tail of that string as its own,
    #    shorter string (e.g. "...のコストを選んで下さい" also serves as
    #    the standalone "コストを選んで下さい" prompt). These are real,
    #    independently-used strings; skipping them (previous behaviour)
    #    left them permanently untranslated. We recover them by locating
    #    the enclosing valid string and extracting the shared tail as its
    #    own entry, with its own pointer_offsets group so it can be
    #    redirected independently when patched.
    recovered = 0
    orphaned = 0
    for val, offs in ptr_map.items():
        if val in valid_vals:
            continue
        fo = val - BASE_ADDR
        if not is_printable_start(fo):
            continue

        # Find the valid string whose range strictly contains this offset.
        i = bisect.bisect_right(valid_starts, fo) - 1
        if i < 0:
            orphaned += 1
            continue
        enclosing_start = valid_starts[i]
        enclosing_end = valid_starts[i + 1] if i + 1 < len(valid_starts) else PATCH_END - BASE_ADDR
        if not (enclosing_start < fo < enclosing_end):
            orphaned += 1
            continue

        entry = build_entry(val, fo, enclosing_end, data, ptr_map)
        if entry:
            results.append(entry)
            recovered += 1
        else:
            orphaned += 1

    results.sort(key=lambda r: int(r['pointer_value'], 16))

    with OUTPUT_CSV.open("w", newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['pointer_offsets','pointer_value','separators','extract'])
        for r in results:
            writer.writerow([r['pointer_offsets'],
                             r['pointer_value'],
                             r['separators'],
                             r['extract']])
    print(f"✔ Extraction terminée → {OUTPUT_CSV}")
    print(f"  {len(valid_vals)} chaînes normales + {recovered} chaînes à suffixe partagé récupérées "
          f"({orphaned} pointeurs restants orphelins, non récupérables sans contexte supplémentaire)")

if __name__ == "__main__":
    extract_strings()
