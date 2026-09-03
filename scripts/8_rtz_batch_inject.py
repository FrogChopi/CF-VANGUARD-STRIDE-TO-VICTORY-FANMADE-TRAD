import csv
import os
from pathlib import Path
import sys

STOP_PATTERN = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0x00])


def reinject_file(bin_path: Path, start_offset: int, records: list):
  # 1. Lecture de l'en-tête original jusqu'à l'offset
  with open(bin_path, "rb") as f_in:
    original_header = f_in.read(start_offset)

  # 2. Reconstruction de la table de textes
  rebuilt_data = bytearray()

  for line_num, (prefix_hex, text) in enumerate(records, start=1):
    try:
      prefix_bytes = bytes.fromhex(prefix_hex)
    except ValueError:
      print(f"  ❌ Erreur octets hexadécimaux '{prefix_hex}' sur {bin_path.name}")
      continue

    # Rétablissement des retours à la ligne
    clean_text = text.replace("\\n", "\n")
    encoded_text = clean_text.encode("utf-16-le")

    # Longueur en nombre de caractères (octets / 2)
    char_count = len(encoded_text) // 2
    if char_count > 255:
      print(
          f"  ⚠ Ligne {line_num} dans {bin_path.name} tronquée (> 255"
          " caractères)"
      )
      char_count = 255
      encoded_text = encoded_text[:510]

    length_byte = bytes([char_count])

    rebuilt_data.extend(prefix_bytes)
    rebuilt_data.extend(length_byte)
    rebuilt_data.extend(encoded_text)

  # Ajout du pattern de fin
  rebuilt_data.extend(STOP_PATTERN)

  # 3. Réécriture directe dans le fichier .bin
  with open(bin_path, "wb") as f_out:
    f_out.write(original_header)
    f_out.write(rebuilt_data)

  print(f"✔ Mis à jour : {bin_path.name} ({len(records)} chaînes réinjectées)")


def process_batch_injection(csv_path_str: str, base_dir_str: str):
  csv_path = Path(csv_path_str)
  base_dir = Path(base_dir_str)

  if not csv_path.exists():
    print(f"❌ CSV introuvable : {csv_path}")
    sys.exit(1)

  # Regroupement des lignes par fichier cible
  # Structure : { relative_path: { "offset": int, "records": [(bytes, text), ...] } }
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

  print(f"🔍 {len(files_map)} fichier(s) à mettre à jour détecté(s).\n")

  for rel_path_str, data in files_map.items():
    target_bin = base_dir / rel_path_str

    # Tentative de repli si le chemin a été tronqué ou modifié
    if not target_bin.exists():
      matches = list(base_dir.rglob(Path(rel_path_str).name))
      if matches:
        target_bin = matches[0]

    if not target_bin.exists():
      print(f"⚠ Fichier cible introuvable : {target_bin}")
      continue

    reinject_file(target_bin, data["offset"], data["records"])

  print("\n🎉 Réinjection terminée.")


if __name__ == "__main__":
  if len(sys.argv) < 3:
    print("Usage: python batch_inject.py <output_all.csv> <racine_romfs>")
    print(
        "Exemple : python batch_inject.py output_all.csv .\\modified\\romfs\\"
    )
    sys.exit(1)

  process_batch_injection(sys.argv[1], sys.argv[2])