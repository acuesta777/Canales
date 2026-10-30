#!/usr/bin/env python3
"""
miniatura.py — Genera 3 versiones de miniatura con Wan 2.6 Image Edit + Pillow

Uso:
    python3 miniatura.py <carpeta_personaje> [opciones]

    --edad   : edad del personaje (ej: 58)
    --cifra  : cifra para el badge dorado (ej: "100 MILLONES")
    --mujer  : usa "The woman in the reference image" (default: "The man")
    --solo 1 : genera solo la versión 1, 2 o 3
    --extra "escena de rancho lujoso"  : agrega escenas extra al pool (se puede repetir)

Referencia: referencias/<personaje>.jpg  (requerida)
Salida    : <carpeta>/miniatura_1.jpg  miniatura_2.jpg  miniatura_3.jpg  (1280×720)

Costo: ~$0.135 (3 imágenes Wan 2.6 × $0.045 c/u)
"""

import sys, os, json, time, base64, random, urllib.request, urllib.error
import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

API_BASE       = "https://api.muapi.ai/api/v1"
KEY_FILE       = Path.home() / ".muapi_key"
IMGBB_KEY_FILE = Path.home() / ".imgbb_key"
CANALES        = Path(__file__).parent
REFS_DIR       = CANALES / "_referencias"
ESCENAS_FILE   = CANALES / "escenas_usadas.json"   # historial anti-repetición

W, H = 1280, 720
IMPACT     = "/System/Library/Fonts/Supplemental/Impact.ttf"
ARIAL_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

R = "\033[91m"; G = "\033[92m"; Y = "\033[93m"; B = "\033[94m"; E = "\033[0m"


# ── pool de 15 escenas de lujo rotativas ─────────────────────────────────────

ESCENAS_LUJO = [
    # Yates y mar
    "on the exterior deck of a superyacht at sunset over the Mediterranean sea, golden light",
    "in the golden dining room of a luxury yacht interior with ocean views through the windows",
    "at the bow of a mega yacht sailing on turquoise Caribbean waters, perfect weather",
    "on a luxury catamaran deck with tropical islands in the background, clear sky",
    "on the upper deck of a superyacht anchored in Monaco harbor with yachts everywhere",
    # Mansiones y propiedades
    "in a mansion living room with panoramic floor-to-ceiling windows overlooking a city at night",
    "in the garden of a luxury mansion beside an infinity pool with mountain views, warm afternoon light",
    "standing at the entrance of a luxury mansion with a Ferrari and Rolls Royce in the driveway",
    "in a Versailles-style gold mansion living room with ornate chandeliers and gilded furniture",
    "beside a private mansion pool surrounded by tropical palm trees and lush gardens",
    "in a mansion breakfast room with panoramic ocean views at sunrise, golden hour light",
    "on the terrace of a clifftop villa overlooking the ocean, dramatic sea view",
    "standing in the grand marble foyer of a luxury mansion with a sweeping staircase",
    "in a modern luxury mansion bedroom with floor-to-ceiling windows overlooking the ocean at dawn",
    "in the rooftop garden of a luxury penthouse with city panorama at golden hour",
    "in a white-walled Mediterranean villa courtyard with fountain and orange trees, afternoon sun",
    "standing beside an outdoor fireplace at a luxury estate at dusk, warm amber glow",
    "in a glass-walled modern mansion living room with infinity pool and jungle view",
    "in a palatial master bedroom with golden accents, massive chandelier and ocean view",
    "on the balcony of a luxury cliffside villa in Positano Italy overlooking the Amalfi coast",
    # Aviones y helicópteros
    "inside a private jet, white leather seats, champagne on the table, smiling confidently",
    "on a private helipad with a luxury helicopter in the background, clear blue sky",
    "boarding a private Gulfstream jet on a sunny tarmac, flight attendant visible",
    "inside a luxurious private jet cabin with cream leather and panoramic oval windows at cruise altitude",
    # Penthouses y hoteles
    "on a penthouse terrace overlooking a glittering city skyline at dusk",
    "in a luxury hotel penthouse suite with floor-to-ceiling Paris cityscape views at night",
    "at a five-star hotel rooftop infinity pool overlooking Dubai skyline at golden hour",
    "in the lobby of an ultra-luxury hotel with marble floors, orchids and grand piano",
    "on the balcony of a Bali overwater bungalow with turquoise lagoon at sunrise",
    # Interiores exclusivos
    "in a private luxury library with dark wood shelves and leather armchairs, warm lighting",
    "in a private home cinema with plush velvet seats and golden accents",
    "in an illuminated luxury wine cellar with thousands of bottles and stone arches",
    "in a private art gallery with museum-quality paintings and perfect lighting",
    "in a luxury walk-in closet with designer bags and shoes lit like a boutique",
    "in an exclusive private members club lounge with dark leather and cigar bar aesthetic",
    "in a luxury spa with marble walls, rose petals and candles, serene atmosphere",
    # Autos y garajes
    "in a luxury showroom garage with a Lamborghini, Ferrari and Rolls-Royce lined up",
    "leaning against a Rolls-Royce Phantom in front of a luxury mansion entrance",
    "seated in the rear of a chauffeured Bentley Mulsanne, city lights outside",
    # Naturaleza y destinos de lujo
    "on a private beach in the Maldives with overwater bungalows visible, crystal clear water",
    "at a luxury safari lodge terrace overlooking the African savanna at sunset",
    "on a snowy Swiss Alps terrace at a luxury chalet, mountains and pine trees",
    "in a lush tropical garden of a private villa in Tuscany, rolling hills beyond",
]

TEXTOS_PRINCIPALES = [
    lambda p, e: f"ASÍ VIVE A SUS {e} AÑOS" if e else "ASÍ VIVE EN EL LUJO",
    lambda p, e: f"LA VERDADERA FORTUNA DE {p}",
    lambda p, e: "ASÍ GASTÓ SUS MILLONES",
    lambda p, e: f"EL LUJOSO ESTILO DE VIDA DE {p}",
    lambda p, e: "LA VIDA QUE POCOS CONOCEN",
    lambda p, e: f"ASÍ ES LA MANSIÓN DE {p}",
]

# Textos sin nombre de artista (para --sin-etiqueta)
TEXTOS_SIN_NOMBRE = [
    lambda p, e: "ASÍ GASTÓ SUS MILLONES",
    lambda p, e: "LA VIDA QUE POCOS CONOCEN",
    lambda p, e: f"ASÍ VIVE A SUS {e} AÑOS" if e else "ASÍ VIVE EN EL LUJO",
    lambda p, e: "ASÍ ES SU VIDA DE LUJO",
    lambda p, e: "LO QUE NADIE TE CONTÓ",
    lambda p, e: "MILLONES Y SECRETOS",
]


def pick_escenas(n: int, extras: list[str]) -> list[str]:
    """Elige n escenas distintas del pool evitando las usadas recientemente."""
    pool = ESCENAS_LUJO + extras

    # Cargar historial
    historial = []
    if ESCENAS_FILE.exists():
        try:
            historial = json.loads(ESCENAS_FILE.read_text())
        except Exception:
            historial = []

    # Filtrar las usadas en los últimos 3 videos (últimas n*3)
    ultimas = set(historial[-(n * 3):]) if historial else set()
    disponibles = [e for e in pool if e not in ultimas]
    if len(disponibles) < n:
        disponibles = pool  # reset si el pool es muy pequeño

    elegidas = random.sample(disponibles, min(n, len(disponibles)))

    # Guardar historial (máx 30 entradas)
    historial = (historial + elegidas)[-30:]
    ESCENAS_FILE.write_text(json.dumps(historial, ensure_ascii=False, indent=2))

    return elegidas


def build_versions(personaje_upper: str, edad: str, cifra: str, genero: str, extras: list[str],
                   sin_etiqueta: bool = False, forzar_escenas: list[str] = None,
                   forzar_textos: list[str] = None) -> list[dict]:
    sujeto   = f"The {genero} in the reference image, face prominently visible and close"
    # Si hay exactamente 3 extras y forzar_escenas, usarlos en orden
    if forzar_escenas and len(forzar_escenas) >= 3:
        escenas = forzar_escenas[:3]
    elif extras and len(extras) == 3:
        escenas = extras
    else:
        escenas  = pick_escenas(3, extras)
    pool_textos = TEXTOS_SIN_NOMBRE if sin_etiqueta else TEXTOS_PRINCIPALES
    if forzar_textos and len(forzar_textos) >= 3:
        textos_raw = forzar_textos[:3]
        textos = [lambda p, e, t=t: t for t in textos_raw]
    else:
        textos   = random.sample(pool_textos, 3)
    badge_v  = cifra if cifra else (f"{edad} AÑOS" if edad else "LUJO TOTAL")
    etiqueta = "" if sin_etiqueta else personaje_upper

    versiones = []
    for escena, texto_fn in zip(escenas, textos):
        versiones.append({
            "prompt":   f"{sujeto}, {escena}, cinematic, photorealistic, no text, no watermark",
            "texto":    texto_fn(personaje_upper, edad),
            "badge":    badge_v,
            "etiqueta": etiqueta,
        })
    return versiones


# ── API Muapi ────────────────────────────────────────────────────────────────

def get_api_key():
    if not KEY_FILE.exists():
        sys.exit(f"{R}ERROR: No encontré clave Muapi en {KEY_FILE}{E}")
    return KEY_FILE.read_text().strip()


def api_post(endpoint, data, api_key):
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{API_BASE}{endpoint}",
        data=body,
        headers={"Content-Type": "application/json", "x-api-key": api_key},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def api_get(url, api_key):
    req = urllib.request.Request(url, headers={"x-api-key": api_key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def poll_task(task_id, api_key, timeout=180):
    start = time.time()
    poll_url = f"{API_BASE}/predictions/{task_id}/result"
    while True:
        elapsed = int(time.time() - start)
        if elapsed >= timeout:
            raise TimeoutError(f"Timeout {timeout}s")
        time.sleep(8)
        try:
            r = api_get(poll_url, api_key)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(10); continue
            print(f"  poll HTTP {e.code} [{elapsed}s]", end="\r", flush=True)
            continue
        except Exception as e:
            print(f"  poll error: {e} [{elapsed}s]", end="\r", flush=True)
            continue
        data   = r.get("data", r)
        status = data.get("status", "")
        elapsed = int(time.time() - start)
        print(f"  status={status} [{elapsed}s]        ", end="\r", flush=True)
        if status == "completed":
            print()
            outputs = data.get("outputs", [])
            if outputs:
                return outputs[0]
            raise RuntimeError("Sin outputs")
        if status == "failed":
            print()
            raise RuntimeError(data.get("error", "failed"))


def upload_imgbb(path: Path) -> str:
    """Sube imagen a imgbb.com y retorna URL permanente."""
    if not IMGBB_KEY_FILE.exists():
        sys.exit(f"{R}ERROR: No encontré clave imgBB en {IMGBB_KEY_FILE}{E}")
    key = IMGBB_KEY_FILE.read_text().strip()
    b64 = base64.b64encode(path.read_bytes()).decode()
    import urllib.parse
    data = urllib.parse.urlencode({"key": key, "image": b64, "name": path.stem}).encode()
    req  = urllib.request.Request("https://api.imgbb.com/1/upload", data=data)
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read())
    if not resp.get("success"):
        raise RuntimeError(f"imgBB upload failed: {resp}")
    url = resp["data"]["url"]
    print(f"  imgBB: {url}")
    return url


def generate_wan26(prompt, ref_url, api_key):
    """Wan 2.6 Image Edit — conserva identidad del personaje desde imagen de referencia."""
    payload = {
        "images_list": [ref_url],
        "prompt":      prompt,
    }
    r = api_post("/wan2.6-image-edit", payload, api_key)
    task_id = r.get("request_id") or r.get("id")
    if not task_id:
        raise RuntimeError(f"Sin task_id: {r}")
    print(f"  task={task_id}")
    img_url = poll_task(task_id, api_key)
    req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


# ── Pillow compositing ───────────────────────────────────────────────────────

def impact(size):
    for path in [IMPACT, ARIAL_BOLD,
                 "/System/Library/Fonts/Helvetica.ttc",
                 "/System/Library/Fonts/Arial.ttf"]:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_bordered_text(draw, xy, text, font, fill=(0, 0, 0), border=(255, 255, 255), bw=3, anchor="la"):
    x, y = xy
    for dx in range(-bw, bw + 1):
        for dy in range(-bw, bw + 1):
            if dx or dy:
                draw.text((x + dx, y + dy), text, font=font, fill=border, anchor=anchor)
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def expand_to_16x9(img_bytes: bytes) -> Image.Image:
    """Expande imagen vertical a 1280x720 con fondo blur de los lados."""
    src = Image.open(io.BytesIO(img_bytes)).convert("RGB")

    # Escalar imagen fuente para que llene 1280 de ancho → blur background
    bg = src.copy()
    bg_ratio = W / bg.width
    bg = bg.resize((W, int(bg.height * bg_ratio)), Image.LANCZOS)
    # Recortar al centro para 1280x720
    if bg.height >= H:
        top = (bg.height - H) // 2
        bg = bg.crop((0, top, W, top + H))
    else:
        canvas_bg = Image.new("RGB", (W, H), (10, 10, 10))
        canvas_bg.paste(bg, (0, (H - bg.height) // 2))
        bg = canvas_bg
    bg = bg.filter(ImageFilter.GaussianBlur(radius=18))

    # Escalar imagen original para que quepa en 1280x720
    ratio_w = W / src.width
    ratio_h = H / src.height
    ratio   = min(ratio_w, ratio_h)
    new_w   = int(src.width * ratio)
    new_h   = int(src.height * ratio)
    src_resized = src.resize((new_w, new_h), Image.LANCZOS)

    # Pegar centrado
    x_off = (W - new_w) // 2
    y_off = (H - new_h) // 2
    bg.paste(src_resized, (x_off, y_off))
    return bg


def add_overlays(img: Image.Image, texto: str, etiqueta: str, badge: str) -> Image.Image:
    """
    Estilo canal de lujo:
    - Barra blanca cuya altura se ajusta al texto (sin espacio muerto)
    - Texto negro Impact lo más grande posible, ocupa todo el ancho
    - Etiqueta roja con nombre del personaje, pegada al borde superior de la barra
    """
    VPAD   = 14   # padding vertical dentro de la barra (arriba y abajo del texto)
    MARGIN = 14   # margen horizontal mínimo

    # ── Calcular tamaño de fuente — lo más grande que quepa en el ancho ───────
    tmp = ImageDraw.Draw(img)
    for size in range(130, 30, -2):
        fnt  = impact(size)
        bbox = tmp.textbbox((0, 0), texto, font=fnt)
        tw   = bbox[2] - bbox[0]
        if tw <= W - MARGIN * 2:
            break

    bbox  = tmp.textbbox((0, 0), texto, font=fnt)
    th    = bbox[3] - bbox[1]
    BAR_H = th + VPAD * 2   # barra exactamente del tamaño del texto

    # ── Canvas final: imagen arriba + barra blanca abajo ──────────────────────
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    img_h  = H - BAR_H
    img_r  = img.resize((W, img_h), Image.LANCZOS) if img.size != (W, img_h) else img
    canvas.paste(img_r, (0, 0))

    draw = ImageDraw.Draw(canvas)

    # ── Texto centrado en la barra ─────────────────────────────────────────────
    tx = W // 2
    ty = H - BAR_H + VPAD
    draw.text((tx, ty), texto, font=fnt, fill=(0, 0, 0), anchor="mt")

    # ── Etiqueta roja — pegada al borde superior de la barra, izquierda ───────
    if etiqueta:
        fnt_etiq = impact(30)
        bbox_e   = draw.textbbox((0, 0), etiqueta, font=fnt_etiq)
        ew = bbox_e[2] - bbox_e[0]
        eh = bbox_e[3] - bbox_e[1]
        epx, epy = 14, 7
        ex1 = MARGIN
        ey2 = H - BAR_H + 2
        ey1 = ey2 - eh - epy * 2
        ex2 = ex1 + ew + epx * 2
        draw.rectangle([ex1, ey1, ex2, ey2], fill="#CC0000")
        draw.text((ex1 + epx, ey1 + epy), etiqueta, font=fnt_etiq, fill="white")

    return canvas


def build_thumbnail(img_bytes: bytes, texto: str, etiqueta: str, badge: str) -> Image.Image:
    """Recorta imagen Wan 2.6 al ancho completo y añade barra blanca dinámica."""
    # Calcular BAR_H real para saber cuánto espacio tiene la imagen
    tmp_img  = Image.new("RGB", (W, H))
    tmp_draw = ImageDraw.Draw(tmp_img)
    for size in range(130, 30, -2):
        fnt  = impact(size)
        bbox = tmp_draw.textbbox((0, 0), texto, font=fnt)
        if bbox[2] - bbox[0] <= W - 28:
            break
    bbox  = tmp_draw.textbbox((0, 0), texto, font=fnt)
    th    = bbox[3] - bbox[1]
    BAR_H = th + 28   # VPAD*2

    src   = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img_h = H - BAR_H

    ratio = max(W / src.width, img_h / src.height)
    nw    = int(src.width  * ratio)
    nh    = int(src.height * ratio)
    src   = src.resize((nw, nh), Image.LANCZOS)
    left  = (nw - W)  // 2
    top   = (nh - img_h) // 2
    src   = src.crop((left, top, left + W, top + img_h))

    return add_overlays(src, texto, etiqueta, badge)


# ── metadata ─────────────────────────────────────────────────────────────────

def update_metadata(carpeta: Path, updates: dict):
    meta_path = carpeta / "metadata.json"
    meta = {}
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
    # Deep merge para pipeline y miniaturas
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(meta.get(k), dict):
            meta[k].update(v)
        else:
            meta[k] = v
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args or args[0].startswith("-"):
        print(__doc__); sys.exit(1)

    carpeta_arg = args[0]
    edad  = ""
    cifra = ""
    genero = "man"

    solo   = None
    extras = []
    sin_etiqueta = False
    i = 1
    while i < len(args):
        if args[i] == "--edad" and i + 1 < len(args):
            edad = args[i + 1]; i += 2
        elif args[i] == "--cifra" and i + 1 < len(args):
            cifra = args[i + 1].upper(); i += 2
        elif args[i] == "--mujer":
            genero = "woman"; i += 1
        elif args[i] == "--sin-etiqueta":
            sin_etiqueta = True; i += 1
        elif args[i] == "--solo" and i + 1 < len(args):
            solo = int(args[i + 1]); i += 2
        elif args[i] == "--extra" and i + 1 < len(args):
            extras.append(args[i + 1]); i += 2
        else:
            i += 1

    carpeta = Path(carpeta_arg)
    if not carpeta.is_absolute():
        carpeta = CANALES / carpeta_arg.rstrip("/")
    if not carpeta.is_dir():
        sys.exit(f"{R}ERROR: No existe la carpeta: {carpeta}{E}")

    personaje = carpeta.name
    personaje_upper = personaje.replace("_", " ").upper()
    ref_path  = REFS_DIR / f"{personaje}.jpg"
    if not ref_path.exists():
        # Intentar .png
        ref_path = REFS_DIR / f"{personaje}.png"
    if not ref_path.exists():
        sys.exit(
            f"{R}ERROR: No encontré imagen de referencia en {REFS_DIR}/{personaje}.jpg{E}\n"
            f"  Guarda la foto del personaje ahí primero."
        )

    api_key  = get_api_key()
    versions = build_versions(personaje_upper, edad, cifra, genero, extras,
                              sin_etiqueta=sin_etiqueta)

    if solo:
        versions = [versions[solo - 1]]
        indices  = [solo]
    else:
        indices  = list(range(1, len(versions) + 1))

    print(f"\n{'='*60}")
    print(f"  MINIATURAS — {personaje_upper}")
    print(f"  Referencia: {ref_path.name}  ({ref_path.stat().st_size // 1024} KB)")
    print(f"  Versiones : {len(indices)}  |  Modelo: Wan 2.6 Image Edit")
    print(f"{'='*60}\n")

    # Subir referencia a imgBB una sola vez y reusar la URL
    print(f"{B}Subiendo referencia a imgBB...{E}")
    ref_url = upload_imgbb(ref_path)

    resultados = {}
    for i, ver in zip(indices, versions):
        print(f"\n{B}[{i}/{len(indices)}]{E} {ver['texto'][:60]}...")
        print(f"  Prompt: {ver['prompt'][:80]}...")
        try:
            img_bytes = generate_wan26(ver["prompt"], ref_url, api_key)
            thumb = build_thumbnail(img_bytes, ver["texto"], ver["etiqueta"], ver["badge"])
            out   = carpeta / f"miniatura_{i}.jpg"
            thumb.save(str(out), "JPEG", quality=95)
            kb = out.stat().st_size // 1024
            print(f"  {G}✓ miniatura_{i}.jpg — {kb} KB{E}\n")
            resultados[f"miniatura_{i}"] = "generada"
        except Exception as e:
            print(f"  {R}✗ Error: {e}{E}\n")
            resultados[f"miniatura_{i}"] = "error"

    # Actualizar metadata.json
    ok = sum(1 for v in resultados.values() if v == "generada")
    update_metadata(carpeta, {
        "miniaturas": resultados,
        "pipeline": {"miniaturas": "completado" if ok == 3 else "error"},
    })

    print(f"{'='*60}")
    print(f"  {ok}/3 miniaturas generadas en {carpeta.name}/")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
