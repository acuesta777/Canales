#!/usr/bin/env python3
"""
Genera contact sheets 4x4 a partir de frames ya extraídos en una carpeta.
Uso: python3 contact_sheets_futbol.py <carpeta_frames> <carpeta_salida>
"""
import sys, pathlib
from PIL import Image, ImageDraw, ImageFont

COLS = 4
ROWS = 4
PER_PAGE = COLS * ROWS
THUMB_W = 320
THUMB_H = 180
PAD = 6
LABEL_H = 18
BG = (20, 20, 20)
TEXT_COLOR = (255, 220, 80)

frames_dir = pathlib.Path(sys.argv[1])
out_dir = pathlib.Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)

# Solo JPGs, ordenados numéricamente
jpgs = sorted([f for f in frames_dir.iterdir() if f.suffix.lower() == ".jpg"],
              key=lambda p: int(p.stem) if p.stem.isdigit() else 0)

print(f"Frames encontrados: {len(jpgs)}")

pages = [jpgs[i:i+PER_PAGE] for i in range(0, len(jpgs), PER_PAGE)]
page_w = COLS * (THUMB_W + PAD) + PAD
page_h = ROWS * (THUMB_H + LABEL_H + PAD) + PAD

try:
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
except:
    font = ImageFont.load_default()

for pi, page in enumerate(pages):
    img = Image.new("RGB", (page_w, page_h), BG)
    draw = ImageDraw.Draw(img)
    for i, jpg in enumerate(page):
        col = i % COLS
        row = i // COLS
        x = PAD + col * (THUMB_W + PAD)
        y = PAD + row * (THUMB_H + LABEL_H + PAD)
        try:
            thumb = Image.open(jpg).convert("RGB")
            thumb = thumb.resize((THUMB_W, THUMB_H), Image.LANCZOS)
            img.paste(thumb, (x, y))
        except:
            draw.rectangle([x, y, x+THUMB_W, y+THUMB_H], fill=(60, 0, 0))
        draw.text((x+2, y+THUMB_H+2), f"#{jpg.stem}", font=font, fill=TEXT_COLOR)
    out_path = out_dir / f"sheet_{pi+1:02d}.jpg"
    img.save(out_path, quality=88)
    print(f"  Sheet {pi+1}/{len(pages)}: {out_path.name}")

print(f"Listo — {len(pages)} sheets en {out_dir}")
