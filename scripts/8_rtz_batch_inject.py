import csv
import os
from pathlib import Path
import sys

STOP_PATTERN = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0x00])


def reinject_file(bin_path: Path, start_offset: int, records: list):
  # 1. Read the original header up to the offset
  with open(bin_path, "rb") as f_in:
    original_header = f_in.read(start_offset)

  # 2. Rebuild the text table
  rebuilt_data = bytearray()

  for line_num, (prefix_hex, text) in enumerate(records, start=1):
    try:
      prefix_bytes = bytes.fromhex(prefix_hex)
    except ValueError:
      print(f"  ❌ Bad hex bytes '{prefix_hex}' in {bin_path.name}")
      continue

    # Restore line breaks
    clean_text = text.replace("\\n", "\n")
    encoded_text = clean_text.encode("utf-16-le")

    # Length in characters (bytes / 2)
    char_count = len(encoded_text) // 2
    if char_count > 255:
      print(
          f"  ⚠ Line {line_num} in {bin_path.name} truncated (> 255"
          " characters)"
      )
      char_count = 255
      encoded_text = encoded_text[:510]

    length_byte = bytes([char_count])

    rebuilt_data.extend(prefix_bytes)
    rebuilt_data.extend(length_byte)
    rebuilt_data.extend(encoded_text)

  # Append the end marker
  rebuilt_data.extend(STOP_PATTERN)

  # 3. Rewrite the .bin in place
  with open(bin_path, "wb") as f_out:
    f_out.write(original_header)
    f_out.write(rebuilt_data)

  print(f"✔ Updated: {bin_path.name} ({len(records)} strings injected)")


def process_batch_injection(csv_path_str: str, base_dir_str: str):
  csv_path = Path(csv_path_str)
  base_dir = Path(base_dir_str)

  if not csv_path.exists():
    print(f"❌ CSV not found: {csv_path}")
    sys.exit(1)

  # Group rows by target file
  # Layout: { relative_path: { "offset": int, "records": [(bytes, text), ...] } }
  files_map = {}

  with open(csv_path, "r", encoding="utf-8-sig") as f:
    reader = csv.reader(f, delimiter=";")
    header = next(reader, None)

    for row in reader:
      if not row or len(row) < 4:
        continue

      rel_path, offset_hex, prefix_bytes, text = (
          row[0],
          row[1],
          row[2],
          row[3],
      )

      if rel_path not in files_map:
        files_map[rel_path] = {"offset": int(offset_hex, 16), "records": []}

      files_map[rel_path]["records"].append((prefix_bytes, text))

  print(f"🔍 {len(files_map)} file(s) to update.\n")

  for rel_path_str, data in files_map.items():
    target_bin = base_dir / rel_path_str

    # Fallback if the path was truncated or changed
    if not target_bin.exists():
      matches = list(base_dir.rglob(Path(rel_path_str).name))
      if matches:
        target_bin = matches[0]

    if not target_bin.exists():
      print(f"⚠ Target file not found: {target_bin}")
      continue

    reinject_file(target_bin, data["offset"], data["records"])

  print("\n🎉 Injection done.")


if __name__ == "__main__":
  if len(sys.argv) < 3:
    print("Usage: python 8_rtz_batch_inject.py <output_all.csv> <romfs_root>")
    print(
        "Example: python 8_rtz_batch_inject.py output_all.csv .\\modified\\romfs\\"
    )
    sys.exit(1)

  process_batch_injection(sys.argv[1], sys.argv[2])