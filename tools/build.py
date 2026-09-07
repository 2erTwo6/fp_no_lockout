#!/usr/bin/env python3
"""FP No Lockout - build tool.

Author: 2erTwo6

Takes a stock mfp-daemon binary (pulled from /odm/bin/hw/mfp-daemon), applies the
two-instruction lockout-neuter patch, and repacks the KernelSU/Magisk module zip.

Usage:
    python3 tools/build.py --stock mfp-daemon.stock [--out-zip fp_no_lockout_v1.1.zip]
"""

import argparse
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODULE_DIR = REPO / "module"
PATCHED_PATH = MODULE_DIR / "bin" / "mfp-daemon"

STOCK_MD5 = "9d50fe61dfb66bac6dc5facff9f860c4"
PATCHED_MD5 = "b070144e292963eafccd2d6083f3ce87"

# (file offset, original instruction bytes, patched instruction bytes)
# ARM64 little-endian instruction words.
PATCHES = [
    (
        0x180A8,
        bytes.fromhex("03db02b9"),  # str w3, [x24, #728]  (failed_match_count = count+1)
        bytes.fromhex("1f2003d5"),  # nop
    ),
    (
        0x18124,
        bytes.fromhex("e81a40b9"),  # ldr w8, [x23, #24]   (per-screenlock quota)
        bytes.fromhex("28008052"),  # mov w8, #1
    ),
]


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def patch(stock: bytes) -> bytes:
    data = bytearray(stock)
    for off, orig, new in PATCHES:
        cur = bytes(data[off : off + 4])
        if cur != orig:
            sys.exit(
                f"error: unexpected bytes at offset 0x{off:X}: {cur.hex()} != {orig.hex()}\n"
                "the stock binary does not match the adapted version"
            )
        data[off : off + 4] = new
        print(f"patched 0x{off:X}: {orig.hex()} -> {new.hex()}")
    return bytes(data)


def build_zip(out: Path) -> None:
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(MODULE_DIR.rglob("*")):
            if p.is_dir():
                continue
            arcname = p.relative_to(MODULE_DIR).as_posix()
            zi = zipfile.ZipInfo.from_file(p, arcname)
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, p.read_bytes())
    print(f"built {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", required=True, help="path to stock /odm/bin/hw/mfp-daemon")
    ap.add_argument("--out-zip", default=str(REPO / "fp_no_lockout_v1.1.zip"))
    args = ap.parse_args()

    stock = Path(args.stock).read_bytes()
    got = md5(stock)
    if got != STOCK_MD5:
        sys.exit(f"error: stock md5 {got} != expected {STOCK_MD5} (different ROM/OTA?)")
    print(f"stock md5 ok: {got}")

    patched = patch(stock)
    got = md5(patched)
    if got != PATCHED_MD5:
        sys.exit(f"error: patched md5 {got} != expected {PATCHED_MD5}")
    print(f"patched md5 ok: {got}")
    PATCHED_PATH.write_bytes(patched)

    build_zip(Path(args.out_zip))

    # sanity check: disassemble patched binary and confirm instructions
    try:
        out = subprocess.run(
            ["aarch64-linux-gnu-objdump", "-d", str(PATCHED_PATH)],
            capture_output=True, text=True,
        )
        asm = out.stdout
        assert "d503201f \tnop" in asm or "nop" in asm.split("180a8:")[1][:40]
        assert "mov\tw8, #0x1" in asm.split("18124:")[1][:80]
        print("disassembly check ok")
    except Exception as e:  # noqa: BLE001
        print(f"warning: could not run objdump verification: {e}")

    print("done")


if __name__ == "__main__":
    main()