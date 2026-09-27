#!/usr/bin/env python3
import gzip
from pathlib import Path
import struct
import sys


def compress_to_rtz(path: Path):
  try:
    raw_data = path.read_bytes()
  except Exception as e:
    print(f"❌ Read error on {path}: {e}")
    return

  # 1) Original size (4 bytes, little-endian)
  size_header = struct.pack("<I", len(raw_data))

  # 2) GZIP compress (level 9 for best ratio)
  try:
    gzip_blob = gzip.compress(raw_data, compresslevel=9)
  except Exception as e:
    print(f"❌ GZIP error on {path.name}: {e}")
    return

  # 3) Build the payload: [decompressed size] + [gzip stream]
  rtz_data = size_header + gzip_blob

  # 4) Write the .rtz next to the .bin
  out = path.with_suffix(".rtz")
  out.write_bytes(rtz_data)
  print(f"✔ Compressed → {out.name}")


def main():
  if len(sys.argv) != 2:
    print("Usage: python 9_recompress_all_rtz.py <folder_or_file.bin>")
    sys.exit(1)

  target = Path(sys.argv[1])
  if not target.exists():
    print(f"❌ Not found: {target}")
    sys.exit(1)

  if target.is_dir():
    # Recursively find every .bin
    bin_files = [f for f in target.rglob("*") if f.suffix.lower() == ".bin"]

    if not bin_files:
      print(f"⚠ No .bin file found in {target} or its subfolders")
      return

    print(
        f"🔍 {len(bin_files)} .bin file(s) found. Compressing..."
    )
    for f in bin_files:
      compress_to_rtz(f)
  else:
    if target.suffix.lower() != ".bin":
      print(f"⚠ {target.name} does not have the .bin extension")
      sys.exit(1)
    compress_to_rtz(target)


if __name__ == "__main__":
  main()