# -*- coding: utf-8 -*-
import csv
import sys
from pathlib import Path

# --- Configurations à ajuster si besoin ---
BASE_ADDR     = 0x0100000  # Adresse virtuelle de base de code.bin
INPUT_BIN     = Path("full_padded.bin")
POINTER_CSV   = Path("extracted_strings_updated.csv")
OUTPUT_BIN    = Path("full_patched.bin")

# --- On augmente la limite de taille de champ CSV ---
try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(2**31 - 1)

MAX_CHAINES = 13988  # Ajuster si besoin

def parse_separators(sep_field: str) -> bytes:
    if sep_field.strip() == "(aucun)":
        return b""
    parts = sep_field.split()
    return bytes(int(p, 16) for p in parts)

def main():
    data = bytearray(INPUT_BIN.read_bytes())
    orig_len = len(data)
    print(f"⚙ code.bin chargé : {orig_len} octets")

    with POINTER_CSV.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=';')
        rows = list(reader)

    cursor = orig_len
    for idx, row in enumerate(rows):
        if idx >= MAX_CHAINES:
            print(f"⚠ Arrêté après {MAX_CHAINES} chaînes.")
            break

        txt = row['extract'].replace('†', '\n')
        utf16_bytes = txt.encode('utf-16le')
        sep_bytes = parse_separators(row['separators'])
        block = utf16_bytes + sep_bytes

        new_file_off = cursor
        new_addr = BASE_ADDR + new_file_off

        for off_s in row['pointer_offsets'].split(','):
            addr_virt = int(off_s, 16)
            off = addr_virt - BASE_ADDR
            if off < 0 or off + 4 > len(data):
                print(f"⚠ Adresse virtuelle invalide/pas dans le fichier : {hex(addr_virt)}")
                continue
            data[off:off + 4] = new_addr.to_bytes(4, 'little')
            print(f"✓ Patch pointer @ virt {hex(addr_virt)} → file offset {hex(off)} = {hex(new_addr)}")

        data.extend(block)
        cursor += len(block)
        print(f"→ Ajout de la chaîne #{idx} ({len(block)} octets) à offset fichier {hex(new_file_off)}")

    OUTPUT_BIN.write_bytes(data)
    print(f"✔ '{OUTPUT_BIN}' généré ({len(data)} octets au total).")

if __name__ == "__main__":
    main()
