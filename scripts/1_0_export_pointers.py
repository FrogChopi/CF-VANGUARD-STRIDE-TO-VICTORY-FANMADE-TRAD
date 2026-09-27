import argparse
import struct

# Range of string data to look for pointers into
START = 0x0949720
END   = 0x0B51CD0
BASE  = 0x100000  # .text load address (decompressed code.bin: text/ro/data are contiguous)


def extract_pointers(data, start, end, base):
    results = []
    for i in range(0, len(data) - 3, 4):
        val = struct.unpack_from("<I", data, i)[0]
        if start <= val < end:
            results.append((base + i, val))
    return results


def main():
    parser = argparse.ArgumentParser(description="Extract every 32-bit pointer into [START, END) without IDA.")
    parser.add_argument("code", nargs="?", default="extract/exefs/code.bin", help="decompressed code.bin")
    parser.add_argument("out", nargs="?", default="rodata_pointers.csv", help="output CSV (offset;value)")
    parser.add_argument("--start", type=lambda x: int(x, 0), default=START)
    parser.add_argument("--end", type=lambda x: int(x, 0), default=END)
    parser.add_argument("--base", type=lambda x: int(x, 0), default=BASE)
    args = parser.parse_args()

    with open(args.code, "rb") as f:
        data = f.read()

    ptrs = extract_pointers(data, args.start, args.end, args.base)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("offset;value\n")
        for ea, val in ptrs:
            f.write(f"{hex(ea)};{hex(val)}\n")

    print(f"✅ {len(ptrs)} pointers into {hex(args.start)}-{hex(args.end)}")
    print(f"✅ Exported to {args.out}")


if __name__ == "__main__":
    main()
