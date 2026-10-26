#!/usr/bin/env python3
"""FP No Lockout - build tool.

Author: 2erTwo6

Takes a stock mfp-daemon binary (pulled from /odm/bin/hw/mfp-daemon), applies the
two-instruction lockout-neuter patch, and repacks the KernelSU/Magisk module zip.

Each ROM version ships its own patched binary; post-fs-data.sh picks the binary
whose stock md5 matches what is actually on /odm at boot (OTA failsafe).

Usage:
    # patch one or more stock binaries (version auto-detected by md5)
    python3 tools/build.py --stock mfp-daemon.os4.stock --stock mfp-daemon.os3.stock

    # unknown ROM: locate the patch sites by structural signature instead of md5
    python3 tools/build.py --stock mfp-daemon.new.stock --scan

    # only repack the zip from the binaries currently in module/bin
    python3 tools/build.py
"""

from __future__ import annotations

import argparse
import hashlib
import struct
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODULE_DIR = REPO / "module"
BIN_DIR = MODULE_DIR / "bin"

# --- instruction words -------------------------------------------------------
NOP = bytes.fromhex("1f2003d5")  # nop
LDR_QUOTA = bytes.fromhex("e81a40b9")  # ldr w8, [x23, #0x18]
HAS_QUOTA = bytes.fromhex("28008052")  # mov w8, #1

# Unique, PC-relative-free anchor: the two count stores back to back.
#   str w3, [x24, #0x2d8]   ; failed_match_count = failed_match_count + 1
#   str w8, [x23, #0x18]    ; valid_times_per_screenlock = valid_times_per_screenlock - 1
SITE_A_ANCHOR = bytes.fromhex("03db02b9e81a00b9")

# Site B sits a fixed distance after site A in every build seen so far
# (same function, same basic-block layout).
SITE_B_DELTA = 0x7C

# --- surrounding fingerprint (all non-PC-relative) ---------------------------
LDR_COUNT = bytes.fromhex("e91a40b9")  # ldr w9, [x23, #0x18]
SUB_ONE = bytes.fromhex("28050051")  # sub w8, w9, #1
CMP_20 = bytes.fromhex("1f510071")  # cmp w8, #0x14

# --- known ROM versions ------------------------------------------------------
# sites are (file offset) == (virtual address) because of the 0x4000-aligned
# single PT_LOAD for .text in this binary.
VERSIONS: dict[str, dict] = {
    "os4.0": {
        "rom": "HyperOS 4 / OS4.0.3.0.XPLCNXM (Android 17, 17OS4.0.261020.230009638.MTPECN.S)",
        "stock_md5": "f943889add94013ab08e9749cc29f077",
        "patched_md5": "d6ef30b1bf6e9a1a23cef7f6172f7f88",
        "out": "mfp-daemon.os4",
        "sites": (0x180A8, 0x18124),
    },
    "os3.0": {
        "rom": "HyperOS 3 / OS3.0 (Android 16)",
        "stock_md5": "9d50fe61dfb66bac6dc5facff9f860c4",
        "patched_md5": "b070144e292963eafccd2d6083f3ce87",
        "out": "mfp-daemon.os3",
        "sites": (0x180A8, 0x18124),
    },
}


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def blt_target(off: int, word: int) -> int | None:
    """Return the branch target of a `b.lt` at `off`, or None."""
    if (word & 0xFF00001F) != 0x5400000B:  # b.cond, cond = LT (0xB)
        return None
    imm19 = (word >> 5) & 0x7FFFF
    if imm19 & (1 << 18):
        imm19 -= 1 << 19
    return off + imm19 * 4


def fingerprint(data: bytes, site_a: int, site_b: int) -> list[str]:
    """Structural sanity checks around the two patch sites. Returns problems."""
    problems = []
    head = data[site_a - 0x20 : site_a]
    if head[:4] != LDR_COUNT:
        problems.append(f"0x{site_a - 0x20:X}: expected ldr w9, [x23, #0x18]")
    if head[0x14:0x18] != SUB_ONE:
        problems.append(f"0x{site_a - 0x0C:X}: expected sub w8, w9, #1")
    if data[site_a : site_a + 8] != SITE_A_ANCHOR:
        problems.append(f"0x{site_a:X}: expected failed_match_count increment pair")
    tail = data[site_a + 0x24 : site_a + 0x2C]
    if tail[:4] != CMP_20:
        problems.append(f"0x{site_a + 0x24:X}: expected cmp w8, #0x14")
    else:
        br = struct.unpack_from("<I", data, site_a + 0x28)[0]
        if blt_target(site_a + 0x28, br) != site_b:
            problems.append(
                f"0x{site_a + 0x28:X}: b.lt does not jump to the quota-check site "
                f"0x{site_b:X}"
            )
    if data[site_b : site_b + 4] != LDR_QUOTA:
        problems.append(f"0x{site_b:X}: expected ldr w8, [x23, #0x18]")
    elif not (struct.unpack_from("<I", data, site_b + 4)[0] & 0x7F000000) == 0x35000000:
        problems.append(f"0x{site_b + 4:X}: expected cbnz w8 (quota has-quota test)")
    return problems


def patch(data: bytes, site_a: int, site_b: int) -> bytes:
    out = bytearray(data)
    out[site_a : site_a + 4] = NOP  # failed_match_count++ -> never increments
    out[site_b : site_b + 4] = HAS_QUOTA  # quota check -> always "has quota"
    return bytes(out)


def text_range(data: bytes) -> tuple[int, int]:
    """(file offset, size) of the executable PT_LOAD, i.e. where .text lives."""
    e_phoff = struct.unpack_from("<Q", data, 0x20)[0]
    e_phentsize = struct.unpack_from("<H", data, 0x36)[0]
    e_phnum = struct.unpack_from("<H", data, 0x38)[0]
    for i in range(e_phnum):
        p = e_phoff + i * e_phentsize
        p_type, p_flags = struct.unpack_from("<II", data, p)
        p_offset, p_vaddr, _, p_filesz = struct.unpack_from("<QQQQ", data, p + 8)
        if p_type == 1 and p_flags & 0x1:  # PT_LOAD | PF_X
            # this binary maps .text with p_offset == p_vaddr (0x4000-aligned)
            return p_offset, p_filesz
    raise ValueError("no executable PT_LOAD found")


def scan_sites(data: bytes) -> tuple[int, int] | None:
    """Find the patch sites by signature (for ROMs not in VERSIONS)."""
    lo, size = text_range(data)
    hits, idx = [], data.find(SITE_A_ANCHOR)
    while idx != -1:
        # instruction-aligned and inside the executable segment only
        if idx % 4 == 0 and lo <= idx < lo + size:
            hits.append(idx)
        idx = data.find(SITE_A_ANCHOR, idx + 1)
    if len(hits) != 1:
        return None
    site_a = hits[0]
    site_b = site_a + SITE_B_DELTA
    if fingerprint(data, site_a, site_b):
        return None
    return site_a, site_b


def cmd_patch(stock_path: Path, do_scan: bool) -> Path | None:
    stock = stock_path.read_bytes()
    got = md5(stock)
    key = next((k for k, v in VERSIONS.items() if v["stock_md5"] == got), None)

    if key is not None:
        ver = VERSIONS[key]
        site_a, site_b = ver["sites"]
        print(f"{stock_path.name}: md5 {got} -> known version {key} ({ver['rom']})")
    else:
        print(f"{stock_path.name}: md5 {got} -> unknown ROM")
        if not do_scan:
            print(
                "  skipped (pass --scan to locate the patch sites by signature)\n"
                f"  known: {', '.join(v['stock_md5'] for v in VERSIONS.values())}"
            )
            return None
        found = scan_sites(stock)
        if found is None:
            print("  signature scan failed: patch sites not found or fingerprint mismatch")
            return None
        site_a, site_b = found
        key = f"custom-{got[:8]}"
        VERSIONS[key] = {
            "rom": "auto-detected (unverified ROM)",
            "stock_md5": got,
            "patched_md5": "",
            "out": f"mfp-daemon.{got[:8]}",
            "sites": (site_a, site_b),
        }
        print(f"  signature scan ok: sites 0x{site_a:X} / 0x{site_b:X}")

    problems = fingerprint(stock, site_a, site_b)
    if problems:
        print("error: binary does not match the expected lockout routine:")
        for p in problems:
            print(f"  - {p}")
        return None

    patched = patch(stock, site_a, site_b)
    print(f"  patched 0x{site_a:X}: {stock[site_a:site_a + 4].hex()} -> {NOP.hex()} (nop)")
    print(f"  patched 0x{site_b:X}: {stock[site_b:site_b + 4].hex()} -> {HAS_QUOTA.hex()} (mov w8, #1)")
    got_patched = md5(patched)

    ver = VERSIONS[key]
    if ver["patched_md5"] and got_patched != ver["patched_md5"]:
        print(f"error: patched md5 {got_patched} != expected {ver['patched_md5']}")
        return None
    if not ver["patched_md5"]:
        ver["patched_md5"] = got_patched
        print(
            "  new version entry (pin it in VERSIONS once verified on device):\n"
            f'    "{key}": {{\n'
            f'        "rom": "...",\n'
            f'        "stock_md5": "{got}",\n'
            f'        "patched_md5": "{got_patched}",\n'
            f'        "out": "{ver["out"]}",\n'
            f'        "sites": (0x{site_a:X}, 0x{site_b:X}),\n'
            f"    }},"
        )
    print(f"  patched md5 {got_patched} -> module/bin/{ver['out']}")

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    out_path = BIN_DIR / ver["out"]
    out_path.write_bytes(patched)
    out_path.chmod(0o755)
    return out_path


def write_manifest() -> Path:
    """Emit module/versions.conf: <stock_md5> <file in module/bin>, read at boot."""
    lines = [
        "# generated by tools/build.py - do not edit by hand",
        "# <stock mfp-daemon md5 on /odm> <patched binary in module/bin>",
    ]
    kept = 0
    for ver in VERSIONS.values():
        if (BIN_DIR / ver["out"]).is_file():
            lines.append(f"{ver['stock_md5']} {ver['out']}")
            kept += 1
    path = MODULE_DIR / "versions.conf"
    path.write_text("\n".join(lines) + "\n")
    print(f"wrote {path.relative_to(REPO)} ({kept} version(s))")
    return path


def build_zip(out: Path) -> None:
    if out.exists():
        out.unlink()
    # executable bits are explicit: Magisk/KSU run post-fs-data.sh and the HAL
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(MODULE_DIR.rglob("*")):
            if p.is_dir() or p.name == ".DS_Store":
                continue
            arcname = p.relative_to(MODULE_DIR).as_posix()
            zi = zipfile.ZipInfo.from_file(p, arcname)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = (0o755 if p.suffix == ".sh" or p.parent.name == "bin" else 0o644) << 16
            z.writestr(zi, p.read_bytes())
    print(f"built {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--stock",
        action="append",
        default=[],
        metavar="FILE",
        help="stock /odm/bin/hw/mfp-daemon to patch (repeatable)",
    )
    ap.add_argument(
        "--scan",
        action="store_true",
        help="for unknown ROMs, locate the patch sites by structural signature",
    )
    ap.add_argument("--out-zip", default=str(REPO / "fp_no_lockout_v1.2.zip"))
    args = ap.parse_args()

    if not args.stock:
        print("no --stock given: repacking zip from module/bin only")
    for s in args.stock:
        if cmd_patch(Path(s), args.scan) is None:
            sys.exit(1)

    missing = [v["out"] for v in VERSIONS.values() if not (BIN_DIR / v["out"]).is_file()]
    if missing:
        print(f"note: module/bin is missing {', '.join(missing)} (that ROM will be skipped at boot)")

    for out in sorted(BIN_DIR.iterdir()):
        if out.is_file():
            print(f"  {out.relative_to(REPO)}  {md5(out.read_bytes())}")

    write_manifest()
    build_zip(Path(args.out_zip))
    print("done")


if __name__ == "__main__":
    main()
