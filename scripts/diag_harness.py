"""Binary-search the white-block cause across feature combinations.

For each combo: launch diag_whiteblock.py, wait for LOADED, raise the window,
capture the root screen, crop the top-left sidebar region, and report the
fraction of dark pixels. A white block => the region is uniformly white
(near-zero dark fraction); a healthy render has dark text/icons there.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path("/home/ruby/code/python/dsh_desktop")

# Ordered for binary search: baseline, single features, then the full app.
COMBOS: list[list[str]] = [
    [],  # baseline ~ smoke test (expected OK)
    ["dev2plain"],  # second hidden QWebEngineView, plain page
    ["devtools"],  # second hidden QWebEngineView with devToolsPage (full app)
    ["menu", "status", "page", "probe", "tray", "zoom", "devtools"],  # full app + devtools
]

DARK_THRESHOLD = 120  # a pixel is "dark" if min channel < this


def run_combo(features: list[str]) -> float | None:
    feat = ",".join(features) or "baseline"
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "diag_whiteblock.py"),
         "--features", ",".join(features)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(ROOT),
    )
    loaded = False
    deadline = time.time() + 90
    for line in proc.stdout:
        if time.time() > deadline:
            break
        if "LOADED" in line:
            loaded = True
            break
    if not loaded:
        proc.kill()
        return None
    time.sleep(2.0)  # let compositing settle

    out = subprocess.run(
        ["xdotool", "search", "--name", "DIAG WHITEBLOCK"],
        capture_output=True, text=True,
    ).stdout.split()
    if not out:
        proc.kill()
        return None
    wid = out[0]
    subprocess.run(["xdotool", "windowraise", wid], check=False)
    time.sleep(0.6)
    geom = subprocess.run(
        ["xdotool", "getwindowgeometry", "--shell", wid],
        capture_output=True, text=True,
    ).stdout
    g = dict(l.split("=") for l in geom.strip().splitlines())
    wx, wy = int(g["X"]), int(g["Y"])

    cap = ROOT / "diag_cap.png"
    subprocess.run(["import", "-window", "root", str(cap)], check=True)
    img = Image.open(cap)

    # Top-left sidebar region, robust to menu-bar presence (offset 40px down).
    x0, y0 = wx + 10, wy + 40
    x1, y1 = wx + 260, wy + 340
    region = img.crop((x0, y0, x1, y1))
    region.save(ROOT / f"diag_region_{feat}.png")
    px = list(region.getdata())
    dark = sum(1 for r, gg, b in px if min(r, gg, b) < DARK_THRESHOLD)
    frac = dark / len(px)
    proc.kill()
    return frac


def main() -> None:
    results = []
    for features in COMBOS:
        label = ",".join(features) or "baseline"
        print(f"\n=== {label} ===", flush=True)
        frac = run_combo(features)
        if frac is None:
            print("  FAILED to load", flush=True)
            results.append((label, None))
            continue
        verdict = "WHITE BLOCK" if frac < 0.005 else "OK"
        print(f"  dark fraction={frac:.4f} -> {verdict}", flush=True)
        results.append((label, frac))

    print("\n\n===== SUMMARY =====", flush=True)
    for label, frac in results:
        if frac is None:
            print(f"  {label:45s} FAILED")
        else:
            verdict = "WHITE BLOCK" if frac < 0.005 else "OK"
            print(f"  {label:45s} {frac:.4f}  {verdict}")


if __name__ == "__main__":
    main()
