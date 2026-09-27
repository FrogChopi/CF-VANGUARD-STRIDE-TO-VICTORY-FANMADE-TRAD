# -*- coding: utf-8 -*-
"""Translates strings that are still in Japanese after update_csv.py using Ollama (qwen2.5:14b).

Usage:
    python scripts/low_trad.py <input_csv> <output_csv> [--column extract] [--model qwen2.5:7b]
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

JP_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")
FURIGANA_RE = re.compile(r"<\|([^|]+)\|[^>]*\|>")

NEWLINE = "†"
MAX_LINE_LENGTH = 30  # Visual line limit on the card

# Technical internal tags hidden during LLM translation
INLINE_RE = re.compile(
    "|".join(
        [
            r"\{\$[0-9A-Fa-f]*\}",
            r"%(?:\d+\$)?[-+0 #]*\d*(?:\.\d+)?[a-zA-Z]",
            r"《[^》]*》",
            r"【[^】]*】",
            r"“[^”]*”",
            r"＊[^＊]*＊",
            r"\*[^\*]*\*",
            r":",
        ]
    )
)

def strip_furigana(text: str) -> str:
    return FURIGANA_RE.sub(r"\1", text)

def count_jp_chars(text: str) -> int:
    """Number of Japanese characters in the text."""
    return len(JP_RE.findall(text))

def needs_translation(text: str) -> bool:
    """A line needs translating only if it has 3 or more JP characters
    (skips fully English lines and very short names)."""
    return count_jp_chars(text) >= 3

def visible_len(s: str) -> int:
    """Calculates the in-game display width:
    - {$...} = 0 chars (invisible)
    - @xx = 1 char
    - Regular chars & spaces = 1 char each
    """
    s_clean = re.sub(r"\{\$[0-9A-Fa-f]*\}", "", s)
    s_clean = re.sub(r"@[0-9A-Fa-f]{2}", "X", s_clean)
    return len(s_clean)

def line_needs_processing(raw: str) -> bool:
    return needs_translation(strip_furigana(raw))

# ---------------------------------------------------------------------------
# CHECKERS / SANITIZE
# ---------------------------------------------------------------------------
FURIGANA_FULL_RE = re.compile(r"<\|[^|<>]+\|[^|<>]*\|>")
STRAY_AT_RE = re.compile(r"@(?![0-9A-Fa-f]{2})")
TRAIL_RE = re.compile(r'(?:\s*[†"])+((?:\{\$[0-9A-Fa-f]*\})*)$')

def _strip_stray_pipes(text: str) -> str:
    out, last = [], 0
    for m in FURIGANA_FULL_RE.finditer(text):
        out.append(text[last:m.start()].replace("|", ""))
        out.append(m.group())
        last = m.end()
    out.append(text[last:].replace("|", ""))
    return "".join(out)

def find_issues(text: str) -> list[str]:
    issues = []
    m = TRAIL_RE.search(text)
    if m and "†" in m.group(0): issues.append("† at end of line")
    if _strip_stray_pipes(text) != text: issues.append("'|' outside furigana tag")
    if '""' in text: issues.append('"" present')
    if ';"' in text: issues.append(';" present')
    if text.endswith('"'): issues.append('" at end of cell')
    if STRAY_AT_RE.search(text): issues.append("isolated @ / incomplete @xx")
    return issues

def sanitize_translation(text: str) -> str:
    text = _strip_stray_pipes(text)
    text = STRAY_AT_RE.sub("", text)
    
    # 1. Collapse "" (or more) into a single "
    text = re.sub(r'"{2,}', '"', text)
    
    # 2. Remove " after a ;
    text = text.replace(';"', ';')
    
    # 3. Remove an orphan " at the end of the cell (odd number of quotes);
    #    a quoted name ("… "Abyss"") keeps its closing quote
    if text.count('"') % 2:
        text = re.sub(r'"$', '', text)
    
    return TRAIL_RE.sub(r"\1", text)

def apply_daggers(text: str, max_len: int = MAX_LINE_LENGTH) -> str:
    """Inserts NEWLINE (†) so that no line exceeds max_len (30) visible characters."""
    if not text:
        return text

    lines = text.split(NEWLINE)
    wrapped_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            wrapped_lines.append("")
            continue

        token_pattern = re.compile(
            r"(\{\$[0-9A-Fa-f]*\}|@[0-9A-Fa-f]{2}|\s+|[^\s\{\@]+|[@\{])"
        )
        tokens = token_pattern.findall(line)
        tokens = [t for t in tokens if t]

        current_chunk = []
        current_len = 0

        for token in tokens:
            t_len = visible_len(token)

            if token.isspace():
                if current_len >= max_len:
                    wrapped_lines.append("".join(current_chunk).rstrip())
                    current_chunk = []
                    current_len = 0
                elif current_chunk:
                    current_chunk.append(" ")
                    current_len += 1
                continue

            # Handle overly long single tokens by splitting character by character
            if t_len > max_len and not token.startswith("{$") and not re.match(r"^@[0-9A-Fa-f]{2}$", token):
                if current_chunk:
                    wrapped_lines.append("".join(current_chunk).rstrip())
                    current_chunk = []
                    current_len = 0
                
                for char in token:
                    c_len = visible_len(char)
                    if current_len + c_len > max_len and current_len > 0:
                        wrapped_lines.append("".join(current_chunk).rstrip())
                        current_chunk = []
                        current_len = 0
                    current_chunk.append(char)
                    current_len += c_len
                continue

            if current_len + t_len > max_len and current_len > 0:
                wrapped_lines.append("".join(current_chunk).rstrip())
                current_chunk = [token]
                current_len = t_len
            else:
                current_chunk.append(token)
                current_len += t_len

        if current_chunk:
            wrapped_lines.append("".join(current_chunk).rstrip())

    return NEWLINE.join(wrapped_lines)

SYSTEM_PROMPT = (
    "You are a professional Japanese-to-English translator working on a trading card "
    "game (Cardfight!! Vanguard). Translate the user's text naturally into English, "
    "keeping the tone appropriate for game dialogue/UI.\n"
    "Strict rules:\n"
    "- Do not add explanations, notes, quotes around the answer, or restate the source text.\n"
    "- Never invent unrelated content. If a segment is unclear, translate it as literally as possible.\n"
    "- The output MUST be a single line: no line breaks under any circumstance.\n"
    "- The text may contain placeholders like <0>, <1> and formatting tags like @40, @41. You MUST preserve them exactly in their correct contextual positions in the translated text.\n"
    "- Output ONLY the translated text."
)

CJK_COUNT_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿]")

def validate_response(response: str, source: str) -> str:
    stripped = response.replace("\r", " ").replace("\n", " ").strip()
    if not stripped: raise ValueError("empty response")

    max_len = max(200, len(source) * 6)
    if len(stripped) > max_len:
        raise ValueError(f"abnormally long response ({len(stripped)} chars)")

    cjk_count = len(CJK_COUNT_RE.findall(stripped))
    if cjk_count > max(3, len(stripped) * 0.3):
        raise ValueError(f"too many CJK characters in output ({cjk_count})")

    return stripped

def call_ollama(text: str, model: str, num_ctx: int = 1024, num_predict: int = 128, retries: int = 5) -> str:
    body = json.dumps({
        "model": model,
        "system": SYSTEM_PROMPT,
        "prompt": text,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": num_ctx, "num_predict": num_predict},
    }).encode("utf-8")

    req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return validate_response(data["response"], text)
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"  ⚠ Ollama error (attempt {attempt}/{retries}): {e}")
            time.sleep(2)
    raise RuntimeError(f"Ollama unreachable/invalid: {last_err}")

def translate_segment(chunk: str, model: str, cache: dict, num_ctx: int = 512, num_predict: int = 128) -> str:
    if chunk in cache: return cache[chunk]
    if not needs_translation(chunk):
        cache[chunk] = chunk
        return chunk

    dynamic_predict = max(num_predict, len(chunk) * 4 + 40)
    translated = call_ollama(chunk, model, num_ctx=max(num_ctx, dynamic_predict + 256), num_predict=dynamic_predict)
    cache[chunk] = translated
    return translated

def translate_cell(raw_text: str, model: str, cache: dict, num_ctx: int = 512, num_predict: int = 128) -> str:
    kanji_text = strip_furigana(raw_text)
    cleaned_text = kanji_text.replace("†", " ").replace("\\n", " ")
    cleaned_text = cleaned_text.replace("\n", " ").replace("\r", " ")
    cleaned_text = re.sub(r" +", " ", cleaned_text).strip()

    # ==========================================
    # PIPELINE 1: TRANSLATION
    # ==========================================
    if needs_translation(cleaned_text):
        tags = []
        def repl(m):
            tags.append(m.group(0))
            return f"<{len(tags)-1}>"
            
        placeholder_text = INLINE_RE.sub(repl, cleaned_text)
        
        # The cache is handled HERE, at the LLM level only
        translated = translate_segment(placeholder_text, model, cache, num_ctx, num_predict)
            
        def restore(m):
            idx = int(m.group(1))
            if 0 <= idx < len(tags):
                return tags[idx]
            return m.group(0)
            
        translated = re.sub(r"<\s*(\d+)\s*>", restore, translated)
    else:
        translated = cleaned_text

    # ==========================================
    # PIPELINE 2: TAG HANDLING
    # ==========================================
    translated = re.sub(r"(?<!\s)(@[0-9A-Fa-f]{2})", r" \1", translated)
    translated = re.sub(r"(@[0-9A-Fa-f]{2})(?!\s)", r"\1 ", translated)
    translated = translated.strip()
    
    # Tags @40 to @44 are surrounded by TWO daggers (NEWLINE)
    translated = re.sub(r"\s*(@(?:40|41|42|43|44))\s*", NEWLINE + r"\1" + NEWLINE, translated)
    
    translated = re.sub(r"(?<!\s)(＊[^＊]+＊)", r" \1", translated)
    translated = re.sub(r"(＊[^＊]+＊)(?!\s)", r"\1 ", translated)
    translated = re.sub(r"(?<!\s)(\*[^\*]+\*)", r" \1", translated)
    translated = re.sub(r"(\*[^\*]+\*)(?!\s)", r"\1 ", translated)
    
    translated = re.sub(r" +", " ", translated).strip()
    
    # ==========================================
    # PIPELINE 3: LINE BREAK INSERTION
    # ==========================================
    translated = sanitize_translation(translated)
    translated = apply_daggers(translated, max_len=MAX_LINE_LENGTH)

    translated = translated.replace("\r", "").replace("\n", "")
    translated = sanitize_translation(translated)
    
    return translated

def load_cache(path: Path) -> dict:
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(path: Path, cache: dict) -> None:
    import os
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=0)
        f.flush()
        os.fsync(f.fileno())

    last_err = None
    for attempt in range(5):
        try:
            tmp_path.replace(path)
            return
        except PermissionError as e:  # noqa: PERF203
            last_err = e
            time.sleep(0.3 * (attempt + 1))
    raise last_err

def check_ollama_reachable(model: str) -> None:
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        names = [m.get("name", "") for m in data.get("models", [])]
        if not any(model in n for n in names):
            print(f"⚠ Model '{model}' does not appear in 'ollama list' ({names}).")
            print("  Run `ollama pull " + model + "` if necessary.")
    except Exception as e:  # noqa: BLE001
        print(f"❌ Cannot reach Ollama on localhost:11434 ({e}).")
        print("  Run `ollama serve` before restarting this script.")
        sys.exit(1)

def sanitize_csv(input_csv: str, output_csv: str, column: str, dry_run: bool) -> None:
    # Read/write with the csv module: CSV quoting ("…""Abyss""…" field)
    # is never seen as text to clean.
    with open(input_csv, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    header = rows[0]
    idx = header.index(column)

    stats: dict[str, list[int]] = {}
    changed = 0
    for n, row in enumerate(rows[1:], start=2):
        if len(row) <= idx:
            continue
        for issue in find_issues(row[idx]):
            stats.setdefault(issue, []).append(n)
        new = sanitize_translation(row[idx])
        if new != row[idx]:
            row[idx] = new
            changed += 1

    for issue, nums in stats.items():
        print(f"  {issue} : {len(nums)} line(s), e.g. {nums[:8]}")
    print(f"{changed} line(s) {'to modify' if dry_run else 'modified'}.")
    if not dry_run:
        with open(output_csv, "w", encoding="utf-8", newline="") as f:
            csv.writer(f, delimiter=";", lineterminator="\n").writerows(rows)
        print(f"File saved to: {output_csv}")

def main() -> None:
    parser = argparse.ArgumentParser(description="Translates strings that are still in Japanese after update_csv.py using Ollama.")
    parser.add_argument("input_csv")
    parser.add_argument("output_csv")
    parser.add_argument("--column", default="extract", help="Column to translate (default: extract)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--cache", default="low_trad_cache.json", help="JSON cache file")
    parser.add_argument("--limit", type=int, default=0, help="Only process N lines (0 = all)")
    parser.add_argument("--num-ctx", type=int, default=512, help="Ollama context size (default: 512)")
    parser.add_argument("--num-predict", type=int, default=128, help="Max output tokens (default: 128)")
    parser.add_argument("--dry-run", action="store_true", help="Count lines without calling Ollama")
    parser.add_argument("--sanitize", action="store_true", help="Only apply checkers")
    args = parser.parse_args()

    if args.sanitize:
        sanitize_csv(args.input_csv, args.output_csv, args.column, args.dry_run)
        return

    if not args.dry_run:
        check_ollama_reachable(args.model)

    cache_path = Path(args.cache)
    cache = load_cache(cache_path)

    with open(args.input_csv, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        fieldnames = reader.fieldnames
        rows = list(reader)

    total_translatable = sum(
        1 for row in rows if line_needs_processing(row.get(args.column, ""))
    )
    print(f"🔍 {total_translatable} line(s) to process (Translate & Format) out of {len(rows)} total.")

    if args.dry_run:
        return

    BATCH = 5
    output_path = Path(args.output_csv)
    resume_from = 0
    if output_path.exists() and output_path.stat().st_size > 0:
        with output_path.open("r", encoding="utf-8", newline="") as f:
            existing_rows = list(csv.reader(f, delimiter=";"))
        resume_from = max(0, len(existing_rows) - 1)
        print(f"↻ Resuming at line {resume_from}/{len(rows)} (existing output file).")
        out_f = output_path.open("a", encoding="utf-8", newline="")
    else:
        out_f = output_path.open("w", encoding="utf-8", newline="")
        csv.writer(out_f, delimiter=";").writerow(fieldnames)
        out_f.flush()
    writer = csv.writer(out_f, delimiter=";")

    processed_count = 0
    failed = 0
    since_flush = 0
    limit_left = args.limit if args.limit else None
    durations: list[float] = [] 
    remaining_to_translate = total_translatable

    def eta_str() -> str:
        if not durations: return "ETA unknown"
        avg = sum(durations[-20:]) / len(durations[-20:])
        remaining = max(0, remaining_to_translate)
        eta_s = avg * remaining
        m, s = divmod(int(eta_s), 60)
        h, m = divmod(m, 60)
        return f"~{avg:.1f}s/trans, ETA {h}h{m:02d}m{s:02d}s ({remaining} remaining)"

    try:
        for i in range(resume_from, len(rows)):
            row = rows[i]
            raw = row.get(args.column, "")
            
            if line_needs_processing(raw):
                if limit_left is not None and limit_left <= 0:
                    print(f"   (limit of {args.limit} reached, stopping at line {i})")
                    break
                
                # The cache covers the LLM step inside translate_cell
                was_cached = not needs_translation(strip_furigana(raw)) or raw in cache
                t0 = time.time()
                try:
                    row[args.column] = translate_cell(raw, args.model, cache, args.num_ctx, args.num_predict)
                    dt = time.time() - t0
                    processed_count += 1
                    remaining_to_translate -= 1
                    if limit_left is not None: limit_left -= 1
                    
                    if was_cached: 
                        print(f"  [cache/reformat] line {i}: instant")
                    else:
                        durations.append(dt)
                        print(f"  [{dt:.2f}s] line {i} → {eta_str()}")
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    remaining_to_translate -= 1
                    print(f"❌ Failed line {i} ({time.time() - t0:.2f}s): {e}")

            writer.writerow([row.get(c, "") for c in fieldnames])
            since_flush += 1

            if since_flush >= BATCH:
                out_f.flush()
                save_cache(cache_path, cache)
                print(f"… line {i + 1}/{len(rows)} ({processed_count} processed, {failed} failed)")
                since_flush = 0
    finally:
        out_f.flush()
        out_f.close()
        save_cache(cache_path, cache)

    print(f"✔ Done: {processed_count} string(s) processed, {failed} failure(s).")

if __name__ == "__main__":
    main()