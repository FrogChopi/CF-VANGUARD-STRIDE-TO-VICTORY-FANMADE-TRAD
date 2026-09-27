import json
import os
from pathlib import Path
import sys

STOP_PATTERN = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0x00])


def extract_records_from_binary(file_path: Path, start_offset: int):
  records = []
  file_size = file_path.stat().st_size

  if start_offset >= file_size:
    print(
        f"    ❌ Offset {hex(start_offset)} out of bounds (size:"
        f" {hex(file_size)})"
    )
    return records

  with open(file_path, "rb") as f:
    f.seek(start_offset)

    while True:
      header = f.read(5)
      if len(header) < 5 or header == STOP_PATTERN:
        break

      prefix_bytes = header[:4]
      length_byte = header[4]
      bytes_to_read = length_byte * 2

      content_bytes = f.read(bytes_to_read)
      if len(content_bytes) < bytes_to_read:
        break

      text_extracted = content_bytes.decode("utf-16-le", errors="replace")
      text_extracted = (
          text_extracted.replace("\r\n", "\\n")
          .replace("\n", "\\n")
          .replace("\r", "\\n")
      )
      text_extracted = text_extracted.replace(";", ",")

      prefix_hex = " ".join(f"{b:02X}" for b in prefix_bytes)
      records.append((prefix_hex, text_extracted))

      peek_bytes = f.read(5)
      if peek_bytes == STOP_PATTERN:
        break
      f.seek(-len(peek_bytes), os.SEEK_CUR)

  return records


def parse_json_and_extract(
    json_path_str: str, base_dir_str: str, output_csv: str = "output_all.csv"
):
  json_path = Path(json_path_str)
  base_dir = Path(base_dir_str)

  if not json_path.exists():
    print(f"❌ JSON not found: {json_path}")
    return
  if not base_dir.exists():
    print(f"❌ Root folder not found: {base_dir}")
    return

  with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

  romfs_data = data.get("romfs", {})
  total_extracted = 0

  with open(output_csv, "w", encoding="utf-8-sig") as f_out:
    f_out.write("path;offset;bytes;extract\n")

    for folder, entries in romfs_data.items():
      print(
          f"\n📁 Folder: '{folder}' ({len(entries)} entry(ies))"
      )

      for entry in entries:
        raw_filename = entry.get("filename")
        offset_hex = entry.get("offset")

        if not raw_filename or not offset_hex:
          continue

        start_offset = int(offset_hex, 16)

        # Look for the .bin first (the offset applies to the decompressed file)
        base_filename = Path(raw_filename).stem
        bin_name = f"{base_filename}.bin"

        # 1. Expected direct path
        target_path = base_dir / folder / bin_name

        # 2. If missing, try the original name
        if not target_path.exists():
          target_path = base_dir / folder / raw_filename

        # 3. Still missing: recursive search in base_dir
        if not target_path.exists():
          matches = list(base_dir.rglob(bin_name))
          if matches:
            target_path = matches[0]

        if not target_path.exists():
          print(f"  ⚠ File missing on disk: {folder}/{bin_name}")
          continue

        print(f"  📄 Scanning: {target_path.name} @ {offset_hex}")
        records = extract_records_from_binary(target_path, start_offset)
        print(f"     ↳ {len(records)} string(s) found")

        for prefix_hex, text in records:
          rel_path = target_path.relative_to(base_dir).as_posix()
          f_out.write(f"{rel_path};{offset_hex};{prefix_hex};{text}\n")
          total_extracted += 1

  print(f"\n✔ Done: {total_extracted} rows exported to '{output_csv}'.")


if __name__ == "__main__":
  if len(sys.argv) < 3:
    print("Usage: python 7_rtz_batch_extract.py <RTZ.json> <romfs_root>")
    sys.exit(1)

  parse_json_and_extract(sys.argv[1], sys.argv[2])