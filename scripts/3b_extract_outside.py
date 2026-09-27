# -*- coding: utf-8 -*-
"""Strings OUTSIDE the known range -> extracted_outside.csv (same format as
extracted_strings.csv, for 3_5_sync_translation.py / update_csv.py / low_trad.py).

    python scripts/3b_extract_outside.py [files/code_literals.json] [extracted_outside.csv]

Source: files/code_literals.json (scripts/1_7_export_code_literals.py in IDA).
Columns:
  pointer_offsets : references, "A:0x..." = ADR instruction, "P:0x..." = pool dword
  pointer_value   : address of the Japanese string
  separators      : 00 00
  extract         : text (line breaks as †)
"""
import csv
import json
import sys
from pathlib import Path

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "files/code_literals.json")
DST = Path(sys.argv[2] if len(sys.argv) > 2 else "extracted_outside.csv")


def main():
    literals = json.loads(SRC.read_text(encoding="utf-8"))
    with DST.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["pointer_offsets", "pointer_value", "separators", "extract"])
        for lit in literals:
            refs = [f"A:0x{a:06X}" for a in lit["adr"]] + [f"P:0x{p:06X}" for p in lit["pool"]]
            w.writerow([",".join(refs), f"0x{lit['literal']:08X}", "00 00", lit["jp"].replace("\n", "†")])
    print(f"✔ {DST}: {len(literals)} out-of-range strings")


if __name__ == "__main__":
    main()
