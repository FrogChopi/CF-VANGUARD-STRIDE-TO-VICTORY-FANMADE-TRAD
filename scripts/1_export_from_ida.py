import idautils, ida_bytes, idc, os

# Configuration de la plage à scanner
START = 0x0949720
END   = 0x0B51CD0

def extract_pointers(start, end):
    results = []
    for seg in idautils.Segments():
        seg_start = idc.get_segm_start(seg)
        seg_end   = idc.get_segm_end(seg)
        ea = seg_start
        while ea < seg_end:
            val = ida_bytes.get_wide_dword(ea)  # pour 4-octets, ou get_wide_word si 2-octets
            if START <= val < END:
                results.append((ea, val))
            ea += 4
    return results

# Exécution
ptrs = extract_pointers(START, END)

# Prépare le fichier de sortie
out_path = os.path.join(os.getcwd(), "rodata_pointers.csv")
with open(out_path, "w", encoding="utf-8") as f:
    f.write("offset;value\n")
    for ea, val in sorted(ptrs):
        f.write(f"{hex(ea)};{hex(val)}\n")
    f.write(f"✅ {len(ptrs)} pointeurs trouvés vers la plage.\n")

print(f"✅ Export terminé dans {out_path}")
