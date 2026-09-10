import argparse
import csv
import json
import re
import unicodedata

# 1. Table d'harmonisation : Petits kana -> Grands kana
KANA_SIZE_MAP = str.maketrans(
    "ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ",
    "あいうえおつやゆよわアイウエオツヤユヨワカケ",
)

# 2. Table de conversion : Katakana (U+30A1..U+30F6) -> Hiragana (U+3041..U+3096)
KATAKANA_TO_HIRAGANA = {i: i - 0x60 for i in range(0x30A1, 0x30F7)}
KATAKANA_TO_HIRAGANA[0x30F4] = 0x3094  # ヴ -> ゔ


def clean_base_text(text: str) -> str:
    """Nettoie guillemets, tirets, Unicode et supprime TOUS les espaces."""
    if not text:
        return ""

    # Normalisation Unicode (NFKC gère la demi-chasse et les espaces pleine chasse)
    text = unicodedata.normalize("NFKC", text)

    # Supprime guillemets et tous les espaces (y compris internes)
    text = re.sub(r'[“”"«»\s]', "", text)

    # Harmonise les petits kana vers les grands kana
    text = text.translate(KANA_SIZE_MAP)

    # Convertit tous les Katakana en Hiragana
    text = text.translate(KATAKANA_TO_HIRAGANA)

    # Harmonise les tirets et barres de prolongation
    text = re.sub(r"[―—–‐-]", "ー", text)

    return text


def extract_variants(raw_text: str) -> tuple[str, str]:
    """Retourne deux variantes normalisées : (avec Kanji gauche, avec Furigana droite)."""
    # 1. Variante principale : garde la partie gauche A de <|A|B|>
    kanji_text = re.sub(r"<\|([^|]+)\|[^>]*\|>", r"\1", raw_text)

    # 2. Variante phonétique : garde la partie droite B de <|A|B|>
    furigana_text = re.sub(r"<\|[^|]+\|([^>]*)\|>", r"\1", raw_text)

    return clean_base_text(kanji_text), clean_base_text(furigana_text)


def load_mapping(json_path: str) -> dict:
    """Charge le dictionnaire JSON et normalise toutes ses clés."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_mapping = {}

    if all(isinstance(v, str) for v in data.values()):
        raw_mapping = data
    else:
        for clan_cards in data.values():
            if isinstance(clan_cards, list):
                for card in clan_cards:
                    name = card.get("name") or card.get("Name")
                    if not name:
                        continue
                    if card.get("Kana"):
                        raw_mapping[card["Kana"]] = name
                    if card.get("Kanji"):
                        raw_mapping[card["Kanji"]] = name

    # Normalisation des clés sans aucun espace
    normalized_mapping = {}
    for k, v in raw_mapping.items():
        normalized_mapping[clean_base_text(k)] = v

    return normalized_mapping


def update_csv(
    json_path: str,
    input_csv_path: str,
    output_csv_path: str,
    text_column: str = "extract",
):
    mapping = load_mapping(json_path)
    count = 0

    with open(input_csv_path, "r", encoding="utf-8") as f_in:
        reader = csv.DictReader(f_in, delimiter=";")
        fieldnames = reader.fieldnames

        rows = []
        for row in reader:
            raw_cell = row.get(text_column, "")
            norm_kanji, norm_furi = extract_variants(raw_cell)

            # Test d'abord sur la graphie avec Kanji, sinon sur la phonétique Furigana
            if norm_kanji in mapping:
                row[text_column] = mapping[norm_kanji]
                count += 1
            elif norm_furi in mapping:
                row[text_column] = mapping[norm_furi]
                count += 1

            rows.append(row)

    # Réécriture brute du CSV
    with open(output_csv_path, "w", encoding="utf-8", newline="") as f_out:
        if fieldnames:
            f_out.write(";".join(fieldnames) + "\n")
        for row in rows:
            line = ";".join(str(row.get(col, "")) for col in fieldnames)
            f_out.write(line + "\n")

    print(f"Traitement terminé : {count} ligne(s) remplacée(s).")
    print(f"Fichier sauvegardé dans : {output_csv_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Remplace la colonne texte d'un CSV par un mapping JSON (furigana, espaces et kana résolus)."
    )
    parser.add_argument(
        "json_file", help="Chemin vers le fichier JSON de mapping"
    )
    parser.add_argument("input_csv", help="Chemin vers le CSV source")
    parser.add_argument("output_csv", help="Chemin vers le CSV de sortie")
    parser.add_argument(
        "--column",
        default="extract",
        help="Nom de la colonne cible (défaut: extract)",
    )

    args = parser.parse_args()
    update_csv(args.json_file, args.input_csv, args.output_csv, args.column)