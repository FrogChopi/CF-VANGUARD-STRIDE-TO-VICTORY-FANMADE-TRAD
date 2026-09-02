# Updated extraction script without cleaning (only newline escaping)

# -*- coding: utf-8 -*-
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

def extract_strings():
    data = bytearray(BIN_PATH.read_bytes())
    ptr_map = load_and_group_pointers(CSV_INPUT)

    valid_vals = []
    for val in ptr_map:
        fo = val - BASE_ADDR
        if fo < 2 or not is_separator(data[fo-2:fo]):
            continue
        try:
            ch = data[fo:fo+2].decode('utf-16le')
            if not ch.isprintable():
                continue
        except Exception:
            continue
        valid_vals.append(val)

    results = []
    for idx, val in enumerate(valid_vals):
        start = val - BASE_ADDR
        end = (valid_vals[idx + 1] - BASE_ADDR) if idx + 1 < len(valid_vals) else PATCH_END - BASE_ADDR

        raw = data[start:end]
        main_chunk, sep_bytes = strip_trailing_separators(raw)

        try:
            text = main_chunk.decode('utf-16le', errors='ignore').rstrip('\x00')
        except Exception:
            continue

        pointers = ",".join(f"0x{off:06X}" for off in ptr_map[val])
        sep_str  = " ".join(f"{b:02X}" for b in sep_bytes) or "(aucun)"
        results.append({
            'pointer_offsets': pointers,
            'pointer_value'  : f"0x{val:08X}",
            'separators'     : sep_str,
            'extract'        : escape_newlines(text),
        })

    with OUTPUT_CSV.open("w", newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['pointer_offsets','pointer_value','separators','extract'])
        for r in results:
            writer.writerow([r['pointer_offsets'],
                             r['pointer_value'],
                             r['separators'],
                             r['extract']])
    print(f"✔ Extraction terminée → {OUTPUT_CSV}")

if __name__ == "__main__":
    extract_strings()
