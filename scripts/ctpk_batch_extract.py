#!/usr/bin/env python3
import argparse
import gzip
from pathlib import Path
import struct
import sys

TARGET_EXT = ".ctpk"
DECOMP_SUFFIX = "_decompressed"


def decompress_ctpk(path: Path):
  # Ignore les fichiers déjà décompressés
  if DECOMP_SUFFIX in path.stem:
    return

  try:
    with path.open("rb") as f:
      size_data = f.read(4)
      if len(size_data) < 4:
        print(f"[WARN] Fichier trop court (< 4 octets) : {path.name}")
        return
      expected_size = struct.unpack("<I", size_data)[0]
      gz_data = f.read()

    decompressed_data = gzip.decompress(gz_data)

    if len(decompressed_data) != expected_size:
      print(
          f"[WARN] Taille différente pour {path.name} : attendu {expected_size},"
          f" obtenu {len(decompressed_data)}"
      )

    # Sortie : fichier_decompressed.ctpk dans le même répertoire
    out_path = path.with_stem(f"{path.stem}{DECOMP_SUFFIX}")
    out_path.write_bytes(decompressed_data)
    print(f"[OK] Décompressé : {path.name} → {out_path.name}")

  except (OSError, gzip.BadGzipFile, EOFError, struct.error) as e:
    print(f"[ERREUR] Échec sur {path.name} : {e}")


def recompress_ctpk(path: Path):
  # Cible uniquement les fichiers _decompressed.ctpk
  if DECOMP_SUFFIX not in path.stem:
    return

  # Retrouve le fichier d'origine à écraser à côté
  original_name = path.stem.replace(DECOMP_SUFFIX, "") + path.suffix
  original_path = path.with_name(original_name)

  try:
    data = path.read_bytes()
    gz_data = gzip.compress(data, compresslevel=9)
    size_prefix = struct.pack("<I", len(data))

    with original_path.open("wb") as out:
      out.write(size_prefix)
      out.write(gz_data)

    print(f"[OK] Recomprimé : {path.name} → {original_path.name}")

  except Exception as e:
    print(f"[ERREUR] Échec de recompression sur {path.name} : {e}")


def process_directory(base_dir: Path, recompress: bool = False):
  # Recherche récursive uniquement des .ctpk
  ctpk_files = [
      p
      for p in base_dir.rglob("*")
      if p.is_file() and p.suffix.lower() == TARGET_EXT
  ]

  if not ctpk_files:
    print(f"⚠ Aucun fichier {TARGET_EXT} trouvé dans {base_dir}")
    return

  action = "Recompression" if recompress else "Décompression"
  print(f"🔍 {len(ctpk_files)} fichier(s) .ctpk détecté(s). Début : {action}...\n")

  for file_path in ctpk_files:
    if recompress:
      recompress_ctpk(file_path)
    else:
      decompress_ctpk(file_path)


def main():
  parser = argparse.ArgumentParser(
      description=(
          "Décompression / Recompression récursive GZIP uniquement pour .ctpk"
      )
  )
  parser.add_argument("path", type=Path, help="Dossier contenant les .ctpk")
  parser.add_argument(
      "--recompress",
      action="store_true",
      help=(
          "Recompresse les fichiers *_decompressed.ctpk vers leur .ctpk d'origine"
      ),
  )
  args = parser.parse_args()

  if not args.path.is_dir():
    print(f"[ERREUR] Dossier introuvable : {args.path}")
    sys.exit(1)

  process_directory(args.path, recompress=args.recompress)


if __name__ == "__main__":
  main()