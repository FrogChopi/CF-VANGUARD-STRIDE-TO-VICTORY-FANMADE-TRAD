# -*- coding: utf-8 -*-
"""Traduit via Ollama (qwen2.5:14b) les chaines encore en japonais après update_csv.py.

Usage:
    python scripts/low_trad.py <input_csv> <output_csv> [--column extract] [--model qwen2.5:14b]

- Les balises furigana <|kanji|kana|> sont remplacées par la partie kanji avant traduction.
- Les tokens suivants sont protégés (jamais envoyés au LLM, restaurés tels quels après coup) :
    @xx            (@0F, @29, @0E, @03 ...)
    {$xxxxx} / {$} (codes couleur/contrôle)
    %x             (%d, %s, %.3f, %d/%d ...)
    \n
    †
    ・
    《xxxx》 / 【xxxx】
    :
    "xxxx"         (guillemets typographiques pleine largeur U+201C/U+201D)
- Un cache JSON (low_trad_cache.json par défaut) permet de reprendre le traitement
  après interruption et évite de retraduire deux fois la même chaîne.
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5:7b"

JP_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")
FURIGANA_RE = re.compile(r"<\|([^|]+)\|[^>]*\|>")

PROTECT_RE = re.compile(
    "|".join(
        [
            r"\{\$[0-9A-Fa-f]*\}",  # {$3040ff}, {$}
            r"@[0-9A-Fa-f]{2}",  # @0F, @29
            r"%(?:\d+\$)?[-+0 #]*\d*(?:\.\d+)?[a-zA-Z]",  # %d, %s, %.3f, %x
            r"《[^》]*》",
            r"【[^】]*】",
            r"“[^”]*”",  # “xxxx”
            r"\\n",
            r"†",  # †
            r"・",  # ・
            r":",
        ]
    )
)
# Même pattern que PROTECT_RE mais avec un groupe capturant, pour re.split.
SPLIT_RE = re.compile(f"({PROTECT_RE.pattern})")


def strip_furigana(text: str) -> str:
    return FURIGANA_RE.sub(r"\1", text)


def needs_translation(text: str) -> bool:
    return bool(JP_RE.search(text))


def split_segments(text: str) -> list[tuple[str, bool]]:
    """Découpe `text` en segments (chunk, is_protected) en alternance.

    Plutôt que d'envoyer les balises protégées au LLM sous forme de placeholders
    (peu fiable : le modèle peut en perdre/déplacer certaines, surtout quand il y
    en a beaucoup dans une même ligne), on les extrait complètement en amont : le
    LLM ne voit jamais que du texte à traduire, et les balises sont recollées telles
    quelles après coup, à leur position d'origine.
    """
    parts = SPLIT_RE.split(text)
    return [(p, i % 2 == 1) for i, p in enumerate(parts) if p != ""]


SYSTEM_PROMPT = (
    "You are a professional Japanese-to-English translator working on a trading card "
    "game (Cardfight!! Vanguard). Translate the user's text naturally into English, "
    "keeping the tone appropriate for game dialogue/UI.\n"
    "Strict rules:\n"
    "- Do not add explanations, notes, quotes around the answer, or restate the "
    "source text.\n"
    "- Never invent unrelated content, names, or stories. If a segment is unclear, "
    "translate it as literally as possible instead of guessing or expanding.\n"
    "- The output MUST be a single line: no line breaks under any circumstance.\n"
    "- Output ONLY the translated text."
)


CJK_COUNT_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")


def validate_response(response: str, source: str) -> str:
    """Lève ValueError si la réponse sent l'hallucination (garde-fous)."""
    if "\n" in response or "\r" in response:
        raise ValueError("réponse multi-ligne (probable hallucination)")

    stripped = response.strip()
    if not stripped:
        raise ValueError("réponse vide")

    max_len = max(200, len(source) * 6)
    if len(stripped) > max_len:
        raise ValueError(
            f"réponse anormalement longue ({len(stripped)} car. pour une source de {len(source)})"
        )

    cjk_count = len(CJK_COUNT_RE.findall(stripped))
    if cjk_count > max(3, len(stripped) * 0.3):
        raise ValueError(f"trop de caractères CJK dans la sortie ({cjk_count})")

    return stripped


def call_ollama(
    text: str,
    model: str,
    num_ctx: int = 2048,
    num_predict: int = 128,
    retries: int = 3,
    timeout: int = 120,
) -> str:
    body = json.dumps(
        {
            "model": model,
            "system": SYSTEM_PROMPT,
            "prompt": text,
            "stream": False,
            "options": {
                "temperature": 0.2,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_response = data["response"]
            return validate_response(raw_response, text)
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"  ⚠ Ollama erreur (tentative {attempt}/{retries}) : {e}")
            time.sleep(2)
    raise RuntimeError(f"Ollama injoignable/invalide : {last_err}")


def load_cache(path: Path) -> dict:
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(path: Path, cache: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=0)


def translate_segment(
    chunk: str, model: str, cache: dict, num_ctx: int = 512, num_predict: int = 128
) -> str:
    """Traduit un segment de texte pur (aucune balise protégée à l'intérieur)."""
    if chunk in cache:
        return cache[chunk]

    if not needs_translation(chunk):
        cache[chunk] = chunk
        return chunk

    dynamic_predict = max(num_predict, len(chunk) * 4 + 40)
    translated = call_ollama(
        chunk,
        model,
        num_ctx=max(num_ctx, dynamic_predict + 256),
        num_predict=dynamic_predict,
    )
    cache[chunk] = translated
    return translated


def translate_cell(
    raw_text: str, model: str, cache: dict, num_ctx: int = 512, num_predict: int = 128
) -> str:
    if raw_text in cache:
        return cache[raw_text]

    kanji_text = strip_furigana(raw_text)

    if not needs_translation(kanji_text):
        cache[raw_text] = kanji_text
        return kanji_text

    parts = []
    for chunk, is_protected in split_segments(kanji_text):
        if is_protected:
            parts.append(chunk)
        else:
            parts.append(translate_segment(chunk, model, cache, num_ctx, num_predict))

    translated = "".join(parts)
    cache[raw_text] = translated
    return translated


def check_ollama_reachable(model: str) -> None:
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        names = [m.get("name", "") for m in data.get("models", [])]
        if not any(model in n for n in names):
            print(f"⚠ Le modèle '{model}' n'apparaît pas dans `ollama list` ({names}).")
            print("  Lance `ollama pull " + model + "` si besoin.")
    except Exception as e:  # noqa: BLE001
        print(f"❌ Impossible de joindre Ollama sur localhost:11434 ({e}).")
        print("  Lance `ollama serve` avant de relancer ce script.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Traduit via Ollama les chaînes encore en japonais après update_csv.py."
    )
    parser.add_argument("input_csv")
    parser.add_argument("output_csv")
    parser.add_argument("--column", default="extract", help="Colonne à traduire (défaut: extract)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Modèle Ollama (défaut: {DEFAULT_MODEL})")
    parser.add_argument("--cache", default="low_trad_cache.json", help="Fichier de cache JSON")
    parser.add_argument("--limit", type=int, default=0, help="Ne traiter que N lignes (0 = toutes), pour tester")
    parser.add_argument("--num-ctx", type=int, default=512, help="Taille du contexte Ollama (défaut: 512)")
    parser.add_argument("--num-predict", type=int, default=128, help="Tokens max en sortie (défaut: 128)")
    parser.add_argument("--dry-run", action="store_true", help="Compte les lignes à traduire sans appeler Ollama")
    args = parser.parse_args()

    if not args.dry_run:
        check_ollama_reachable(args.model)

    cache_path = Path(args.cache)
    cache = load_cache(cache_path)

    with open(args.input_csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        fieldnames = reader.fieldnames
        rows = list(reader)

    total_translatable = sum(
        1 for row in rows if needs_translation(strip_furigana(row.get(args.column, "")))
    )
    print(f"🔍 {total_translatable} ligne(s) à traduire sur {len(rows)} au total.")

    if args.dry_run:
        return

    BATCH = 5
    output_path = Path(args.output_csv)
    resume_from = 0
    if output_path.exists() and output_path.stat().st_size > 0:
        with output_path.open("r", encoding="utf-8", newline="") as f:
            existing_rows = list(csv.reader(f, delimiter=";"))
        resume_from = max(0, len(existing_rows) - 1)  # -1 pour le header
        print(f"↻ Reprise à la ligne {resume_from}/{len(rows)} (fichier de sortie existant).")
        out_f = output_path.open("a", encoding="utf-8", newline="")
    else:
        out_f = output_path.open("w", encoding="utf-8", newline="")
        csv.writer(out_f, delimiter=";").writerow(fieldnames)
        out_f.flush()
    writer = csv.writer(out_f, delimiter=";")

    translated_count = 0
    failed = 0
    since_flush = 0
    limit_left = args.limit if args.limit else None

    durations: list[float] = []  # temps des vrais appels LLM (hors cache), pour l'ETA
    remaining_to_translate = total_translatable

    def eta_str() -> str:
        if not durations:
            return "ETA inconnue"
        avg = sum(durations[-20:]) / len(durations[-20:])
        remaining = max(0, remaining_to_translate)
        eta_s = avg * remaining
        m, s = divmod(int(eta_s), 60)
        h, m = divmod(m, 60)
        return f"~{avg:.1f}s/trad, ETA {h}h{m:02d}m{s:02d}s ({remaining} restantes)"

    try:
        for i in range(resume_from, len(rows)):
            row = rows[i]
            raw = row.get(args.column, "")
            if needs_translation(strip_furigana(raw)):
                if limit_left is not None and limit_left <= 0:
                    print(f"   (limite de {args.limit} traduction(s) atteinte, arrêt à la ligne {i})")
                    break
                was_cached = raw in cache
                t0 = time.time()
                try:
                    row[args.column] = translate_cell(
                        raw, args.model, cache, num_ctx=args.num_ctx, num_predict=args.num_predict
                    )
                    dt = time.time() - t0
                    translated_count += 1
                    remaining_to_translate -= 1
                    if limit_left is not None:
                        limit_left -= 1
                    if was_cached:
                        print(f"  [cache] ligne {i} : instantané")
                    else:
                        durations.append(dt)
                        print(f"  [{dt:.2f}s] ligne {i} → {eta_str()}")
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    remaining_to_translate -= 1
                    print(f"❌ Échec ligne {i} ({time.time() - t0:.2f}s) : {e}")

            writer.writerow([row.get(c, "") for c in fieldnames])
            since_flush += 1

            if since_flush >= BATCH:
                out_f.flush()
                save_cache(cache_path, cache)
                print(f"… ligne {i + 1}/{len(rows)} ({translated_count} traduites, {failed} échecs)")
                since_flush = 0
    finally:
        out_f.flush()
        out_f.close()
        save_cache(cache_path, cache)

    print(f"✔ Terminé : {translated_count} chaîne(s) traduite(s), {failed} échec(s).")
    print(f"Fichier sauvegardé dans : {args.output_csv}")


if __name__ == "__main__":
    main()
