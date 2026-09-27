# Run in IDA (File > Script file) on the analyzed code.bin.
# Writes files/ida_trusted_offsets.txt: the pointer locations (from the
# pointer CSV) that IDA typed as offsets. 4_inject_from_file.py trusts them
# for repatching.
import csv, os
import ida_bytes, idc

POINTER_CSV = "fresh_rodata_pointers.csv"
OUT         = os.path.join("files", "ida_trusted_offsets.txt")

trusted = []
with open(POINTER_CSV, encoding="utf-8") as f:
    for row in csv.reader(f, delimiter=";"):
        if len(row) < 2 or row[0].lower() == "offset":
            continue
        try:
            ea = int(row[0], 16)
        except ValueError:
            continue
        if idc.get_item_head(ea) == ea and ida_bytes.is_off0(ida_bytes.get_flags(ea)):
            trusted.append(ea)

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(f"0x{ea:06X}" for ea in sorted(set(trusted))) + "\n")

print(f"✅ {len(set(trusted))} trusted offsets written to {OUT}")
