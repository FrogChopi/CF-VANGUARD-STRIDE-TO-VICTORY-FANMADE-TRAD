#!/usr/bin/env python3
import gzip
from pathlib import Path
import struct
import sys

target_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")

for decomp in target_dir.rglob("*_decompressed.ctpk"):
  orig = decomp.with_name(decomp.name.replace("_decompressed.ctpk", ".ctpk"))
  data = decomp.read_bytes()

  # Header 4 octets (taille uint32 LE) + payload gzip niveau 9
  blob = struct.pack("<I", len(data)) + gzip.compress(data, compresslevel=9)
  orig.write_bytes(blob)
  print(f"✔ Recompressé : {decomp.name} → {orig.name}")