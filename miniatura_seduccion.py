#!/usr/bin/env python3
"""
miniatura_seduccion.py — Genera 3 miniaturas estilo ThatGuy con Python puro
Stick figures dibujados con Pillow, fondo negro, texto grande arriba.

Uso:
  python3 miniatura_seduccion.py seduccion/7_errores/
"""

import sys, math, pathlib
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1280, 720

FONTS = [
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Arial.ttf",
]

def get_font(size):
    for f in FONTS:
        if pathlib.Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()

# ── Motor neon con Gaussian blur ─────────────────────────────────────────────

class NeonCanvas:
    """Dibuja en capas separadas y combina con glow gaussiano."""
    def __init__(self, size):
        self.size  = size
        self.base  = Image.new("RGB", size, (0, 0, 0))
        self.glow  = Image.new("RGB", size, (0, 0, 0))
        self.sharp = Image.new("RGB", size, (0, 0, 0))
        self.dg = ImageDraw.Draw(self.glow)
        self.ds = ImageDraw.Draw(self.sharp)

    def line(self, p1, p2, color, width=8):
        self.dg.line([p1, p2], fill=color, width=width + 14)
        self.ds.line([p1, p2], fill=color, width=width)

    def circle(self, center, radius, color, width=8):
        cx, cy = center
        self.dg.ellipse([cx-radius, cy-radius, cx+radius, cy+radius],
                        outline=color, width=width + 14)
        self.ds.ellipse([cx-radius, cy-radius, cx+radius, cy+radius],
                        outline=color, width=width)

    def dot(self, center, radius, color):
        cx, cy = center
        self.dg.ellipse([cx-radius, cy-radius, cx+radius, cy+radius], fill=color)
        self.ds.ellipse([cx-radius, cy-radius, cx+radius, cy+radius], fill=color)

    def arc(self, bbox, start, end, color, width=5):
        self.dg.arc(bbox, start, end, fill=color, width=width + 10)
        self.ds.arc(bbox, start, end, fill=color, width=width)

    def ellipse_outline(self, bbox, color, width=5):
        self.dg.ellipse(bbox, outline=color, width=width + 10)
        self.ds.ellipse(bbox, outline=color, width=width)

    def x_mark(self, cx, cy, size, color, width=5):
        self.line((cx-size, cy-size), (cx+size, cy+size), color, width)
        self.line((cx+size, cy-size), (cx-size, cy+size), color, width)

    def heart(self, cx, cy, size, color):
        s = size
        for d in [self.dg, self.ds]:
            d.ellipse([cx-s, cy-s//2, cx, cy+s//2], fill=color)
            d.ellipse([cx, cy-s//2, cx+s, cy+s//2], fill=color)
            d.polygon([(cx-s, cy+s//4), (cx+s, cy+s//4), (cx, cy+s+s//2)], fill=color)

    def arrow(self, p1, p2, color, width=6):
        self.line(p1, p2, color, width)
        dx, dy = p2[0]-p1[0], p2[1]-p1[1]
        angle  = math.atan2(dy, dx)
        size   = 28
        for a in [angle + 2.5, angle - 2.5]:
            px = int(p2[0] - size * math.cos(a))
            py = int(p2[1] - size * math.sin(a))
            self.line(p2, (px, py), color, width)

    def compose(self):
        blurred = self.glow.filter(ImageFilter.GaussianBlur(radius=14))
        out = Image.composite(blurred, self.base,
                              blurred.convert("L"))
        out = Image.composite(self.sharp, out,
                              self.sharp.convert("L"))
        return out


def stick_figure(canvas, cx, cy, scale=1.0, color=(255,255,255),
                 pose="normal", line_w=7):
    s   = scale
    R   = int(38 * s)
    lw  = max(4, int(line_w * s))

    head_y   = cy - int(155 * s)
    neck_y   = head_y + R
    shoulder = neck_y + int(22 * s)
    hip_y    = shoulder + int(105 * s)
    knee_y   = hip_y + int(90 * s)
    foot_y   = knee_y + int(80 * s)

    # Cabeza
    canvas.circle((cx, head_y), R, color, lw)

    # Ojos (puntos azules como en la referencia)
    ey = head_y - int(10 * s)
    ex = int(13 * s)
    er = max(4, int(7 * s))
    canvas.dot((cx - ex, ey), er, (100, 180, 255))
    canvas.dot((cx + ex, ey), er, (100, 180, 255))

    # Cuerpo
    canvas.line((cx, neck_y), (cx, hip_y), color, lw)

    if pose == "normal":
        canvas.arc([cx-int(13*s), head_y+int(6*s), cx+int(13*s), head_y+int(20*s)],
                   0, 180, color, max(2, int(3*s)))
        canvas.line((cx, shoulder), (cx-int(60*s), shoulder+int(55*s)), color, lw)
        canvas.line((cx, shoulder), (cx+int(60*s), shoulder+int(55*s)), color, lw)
        canvas.line((cx, hip_y), (cx-int(40*s), knee_y), color, lw)
        canvas.line((cx-int(40*s), knee_y), (cx-int(45*s), foot_y), color, lw)
        canvas.line((cx, hip_y), (cx+int(40*s), knee_y), color, lw)
        canvas.line((cx+int(40*s), knee_y), (cx+int(45*s), foot_y), color, lw)

    elif pose == "confident":
        canvas.arc([cx-int(15*s), head_y+int(6*s), cx+int(15*s), head_y+int(22*s)],
                   0, 180, color, max(2, int(3*s)))
        canvas.line((cx, shoulder), (cx-int(55*s), shoulder+int(40*s)), color, lw)
        canvas.line((cx-int(55*s), shoulder+int(40*s)), (cx-int(40*s), hip_y-int(12*s)), color, lw)
        canvas.line((cx, shoulder), (cx+int(55*s), shoulder+int(40*s)), color, lw)
        canvas.line((cx+int(55*s), shoulder+int(40*s)), (cx+int(40*s), hip_y-int(12*s)), color, lw)
        canvas.line((cx, hip_y), (cx-int(50*s), knee_y), color, lw)
        canvas.line((cx-int(50*s), knee_y), (cx-int(55*s), foot_y), color, lw)
        canvas.line((cx, hip_y), (cx+int(50*s), knee_y), color, lw)
        canvas.line((cx+int(50*s), knee_y), (cx+int(55*s), foot_y), color, lw)

    elif pose == "walking_away":
        canvas.arc([cx-int(13*s), head_y+int(6*s), cx+int(13*s), head_y+int(20*s)],
                   0, 180, color, max(2, int(3*s)))
        canvas.line((cx, shoulder), (cx-int(65*s), shoulder+int(45*s)), color, lw)
        canvas.line((cx, shoulder), (cx+int(45*s), shoulder+int(65*s)), color, lw)
        canvas.line((cx, hip_y), (cx-int(45*s), knee_y), color, lw)
        canvas.line((cx-int(45*s), knee_y), (cx-int(55*s), foot_y), color, lw)
        canvas.line((cx, hip_y), (cx+int(55*s), knee_y-int(18*s)), color, lw)
        canvas.line((cx+int(55*s), knee_y-int(18*s)), (cx+int(65*s), foot_y-int(12*s)), color, lw)

    elif pose == "shocked":
        canvas.ellipse_outline(
            [cx-int(11*s), head_y+int(7*s), cx+int(11*s), head_y+int(23*s)],
            color, max(2, int(3*s)))
        canvas.line((cx, shoulder), (cx-int(75*s), shoulder-int(60*s)), color, lw)
        canvas.line((cx, shoulder), (cx+int(75*s), shoulder-int(60*s)), color, lw)
        canvas.line((cx, hip_y), (cx-int(40*s), knee_y), color, lw)
        canvas.line((cx-int(40*s), knee_y), (cx-int(44*s), foot_y), color, lw)
        canvas.line((cx, hip_y), (cx+int(40*s), knee_y), color, lw)
        canvas.line((cx+int(40*s), knee_y), (cx+int(44*s), foot_y), color, lw)

    elif pose == "sad":
        canvas.arc([cx-int(13*s), head_y+int(12*s), cx+int(13*s), head_y+int(25*s)],
                   180, 360, color, max(2, int(3*s)))
        canvas.line((cx, shoulder), (cx-int(45*s), shoulder+int(70*s)), color, lw)
        canvas.line((cx, shoulder), (cx+int(45*s), shoulder+int(70*s)), color, lw)
        canvas.line((cx, hip_y), (cx-int(22*s), knee_y), color, lw)
        canvas.line((cx-int(22*s), knee_y), (cx-int(25*s), foot_y), color, lw)
        canvas.line((cx, hip_y), (cx+int(22*s), knee_y), color, lw)
        canvas.line((cx+int(22*s), knee_y), (cx+int(25*s), foot_y), color, lw)

# ── Texto ─────────────────────────────────────────────────────────────────────

def draw_text_border(draw, xy, text, font, fill, border_color=(0,0,0), bw=7):
    x, y = xy
    for dx in range(-bw, bw+1, 2):
        for dy in range(-bw, bw+1, 2):
            if dx != 0 or dy != 0:
                draw.text((x+dx, y+dy), text, font=font, fill=border_color, anchor="mm")
    draw.text((x, y), text, font=font, fill=fill, anchor="mm")

def add_text_top(img, lineas):
    """
    lineas: [(texto, color, tamaño_fuente), ...]
    Texto apilado desde arriba con padding, NO superpone a los stick figures.
    """
    draw = ImageDraw.Draw(img)
    y = 30
    for text, color, fsize in lineas:
        font = get_font(fsize)
        bbox = draw.textbbox((0, 0), text, font=font, anchor="lt")
        th = bbox[3] - bbox[1]
        y_center = y + th // 2
        draw_text_border(draw, (W // 2, y_center), text, font, fill=color)
        y += th + 8
    return img, y  # retorna hasta dónde llegó el texto

# ── 3 versiones ──────────────────────────────────────────────────────────────

def version1(path):
    """Hombre confiado (rojo) + mujer alejándose (cian) — neon glow."""
    nc = NeonCanvas((W, H))
    cy = H // 2 + 80

    stick_figure(nc, W//2 - 260, cy, scale=2.0,
                 color=(255, 55, 55), pose="confident", line_w=8)
    stick_figure(nc, W//2 + 230, cy, scale=1.8,
                 color=(0, 220, 255), pose="walking_away", line_w=7)

    nc.arrow((W//2 - 90, cy - 100), (W//2 + 70, cy - 100), (255, 55, 55), 7)
    nc.x_mark(W//2 - 200, cy - 200, 26, (255, 55, 55), 6)

    nc.compose().save(path, "JPEG", quality=95)

def version2(path):
    """Split: triste (gris) vs confiado (verde) — neon glow."""
    nc = NeonCanvas((W, H))
    cy = H // 2 + 80

    # Línea divisoria
    nc.line((W//2, 10), (W//2, H - 10), (70, 70, 70), 3)

    stick_figure(nc, W//4, cy, scale=1.9,
                 color=(160, 160, 160), pose="sad", line_w=7)
    for ox, oy in [(-110, -150), (100, -130), (0, -200)]:
        nc.x_mark(W//4 + ox, cy + oy, 22, (255, 50, 50), 6)

    stick_figure(nc, 3*W//4, cy, scale=2.0,
                 color=(0, 255, 90), pose="confident", line_w=8)
    for ox, oy in [(-90, -160), (95, -140), (0, -210)]:
        nc.heart(3*W//4 + ox, cy + oy, 22, (255, 70, 70))

    nc.compose().save(path, "JPEG", quality=95)

def version3(path):
    """Hombre sorprendido (amarillo) + mujer indiferente (cian) — neon glow."""
    nc = NeonCanvas((W, H))
    cy = H // 2 + 80

    stick_figure(nc, W//2 - 150, cy, scale=2.1,
                 color=(255, 215, 0), pose="shocked", line_w=9)
    stick_figure(nc, W//2 + 290, cy, scale=1.7,
                 color=(0, 210, 255), pose="walking_away", line_w=7)

    for ox, oy in [(-180, -170), (100, -190), (-90, -240), (80, -110)]:
        nc.x_mark(W//2 - 150 + ox, cy + oy, 24, (255, 50, 50), 6)

    nc.arrow((W//2 + 60, cy - 260), (W//2 - 50, cy - 210), (255, 50, 50), 7)

    nc.compose().save(path, "JPEG", quality=95)

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 miniatura_seduccion.py seduccion/7_errores/")
        sys.exit(1)

    carpeta = pathlib.Path(sys.argv[1]).expanduser()
    if not carpeta.exists():
        print(f"✗ No existe: {carpeta}")
        sys.exit(1)

    versiones = [
        ("miniatura_v1_deja_errores.jpg", version1),
        ("miniatura_v2_cual_eres.jpg",    version2),
        ("miniatura_v3_nunca_notaste.jpg", version3),
    ]

    print(f"\n  Generando 3 miniaturas (Python puro) para: {carpeta.name}\n")
    for nombre, fn in versiones:
        out = carpeta / nombre
        fn(out)
        print(f"  ✓  {nombre}")

    print(f"\n  Listas en: {carpeta}/\n")

if __name__ == "__main__":
    main()
