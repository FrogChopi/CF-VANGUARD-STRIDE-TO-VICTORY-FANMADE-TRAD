#!/usr/bin/env python3
import sys
from pathlib import Path

def pad_data_section(bin_path, data_offset, data_size, pad_size, out_path):
    # Lit le binaire original
    data = bytearray(Path(bin_path).read_bytes())

    # Calcule les bornes
    start = data_offset
    end   = data_offset + data_size

    # if end > len(data):
    #     print(f"Erreur : data_offset+data_size ({end}) dépasse la taille du fichier ({len(data)})")
    #     return

    # Génère le padding
    padding = b'\x00' * pad_size

    # Insère le padding après .data
    new_data = data[:end] + padding + data[end:]

    # Sauvegarde
    Path(out_path).write_bytes(new_data)
    print(f"Paddé {pad_size} octets après .data (offsets {hex(end)}–{hex(end+pad_size)}).")
    print(f"Nouvelle taille du binaire : {len(new_data)} bytes.")

if __name__ == '__main__':
    if len(sys.argv) != 6:
        print("Usage: pad_data.py <full.bin> <data_offset> <data_size> <pad_size> <out.bin>")
        sys.exit(1)

    _, bin_path, off_str, size_str, pad_str, out_path = sys.argv
    data_offset = int(off_str, 0)
    data_size   = int(size_str, 0)
    pad_size    = int(pad_str, 0)

    pad_data_section(bin_path, data_offset, data_size, pad_size, out_path)
