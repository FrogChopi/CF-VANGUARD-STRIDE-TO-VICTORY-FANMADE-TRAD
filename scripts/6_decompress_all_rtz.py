#!/usr/bin/env python3
import gzip
from pathlib import Path
import struct
import sys


def decompress_rtz(path: Path):
  data = path.read_bytes()

  if len(data) < 4:
    print(f"❌ File too short to hold a header: {path}")
    return

  # 1) Read the decompressed size
  (size,) = struct.unpack("<I", data[:4])

  # 2) Extract the GZIP stream
  gzip_blob = data[4:]

  # 3) GZIP decompression
  try:
    raw = gzip.decompress(gzip_blob)
  except Exception as e:
    print(f"❌ GZIP error on {path}: {e}")
    return

  if len(raw) != size:
    print(
        f"⚠ Warning: decompressed size ({len(raw)}) ≠ header ({size}) for"
        f" {path.name}"
    )

  # 4) Write the .bin next to the .rtz
  out = path.with_suffix(".bin")
  out.write_bytes(raw)
  print(f"✔ Decompressed → {out}")


def main():
  if len(sys.argv) != 2:
    print("Usage: python 6_decompress_all_rtz.py <folder_or_file.rtz>")
    sys.exit(1)

  target = Path(sys.argv[1])
  if not target.exists():
    print(f"❌ Not found: {target}")
    sys.exit(1)

  if target.is_dir():
    # Recursively find every .rtz (.rtz and .RTZ)
    rtz_files = [f for f in target.rglob("*") if f.suffix.lower() == ".rtz"]

    if not rtz_files:
      print(f"⚠ No .rtz file found in {target} or its subfolders")
      return

    print(f"🔍 {len(rtz_files)} .rtz file(s) found. Processing...")
    for f in rtz_files:
      decompress_rtz(f)
  else:
    if target.suffix.lower() != ".rtz":
      print(f"⚠ {target.name} does not have the .rtz extension")
      sys.exit(1)
    decompress_rtz(target)


if __name__ == "__main__":
  main()