#!/usr/bin/env python3
import gzip
from pathlib import Path
import struct
import sys


def decompress_rtz(path: Path):
  data = path.read_bytes()

  if len(data) < 4:
    print(f"❌ Fichier trop court pour contenir un header : {path}")
    return

  # 1) Lire la taille du bloc décompressé
  (size,) = struct.unpack("<I", data[:4])

  # 2) Extraire le flux GZIP
  gzip_blob = data[4:]

  # 3) Décompression GZIP
  try:
    raw = gzip.decompress(gzip_blob)
  except Exception as e:
    print(f"❌ Erreur GZIP sur {path} : {e}")
    return

  if len(raw) != size:
    print(
        f"⚠ Attention : taille décompressée ({len(raw)}) ≠ header ({size}) pour"
        f" {path.name}"
    )

  # 4) Écrire le .bin au même emplacement que le .rtz
  out = path.with_suffix(".bin")
  out.write_bytes(raw)
  print(f"✔ Décompressé → {out}")


def main():
  if len(sys.argv) != 2:
    print("Usage: python rtz_tool.py <dossier_ou_fichier.rtz>")
    sys.exit(1)

  target = Path(sys.argv[1])
  if not target.exists():
    print(f"❌ Introuvable : {target}")
    sys.exit(1)

  if target.is_dir():
    # Recherche récursive de tous les .rtz dans l'arborescence
    # (prend en compte la casse .rtz et .RTZ)
    rtz_files = [f for f in target.rglob("*") if ( f.suffix.lower() == ".rtz" || f.suffix.lower() == ".rts" ) ]

    if not rtz_files:
      print(f"⚠ Aucun fichier .rtz trouvé dans {target} ou ses sous-dossiers")
      return

    print(f"🔍 {len(rtz_files)} fichier(s) .rtz trouvé(s). Début du traitement...")
    for f in rtz_files:
      decompress_rtz(f)
  else:
    if target.suffix.lower() != ".rtz":
      print(f"⚠ Le fichier {target.name} n'a pas l'extension .rtz")
      sys.exit(1)
    decompress_rtz(target)


if __name__ == "__main__":
  main()