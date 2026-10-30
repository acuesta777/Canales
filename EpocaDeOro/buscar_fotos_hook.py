#!/usr/bin/env python3
"""
buscar_fotos_hook.py — Busca imágenes y clips cortos para el hook de La Verdad Dorada.

Por cada artista descarga:
  - 3 fotos vía Brave Image Search  → hook_fotos/NNN_slug_01.jpg ...
  - 2 clips cortos vía YouTube Search → hook_clips/NNN_slug_01.mp4 ...

Los clips se descargan en calidad baja (max 480p, máx 60s) para procesar rápido.
El render aplica hflip + reframe + speed±2% (transformación fair use).

Uso:
  python3 buscar_fotos_hook.py "Video-001/" --desde-txts
  python3 buscar_fotos_hook.py "Video-001/" "Lupe Velez" "Jorge Negrete"

API key imágenes : ~/.brave_key
yt-dlp           : /opt/homebrew/bin/yt-dlp
"""

import sys, json, time, re, subprocess, unicodedata, urllib.request, urllib.parse, pathlib

YTDLP    = "/opt/homebrew/bin/yt-dlp"
KEY_FILE = pathlib.Path.home() / ".brave_key"

N_FOTOS = 3   # fotos por artista
N_CLIPS = 2   # clips por artista
MAX_DUR = 60  # segundos máximos por clip

BLOCKED_DOMAINS = [
    "alamy", "gettyimages", "shutterstock", "istockphoto", "dreamstime",
    "123rf", "depositphotos", "vectorstock", "freepik", "pngtree",
]
NEGATIVE_WORDS = [
    "cartoon", "illustration", "vector", "icon", "logo", "clipart",
    "meme", "drawing", "wallpaper hd", "png",
]

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
NEGRITA  = "\033[1m"
RESET    = "\033[0m"


def norm(text):
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")

def slugify(s):
    return re.sub(r"[^a-z0-9]+", "_", norm(s)).strip("_")[:40]

def get_key():
    if not KEY_FILE.exists():
        sys.exit(f"[ERROR] Falta {KEY_FILE}")
    return KEY_FILE.read_text().strip()


# ─── IMÁGENES ────────────────────────────────────────────────────────────────

def brave_search(query, key, count=20):
    url = "https://api.search.brave.com/res/v1/images/search?" + urllib.parse.urlencode({
        "q": query, "count": count, "safesearch": "strict",
        "search_lang": "es", "spellcheck": "true",
    })
    req = urllib.request.Request(url, headers={
        "X-Subscription-Token": key, "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read()).get("results", [])

def score_img(r):
    props  = r.get("properties", {})
    title  = (r.get("title") or "").lower()
    source = (r.get("url") or "").lower()
    w = props.get("width", 0) or 0
    h = props.get("height", 0) or 0
    if any(d in source for d in BLOCKED_DOMAINS): return -1
    if any(nw in title for nw in NEGATIVE_WORDS): return -1
    if w and w < 400: return -1
    score = 0
    if h > w:       score += 2   # retrato — ideal
    if w >= 1000:   score += 3
    elif w >= 700:  score += 1
    return score

def download_img(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        data = r.read()
    if len(data) < 15_000:
        raise RuntimeError("imagen muy pequeña")
    dest.write_bytes(data)
    return len(data)

def buscar_fotos(nombre, fotos_dir, idx, key):
    queries = [
        f"{nombre} actor actriz cine mexicano retrato fotografía",
        f"{nombre} epoca de oro cine mexicano",
        f"{nombre} foto histórica",
    ]
    descargadas = []
    n = 0
    for query in queries:
        if n >= N_FOTOS:
            break
        try:
            results = brave_search(query, key)
        except Exception as e:
            print(f"    ✗ búsqueda Brave falló: {e}")
            continue
        scored = sorted(
            [(score_img(r), r) for r in results if score_img(r) >= 0],
            key=lambda x: -x[0]
        )
        for _, r in scored:
            if n >= N_FOTOS:
                break
            props   = r.get("properties", {})
            img_url = props.get("url") or ""
            if not img_url:
                continue
            dest = fotos_dir / f"{idx:02d}_{slugify(nombre)}_{n+1:02d}.jpg"
            try:
                size = download_img(img_url, dest)
                print(f"    {VERDE}✓ foto {n+1}: {dest.name} ({size//1024}KB, {props.get('width')}x{props.get('height')}){RESET}")
                descargadas.append(str(dest))
                n += 1
            except Exception:
                continue
        time.sleep(1.0)
    return descargadas


# ─── CLIPS ───────────────────────────────────────────────────────────────────

def buscar_clips_yt(nombre, clips_dir, idx):
    """Busca clips en YouTube, descarga y corta a MAX_DUR segundos."""
    FFMPEG = "/opt/homebrew/bin/ffmpeg"
    queries = [
        f"{nombre} cine mexicano",
        f"{nombre} pelicula escena",
    ]
    descargados = []
    n = 0
    for query in queries:
        if n >= N_CLIPS:
            break
        slug  = slugify(nombre)
        tmp   = clips_dir / f"{idx:02d}_{slug}_{n+1:02d}_raw.mp4"
        final = clips_dir / f"{idx:02d}_{slug}_{n+1:02d}.mp4"
        cmd = [
            YTDLP,
            f"ytsearch5:{query}",
            "--format", "best[height<=480][ext=mp4]/best[ext=mp4]/best",
            "--output", str(tmp),
            "--max-downloads", "1",
            "--no-playlist",
            "--extractor-args", "youtube:player_client=android",
            "--download-sections", f"*0-{MAX_DUR}",
            "--force-keyframes-at-cuts",
            "--quiet",
            "--no-warnings",
        ]
        try:
            subprocess.run(cmd, timeout=180, capture_output=True)
            if tmp.exists() and tmp.stat().st_size > 50_000:
                # Cortar a MAX_DUR segundos
                cut_cmd = [
                    FFMPEG, "-y", "-i", str(tmp),
                    "-t", str(MAX_DUR),
                    "-c:v", "libx264", "-c:a", "aac",
                    "-preset", "ultrafast", "-crf", "28",
                    str(final), "-loglevel", "error"
                ]
                subprocess.run(cut_cmd, timeout=120, capture_output=True)
                tmp.unlink(missing_ok=True)
                if final.exists():
                    size_kb = final.stat().st_size // 1024
                    print(f"    {VERDE}✓ clip {n+1}: {final.name} ({size_kb}KB, {MAX_DUR}s){RESET}")
                    descargados.append(str(final))
                    n += 1
                else:
                    print(f"    {AMARILLO}⚠ ffmpeg falló al cortar clip{RESET}")
            else:
                tmp.unlink(missing_ok=True)
                print(f"    {AMARILLO}⚠ sin clip para: {query}{RESET}")
        except subprocess.TimeoutExpired:
            tmp.unlink(missing_ok=True)
            print(f"    {AMARILLO}⚠ timeout buscando clip{RESET}")
        except Exception as e:
            print(f"    ✗ error clip: {e}")
        time.sleep(1.5)
    return descargados


# ─── ARTISTAS ────────────────────────────────────────────────────────────────

def leer_artistas_desde_txts(folder):
    txts = sorted(folder.glob("[0-9][1-9]_*.txt"))
    nombres = []
    for txt in txts:
        nombre = re.sub(r"^\d+_", "", txt.stem).strip()
        if nombre:
            nombres.append(nombre)
    return nombres


def leer_artistas_desde_timeline(folder):
    tl_path = folder / "hook_timeline.json"
    if not tl_path.exists():
        sys.exit(f"[ERROR] No existe hook_timeline.json — corre primero generar_hook_timeline_epocadeoro.py")
    tl = json.loads(tl_path.read_text(encoding="utf-8"))
    return [(s["idx"], s["nombre"]) for s in tl["segments"]]


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)

    folder = pathlib.Path(sys.argv[1])
    if not folder.is_dir():
        sys.exit(f"[ERROR] No existe: {folder}")

    usar_timeline = "--desde-timeline" in sys.argv
    usar_txts     = "--desde-txts" in sys.argv

    if usar_timeline:
        artistas = leer_artistas_desde_timeline(folder)  # [(idx, nombre), ...]
        nombres  = [n for _, n in artistas]
        indices  = [i for i, _ in artistas]
    elif usar_txts:
        nombres = leer_artistas_desde_txts(folder)
        if not nombres:
            sys.exit("[ERROR] No encontré TXTs de artistas (01_*.txt ...)")
        indices = list(range(1, len(nombres) + 1))
    else:
        nombres = [a for a in sys.argv[2:] if not a.startswith("--")]
        indices = list(range(1, len(nombres) + 1))

    if not nombres:
        sys.exit("[ERROR] Pasa nombres o usa --desde-txts")

    key      = get_key()
    fotos_dir = folder / "hook_fotos"
    clips_dir = folder / "hook_clips"
    fotos_dir.mkdir(exist_ok=True)
    clips_dir.mkdir(exist_ok=True)

    print(f"\n{NEGRITA}{'='*62}")
    print(f"  MEDIA HOOK — La Verdad Dorada")
    print(f"  {len(nombres)} artista(s) | {N_FOTOS} fotos + {N_CLIPS} clips c/u")
    print(f"  Transformación fair use: hflip + reframe + speed±2%")
    print(f"{'='*62}{RESET}\n")

    manifest = []
    for i, nombre in zip(indices, nombres):
        print(f"{NEGRITA}[{i}/{len(nombres)}] {nombre.upper()}{RESET}")

        print(f"  {AMARILLO}→ Fotos (Brave Images):{RESET}")
        fotos = buscar_fotos(nombre, fotos_dir, i, key)

        print(f"  {AMARILLO}→ Clips (YouTube Search):{RESET}")
        clips = buscar_clips_yt(nombre, clips_dir, i)

        manifest.append({
            "idx": i, "nombre": nombre,
            "fotos": fotos, "clips": clips,
        })
        print()
        time.sleep(1.0)

    # Guardar manifiesto
    m_path = folder / "hook_media_manifest.json"
    m_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

    total_fotos = sum(len(r["fotos"]) for r in manifest)
    total_clips = sum(len(r["clips"]) for r in manifest)

    print(f"{NEGRITA}{'='*62}")
    print(f"  ✓ {total_fotos} fotos  →  {fotos_dir.name}/")
    print(f"  ✓ {total_clips} clips  →  {clips_dir.name}/")
    print(f"  Manifiesto: {m_path.name}")
    print(f"  Siguiente: render_hook_epocadeoro.py")
    print(f"{'='*62}{RESET}")


if __name__ == "__main__":
    main()
