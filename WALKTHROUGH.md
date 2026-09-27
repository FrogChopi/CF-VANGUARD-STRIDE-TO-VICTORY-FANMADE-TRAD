# WALKTHROUGH

All commands are run from the project root (PowerShell). Tools needed: `3dstool.exe`, `ctrtool.exe`, `makerom.exe`, Python 3, and optionally IDA Pro, Kuriimu2 and Ollama.

## 1. GET FILES

From a decrypted `.3ds`:

```bash
mkdir extract
.\3dstool.exe -xv -t cci -f '..\CardFight!! Vanguard G - Stride to Victory!! (Japan).3ds' -0 extract.cxi
.\3dstool.exe -x -t cxi -f extract.cxi --header extract/header.bin --exh extract/exheader.bin --exefs extract/exefs.bin --romfs extract/romfs.bin
.\3dstool.exe -xu -t exefs -f extract/exefs.bin --decompresscode --exefs-dir extract/exefs
.\3dstool.exe -xu -t romfs -f extract/romfs.bin --romfs-dir extract/romfs
```

From a decrypted `.cia` (not my problem how you get it :3):

```bash
.\ctrtool.exe --exheader extract/exheader.bin --romfsdir extract/romfs --romfs extract/romfs.bin --exefsdir extract/exefs --exefs extract/exefs.bin --decompresscode .\cf_vanguard.cia
```

- `exefs` contains the game executable `code.bin` + `banner.bin`
- `romfs` contains all game files/assets: `.ctpk` are textures, `.rtz` are scenes (mini executables)
- **BEFORE GOING FURTHER** make a working copy, you'll thank me later. `extract/` stays pristine, everything is patched in `modified/`:

```bash
Copy-Item -Recurse extract modified
```

## 2. CODE.BIN STRINGS

The files in `files/` are already produced for CFV Stride to Victory!! (IDA offsets, code literals, pointer review, keyword decisions, tagged card database...), so the IDA steps can be skipped.

### 2.1 Find the string range

You need `a lot of patience, a strong coffee machine and truly solid reverse engineering skills`, or just a good tool (IDA Pro + Hex-Rays with [this plugin](https://github.com/kynex7510/3ds_ida)).
Explore `code.bin` and find the bounds of the string table. For CFV STV they are `0x949720` → `0xB51CD0` (virtual addresses; other FuRyu 3DS card games use the same format).

### 2.2 Pad code.bin

Extracting exefs prints the code layout:

```bash
# Name:                   vanguard
# Code text address:      0x00100000
# Code text max pages:    0x000007D3 (0x007D3000)
# Code ro address:        0x008D3000
# Code ro max pages:      0x0000034C (0x0034C000)
# => Code data address:   0x00C1F000   -> file offset 0x00C1F000 - 0x00100000 = 0xB1F000
# => Code data size:      0x001BBF78
# => Code bss size:       0x001E16FC
```

The `.bss` is zero-filled in memory only, so it's appended as real zeros after `.data`. The new strings can then go at the end of the file without overwriting it:

```bash
python scripts/2_pad_data.py extract/exefs/code.bin 0xB1F000 0x1BBF78 0x1E16FC full_padded.bin
```

### 2.3 Pointers

```bash
# every dword pointing into the range (no IDA needed) -> fresh_rodata_pointers.csv
python scripts/1_export_pointers.py full_padded.bin fresh_rodata_pointers.csv
```

Some of those "pointers" are impostors (random data or code that happens to look like an address). Rewriting one of them corrupts the game, so `4_inject_from_file.py` only repatches locations it can prove are pointers (see 2.7). Two optional IDA scripts help with that (File > Script file, on the analyzed `code.bin`):

- `1_6_export_ida_offsets.py` → `files/ida_trusted_offsets.txt`: locations IDA typed as offsets.
- `1_7_export_code_literals.py` → `files/code_literals.json`: Japanese strings **outside** the range that the code loads directly (`ADR` literals in `.text`, `LDR` from a literal pool). It needs `full_padded.bin` and `extracted_strings.csv` (2.4) and expects the IDB two folders below the project root.

### 2.4 Extract

```bash
# strings of the range -> extracted_strings.csv
python scripts/3_extract_from_pointer.py
# strings outside the range (files/code_literals.json) -> extracted_outside.csv
python scripts/3b_extract_outside.py
```

`3_extract_from_pointer.py` skips the known impostors (`IMPOSTOR_OFFSETS`, non-pointer fields of the card table) and pointers that don't land at a string start.

### 2.5 Sync the translation

`extracted_strings_updated.csv` / `extracted_outside_updated.csv` are the translated files. After a fresh extraction, sync them so no translation is lost (a `.bak` is kept):

```bash
python scripts/3_5_sync_translation.py
python scripts/3_5_sync_translation.py extracted_outside.csv extracted_outside_updated.csv
```

Card names come from `files/name_table.json` first, so they match the `.rtz` texts.

### 2.6 Translate

Keep the control codes (`@xx`, `{$xxxxxx}`, `%d`...) and `†` (line break).

```bash
# (once) convert the English card database to the game's text format -> files/vanguard_cards_balise.json
python scripts/build_card_db.py vanguard_cards_enriched.json files/vanguard_cards_balise.json
# card names + official card effects and flavors (only rows still in Japanese, unless --overwrite)
python scripts/update_csv.py files/name_table.json extracted_strings_updated.csv extracted_strings_updated.csv --cards files/vanguard_cards_balise.json
# card names quoted in effects ("...") -> exact in-game names
python scripts/3_7_fix_quoted_names.py
# name keywords ("a card whose name contains X") must match the same cards as in JP
python scripts/3_6_keywords.py
# set lines (@42) -> game's set code + official English set name (files/set_names.json)
python scripts/3_8_fix_set_lines.py
# optional: machine-translate what's still in Japanese (needs `ollama serve`, resumable, cached in low_trad_cache.json)
python scripts/low_trad.py extracted_strings_updated.csv extracted_strings_updated_trad.csv
python scripts/low_trad.py extracted_strings_updated_trad.csv extracted_strings_updated.csv --sanitize
# final check: exits with code 1 if a keyword is broken
python scripts/3_6_keywords.py --check
```

`compare_cards.py` writes `cards_compare.csv`, a side-by-side of the game's cards and the database, useful to check the card matching.

### 2.7 Inject

```bash
# full_padded.bin + extracted_strings_updated.csv + extracted_outside_updated.csv -> full_patched.bin
python scripts/4_inject_from_file.py
# exheader sizes for the grown code.bin (also pads code.bin to a page boundary)
python scripts/5_patch_exheader.py extract/exheader.bin full_patched.bin exheader_patched.bin
```

`4_inject_from_file.py` prints the locations it couldn't prove as pointers and leaves them untouched (details in `injection_report.csv`). Check them, then add them to `files/pointer_review.csv` with the verdict `pointeur` or `imposteur`. `MAX_CHAINES` limits how many strings are injected, to bisect a crash.

Quick test in Azahar without rebuilding the `.3ds` (title id `0004000000170500`):

```bash
$mod = "$env:APPDATA\Azahar\load\mods\0004000000170500"
python scripts/4_inject_from_file.py "$mod\exefs\code.bin"
python scripts/5_patch_exheader.py extract/exheader.bin "$mod\exefs\code.bin" "$mod\exheader.bin"
```

## 3. RTZ STRINGS (scenes)

`.rtz` = 4-byte decompressed size + gzip stream. The text table sits at a per-file offset listed in `files/RTZ.json`.

```bash
python scripts/6_decompress_all_rtz.py .\modified\romfs\
python scripts/7_rtz_batch_extract.py files/RTZ.json .\modified\romfs\
# -> output_all.csv, translate it like extracted_strings_updated.csv
python scripts/update_csv.py files/name_table.json output_all.csv output_all_updated.csv
python scripts/low_trad.py output_all_updated.csv output_all_updated_trad.csv
```

A line is at most 255 characters (the length is stored on 1 byte).

## 4. CTPK (textures)

`.ctpk` files are gzipped the same way as `.rtz`. The edited images (GIMP `.xcf`) are in `image_xcf/`.

```bash
# writes a <name>_decompressed.ctpk next to each .ctpk
python scripts/ctpk_batch.py .\modified\romfs\
mkdir ctpk_extracted
Kuriimu2.exe
# Tools > Batch Extractor > CTPK plugin > Sub Directories > input .\modified\romfs\ > output ctpk_extracted
# Kuriimu2 tends to crash when given more than one folder; kill it once done if needed.
# Edit the images, then re-import them into the *_decompressed.ctpk files with Kuriimu2.
```

## 5. REBUILD

```bash
# repack every *_decompressed.ctpk into its .ctpk
python scripts/ctpk_batch.py .\modified\romfs\ --recompress
# inject the translated text into the decompressed .rtz (.bin), then recompress them
python scripts/8_rtz_batch_inject.py output_all_updated_trad.csv .\modified\romfs\
python scripts/9_recompress_all_rtz.py .\modified\romfs\
# rebuild romfs
.\3dstool.exe -czt romfs --romfs-dir .\modified\romfs -f romfs_patched.bin
# code.bin + exheader (2.7)
python scripts/4_inject_from_file.py
python scripts/5_patch_exheader.py extract/exheader.bin full_patched.bin exheader_patched.bin
# build the game
.\makerom.exe -f cci -o rebuild_vanguard_stv.3ds -code full_patched.bin -exheader exheader_patched.bin -romfs romfs_patched.bin -rsf files/cf_vanguard.rsf
```

## SCRIPTS

| Script | Role |
| --- | --- |
| `1_export_pointers.py` | dump every pointer into the string range → `fresh_rodata_pointers.csv` |
| `1_6_export_ida_offsets.py` | (IDA) pointer locations typed as offsets → `files/ida_trusted_offsets.txt` |
| `1_7_export_code_literals.py` | (IDA) JP strings outside the range loaded by the code → `files/code_literals.json` |
| `2_pad_data.py` | append the `.bss` as zeros after `.data` |
| `3_extract_from_pointer.py` | pointers → `extracted_strings.csv` |
| `3b_extract_outside.py` | `files/code_literals.json` → `extracted_outside.csv` |
| `3_5_sync_translation.py` | merge a fresh extraction into the translated CSV |
| `3_6_keywords.py` | keep card name keywords matching the same cards |
| `3_7_fix_quoted_names.py` | quoted card names in effects → in-game names |
| `3_8_fix_set_lines.py` | rewrite the `@42` set lines |
| `4_inject_from_file.py` | relocate translated strings and repatch proven pointers → `full_patched.bin` |
| `5_patch_exheader.py` | update exheader sizes for the grown code.bin |
| `6_decompress_all_rtz.py` / `9_recompress_all_rtz.py` | `.rtz` ⇄ `.bin` |
| `7_rtz_batch_extract.py` / `8_rtz_batch_inject.py` | RTZ text ⇄ `output_all.csv` |
| `ctpk_batch.py` | `.ctpk` ⇄ `_decompressed.ctpk` (`--recompress`) |
| `update_csv.py` | card names from `name_table.json`, official effects/flavors with `--cards` |
| `build_card_db.py` | English card database → game text format |
| `compare_cards.py` | game cards vs database report (also used by `update_csv.py` and `3_8`) |
| `low_trad.py` | machine-translate remaining JP via Ollama, `--sanitize` to clean a CSV |
| `vanguard_tables.py` | code.bin table addresses shared by the scripts |
