#!/usr/bin/env python3
"""
harvester_belice.py — Busca material para cada segmento del timeline de Belice.

Cadena por segmento:
  - PIXABAY: stock genérico (selva, playa, arrecife, barcos, etc.)
  - BRAVE:   imágenes reales de Belice (calles, mapas, mercados, landmarks)
  - FLOW:    abstracto/animado/compuesto — queda pendiente para VEO

Uso: python3 belice/harvester_belice.py belice/belice/
"""

import sys, json, subprocess, urllib.request, urllib.parse, urllib.error
import pathlib, time, gzip as _gzip

CANALES_DIR = pathlib.Path(__file__).parent.parent
YTDLP   = "/opt/homebrew/bin/yt-dlp"
FFMPEG  = "ffmpeg"
FFPROBE = "ffprobe"

PEXELS_KEY  = pathlib.Path.home().joinpath(".pexels_key").read_text().strip()
PIXABAY_KEY = pathlib.Path.home().joinpath(".pixabay_key").read_text().strip()
BRAVE_KEY   = pathlib.Path.home().joinpath(".brave_key").read_text().strip()

# ── Clasificación de segmentos ────────────────────────────────────────────────
# pixabay: stock genérico funciona bien
# brave:   necesita foto real de Belice → zoompan
# flow:    abstracto/animado/compuesto → VEO pendiente

CLASIFICACION = {
    # seg_id: (fuente, query) — basado en audio real del SRT
     1: ("brave",   "Central America map Belize highlighted"),             # "país en el mapa de América Central que su vecino dice que le pertenece"
     2: ("pixabay", "tropical jungle aerial dense canopy"),                # "la mitad completa de su territorio, selva"
     3: ("brave",   "Belize City modern street aerial"),                   # "ese país sigue funcionando" — NO mercado
     4: ("brave",   "Central America map countries Spanish"),              # "sigue creciendo, ni siquiera habla español"
     5: ("pixabay", "caribbean coast belize aerial beach"),                # "Belice, pequeño rincón entre selva y Caribe"
     6: ("pixabay", "caribbean sea coral reef aerial"),                    # "Caribe que casi nadie conoce" — pixabay, no flow
     7: ("flow",    None),                                                 # "diez datos que te van a cambiar la idea" — animación cuenta regresiva
     8: ("flow",    None),                                                 # "dato número 1 tan fuerte, dale pausa" — animación impacto
     9: ("flow",    None),                                                 # "suscríbete" — animación YT
    10: ("flow",    None),                                                 # "suscríbete ahora" — animación YT
    11: ("brave",   "Belize City street sign English language"),           # "un país que habla inglés"
    12: ("brave",   "Central America map countries overview"),             # "el mapa de Centroamérica"
    13: ("brave",   "Central America map Guatemala Honduras Nicaragua"),   # "Guatemala, Honduras, El Salvador, Nicaragua..."
    14: ("pixabay", "book open spanish text reading"),                     # "todos hablan español como idioma oficial"
    15: ("pixabay", "aerial belize coast jungle"),                         # "todos menos uno, Belice"
    16: ("brave",   "Belize sign English official language"),              # "idioma oficial es el inglés"
    17: ("pixabay", "old colonial architecture vintage"),                  # "no es un capricho ni una moda reciente"
    18: ("brave",   "british colonial fort caribbean historic"),           # "herencia de hace más de 300 años"
    19: ("pixabay", "sailing ship galleon spanish colonial ocean"),        # "España conquistaba y colonizaba casi todo"
    20: ("pixabay", "tropical jungle swamp coast mangrove aerial"),       # "zona de selva, pantanos y costa"
    21: ("brave",   "Central America map Spanish territory highlight"),    # "no le interesaba a la Corona española"
    22: ("pixabay", "pirate ship sailing caribbean ocean"),                # "llegaron los ingleses, primero como piratas"
    23: ("brave",   "men cutting mahogany logs tropical jungle"),          # "cortadores de madera"
    24: ("pixabay", "naval battle sailing ships cannon historical"),       # "Batalla de Cayo San Jorge"
    25: ("brave",   "British soldiers colonial uniform victory"),          # "británicos vencieron a las fuerzas españolas"
    26: ("brave",   "old colonial map territory border 1800s"),            # "destino de este pedazo de tierra"
    27: ("brave",   "British flag colonial caribbean fort"),               # "colonia británica"
    28: ("brave",   "Honduras Britanica British Honduras map"),            # "se llamó Honduras Británica"
    29: ("brave",   "Belize City street English signs stores"),            # "cuando entras a Belice, todos los letreros"
    30: ("pixabay", "official documents books education desk"),            # "documentos oficiales, noticias, educación"
    31: ("pixabay", "school classroom children learning"),                 # "educación escolar son en inglés"
    32: ("brave",   "colorful Caribbean street Belize people walking"),   # "caminando por la calle vas a escuchar de todo"
    33: ("brave",   "Belize people conversation street Spanish"),          # "español porque beliceños tienen raíces mexicanas"
    34: ("brave",   "Mexico Guatemala border cultural mix people"),        # "raíces mexicanas o guatemaltecas"
    35: ("flow",    None),                                                 # "criol, mezcla de inglés con raíces africanas" — animación sonido
    36: ("brave",   "Belize people daily life conversation"),              # "idioma del día a día"
}

used_urls: set = set()

# ── Pixabay ───────────────────────────────────────────────────────────────────

def buscar_pixabay(query: str, per_page: int = 8):
    url = (f"https://pixabay.com/api/videos/?key={PIXABAY_KEY}"
           f"&q={urllib.parse.quote(query)}&per_page={per_page}&video_type=film&min_width=1280")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        for h in data.get("hits", []):
            for quality in ["large", "medium"]:
                vurl = h.get("videos", {}).get(quality, {}).get("url")
                if vurl and vurl not in used_urls:
                    return vurl
    except Exception as e:
        print(f"    Pixabay error: {e}")
    return None

def descargar_directo(url: str, dest: pathlib.Path) -> bool:
    r = subprocess.run(
        ["curl", "-sL", "-A", "Mozilla/5.0", "-o", str(dest), url],
        capture_output=True, timeout=40
    )
    return dest.exists() and dest.stat().st_size > 10000

# ── Brave ─────────────────────────────────────────────────────────────────────

def buscar_brave(query: str, count: int = 8):
    """Devuelve lista de URLs de imágenes desde Brave Image Search."""
    url = f"https://api.search.brave.com/res/v1/images/search?q={urllib.parse.quote(query)}&count={count}&safesearch=off"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_KEY,
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            try: raw = _gzip.decompress(raw)
            except: pass
            data = json.loads(raw)
        results = []
        for item in data.get("results", []):
            img_url = item.get("properties", {}).get("url") or item.get("url", "")
            if img_url and img_url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                if img_url not in used_urls:
                    results.append(img_url)
        return results
    except Exception as e:
        print(f"    Brave error: {e}")
    return []

def descargar_imagen(url: str, dest: pathlib.Path) -> bool:
    r = subprocess.run(
        ["curl", "-sL", "-A", "Mozilla/5.0", "--max-time", "15",
         "-o", str(dest), url],
        capture_output=True, timeout=20
    )
    if not dest.exists() or dest.stat().st_size < 5000:
        return False
    # Verificar que es imagen válida con ffprobe
    probe = subprocess.run(
        [FFPROBE, "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(dest)],
        capture_output=True, text=True, timeout=5
    )
    dims = probe.stdout.strip()
    if not dims or "," not in dims:
        return False
    w, h = dims.split(",")[:2]
    return int(w) >= 400 and int(h) >= 300

# ── Zoompan ───────────────────────────────────────────────────────────────────

def aplicar_zoompan(src: pathlib.Path, dest: pathlib.Path, dur: float) -> bool:
    sys.path.insert(0, str(CANALES_DIR))
    try:
        from zoompan_clip import make_zoompan
        make_zoompan(src, dest, dur)
        return dest.exists() and dest.stat().st_size > 1000
    except Exception as e:
        print(f"    zoompan error: {e}")
        return False

def recortar_video(src: pathlib.Path, dest: pathlib.Path, dur: float) -> bool:
    r = subprocess.run(
        [FFMPEG, "-y", "-i", str(src), "-t", str(dur),
         "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-an", "-r", "30", str(dest)],
        capture_output=True
    )
    return dest.exists() and dest.stat().st_size > 1000

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 belice/harvester_belice.py belice/belice/")
        sys.exit(1)

    carpeta   = pathlib.Path(sys.argv[1])
    tl_path   = carpeta / "05-montaje" / "timeline.json"
    img_dir   = carpeta / "03-imagenes"
    meta_path = carpeta / "metadata.json"
    img_dir.mkdir(exist_ok=True)

    tl   = json.loads(tl_path.read_text())
    segs = tl["visual_timeline"]
    total = len(segs)

    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
    meta.setdefault("footage", {})
    meta.setdefault("deleted_yt_clips", {})
    meta.setdefault("rejected_yt_clips", {})

    stats = {"pixabay": 0, "brave": 0, "flow": 0}

    print(f"\n{'='*60}")
    print(f"  HARVESTER BELICE — {total} segmentos")
    print(f"{'='*60}\n")

    for seg in segs:
        sid  = seg["segment_id"]
        dur  = seg["end_seconds"] - seg["start_seconds"]
        desc = seg.get("scene_description_es", "")
        clip_name = f"flow_{sid:04d}_zp.mp4"
        clip_path = img_dir / clip_name

        fuente_plan, query = CLASIFICACION.get(sid, ("flow", None))

        print(f"  [{sid:02d}/{total}] {seg['start_seconds']:.1f}s [{fuente_plan.upper()}] — {desc[:65]}")

        if clip_path.exists() and clip_path.stat().st_size > 1000:
            print(f"    ✓ Ya existe\n")
            if clip_name not in meta["footage"]:
                meta["footage"][clip_name] = {"fuente": fuente_plan, "estado": "pendiente"}
            continue

        exito = False

        # ── PIXABAY ──
        if fuente_plan == "pixabay" and query:
            vurl = buscar_pixabay(query)
            if vurl:
                tmp = img_dir / f"_tmp_{sid:04d}.mp4"
                print(f"    ↓ Pixabay: {vurl[30:80]}...")
                if descargar_directo(vurl, tmp):
                    if recortar_video(tmp, clip_path, dur):
                        tmp.unlink(missing_ok=True)
                        used_urls.add(vurl)
                        print(f"    ✅ Pixabay OK")
                        meta["footage"][clip_name] = {"fuente": "pixabay", "estado": "pendiente", "query": query}
                        stats["pixabay"] += 1
                        exito = True
                    else:
                        tmp.unlink(missing_ok=True)
                        print(f"    ⚠ Pixabay: falló conversión")
                else:
                    tmp.unlink(missing_ok=True)
                    print(f"    ⚠ Pixabay: falló descarga")

        # ── BRAVE ──
        if fuente_plan == "brave" and query and not exito:
            imgs = buscar_brave(query)
            print(f"    Brave: {len(imgs)} imágenes encontradas")
            for img_url in imgs[:5]:
                tmp_img = img_dir / f"_tmp_{sid:04d}.jpg"
                if descargar_imagen(img_url, tmp_img):
                    if aplicar_zoompan(tmp_img, clip_path, dur):
                        tmp_img.unlink(missing_ok=True)
                        used_urls.add(img_url)
                        print(f"    ✅ Brave OK → {img_url[8:60]}...")
                        meta["footage"][clip_name] = {"fuente": "brave", "estado": "pendiente", "query": query}
                        stats["brave"] += 1
                        exito = True
                        break
                    else:
                        tmp_img.unlink(missing_ok=True)
                else:
                    tmp_img.unlink(missing_ok=True)
            if not exito:
                print(f"    ⚠ Brave: ninguna imagen descargable")

        # ── FLOW ──
        if not exito:
            prompt = seg.get("ia_prompt", desc)
            print(f"    🔵 Flow pendiente")
            meta["footage"][clip_name] = {"fuente": "flow", "estado": "pendiente", "prompt": prompt}
            stats["flow"] += 1

        print()
        time.sleep(0.2)

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    print(f"\n{'='*60}")
    print(f"  RESUMEN")
    print(f"  ✅ Pixabay: {stats['pixabay']} clips")
    print(f"  ✅ Brave:   {stats['brave']} imágenes")
    print(f"  🔵 Flow:    {stats['flow']} pendientes")
    print(f"{'='*60}\n")

    if stats["flow"] > 0:
        flow_segs = [seg for seg in segs
                     if meta["footage"].get(f"flow_{seg['segment_id']:04d}_zp.mp4", {}).get("fuente") == "flow"]
        prompts_path = carpeta / "05-montaje" / "flow_pendientes.txt"
        with open(prompts_path, "w") as f:
            for s in flow_segs:
                f.write(f"[{s['segment_id']}] {s.get('ia_prompt', '')}\n\n")
        print(f"  Prompts Flow → {prompts_path}\n")

if __name__ == "__main__":
    main()
