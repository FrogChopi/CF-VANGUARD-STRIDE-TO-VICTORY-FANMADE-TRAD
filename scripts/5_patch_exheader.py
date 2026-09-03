# -*- coding: utf-8 -*-
import sys, os, struct
from pathlib import Path

def round_up_0x1000(val):
    return (val + 0xFFF) & ~0xFFF

def patch_exheader(exheader_path, padded_path, patched_path):
    size_padded = os.path.getsize(padded_path)
    size_patched = os.path.getsize(patched_path)
    delta = size_patched - size_padded

    base_data_size = 0x001BBF78 + 0x001E16FC
    raw_new_data_size = base_data_size + delta
    new_data_size = round_up_0x1000(raw_new_data_size)
    pages = new_data_size // 0x1000

    ex = bytearray(Path(exheader_path).read_bytes())

    code_size = round_up_0x1000(size_patched)
    ex[0x00:0x04] = struct.pack('<I', code_size)
    ex[0x08:0x0C] = struct.pack('<I', 0)
    ex[0x0C:0x10] = struct.pack('<I', new_data_size)

    # Ajout : patch du champ "physical region size" à offset 0x34
    ex[0x34:0x38] = struct.pack('<I', pages)

    out = exheader_path.replace('.bin', '_patched.bin')
    Path(out).write_bytes(ex)

    print(f"🎃 padded = {size_padded} B, 🩹 patched = {size_patched} B, Δ delta = {delta} B")
    print(f"🧮 base_data_size = 0x{base_data_size:08X}")
    print(f"👍 → new_data_size (avant page align) = 0x{raw_new_data_size:08X}")
    print(f"📐 → new_data_size (aligné 0x1000) = 0x{new_data_size:08X}")
    print(f"✔  → ExHeader patched: code_size={code_size}, data_size={new_data_size}, phys_pages={pages}")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: patch_exheader.py exheader.bin full_padded.bin full_patched.bin")
        sys.exit(1)
    patch_exheader(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]))
