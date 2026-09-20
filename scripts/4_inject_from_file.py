# -*- coding: utf-8 -*-
import csv
import sys
from pathlib import Path

# --- Configurations à ajuster si besoin ---
BASE_ADDR     = 0x0100000  # Adresse virtuelle de base de code.bin
INPUT_BIN     = Path("full_padded.bin")
POINTER_CSV   = Path("extracted_strings_updated_trad.csv")
OUTPUT_BIN    = Path("full_patched.bin")

# Chaînes à taille fixe (pas de pointeur à repatcher, on écrase sur place),
# ex. les chaînes de dialogue/furigana trouvées avant PATCH_START : leur
# emplacement est référencé par valeur immédiate/pool littéral, pas par une
# entrée de rodata_pointers.csv, donc pas de relocalisation possible ici.
INPLACE_CSV   = Path("furigana_inplace.csv")

# --- On augmente la limite de taille de champ CSV ---
try:
    csv.field_size_limit(sys.maxsize)
except OverflowError:
    csv.field_size_limit(2**31 - 1)

MAX_CHAINES = 13988  # 100%

# Offsets de pointeur à NE PAS repatcher (laissés sur le texte JP d'origine),
# identifiés par bisection : le record "Gunnergear Dracokid" a 2 pointeurs
# partageant la même chaîne (0xD46B2C et 0xD46B30) ; un seul suffit pour
# l'affichage, l'autre semble servir de clé interne (recherche/tri) au jeu.
# SKIP_POINTER_OFFSETS = {0xD46B2C}

def parse_separators(sep_field: str) -> bytes:
    if sep_field.strip() == "(aucun)":
        return b""
    parts = sep_field.split()
    return bytes(int(p, 16) for p in parts)

def inject_inplace(data: bytearray):
    """Réinjecte les chaînes à taille fixe de INPLACE_CSV, en écrasant sur
    place l'empan exact du texte JP d'origine (rien avant/après n'est
    touché). Texte traduit complété avec des 0x0000 si plus court, tronqué
    + averti si plus long. Aucun repatch de pointeur : ces chaînes ne sont
    pas relocalisables (référencées par pool littéral, pas par un pointeur
    listé dans rodata_pointers.csv)."""
    if not INPLACE_CSV.exists():
        return

    with INPLACE_CSV.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=';')
        rows = list(reader)

    applied = 0
    truncated = 0
    for row in rows:
        off = int(row['offset'], 16)
        total_u16 = int(row['size_u16'])
        total_bytes = total_u16 * 2
        en = row['en'].strip()
        txt = en if en else row['jp']  # pas encore traduit -> on réécrit le JP tel quel

        body_bytes = txt.encode('utf-16le')

        if len(body_bytes) > total_bytes:
            # tronque au nombre entier de caractères UTF-16 qui rentrent
            max_chars = total_bytes // 2
            body_bytes = txt[:max_chars].encode('utf-16le')
            print(f"⚠ Traduction trop longue @ {row['offset']} ({len(txt.encode('utf-16le'))} > {total_bytes} octets dispo) → tronquée : {txt!r}")
            truncated += 1

        block = body_bytes + b'\x00' * (total_bytes - len(body_bytes))  # padding

        if off + total_bytes > len(data):
            print(f"⚠ Offset hors limites, ignoré : {row['offset']}")
            continue

        data[off:off + total_bytes] = block
        applied += 1

    print(f"✔ Réinjection en place (taille fixe) : {applied} chaînes patchées, {truncated} tronquées ({INPLACE_CSV}).")

def main():
    data = bytearray(INPUT_BIN.read_bytes())
    orig_len = len(data)
    print(f"⚙ code.bin chargé : {orig_len} octets")

    inject_inplace(data)

    with POINTER_CSV.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=';')
        rows = list(reader)

    cursor = orig_len
    for idx, row in enumerate(rows):
        if idx >= MAX_CHAINES:
            print(f"⚠ Arrêté après {MAX_CHAINES} chaînes.")
            break

        # if idx in EXCLUDE_IDX:
        #     print(f"⏭ Chaîne #{idx} exclue (imposteur) : {row['extract'][:40]!r}")
        #     continue

        txt = row['extract'].replace('†', '\n')
        utf16_bytes = txt.encode('utf-16le')
        sep_bytes = parse_separators(row['separators'])
        length_prefix = (len(utf16_bytes) // 2).to_bytes(4, 'little')
        block = length_prefix + utf16_bytes + sep_bytes

        new_file_off = cursor + 4  # le pointeur vise les données, juste après l'en-tête de longueur
        new_addr = BASE_ADDR + new_file_off

        for off_s in row['pointer_offsets'].split(','):
            addr_virt = int(off_s, 16)
            off = addr_virt - BASE_ADDR
            if off < 0 or off + 4 > len(data):
                print(f"⚠ Adresse virtuelle invalide/pas dans le fichier : {hex(addr_virt)}")
                continue
            data[off:off + 4] = new_addr.to_bytes(4, 'little')
            print(f"✓ Patch pointer @ virt {hex(addr_virt)} → file offset {hex(off)} = {hex(new_addr)}")

        data.extend(block)
        cursor += len(block)
        print(f"→ Ajout de la chaîne #{idx} ({len(block)} octets) à offset fichier {hex(new_file_off)}")

    OUTPUT_BIN.write_bytes(data)
    print(f"✔ '{OUTPUT_BIN}' généré ({len(data)} octets au total).")

if __name__ == "__main__":
    main()
