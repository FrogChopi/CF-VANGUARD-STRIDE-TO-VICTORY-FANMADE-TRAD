#!/usr/bin/env python3
import argparse
import gzip
from pathlib import Path
import struct
import sys

TARGET_EXT = ".ctpk"
DECOMP_SUFFIX = "_decompressed"


def decompress_ctpk(path: Path):
  # Skip files that are already decompressed
  if DECOMP_SUFFIX in path.stem:
    return

  try:
    with path.open("rb") as f:
      size_data = f.read(4)
      if len(size_data) < 4:
        print(f"[WARN] File too short (< 4 bytes): {path.name}")
        return
      expected_size = struct.unpack("<I", size_data)[0]
      gz_data = f.read()

    decompressed_data = gzip.decompress(gz_data)

    if len(decompressed_data) != expected_size:
      print(
          f"[WARN] Size mismatch for {path.name}: expected {expected_size},"
          f" got {len(decompressed_data)}"
      )

    # Output: file_decompressed.ctpk in the same folder
    out_path = path.with_stem(f"{path.stem}{DECOMP_SUFFIX}")
    out_path.write_bytes(decompressed_data)
    print(f"[OK] Decompressed: {path.name} → {out_path.name}")

  except (OSError, gzip.BadGzipFile, EOFError, struct.error) as e:
    print(f"[ERROR] Failed on {path.name}: {e}")


def recompress_ctpk(path: Path):
  # Only handle _decompressed.ctpk files
  if DECOMP_SUFFIX not in path.stem:
    return

  # Find the original file next to it, to overwrite
  original_name = path.stem.replace(DECOMP_SUFFIX, "") + path.suffix
  original_path = path.with_name(original_name)

  try:
    data = path.read_bytes()
    gz_data = gzip.compress(data, compresslevel=9)
    size_prefix = struct.pack("<I", len(data))

    with original_path.open("wb") as out:
      out.write(size_prefix)
      out.write(gz_data)

    print(f"[OK] Recompressed: {path.name} → {original_path.name}")

  except Exception as e:
    print(f"[ERROR] Recompression failed on {path.name}: {e}")


def process_directory(base_dir: Path, recompress: bool = False):
  # Recursively find .ctpk files only
  ctpk_files = [
      p
      for p in base_dir.rglob("*")
      if p.is_file() and p.suffix.lower() == TARGET_EXT
  ]

  if not ctpk_files:
    print(f"⚠ No {TARGET_EXT} file found in {base_dir}")
    return

  action = "Recompression" if recompress else "Decompression"
  print(f"🔍 {len(ctpk_files)} .ctpk file(s) found. {action}...\n")

  for file_path in ctpk_files:
    if recompress:
      recompress_ctpk(file_path)
    else:
      decompress_ctpk(file_path)


def main():
  parser = argparse.ArgumentParser(
      description=(
          "Recursive GZIP decompression / recompression of .ctpk files"
      )
  )
  parser.add_argument("path", type=Path, help="Folder containing the .ctpk files")
  parser.add_argument(
      "--recompress",
      action="store_true",
      help=(
          "Recompress *_decompressed.ctpk files back into their original .ctpk"
      ),
  )
  args = parser.parse_args()

  if not args.path.is_dir():
    print(f"[ERROR] Folder not found: {args.path}")
    sys.exit(1)

  process_directory(args.path, recompress=args.recompress)


if __name__ == "__main__":
  main()