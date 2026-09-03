#!/usr/bin/env python3
import gzip
from pathlib import Path
import struct
import sys


def compress_to_rtz(path: Path):
  try:
    raw_data = path.read_bytes()
  except Exception as e:
    print(f"❌ Erreur de lecture sur {path} : {e}")
    return

  # 1) Calculer la taille d'origine (sur 4 octets, Little-Endian)
  size_header = struct.pack("<I", len(raw_data))

  # 2) Compresser les données en GZIP (niveau 9 pour un taux optimal)
  try:
    gzip_blob = gzip.compress(raw_data, compresslevel=9)
  except Exception as e:
    print(f"❌ Erreur GZIP sur {path.name} : {e}")
    return

  # 3) Assembler le payload : [taille décompressée] + [flux gzip]
  rtz_data = size_header + gzip_blob

  # 4) Écrire le fichier .rtz au même emplacement
  out = path.with_suffix(".rtz")
  out.write_bytes(rtz_data)
  print(f"✔ Compressé → {out.name}")


def main():
  if len(sys.argv) != 2:
    print("Usage: python rtz_compress.py <dossier_ou_fichier.bin>")
    sys.exit(1)

  target = Path(sys.argv[1])
  if not target.exists():
    print(f"❌ Introuvable : {target}")
    sys.exit(1)

  if target.is_dir():
    # Recherche récursive de tous les fichiers .bin
    bin_files = [f for f in target.rglob("*") if f.suffix.lower() == ".bin"]

    if not bin_files:
      print(f"⚠ Aucun fichier .bin trouvé dans {target} ou ses sous-dossiers")
      return

    print(
        f"🔍 {len(bin_files)} fichier(s) .bin trouvé(s). Début de la"
        " compression..."
    )
    for f in bin_files:
      compress_to_rtz(f)
  else:
    if target.suffix.lower() != ".bin":
      print(f"⚠ Le fichier {target.name} n'a pas l'extension .bin")
      sys.exit(1)
    compress_to_rtz(target)


if __name__ == "__main__":
  main()