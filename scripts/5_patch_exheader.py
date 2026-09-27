# -*- coding: utf-8 -*-
"""
Patch the 3DS ExHeader for a code.bin whose .data section was grown
(layout: original .data | .bss as real zeros | translated .data).

SCI (System Control Info) offsets:
  0x10 text addr / 0x14 text pages / 0x18 text size
  0x1C stack size
  0x20 ro   addr / 0x24 ro   pages / 0x28 ro   size
  0x30 data addr / 0x34 data pages / 0x38 data size
  0x3C bss size
Bytes 0x00-0x0F (name, remaster version) are NOT touched, except bit 0 of
0x0D ("compressed code" flag), which is cleared since code.bin is decompressed.
"""
import sys, struct
from pathlib import Path

PAGE = 0x1000
def pages_of(n): return (n + PAGE - 1) // PAGE

def patch_exheader(exheader_path, code_path, out_path=None):
    ex = bytearray(Path(exheader_path).read_bytes())

    # Pad code.bin (in place) with zeros up to a page boundary:
    # Azahar/Citra map .data in whole pages and would read past the file otherwise.
    code = Path(code_path).read_bytes()
    pad = -len(code) % PAGE
    if pad:
        Path(code_path).write_bytes(code + b"\0" * pad)
        print(f"ℹ code.bin padded: 0x{len(code):X} -> 0x{len(code) + pad:X}")
    code_size = len(code) + pad

    text_pages = struct.unpack_from('<I', ex, 0x14)[0]
    ro_pages   = struct.unpack_from('<I', ex, 0x24)[0]
    old_data_pages, old_data_size, old_bss = struct.unpack_from('<III', ex, 0x34)

    # We always work on the decompressed code.bin: clear the "compressed code"
    # flag (bit 0 of 0x0D), otherwise the loader tries to decompress it (BLZ).
    if ex[0x0D] & 1:
        ex[0x0D] &= ~1 & 0xFF
        print("ℹ 'compressed code' flag (0x0D bit 0) cleared")

    rw_offset = (text_pages + ro_pages) * PAGE      # start of .data in code.bin
    if code_size <= rw_offset:
        sys.exit("❌ code.bin is smaller than .text + .rodata: wrong file?")

    new_data_size  = code_size - rw_offset           # everything after .rodata in the file
    new_data_pages = pages_of(new_data_size)
    # The RW area must cover AT LEAST the original data + bss.
    #  - with translation (bss as zeros + translated data in the file) -> bss = 0
    #  - without translation (file = original .data only)              -> original bss
    #  - in between                                                    -> whatever is missing
    orig_rw_end = old_data_size + old_bss
    new_bss     = max(0, orig_rw_end - new_data_size)


    struct.pack_into('<I', ex, 0x34, new_data_pages)
    struct.pack_into('<I', ex, 0x38, new_data_size)
    struct.pack_into('<I', ex, 0x3C, new_bss)

    # Check: what the loader allocates must hold the whole code.bin
    alloc = (text_pages + ro_pages + pages_of(new_data_size + new_bss)) * PAGE
    assert alloc >= code_size, "loader allocation < code.bin size"

    out = Path(out_path) if out_path else Path(exheader_path).with_name(Path(exheader_path).stem + '_patched.bin')
    out.write_bytes(ex)

    print(f"code.bin        = 0x{code_size:08X}")
    print(f".data offset    = 0x{rw_offset:08X}")
    print(f".data pages     : {old_data_pages} -> {new_data_pages}")
    print(f".data size      : 0x{old_data_size:08X} -> 0x{new_data_size:08X}")
    print(f".bss  size      : 0x{old_bss:08X} -> 0x{new_bss:08X}")
    print(f"loader alloc    = 0x{alloc:08X} (total {alloc // PAGE} pages)")
    print(f"✔ written: {out}")

if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print("Usage: 5_patch_exheader.py exheader_ORIGINAL.bin code_patched.bin [out.bin]")
        print("  (the exheader MUST be the original one: its data/bss sizes are the reference)")
        sys.exit(1)
    patch_exheader(*sys.argv[1:])
