import argparse
import csv
import json
import re


def normalize_text(text: str) -> str:
    """Nettoie les cartouches <|Gauche|Droite|>, les guillemets et normalise les espaces."""
    if not text:
        return ""

    # 1. Résout <|A|B|> en gardant uniquement la valeur de gauche A
    text = re.sub(r'<\|([^|]+)\|[^>]*\|>', r'\1', text)

    # 2. Nettoie les guillemets typographiques
    text = re.sub(r'[“”"«»]', '', text)

    # 3. Remplace l'espace japonaise pleine chasse (U+3000) et insécable
    text = text.replace('\u3000', ' ').replace('\xa0', ' ')

    # 4. Réduit les espaces consécutifs et nettoie les bords
    return " ".join(text.split())


def load_mapping(json_path):
    """Charge le dictionnaire JSON et normalise toutes ses clés."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_mapping = {}

    # Dictionnaire simple direct {jp: en}
    if all(isinstance(v, str) for v in data.values()):
        raw_mapping = data
    else:
        # Structure de cartes par clans/listes
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

    # Normalisation des clés pour garantir les correspondances
    normalized_mapping = {}
    for k, v in raw_mapping.items():
        normalized_mapping[normalize_text(k)] = v

    return normalized_mapping


def update_csv(
    json_path, input_csv_path, output_csv_path, text_column="extract"
):
    mapping = load_mapping(json_path)
    count = 0

    with open(input_csv_path, "r", encoding="utf-8") as f_in:
        reader = csv.DictReader(f_in, delimiter=";")
        fieldnames = reader.fieldnames

        rows = []
        for row in reader:
            raw_cell = row.get(text_column, "")
            norm_cell = normalize_text(raw_cell)

            if norm_cell in mapping:
                row[text_column] = mapping[norm_cell]
                count += 1

            rows.append(row)

    # Écriture brute sans dédoublement RFC 4180 des guillemets
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
        description="Remplace la colonne texte d'un CSV par un mapping JSON (furigana & espaces résolus)."
    )
    parser.add_argument("json_file", help="Chemin vers le fichier JSON de mapping")
    parser.add_argument("input_csv", help="Chemin vers le CSV source")
    parser.add_argument("output_csv", help="Chemin vers le CSV de sortie")
    parser.add_argument(
        "--column",
        default="extract",
        help="Nom de la colonne cible (défaut: extract)",
    )

    args = parser.parse_args()
    update_csv(args.json_file, args.input_csv, args.output_csv, args.column)