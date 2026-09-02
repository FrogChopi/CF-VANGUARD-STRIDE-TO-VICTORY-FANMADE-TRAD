import re
import pandas as pd
import requests
from tqdm import tqdm

# Configuration
INPUT_CSV = 'extracted_strings.csv'
OUTPUT_CSV = 'extracted_strings_translated.csv'
LIBRETRANSLATE_URL = 'http://localhost:5001/translate'
MAX_LINES = 13988

# Regex prétraitements
KANJI_KANA_RE = re.compile(r'<\|([^|]+)\|[^|]+\|>')
# Balises à isoler : {$hex...}, {$}, @xx
TAG_RE = re.compile(r'(\{\$[0-9A-Fa-f]*\}|\@[0-9A-Fa-f]{2}|[^\w\u3040-\u309F\u30A0-\u30FF]+)')
# Détection kana
KANA_RE = re.compile(r'[\u3040-\u309F\u30A0-\u30FF]')

def preprocess(text: str) -> str:
    """Remplace <|kanji|kana|> par le kanji."""
    return KANJI_KANA_RE.sub(lambda m: m.group(1), text)

def split_tokens(text: str):
    """Découpe en tokens en conservant les séparateurs."""
    parts = TAG_RE.split(text)
    return [p for p in parts if p is not None and p != '']

def translate_token(token: str) -> str:
    """Appelle LibreTranslate si le token contient des kana."""
    if not KANA_RE.search(token):
        return token
    payload = {
        'q': token,
        'source': 'ja',
        'target': 'en',
        'format': 'text'
    }
    try:
        resp = requests.post(LIBRETRANSLATE_URL, json=payload, timeout=5)
        resp.raise_for_status()
        return resp.json().get('translatedText', token)
    except Exception as e:
        print(f"Erreur traduction '{token}': {e}")
        return token  # fallback

def pad_to_length(orig: str, translated: str) -> str:
    """Pad translated avec des espaces pour atteindre la longueur de orig."""
    diff = len(orig) - len(translated)
    return translated + (' ' * diff if diff > 0 else '')

def translate_extract(orig: str) -> str:
    """Effectue l’ensemble du flux pour une seule chaîne."""
    pre = preprocess(orig)
    tokens = split_tokens(pre)
    trans_tokens = [translate_token(tok) for tok in tokens]
    joined = ''.join(trans_tokens)
    return pad_to_length(orig, joined)

def main():
    df = pd.read_csv(INPUT_CSV, sep=';', dtype=str)
    df_subset = df.iloc[:MAX_LINES].copy()

    # Initialisation de tqdm
    tqdm.pandas(desc="Traduction en cours")

    # Application avec barre de progression
    df_subset['translated'] = df_subset['extract'].progress_apply(translate_extract)

    df.loc[df_subset.index, 'extract'] = df_subset['translated']
    df.to_csv(OUTPUT_CSV, sep=';', index=False)
    print(f"Terminé. Résultat dans {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
