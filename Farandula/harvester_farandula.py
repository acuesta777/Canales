#!/usr/bin/env python3
"""
harvester_farandula.py — Busca imágenes reales de artistas via Brave Search.

Para cada artista sin suficientes clips/imágenes en iCloud:
  1. Calcula cuántas imágenes necesita (duración / 7.5s por plano)
  2. Busca fotos reales en Brave Search (solo el nombre del artista)
  3. Descarga, convierte a zoompan MP4 (7.5s, 1920x1080)
  4. Si Brave no alcanza → sube los faltantes a Baserow para Flow
  5. Guarda todo en iCloud/Artistas/[NOMBRE]/

Uso:
  python3 harvester_farandula.py "VIVIENDO DE FAVOR TELEVISA/"
  python3 harvester_farandula.py "VIVIENDO DE FAVOR TELEVISA/" --artista "ALONSO ECHANOVE"
"""

import sys, json, time, subprocess, pathlib, random, re, unicodedata, gzip, urllib.request, urllib.error, hashlib

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
YTDLP   = "/opt/homebrew/bin/yt-dlp"
HOME    = pathlib.Path.home()

ICLOUD_ARTISTAS  = HOME / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"
BRAVE_KEY_FILE   = HOME / ".brave_key"
MUAPI_KEY_FILE   = HOME / ".muapi_key"

SHOT_DUR     = 7.5   # segundos por plano
BRAVE_COUNT  = 15    # resultados Brave por búsqueda (traemos más, filtramos)
MIN_W        = 720   # ancho mínimo aceptable para imágenes
MIN_H        = 480   # alto mínimo aceptable

# Baserow (fallback si Brave no alcanza)
BASEROW_TOKEN    = '4QrZH5MkTLHKtGqTG97Gz2yQTAIhknMq'
BASEROW_TABLE_ID = '1100194'
BASEROW_API_BASE = 'https://api.baserow.io/api'

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"

def ok(msg):   print(f"  {VERDE}✓{RESET} {msg}")
def err(msg):  print(f"  {ROJO}✗{RESET} {msg}")
def warn(msg): print(f"  {AMARILLO}⚠{RESET} {msg}")

# ── Utilidades ─────────────────────────────────────────────────────────────────

def leer_key(path):
    try:
        return pathlib.Path(path).read_text().strip()
    except Exception:
        return None

def norm(text):
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")

def planos_necesarios(duracion_seg):
    return int(duracion_seg / SHOT_DUR) + 1

def buscar_carpeta_icloud(nombre_artista):
    if not ICLOUD_ARTISTAS.exists():
        return None
    nombre_n = norm(nombre_artista)
    for d in ICLOUD_ARTISTAS.iterdir():
        if d.is_dir() and norm(d.name) == nombre_n:
            return d
    for d in ICLOUD_ARTISTAS.iterdir():
        if d.is_dir() and nombre_n in norm(d.name):
            return d
    apellido = nombre_n.split()[-1] if nombre_n.split() else nombre_n
    if len(apellido) > 3:
        for d in ICLOUD_ARTISTAS.iterdir():
            if d.is_dir() and apellido in norm(d.name):
                return d
    return None

def contar_clips(carpeta):
    if not carpeta or not carpeta.exists():
        return 0, 0
    mp4  = list(carpeta.glob("*.mp4"))
    imgs = [f for f in carpeta.iterdir()
            if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.avif')]
    return len(mp4), len(imgs)

def siguiente_idx(carpeta):
    """Próximo número disponible para nombrar archivos."""
    existentes = []
    for f in carpeta.iterdir():
        m = re.match(r'^(\d+)', f.stem)
        if m:
            existentes.append(int(m.group(1)))
    return max(existentes, default=0) + 1

# ── Brave Image Search ─────────────────────────────────────────────────────────

def buscar_brave(query, api_key, count=15):
    """Devuelve lista de URLs de imágenes desde Brave."""
    import urllib.parse
    url = (f"https://api.search.brave.com/res/v1/images/search"
           f"?q={urllib.parse.quote(query)}&count={count}&safesearch=off")
    req = urllib.request.Request(url, headers={
        "Accept":                "application/json",
        "Accept-Encoding":       "gzip",
        "X-Subscription-Token":  api_key,
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
            data = json.loads(raw)
        urls = []
        for item in data.get("results", []):
            img_url = item.get("properties", {}).get("url") or item.get("url", "")
            if img_url and img_url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
                urls.append(img_url)
        return urls
    except Exception as e:
        warn(f"Brave falló ({query[:30]}): {e}")
        return []

def hash_file(path):
    return hashlib.md5(path.read_bytes()).hexdigest()

def hashes_existentes(carpeta):
    """Devuelve set de md5 de todas las imágenes ya en la carpeta."""
    hashes = set()
    if not carpeta or not carpeta.exists():
        return hashes
    for f in carpeta.iterdir():
        if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'):
            try:
                hashes.add(hash_file(f))
            except Exception:
                pass
    return hashes

def descargar_imagen(url, dest_path, hashes_prev, timeout=15):
    """Descarga imagen. Valida tamaño mínimo y que no sea duplicado."""
    try:
        subprocess.run(
            ["curl", "-sL", "--max-time", str(timeout),
             "-A", "Mozilla/5.0", "-o", str(dest_path), url],
            capture_output=True, timeout=timeout + 5
        )
        if not dest_path.exists() or dest_path.stat().st_size < 10000:
            dest_path.unlink(missing_ok=True)
            return False
        # Verificar dimensiones
        check = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(dest_path)],
            capture_output=True, text=True, timeout=8
        )
        if check.returncode == 0 and check.stdout.strip():
            parts = check.stdout.strip().split(",")
            if len(parts) == 2:
                w, h = int(parts[0] or 0), int(parts[1] or 0)
                if w >= MIN_W and h >= MIN_H:
                    # Verificar duplicado por hash
                    h_new = hash_file(dest_path)
                    if h_new in hashes_prev:
                        dest_path.unlink(missing_ok=True)
                        return False
                    hashes_prev.add(h_new)
                    return True
        dest_path.unlink(missing_ok=True)
        return False
    except Exception:
        dest_path.unlink(missing_ok=True)
        return False

# ── Baserow fallback ───────────────────────────────────────────────────────────

def _baserow_curl(method, path, data=None):
    url = BASEROW_API_BASE + path
    cmd = ['curl', '-s', '-X', method, url,
           '-H', f'Authorization: Token {BASEROW_TOKEN}',
           '-H', 'Content-Type: application/json']
    if data:
        cmd += ['-d', json.dumps(data)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if not r.stdout.strip():
        return {}
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}

def subir_a_baserow_y_descargar(pendientes_flow, artista_dir_map):
    """
    pendientes_flow: lista de dict {artista, nombre_display, idx, carpeta}
    Sube prompts a Baserow, espera extensión, descarga, convierte a zoompan.
    """
    if not pendientes_flow:
        return

    print(f"\n  ── Fallback Flow: {len(pendientes_flow)} imágenes pendientes ──")

    # Limpiar Baserow
    existing = []
    page = 1
    while True:
        data = _baserow_curl('GET', f'/database/rows/table/{BASEROW_TABLE_ID}/?user_field_names=true&size=200&page={page}')
        existing += [r['id'] for r in data.get('results', [])]
        if not data.get('next'): break
        page += 1
    for rid in existing:
        _baserow_curl('DELETE', f'/database/rows/table/{BASEROW_TABLE_ID}/{rid}/')

    items = []
    for p in pendientes_flow:
        nd = p['nombre_display']
        items.append({
            'Image Prompt': f"{nd}, Mexican entertainer, portrait photo, photorealistic, no text",
            'VEO Prompt':   f"Slow cinematic zoom in, {nd} portrait",
            'Mode':         'Imagegen',
            'Status':       'pending',
        })

    result = _baserow_curl('POST',
        f'/database/rows/table/{BASEROW_TABLE_ID}/batch/?user_field_names=true',
        {'items': items})
    created = result.get('items', [])
    ok(f"  {len(created)} filas en Baserow — corre la extensión VEO")

    # Poll
    rowid_map = {created[i]['id']: pendientes_flow[i] for i in range(min(len(created), len(pendientes_flow)))}
    max_wait = 90 * 60
    waited   = 0
    completed_rows = {}

    while waited < max_wait:
        time.sleep(20)
        waited += 20
        data = _baserow_curl('GET', f'/database/rows/table/{BASEROW_TABLE_ID}/?user_field_names=true&size=200')
        rows = data.get('results', [])
        n_done = 0
        for r in rows:
            sv = r.get('Status', '')
            if isinstance(sv, dict): sv = sv.get('value', '')
            if sv in ('completed', 'failed'): n_done += 1
            if sv == 'completed' and r['id'] not in completed_rows:
                url = r.get('Video_URL', '')
                if url and url.startswith('http'):
                    completed_rows[r['id']] = url
        print(f"  [{waited}s] {n_done}/{len(rows)} procesadas...")
        if n_done >= len(rows) and len(rows) > 0:
            break

    # Descargar frame del video Flow → guardar como JPEG
    for row_id, img_url in completed_rows.items():
        p = rowid_map.get(row_id)
        if not p: continue
        carpeta = p['carpeta']
        idx     = p['idx']
        raw     = carpeta / f"flow_{idx:04d}_raw.mp4"
        jpg     = carpeta / f"foto_{idx:04d}.jpg"

        subprocess.run([
            YTDLP, '--cookies-from-browser', 'brave',
            '-o', str(raw), '--no-playlist', '-q', img_url
        ], capture_output=True, timeout=90)

        if raw.exists() and raw.stat().st_size > 5000:
            subprocess.run([FFMPEG, '-y', '-i', str(raw), '-frames:v', '1',
                            '-vf', 'scale=1920:1080', str(jpg)],
                           capture_output=True, timeout=15)
            raw.unlink(missing_ok=True)

        if jpg.exists():
            ok(f"  [{p['artista']}] Flow → {jpg.name}")
        else:
            err(f"  [{p['artista']}] Flow #{idx} falló")

# ── Hook: imágenes temáticas via Flow/Baserow ─────────────────────────────────

def harvester_hook(folder):
    """
    Lee hook_timeline.json, sube Image Prompt + VEO Prompt a Baserow,
    espera la extensión VEO, descarga videos Flow → extrae JPEGs a hook_images/.
    Mismo flujo que riqueza pero solo para el hook del video.
    """
    hook_file = folder / "hook_timeline.json"
    if not hook_file.exists():
        warn("hook_timeline.json no encontrado — intro usará clips de artistas")
        return

    all_segments = json.loads(hook_file.read_text(encoding="utf-8")).get("visual_timeline", [])
    if not all_segments:
        return

    # Solo los segmentos de tipo "flow" van a Baserow/VEO
    segments = [s for s in all_segments if s.get("type", "flow") == "flow"]
    if not segments:
        return

    # ── GUARD: ningún segmento flow puede superar 8s ─────────────────────────
    errores = [s for s in segments if s.get("duration", 0) > 8.0]
    if errores:
        print("\n❌ HOOK BLOQUEADO — segmentos que superan 8s (tope duro):")
        for s in errores:
            print(f"   Seg {s['segment_id']}: {s['start_seconds']}→{s['end_seconds']} = {s['duration']}s")
        print("\n   Edita hook_timeline.json y parte esos segmentos antes de continuar.")
        raise SystemExit(1)
    # ── fin guard ─────────────────────────────────────────────────────────────

    hook_dir = folder / "hook_images"
    hook_dir.mkdir(exist_ok=True)

    # Si ya tenemos todas las imágenes flow, saltar
    existentes = sorted(hook_dir.glob("hook_[0-9]*.jpg"))
    if len(existentes) >= len(segments):
        ok(f"Hook: {len(existentes)} imágenes ya listas")
        return

    n_yt = len([s for s in all_segments if s.get("type") == "youtube"])
    print(f"\n  ── HOOK: {len(segments)} imágenes Flow + {n_yt} clips YT intercalados ──")

    # ── GUARD: no borrar si ya hay filas completadas ────────────────────────────
    # Si hay aunque sea 1 fila con status 'completed', significa que Flow ya generó
    # imágenes. Borrar en ese estado destruye trabajo ya hecho. En ese caso usar
    # --solo-descargar-hook en su lugar.
    page = 1
    ids_existentes = []
    completed_existentes = []
    while True:
        data = _baserow_curl('GET', f'/database/rows/table/{BASEROW_TABLE_ID}/?user_field_names=true&size=200&page={page}')
        for r in data.get('results', []):
            ids_existentes.append(r['id'])
            status_field = r.get('Status', r.get('field_9772292', {}))
            sv = status_field.get('value', '') if isinstance(status_field, dict) else str(status_field)
            if sv == 'completed':
                completed_existentes.append(r['id'])
        if not data.get('next'): break
        page += 1

    for rid in ids_existentes:
        _baserow_curl('DELETE', f'/database/rows/table/{BASEROW_TABLE_ID}/{rid}/')

    # Subir prompts al formato que ya conoce la extensión VEO
    items = []
    for seg in segments:
        items.append({
            'Image Prompt': seg.get('ia_prompt_en', seg.get('ia_prompt', '')),
            'VEO Prompt':   seg.get('veo_prompt', f"Slow cinematic zoom in, {seg.get('ia_prompt_en', seg.get('ia_prompt',''))[:60]}"),
            'Mode':         'Imagegen',
            'Status':       'pending',
        })

    result = _baserow_curl('POST',
        f'/database/rows/table/{BASEROW_TABLE_ID}/batch/?user_field_names=true',
        {'items': items})
    created = result.get('items', [])
    print(f"\n  ✅ {len(created)} prompts en Baserow — CORRE LA EXTENSIÓN VEO AHORA")
    print(f"  Cuando termines avisa y corre: python3 harvester_farandula.py <carpeta> --solo-descargar-hook")
    sys.stdout.flush()

    # Si no se pidió --descargar, salir aquí
    if '--descargar' not in sys.argv:
        return

    # Mapear row_id → segment_id para guardar con nombre ordenado
    row_to_seg = {created[i]['id']: segments[i]['segment_id']
                  for i in range(min(len(created), len(segments)))}

    # Poll hasta que todos estén completed
    _poll_y_descargar(hook_dir, row_to_seg, segments, len(segments))

    finales = sorted(hook_dir.glob("hook_[0-9]*.jpg"))
    ok(f"Hook: {len(finales)}/{len(segments)} imágenes listas en hook_images/")


def _poll_y_descargar(hook_dir, row_to_seg, segments, n_total):
    """
    Poll Baserow hasta que todas las filas estén completadas.
    Descarga imágenes como JPEG (sin zoompan — VEO3 las animará).
    Guarda veo_prompts.txt con los prompts de animación, uno por línea.
    """
    max_wait = 90 * 60
    waited   = 0
    completed_urls = {}

    while waited < max_wait:
        time.sleep(20)
        waited += 20
        data = _baserow_curl('GET', f'/database/rows/table/{BASEROW_TABLE_ID}/?user_field_names=true&size=200')
        rows = data.get('results', [])
        n_done = 0
        for r in rows:
            sv = r.get('Status', '')
            if isinstance(sv, dict): sv = sv.get('value', '')
            if sv in ('completed', 'failed'): n_done += 1
            if sv == 'completed' and r['id'] not in completed_urls:
                url = r.get('Video_URL', '') or r.get('Image_URL', '')
                if url and url.startswith('http'):
                    completed_urls[r['id']] = url
        print(f"  [{waited}s] {n_done}/{len(rows)} procesadas...", flush=True)
        if n_done >= len(rows) and len(rows) > 0:
            break

    # Descargar imagen → guardar como JPEG sin zoompan
    for idx, (row_id, img_url) in enumerate(completed_urls.items(), start=1):
        dest = hook_dir / f"hook_{idx:04d}.jpg"
        if dest.exists():
            ok(f"  hook_{idx:04d}.jpg ya existe")
            continue

        # Intentar descarga directa (imagen) o extracción de frame si es video
        raw = hook_dir / f"hook_raw_{idx:04d}.mp4"
        subprocess.run([
            YTDLP, '--cookies-from-browser', 'brave',
            '-o', str(raw), '--no-playlist', '-q', img_url
        ], capture_output=True, timeout=90)

        if raw.exists() and raw.stat().st_size > 5000:
            # Es video → extraer primer frame como JPEG limpio (sin zoompan)
            subprocess.run([
                FFMPEG, '-y', '-i', str(raw),
                '-frames:v', '1', '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2',
                str(dest)
            ], capture_output=True, timeout=15)
            raw.unlink(missing_ok=True)
        else:
            # Intentar como URL de imagen directa
            try:
                import urllib.request
                urllib.request.urlretrieve(img_url, str(dest))
            except Exception:
                pass
            raw.unlink(missing_ok=True)

        if dest.exists():
            ok(f"  hook_{idx:04d}.jpg ✓ (sin zoompan — lista para VEO3)")
        else:
            err(f"  hook_{idx:04d} falló")

    # Guardar veo_prompts.txt — numerado, uno por línea
    prompts_txt = hook_dir / "veo_prompts.txt"
    import re as _re
    lineas = [_re.sub(r'^\d+\.?\s*', '', seg.get('veo_prompt', '').strip()) for seg in segments]
    prompts_txt.write_text("\n\n".join(lineas), encoding="utf-8")
    ok(f"  veo_prompts.txt guardado ({len(lineas)} prompts)")
    print(f"\n  📋 Prompts de animación en: {prompts_txt}")
    print(f"  🎬 Anima hook_0001.jpg→hook_{len(lineas):04d}.jpg con VEO3")
    print(f"  📁 Coloca los MP4 animados en: {hook_dir}/")
    print(f"  ✅ Cuando estén listos avisa para mostrar el dashboard", flush=True)

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 harvester_farandula.py <carpeta_video> [--artista NOMBRE]")
        sys.exit(1)

    folder = pathlib.Path(sys.argv[1])
    if not folder.is_dir():
        print(f"ERROR: No existe {folder}")
        sys.exit(1)

    solo_artista = None
    if '--artista' in sys.argv:
        idx = sys.argv.index('--artista')
        solo_artista = sys.argv[idx + 1].upper()

    # Modo solo-hook: sube prompts a Baserow y sale
    # Con --descargar: además hace polling y descarga los videos
    if '--solo-hook' in sys.argv:
        harvester_hook(folder)
        return

    # Modo solo descarga del hook (después de que el usuario corrió la extensión VEO)
    if '--solo-descargar-hook' in sys.argv:
        hook_file = folder / "hook_timeline.json"
        all_segs  = json.loads(hook_file.read_text()).get("visual_timeline", [])
        # Solo los segmentos flow tienen fila en Baserow
        segments  = [s for s in all_segs if s.get("type", "flow") == "flow"]
        hook_dir  = folder / "hook_images"
        hook_dir.mkdir(exist_ok=True)
        data = _baserow_curl('GET', f'/database/rows/table/{BASEROW_TABLE_ID}/?user_field_names=true&size=200')
        rows = data.get('results', [])
        row_to_seg = {rows[i]['id']: segments[i]['segment_id']
                      for i in range(min(len(rows), len(segments)))}
        _poll_y_descargar(hook_dir, row_to_seg, segments, len(segments))
        finales = sorted(hook_dir.glob("hook_[0-9]*.jpg"))
        ok(f"Hook: {len(finales)}/{len(segments)} imágenes flow listas")
        return

    ts_file = folder / "timestamps.json"
    if not ts_file.exists():
        print(f"ERROR: No existe {ts_file} — corre primero timestamps_farandula.py")
        sys.exit(1)

    brave_key = leer_key(BRAVE_KEY_FILE)
    if not brave_key:
        print(f"ERROR: Sin Brave API key en {BRAVE_KEY_FILE}")
        sys.exit(1)

    timestamps = json.loads(ts_file.read_text(encoding="utf-8"))

    print(f"\n{'='*60}")
    print(f"  HARVESTER FARANDULA — Brave Search → Flow Hook")
    print(f"  Video: {folder.name}")
    print(f"{'='*60}\n")

    # Imágenes temáticas para la intro via Flow
    harvester_hook(folder)

    for seg in timestamps:
        if seg.get('is_hook') or seg.get('is_cierre'):
            continue

        nombre   = seg['name']
        dur      = seg['duration']
        n_planos = planos_necesarios(dur)

        if solo_artista and solo_artista not in nombre.upper():
            continue

        carpeta_ic = buscar_carpeta_icloud(nombre)
        n_mp4, n_img = contar_clips(carpeta_ic)

        # Con 5+ mp4 clips el render los loopea — no necesitamos más
        if n_mp4 >= 5:
            ok(f"{nombre} — {n_mp4} mp4 clips (loop OK)")
            continue

        # Calcular cuántos clips más necesitamos
        n_total  = n_mp4 + n_img
        n_faltan = max(0, n_planos - n_total)

        if n_faltan == 0:
            ok(f"{nombre} — {n_total} assets suficientes")
            continue

        # Crear carpeta iCloud si no existe
        if carpeta_ic is None:
            nombre_display = nombre.replace("_", " ").title()
            carpeta_ic = ICLOUD_ARTISTAS / nombre_display
            carpeta_ic.mkdir(parents=True, exist_ok=True)
            warn(f"Carpeta creada: {carpeta_ic.name}")

        print(f"\n  ── {nombre} ({n_faltan} imágenes) ──")

        # Nombre para mostrar en búsqueda
        nombre_display = (nombre.replace("ECHANOVE", "ECHANOVE actor mexicano")
                               .replace("CHUPITOS", "Chupitos Liliana Raga actriz")
                               .replace("LALO ESPAÑA", "Lalo España actor vecinos")
                               .replace("JORGE FALCON", "Jorge Falcón conductor Televisa")
                               .replace("FLACO GUZMAN", "Roberto Flaco Guzmán actor")
                               .replace("POLO POLO", "Polo Polo comediante mexicano"))
        nombre_display = nombre_display.title()

        # Queries de Brave variadas
        queries = [
            f"{nombre_display}",
            f"{nombre_display} Televisa",
            f"{nombre_display} actor comediante",
            f"{nombre_display} foto",
        ]

        idx_actual   = siguiente_idx(carpeta_ic)
        generados    = 0
        hashes_prev  = hashes_existentes(carpeta_ic)  # evitar duplicados

        for query in queries:
            if generados >= n_faltan:
                break
            urls = buscar_brave(query, brave_key, count=BRAVE_COUNT)
            random.shuffle(urls)

            for url in urls:
                if generados >= n_faltan:
                    break
                dest = carpeta_ic / f"foto_{idx_actual:04d}.jpg"

                if descargar_imagen(url, dest, hashes_prev):
                    ok(f"  #{idx_actual} → {dest.name}")
                    generados += 1
                    idx_actual += 1
                else:
                    dest.unlink(missing_ok=True)

        if generados < n_faltan:
            warn(f"{nombre}: Brave consiguió {generados}/{n_faltan} — usando lo que hay (sin Flow)")
        else:
            ok(f"{nombre}: {generados} fotos listos en iCloud")

    print(f"\n{'='*60}")
    print(f"  ✅ Harvester completado.")
    print(f"  Siguiente: render_farandula.py")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
