#!/usr/bin/env python3
"""Render a real run transcript into terminal-style PNG frames + an animated GIF.

Honesty contract (P-C showroom law): this script NEVER invents content. Every
pixel of text is a verbatim line from the input transcript. Frames are a
scrolling viewport over the real capture, exactly like asciinema. The raw
transcript is committed beside the frames so anyone can diff frame text vs source.

Usage:
  python render_frames.py <transcript.txt> <out_dir> <basename> [--lines N] [--step N] [--title STR]
"""
import argparse
import os
import textwrap

from PIL import Image, ImageDraw, ImageFont

BG = (13, 17, 23)
FG_DEFAULT = (201, 209, 217)
FG_GREEN = (63, 185, 80)
FG_CYAN = (121, 192, 255)
FG_YELLOW = (210, 153, 34)
FG_RED = (248, 81, 73)
FG_DIM = (110, 118, 129)
FONT_CANDIDATES = [
    "C:/Windows/Fonts/consola.ttf",
    "C:/Windows/Fonts/cour.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


def color_for(line: str):
    s = line.strip()
    if s.startswith("PASS") or s.startswith("  ok") or s.startswith("lifecycle_leg: PASS") or s.startswith("EXIT=0"):
        return FG_GREEN
    if s.startswith("STEP:") or s.startswith("##"):
        return FG_CYAN
    if s.startswith("COUNTERS") or s.startswith("POST-RECORDED"):
        return FG_YELLOW
    if s.startswith("FAIL") or " FAIL " in s or "Traceback" in s:
        return FG_RED
    return FG_DEFAULT


def chunked(seq, size, step):
    """Viewport slices: start at 0, step, until the final slice ends at len(seq)."""
    if len(seq) <= size:
        yield seq
        return
    i = 0
    while i + size < len(seq):
        yield seq[i:i + size]
        i += step
    yield seq[-size:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("out_dir")
    ap.add_argument("basename")
    ap.add_argument("--lines", type=int, default=22, help="viewport height in lines")
    ap.add_argument("--step", type=int, default=0, help="scroll step (0 = chunked, non-overlapping)")
    ap.add_argument("--cols", type=int, default=112)
    ap.add_argument("--title", default="", help="terminal title bar text")
    args = ap.parse_args()

    with open(args.transcript, "r", encoding="utf-8", newline="\n") as f:
        raw = f.read().replace("\r\n", "\n").replace("\r", "\n")
    src_lines = [ln for ln in raw.split("\n")]
    # word-wrap long lines so nothing is clipped (wrap is display-only; raw file is canonical)
    lines = []
    for ln in src_lines:
        if len(ln) <= args.cols:
            lines.append(ln)
        else:
            wrapped = textwrap.wrap(ln, width=args.cols, break_long_words=True, break_on_hyphens=False)
            lines.extend(wrapped[:1] + ["  " + w for w in wrapped[1:]])
    step = args.step if args.step > 0 else args.lines
    views = list(chunked(lines, args.lines, step))

    os.makedirs(args.out_dir, exist_ok=True)
    font_path = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
    if font_path is None:
        raise SystemExit("no monospace font found")
    fs, lh, pad = 20, 27, 28
    tw = fs * 0.55  # approx monospace advance at fs=20
    W = int(args.cols * tw) + 2 * pad
    H = lh * (args.lines + 1) + 2 * pad + lh  # +1 prompt line, +1 title bar
    font = ImageFont.truetype(font_path, fs)
    small = ImageFont.truetype(font_path, fs - 4)

    paths = []
    for idx, view in enumerate(views, start=1):
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        # title bar
        d.rectangle([0, 0, W, lh + 10], fill=(22, 27, 34))
        for c_i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
            d.ellipse([pad - 12 + c_i * 24, 8, pad + 2 + c_i * 24, 22], fill=c)
        title = args.title or os.path.basename(args.transcript)
        d.text((pad + 64, 6), f"{title}  —  frame {idx}/{len(views)}", font=small, fill=FG_DIM)
        # body
        y = lh + 14
        for ln in view:
            d.text((pad, y), ln, font=font, fill=color_for(ln))
            y += lh
        # prompt footer
        d.text((pad, y), "$", font=font, fill=FG_GREEN)
        p = os.path.join(args.out_dir, f"{args.basename}_{idx:02d}.png")
        img.save(p)
        paths.append(p)

    # animated GIF
    frames = [Image.open(p).convert("P", palette=Image.ADAPTIVE, colors=128) for p in paths]
    gif_path = os.path.join(args.out_dir, f"{args.basename}.gif")
    dur = 1600
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=dur, loop=0, disposal=2)
    print(f"frames={len(paths)} gif={gif_path}")
    for p in paths:
        print(p, os.path.getsize(p))
    print(gif_path, os.path.getsize(gif_path))


if __name__ == "__main__":
    main()
