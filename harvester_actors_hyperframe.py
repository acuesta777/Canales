#!/usr/bin/env python3
"""
harvester_actors_hyperframe.py — Genera clips HyperFrame para actores detectados en el timeline.

Usa la misma lógica visual de EpocaDeOro (_render_photo_card):
  - Fondo negro con cuadrícula animada
  - Foto en B&N con borde blanco que entra deslizándose
  - Badge dorado con nombre del actor

Para cada segmento source=hyperframe en timeline.json:
  1. Busca foto del actor en Brave Image Search
  2. Descarga la mejor foto disponible
  3. Genera clip HyperFrame (PIL frame-a-frame igual que EpocaDeOro)
  4. Guarda como 03-imagenes/flow_XXXX_zp.mp4

Uso:
  python3 harvester_actors_hyperframe.py series/embrujadas_demo/
"""

import sys, json, pathlib, subprocess, urllib.request, urllib.parse, shutil, tempfile

BASE_DIR  = pathlib.Path(__file__).parent
KEY_FILE  = pathlib.Path.home() / ".brave_key"
FFMPEG    = "/opt/homebrew/bin/ffmpeg"

W, H, FPS = 1920, 1080, 30

BLOCKED_DOMAINS = [
    "alamy", "gettyimages", "shutterstock", "istockphoto", "dreamstime",
    "123rf", "depositphotos", "vectorstock", "freepik", "pngtree",
]
NEGATIVE_WORDS = ["cartoon", "illustration", "vector", "icon", "logo",
                  "clipart", "meme", "drawing", "wallpaper", "png"]

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"


def brave_search(query: str, key: str, count: int = 15) -> list:
    url = ("https://api.search.brave.com/res/v1/images/search?"
           + urllib.parse.urlencode({"q": query, "count": count, "safesearch": "off"}))
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": key,
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            import gzip as _gz
            raw = r.read()
            if r.info().get("Content-Encoding") == "gzip":
                raw = _gz.decompress(raw)
            data = json.loads(raw)
    except Exception as e:
        print(f"  ⚠ Brave error: {e}")
        return []

    results = []
    for item in data.get("results", []):
        url_img = item.get("properties", {}).get("url", "")
        title   = item.get("title", "").lower()
        if not url_img:
            continue
        if any(d in url_img for d in BLOCKED_DOMAINS):
            continue
        if any(w in title for w in NEGATIVE_WORDS):
            continue
        results.append({"url": url_img, "source": item.get("url", "")})
    return results


def download_photo(url: str, dest: pathlib.Path) -> bool:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        if len(data) < 5000:
            return False
        dest.write_bytes(data)
        return True
    except Exception:
        return False


def render_photo_card(photo_path: pathlib.Path, actor_name: str,
                      out_mp4: pathlib.Path, dur: float = 5.0,
                      slide_from: str = "right") -> bool:
    """
    Genera un clip HyperFrames-style idéntico al de EpocaDeOro:
      - Fondo negro + cuadrícula animada
      - Foto en B&N con borde blanco, entra deslizándose desde slide_from
      - Badge dorado con nombre del actor (sube desde abajo)
    """
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance

    GOLD     = (201, 162, 39)
    GRID_STEP = 60
    BORDER_W  = 10
    SLIDE_IN_DUR = 0.55
    MAX_W_F, MAX_H_F = 1382, 842

    try:
        font_name = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Black.ttf", 46)
    except Exception:
        font_name = ImageFont.load_default()

    # Cargar foto y convertir a B&N — siempre escalar para llenar el área objetivo
    try:
        photo = Image.open(str(photo_path)).convert("RGB")
        # Escalar SIEMPRE (arriba o abajo) para que el lado más largo llene el área
        ratio = min(MAX_W_F / photo.width, MAX_H_F / photo.height)
        nw, nh = max(1, int(photo.width * ratio)), max(1, int(photo.height * ratio))
        photo = photo.resize((nw, nh), Image.LANCZOS)
        photo = ImageEnhance.Contrast(photo.convert("L").convert("RGB")).enhance(1.1)
    except Exception as e:
        print(f"  {ROJO}✗ No se pudo abrir foto: {e}{RESET}")
        return False

    def ease_out(t): return 1 - (1 - t) ** 3

    frames_dir = out_mp4.parent / f"_hf_frames_{out_mp4.stem}"
    frames_dir.mkdir(parents=True, exist_ok=True)

    TOTAL_FRAMES = int(dur * FPS)
    badge_text   = actor_name.upper()

    for fi in range(TOTAL_FRAMES):
        t = fi / FPS

        img  = Image.new("RGB", (W, H), (13, 13, 13))
        draw = ImageDraw.Draw(img)

        # Cuadrícula animada (drift continuo)
        drift_x = int(-40 * (t / dur))
        drift_y = int(-28 * (t / dur))
        for gx in range(-GRID_STEP + (drift_x % GRID_STEP), W + GRID_STEP, GRID_STEP):
            draw.line([(gx, 0), (gx, H)], fill=(30, 30, 30))
        for gy in range(-GRID_STEP + (drift_y % GRID_STEP), H + GRID_STEP, GRID_STEP):
            draw.line([(0, gy), (W, gy)], fill=(30, 30, 30))

        # Foto con slide-in
        pw, ph = photo.size
        px_final = (W - pw) // 2
        py = (H - ph) // 2

        if t < SLIDE_IN_DUR:
            progress = ease_out(t / SLIDE_IN_DUR)
            if slide_from == "right":
                px = px_final + int((1.0 - progress) * (W - px_final + pw // 2))
                px = min(px, W + pw)
            else:
                px = px_final - int((1.0 - progress) * (px_final + pw // 2 + W // 4))
                px = max(px, -pw)
        else:
            pan = int(ease_out(min(1.0, (t - SLIDE_IN_DUR) / (dur - SLIDE_IN_DUR))) * 8)
            px  = px_final + (pan if slide_from == "right" else -pan)

        # Borde blanco
        draw.rectangle([px - BORDER_W, py - BORDER_W,
                         px + pw + BORDER_W, py + ph + BORDER_W],
                        fill=(220, 220, 220))
        # Pegar foto (clip a canvas)
        if px < W and px + pw > 0:
            src_x  = max(0, -px)
            dst_x  = max(0, px)
            paste_w = min(pw - src_x, W - dst_x)
            if paste_w > 0:
                crop = photo.crop((src_x, 0, src_x + paste_w, ph))
                img.paste(crop, (dst_x, py))

        # Badge dorado — aparece después del slide-in, justo debajo de la foto
        if t > SLIDE_IN_DUR:
            badge_prog = ease_out(min(1.0, (t - SLIDE_IN_DUR) / 0.4))
            bb = draw.textbbox((0, 0), badge_text, font=font_name)
            bw = (bb[2] - bb[0]) + 80
            bh = 54
            # Siempre debajo del borde inferior de la foto + margen
            by_final = min(py + ph + BORDER_W + 20, H - bh - 20)
            by  = int(by_final + (1.0 - badge_prog) * 60)
            bx  = W // 2 - bw // 2

            draw.rectangle([bx, by, bx + bw, by + bh], fill=(*GOLD,))
            draw.rectangle([bx, by - 4, bx + bw, by - 2], fill=(*GOLD,))
            draw.text((bx + 40, by + 10), badge_text, font=font_name, fill=(255, 255, 255))

        img.save(str(frames_dir / f"f{fi:05d}.jpg"), quality=90)

    # Encodear frames a mp4
    result = subprocess.run([
        FFMPEG, "-y", "-framerate", str(FPS),
        "-i", str(frames_dir / "f%05d.jpg"),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-an", str(out_mp4), "-loglevel", "error"
    ], capture_output=True, text=True)

    shutil.rmtree(frames_dir, ignore_errors=True)

    if result.returncode != 0:
        print(f"  {ROJO}✗ ffmpeg falló: {result.stderr[:200]}{RESET}")
        return False
    return True


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 harvester_actors_hyperframe.py <carpeta>")
        sys.exit(1)

    carpeta  = BASE_DIR / sys.argv[1]
    tl_path  = carpeta / "05-montaje" / "timeline.json"
    imgs_dir = carpeta / "03-imagenes"
    imgs_dir.mkdir(parents=True, exist_ok=True)

    if not tl_path.exists():
        print(f"ERROR: No existe {tl_path}"); sys.exit(1)

    if not KEY_FILE.exists():
        print(f"ERROR: Sin Brave API key en {KEY_FILE}"); sys.exit(1)
    brave_key = KEY_FILE.read_text().strip()

    tl      = json.loads(tl_path.read_text(encoding="utf-8"))
    hf_segs = [s for s in tl.get("visual_timeline", []) if s.get("source") == "hyperframe"]

    if not hf_segs:
        print("Sin segmentos HyperFrame en el timeline.")
        return

    print(f"\n{'═'*60}")
    print(f"  HARVESTER ACTORS HYPERFRAME — {carpeta.name}")
    print(f"  {len(hf_segs)} actor(es) detectados")
    print(f"{'═'*60}\n")

    ok = 0
    for idx, seg in enumerate(hf_segs):
        actor_name = seg.get("actor_name", "Actor")
        seg_id     = seg.get("segment_id", idx)
        duration   = float(seg.get("duration", 5))
        slide_from = "right" if idx % 2 == 0 else "left"

        # segment_id puede ser string "flow_0006" o int
        if isinstance(seg_id, str) and seg_id.startswith("flow_"):
            num_str = seg_id.replace("flow_", "")
            out_name = f"flow_{num_str}_zp.mp4"
        else:
            out_name = f"flow_{int(seg_id):04d}_zp.mp4"

        out_mp4 = imgs_dir / out_name

        if out_mp4.exists():
            print(f"  ✓ {actor_name} → ya existe {out_name}")
            ok += 1
            continue

        print(f"  [{seg_id}] {actor_name} (slide {slide_from}, {duration}s)...")

        # 1. Buscar foto en Brave
        query   = seg.get("actor_search_query", f"{actor_name} foto")
        results = brave_search(query, brave_key)
        if not results:
            print(f"  {AMARILLO}⚠ Sin resultados Brave para: {query}{RESET}")
            continue

        # 2. Descargar mejor foto
        photo_path = None
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            for i, r in enumerate(results[:6]):
                ext  = pathlib.Path(urllib.parse.urlparse(r["url"]).path).suffix or ".jpg"
                dest = tmp_path / f"foto_{i:02d}{ext}"
                if download_photo(r["url"], dest):
                    print(f"     → foto: {r['url'][:70]}...")
                    saved = imgs_dir / f"_hf_foto_{out_name.replace('_zp.mp4','')}{ext}"
                    dest.rename(saved)
                    photo_path = saved
                    break

        if not photo_path or not photo_path.exists():
            print(f"  {ROJO}✗ No se pudo descargar foto para {actor_name}{RESET}")
            continue

        # 3. Generar HyperFrame (mismo estilo EpocaDeOro)
        print(f"     → renderizando HyperFrame...")
        if render_photo_card(photo_path, actor_name, out_mp4, duration, slide_from):
            print(f"  {VERDE}✓ {actor_name} → {out_name}{RESET}")
            ok += 1
        else:
            print(f"  {ROJO}✗ Falló render para {actor_name}{RESET}")

    print(f"\n  ✓ {ok}/{len(hf_segs)} HyperFrames generados → {imgs_dir}")


if __name__ == "__main__":
    main()
