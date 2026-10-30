#!/usr/bin/env python3
"""
cubrir_deficit.py — Cubre déficit de clips por artista en 3 pasos:

  1. Convierte imágenes existentes en la carpeta iCloud del artista → clips _zp.mp4
  2. Extrae fotogramas del video de referencia en el segmento donde se habla del artista,
     los valida con Claude Vision (que el artista aparezca), y los anima con zoompan
  3. Si aún faltan → busca fotos en Brave y las anima con zoompan

Uso:
  python3 cubrir_deficit.py "CARPETA_VIDEO/" --url-ref "https://youtube.com/watch?v=XXX"
  python3 cubrir_deficit.py "CARPETA_VIDEO/" --url-ref "https://..." --artista "Carlos Villagrán"
  python3 cubrir_deficit.py "CARPETA_VIDEO/" --url-ref "https://..." --solo-paso 2

El script lee timestamps.json + audio.srt de la carpeta del video para saber
en qué segundo del video de referencia se habla de cada artista.
"""

import sys, os, re, json, math, pathlib, subprocess, tempfile, shutil, time
import unicodedata, hashlib, urllib.request, urllib.parse, argparse, base64
from icloud_match import buscar_carpeta_icloud as _buscar_carpeta_segura

FFMPEG   = "/opt/homebrew/bin/ffmpeg"
FFPROBE  = "/opt/homebrew/bin/ffprobe"
YTDLP    = "/opt/homebrew/bin/yt-dlp"
HOME     = pathlib.Path.home()
ICLOUD   = HOME / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"
ICLOUD_YT = HOME / "Library/Mobile Documents/com~apple~CloudDocs/yt"
BRAVE_KEY_FILE = HOME / ".brave_key"

SHOT_DUR  = 7.5   # duración slot render
CLIP_DUR  = 7.0   # duración clip generado
FPS       = 25
W, H      = 1920, 1080

LOGO_X_PCT = 0.82   # crop logo: cortar desde este % horizontal
LOGO_H_PCT = 0.09   # crop logo: altura en % del frame
SUB_H_PX   = 85     # píxeles a cortar de abajo (subtítulos)

# Variaciones de zoompan — z=1.5 FIJO (pan ~16.7% del frame, visible y energético)
_Z = 1.5
_F = int(FPS * CLIP_DUR)
ZOOM_EXPRS = [
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(on/{_F})':y='ih/2-(ih/{_Z}/2)':d={_F}:s={W}x{H}:fps={FPS}",
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(1-on/{_F})':y='ih/2-(ih/{_Z}/2)':d={_F}:s={W}x{H}:fps={FPS}",
    f"zoompan=z='{_Z}':x='iw/2-(iw/{_Z}/2)':y='(ih-ih/{_Z})*0.5*(on/{_F})':d={_F}:s={W}x{H}:fps={FPS}",
    f"zoompan=z='{_Z}':x='iw/2-(iw/{_Z}/2)':y='(ih-ih/{_Z})*0.5*(1-on/{_F})':d={_F}:s={W}x{H}:fps={FPS}",
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(on/{_F})':y='(ih-ih/{_Z})*0.5*(on/{_F})':d={_F}:s={W}x{H}:fps={FPS}",
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(1-on/{_F})':y='(ih-ih/{_Z})*0.5*(1-on/{_F})':d={_F}:s={W}x{H}:fps={FPS}",
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(on/{_F})':y='(ih-ih/{_Z})*0.5*(1-on/{_F})':d={_F}:s={W}x{H}:fps={FPS}",
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(1-on/{_F})':y='(ih-ih/{_Z})*0.5*(on/{_F})':d={_F}:s={W}x{H}:fps={FPS}",
]

VERDE  = "\033[92m"; ROJO   = "\033[91m"; AMARILLO = "\033[93m"; RESET = "\033[0m"
def ok(m):   print(f"  {VERDE}✅ {m}{RESET}")
def warn(m): print(f"  {AMARILLO}⚠ {m}{RESET}")
def err(m):  print(f"  {ROJO}✗ {m}{RESET}")


# ── Utilidades ─────────────────────────────────────────────────────────────────

def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z0-9 ]", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))


def buscar_carpeta_icloud(nombre):
    return _buscar_carpeta_segura(nombre)


def contar_clips(carpeta):
    if not carpeta or not carpeta.exists():
        return 0
    return len([f for f in carpeta.glob("*.mp4") if "_zp" not in f.stem or True])


def clips_necesarios(duracion):
    return math.ceil(duracion / SHOT_DUR)


def slots_disponibles(carpeta):
    if not carpeta or not carpeta.exists():
        return 0
    return len(list(carpeta.glob("*.mp4")))


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def imagen_a_clip_zp(img_path, dst_path, variacion=0):
    """Convierte imagen → MP4 con blur-fill 16:9 + zoompan. Retorna True si ok."""
    zoom_expr = ZOOM_EXPRS[variacion % len(ZOOM_EXPRS)]
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
        f"{zoom_expr},fps={FPS}"
    )
    r = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-i", str(img_path),
         "-vf", vf,
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
         "-pix_fmt", "yuv420p", "-an", str(dst_path)],
        capture_output=True, timeout=120
    )
    return r.returncode == 0 and dst_path.exists() and dst_path.stat().st_size > 5000


def get_video_info(path):
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, timeout=15
    )
    d = json.loads(r.stdout)
    w = int(d["streams"][0]["width"])
    h = int(d["streams"][0]["height"])
    dur = float(d["format"]["duration"])
    return w, h, dur


def extraer_frame(video_path, t_sec, dst_jpg):
    """Extrae un frame del video en t_sec, aplica crop logo+subs, guarda JPEG."""
    try:
        w, h, _ = get_video_info(video_path)
    except Exception:
        w, h = W, H

    logo_x  = int(w * LOGO_X_PCT)
    logo_h  = int(h * LOGO_H_PCT)
    crop_h  = h - logo_h - SUB_H_PX
    # Crop: quita logo arriba-derecha y subtítulos abajo
    # Usa el ancho completo pero desde logo_h hacia abajo, hasta h-SUB_H_PX
    vf = f"crop={logo_x}:{crop_h}:0:{logo_h}"

    r = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
         "-ss", str(t_sec), "-i", str(video_path),
         "-vframes", "1", "-vf", vf,
         "-q:v", "2", "-y", str(dst_jpg)],
        capture_output=True, timeout=30
    )
    return r.returncode == 0 and dst_jpg.exists() and dst_jpg.stat().st_size > 3000


def leer_brave_key():
    if BRAVE_KEY_FILE.exists():
        return BRAVE_KEY_FILE.read_text().strip()
    return os.environ.get("BRAVE_KEY", "")


def buscar_brave_imagenes(query, api_key, count=10):
    url = f"https://api.search.brave.com/res/v1/images/search?q={urllib.parse.quote(query)}&count={count}&safesearch=off"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    })
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read()
            try:
                import gzip; raw = gzip.decompress(raw)
            except Exception: pass
            data = json.loads(raw)
        results = []
        for item in data.get("results", []):
            img_url = item.get("properties", {}).get("url") or item.get("url", "")
            if img_url and img_url.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
                results.append(img_url)
        return results
    except Exception as e:
        warn(f"Brave error: {e}")
        return []


def descargar_imagen(url, dst):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
        if len(data) < 5000:
            return False
        dst.write_bytes(data)
        return True
    except Exception:
        return False


# ── SRT parser ─────────────────────────────────────────────────────────────────

def srt_time(t):
    t = t.replace(",", ".")
    parts = t.split(":")
    h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def parse_srt(srt_path):
    entries = []
    content = pathlib.Path(srt_path).read_text(encoding="utf-8", errors="replace")
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        try:
            arrow = lines[1].split("-->")
            start = srt_time(arrow[0].strip())
            end   = srt_time(arrow[1].strip())
            text  = " ".join(lines[2:]).strip()
            text  = re.sub(r"<[^>]+>", "", text)
            entries.append({"start": start, "end": end, "text": text})
        except Exception:
            continue
    return entries


def texto_en_rango(entries, t_start, t_end):
    partes = []
    for e in entries:
        if e["start"] < t_end and e["end"] > t_start:
            partes.append(e["text"])
    return " ".join(partes)


# ── Validación visual con Claude ───────────────────────────────────────────────

def validar_frame_con_ia(img_path, nombre_artista):
    """
    Usa Claude claude-haiku-4-5-20251001 para verificar que el artista aparece en el frame.
    Retorna True si la imagen es válida (el artista aparece claramente).
    """
    try:
        import anthropic
        client = anthropic.Anthropic()
        img_data = base64.standard_b64encode(img_path.read_bytes()).decode()
        ext = img_path.suffix.lower().lstrip(".")
        media = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"

        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media, "data": img_data}},
                    {"type": "text", "text": (
                        f"¿Aparece claramente {nombre_artista} en esta imagen? "
                        "Responde SOLO 'SI' o 'NO'. "
                        "Responde NO si la imagen está borrosa, es un logo, un texto, "
                        "o si aparece otra persona diferente."
                    )}
                ]
            }]
        )
        respuesta = resp.content[0].text.strip().upper()
        return respuesta.startswith("SI") or respuesta.startswith("SÍ")
    except Exception as e:
        warn(f"Validación IA falló: {e} — aceptando frame")
        return True


# ── PASO 1: Imágenes existentes en carpeta iCloud ──────────────────────────────

def paso1_convertir_imagenes(carpeta, nombre, variacion_base=0):
    """
    Convierte todas las imágenes en la carpeta a clips _zp.mp4 y borra los originales.
    Retorna cantidad de clips nuevos generados.
    """
    IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
    imgs = [f for f in carpeta.iterdir() if f.suffix.lower() in IMG_EXT]
    if not imgs:
        return 0

    print(f"\n  [PASO 1] Convirtiendo {len(imgs)} imágenes existentes en '{carpeta.name}'...")
    generados = 0
    for i, img in enumerate(sorted(imgs)):
        stem_safe = re.sub(r"[^\w]", "_", img.stem)[:40]
        dst = carpeta / f"foto_{stem_safe}_zp.mp4"
        if dst.exists():
            img.unlink()
            continue
        variacion = (variacion_base + i) % len(ZOOM_EXPRS)
        if imagen_a_clip_zp(img, dst, variacion):
            ok(f"  {img.name} → {dst.name}")
            img.unlink()
            generados += 1
        else:
            warn(f"  Falló: {img.name}")
    return generados


# ── PASO 2: Fotogramas del video de referencia ─────────────────────────────────

def descargar_video_ref(url, tmp_dir):
    """Descarga el video de referencia si no está ya descargado. Retorna ruta."""
    dst = tmp_dir / "video_ref.mp4"
    if dst.exists() and dst.stat().st_size > 1_000_000:
        return dst

    # Buscar en iCloud/yt primero
    nombre_video = None
    for f in ICLOUD_YT.glob("*.mp4"):
        if "referencia" in f.stem.lower() or "ref" in f.stem.lower():
            return f

    print(f"  Descargando video de referencia...")
    r = subprocess.run(
        [YTDLP, "--cookies-from-browser", "brave",
         "--extractor-args", "youtube:player_client=web",
         "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
         "--merge-output-format", "mp4",
         "-o", str(dst), url],
        capture_output=True, timeout=600
    )
    if r.returncode != 0 or not dst.exists():
        err(f"No se pudo descargar el video de referencia")
        return None
    ok(f"Video descargado: {dst.stat().st_size // 1_000_000}MB")
    return dst


def encontrar_segmento_artista_en_srt(srt_entries, nombre_artista, video_dur):
    """
    Busca en el SRT del video de referencia dónde se habla PRINCIPALMENTE del artista.
    Retorna (inicio_s, fin_s) del segmento más denso de menciones.

    Estrategia: ventana deslizante de 60s, cuenta menciones del nombre → toma la más densa.
    Exige que el nombre aparezca al menos 2 veces en el rango para ser válido.
    """
    nombre_n = norm(nombre_artista)
    palabras_clave = [p for p in nombre_n.split() if len(p) > 3]
    if not palabras_clave:
        return None, None

    VENTANA = 90  # segundos
    PASO    = 15

    mejor_score = 0
    mejor_inicio = None

    t = 0.0
    while t < video_dur - VENTANA:
        texto = texto_en_rango(srt_entries, t, t + VENTANA)
        texto_n = norm(texto)
        score = sum(texto_n.count(p) for p in palabras_clave)
        if score > mejor_score:
            mejor_score = score
            mejor_inicio = t
        t += PASO

    if mejor_score < 2 or mejor_inicio is None:
        return None, None

    # Expandir un poco el rango
    inicio = max(0, mejor_inicio - 10)
    fin    = min(video_dur, mejor_inicio + VENTANA + 10)
    return inicio, fin


def paso2_fotogramas_video_ref(carpeta, nombre, url_ref, srt_ref_path, video_cache_dir, n_objetivo):
    """
    Extrae fotogramas del video de referencia en el segmento del artista,
    los valida con IA y los convierte a clips zoompan.
    Retorna cantidad de clips nuevos.
    """
    print(f"\n  [PASO 2] Buscando fotogramas de '{nombre}' en video de referencia...")

    # Leer SRT del video de referencia
    if not srt_ref_path or not pathlib.Path(srt_ref_path).exists():
        warn("No hay SRT del video de referencia — saltando paso 2")
        return 0

    srt_entries = parse_srt(srt_ref_path)
    if not srt_entries:
        warn("SRT vacío — saltando paso 2")
        return 0

    # Descargar video si no existe
    video_path = descargar_video_ref(url_ref, video_cache_dir)
    if not video_path:
        return 0

    try:
        vw, vh, video_dur = get_video_info(video_path)
    except Exception as e:
        err(f"No se pudo leer el video: {e}")
        return 0

    # Localizar segmento del artista en el SRT
    inicio_s, fin_s = encontrar_segmento_artista_en_srt(srt_entries, nombre, video_dur)
    if inicio_s is None:
        warn(f"No se encontró segmento de '{nombre}' en el SRT de referencia")
        return 0

    # Mostrar segmento y pedir confirmación antes de extraer
    mins_i = int(inicio_s // 60); segs_i = int(inicio_s % 60)
    mins_f = int(fin_s   // 60); segs_f = int(fin_s   % 60)
    texto_seg = texto_en_rango(srt_entries, inicio_s, min(inicio_s + 60, fin_s))
    texto_preview = texto_seg[:300] + ("..." if len(texto_seg) > 300 else "")

    print(f"\n  {'─'*55}")
    print(f"  {AMARILLO}Segmento encontrado para '{nombre}':{RESET}")
    print(f"  ⏱  {mins_i:02d}:{segs_i:02d} → {mins_f:02d}:{segs_f:02d}  ({fin_s-inicio_s:.0f}s)")
    print(f"  📄 Texto del SRT:")
    for linea in texto_preview.split(". "):
        if linea.strip():
            print(f"       {linea.strip()}.")
    print(f"  {'─'*55}")
    print(f"  ¿Extraer fotogramas de este segmento para '{nombre}'? [s/n]: ", end="", flush=True)

    try:
        respuesta = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        respuesta = "n"

    if respuesta not in ("s", "si", "sí", "y", "yes"):
        warn(f"  Saltando extracción de fotogramas para '{nombre}' por indicación del usuario")
        return 0

    print(f"  Extrayendo fotogramas de {inicio_s:.0f}s → {fin_s:.0f}s...")

    # Extraer frames cada N segundos dentro del rango (con margen amplio)
    duracion_seg = fin_s - inicio_s
    # Sacar ~3x los frames que necesitamos para filtrar los malos
    n_frames_objetivo = n_objetivo * 3
    intervalo = max(2.0, duracion_seg / n_frames_objetivo)

    frames_tmp = video_cache_dir / f"frames_{norm(nombre).replace(' ','_')}"
    frames_tmp.mkdir(exist_ok=True)

    generados = 0
    variacion = slots_disponibles(carpeta)  # continuar desde donde quedamos

    t = inicio_s
    frame_idx = 0
    while t < fin_s and generados < n_objetivo:
        frame_jpg = frames_tmp / f"frame_{frame_idx:04d}.jpg"
        if extraer_frame(video_path, t, frame_jpg):
            # Validar con IA
            if validar_frame_con_ia(frame_jpg, nombre):
                stem = f"ref_{frame_idx:04d}"
                dst_zp = carpeta / f"{stem}_zp.mp4"
                if not dst_zp.exists():
                    if imagen_a_clip_zp(frame_jpg, dst_zp, variacion % len(ZOOM_EXPRS)):
                        ok(f"  frame {t:.0f}s → {dst_zp.name}")
                        generados += 1
                        variacion += 1
                    else:
                        warn(f"  zoompan falló en frame {t:.0f}s")
            else:
                print(f"    ✗ frame {t:.0f}s — artista no visible, descartado")
            frame_jpg.unlink(missing_ok=True)
        t += intervalo
        frame_idx += 1

    return generados


# ── PASO 3: Brave → descargar fotos → animar ──────────────────────────────────

def paso3_brave(carpeta, nombre, n_objetivo):
    """
    Busca fotos del artista en Brave, descarga y convierte a clips zoompan.
    Retorna cantidad de clips nuevos generados.
    """
    print(f"\n  [PASO 3] Fotos de Brave para '{nombre}' — se necesitan {n_objetivo} clips")
    print(f"  ¿Buscar fotos de '{nombre}' en Brave y animarlas? [s/n]: ", end="", flush=True)
    try:
        respuesta = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        respuesta = "n"
    if respuesta not in ("s", "si", "sí", "y", "yes"):
        warn(f"  Saltando Brave para '{nombre}'")
        return 0

    brave_key = leer_brave_key()
    if not brave_key:
        warn("No hay Brave API key — saltando paso 3")
        return 0

    queries = [
        f"{nombre} foto",
        f"{nombre} actor Mexico",
        f"{nombre} entrevista foto",
        f"{nombre} telenovela",
    ]

    hashes_existentes = set()
    for mp4 in carpeta.glob("*_zp.mp4"):
        try:
            hashes_existentes.add(md5_file(mp4)[:8])
        except Exception:
            pass

    tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="brave_fotos_"))
    generados = 0
    variacion = slots_disponibles(carpeta)

    for query in queries:
        if generados >= n_objetivo:
            break
        resultados = buscar_brave_imagenes(query, brave_key, count=10)
        for url in resultados:
            if generados >= n_objetivo:
                break
            ext = url.lower().split("?")[0].rsplit(".", 1)[-1]
            if ext not in ("jpg", "jpeg", "png", "webp"):
                ext = "jpg"
            img_tmp = tmp_dir / f"brave_{generados:04d}.{ext}"
            if not descargar_imagen(url, img_tmp):
                continue
            # Dedup por hash
            h = md5_file(img_tmp)[:8]
            if h in hashes_existentes:
                img_tmp.unlink()
                continue
            hashes_existentes.add(h)

            # Validar con IA
            if not validar_frame_con_ia(img_tmp, nombre):
                print(f"    ✗ imagen Brave descartada (artista no visible)")
                img_tmp.unlink()
                continue

            dst_zp = carpeta / f"brave_{generados:04d}_zp.mp4"
            if imagen_a_clip_zp(img_tmp, dst_zp, variacion % len(ZOOM_EXPRS)):
                ok(f"  Brave → {dst_zp.name}")
                generados += 1
                variacion += 1
            img_tmp.unlink()

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return generados


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("carpeta_video", help="Carpeta del video ej: 'VIVIENDO DE FAVOR Y OLVIDADOS/'")
    ap.add_argument("--url-ref", required=True, help="URL YouTube del video de referencia")
    ap.add_argument("--artista", default=None, help="Procesar solo este artista")
    ap.add_argument("--solo-paso", type=int, default=0, choices=[0,1,2,3],
                    help="Correr solo el paso N (0=todos)")
    ap.add_argument("--srt-ref", default=None,
                    help="Ruta al SRT del video de referencia (si ya existe)")
    args = ap.parse_args()

    base_dir = pathlib.Path("/Users/anyelocuesta/Downloads/Canales/Farandula")
    video_dir = base_dir / args.carpeta_video.rstrip("/")
    if not video_dir.exists():
        err(f"No existe: {video_dir}"); sys.exit(1)

    ts_path  = video_dir / "timestamps.json"
    srt_path = video_dir / "audio.srt"
    if not ts_path.exists():
        err(f"No existe timestamps.json en {video_dir}"); sys.exit(1)

    timestamps = json.loads(ts_path.read_text())
    srt_audio  = parse_srt(srt_path) if srt_path.exists() else []

    # Directorio cache compartido para el video de referencia
    video_cache = video_dir / "_video_ref_cache"
    video_cache.mkdir(exist_ok=True)

    # SRT del video de referencia
    srt_ref_path = args.srt_ref
    if not srt_ref_path:
        srt_ref_auto = video_cache / "video_ref.es.vtt"
        srt_ref_auto2 = video_cache / "video_ref.es.srt"
        if srt_ref_auto.exists():
            srt_ref_path = str(srt_ref_auto)
        elif srt_ref_auto2.exists():
            srt_ref_path = str(srt_ref_auto2)
        else:
            # Descargar SRT del video de referencia
            print("  Descargando SRT del video de referencia...")
            r = subprocess.run(
                [YTDLP, "--cookies-from-browser", "brave",
                 "--extractor-args", "youtube:player_client=tv_embedded",
                 "--write-auto-subs", "--write-subs", "--sub-lang", "es",
                 "--skip-download", "-o", str(video_cache / "video_ref"),
                 args.url_ref],
                capture_output=True, timeout=60
            )
            # Buscar SRT descargado
            for f in video_cache.glob("video_ref.*"):
                if f.suffix in (".vtt", ".srt") or ".es" in f.name:
                    srt_ref_path = str(f)
                    break
            if srt_ref_path:
                ok(f"SRT de referencia: {pathlib.Path(srt_ref_path).name}")
            else:
                warn("No se pudo descargar el SRT del video de referencia")

    print(f"\n{'='*60}")
    print(f"  cubrir_deficit.py → {video_dir.name}")
    print(f"{'='*60}")

    artistas = [s for s in timestamps if not s.get("is_hook") and not s.get("is_cierre")]
    if args.artista:
        artistas = [s for s in artistas if norm(s["name"]) == norm(args.artista)]
        if not artistas:
            err(f"Artista '{args.artista}' no encontrado en timestamps.json")
            sys.exit(1)

    resumen = []

    for seg in artistas:
        nombre   = seg["name"]
        duracion = seg.get("duration", 180)
        necesita = clips_necesarios(duracion)

        carpeta = buscar_carpeta_icloud(nombre)
        if not carpeta:
            warn(f"No hay carpeta iCloud para '{nombre}' — creando...")
            carpeta = ICLOUD / nombre
            carpeta.mkdir(exist_ok=True)

        disponibles_antes = slots_disponibles(carpeta)
        if disponibles_antes >= necesita:
            print(f"\n  ✓ {nombre}: {disponibles_antes} clips ≥ {necesita} necesarios — OK")
            continue

        deficit = necesita - disponibles_antes
        print(f"\n{'─'*60}")
        print(f"  {ROJO}DÉFICIT{RESET}: {nombre} — tiene {disponibles_antes}, necesita {necesita} ({deficit} faltan)")

        nuevos_total = 0

        # ── PASO 1 ──────────────────────────────────────────────
        if args.solo_paso in (0, 1):
            n1 = paso1_convertir_imagenes(carpeta, nombre)
            nuevos_total += n1
            if n1:
                print(f"  Paso 1: +{n1} clips de imágenes locales")

        # Recalcular déficit
        disponibles = slots_disponibles(carpeta)
        falta = necesita - disponibles
        if falta <= 0:
            ok(f"  {nombre}: déficit cubierto con paso 1")
            resumen.append((nombre, necesita, disponibles, "paso1"))
            continue

        # ── PASO 2 ──────────────────────────────────────────────
        if args.solo_paso in (0, 2):
            # Con margen 30%
            n_pedir = math.ceil(falta * 1.3)
            n2 = paso2_fotogramas_video_ref(carpeta, nombre, args.url_ref,
                                             srt_ref_path, video_cache, n_pedir)
            nuevos_total += n2
            if n2:
                print(f"  Paso 2: +{n2} clips de video de referencia")

        disponibles = slots_disponibles(carpeta)
        falta = necesita - disponibles
        if falta <= 0:
            ok(f"  {nombre}: déficit cubierto con paso 2")
            resumen.append((nombre, necesita, disponibles, "paso1+2"))
            continue

        # ── PASO 3 ──────────────────────────────────────────────
        if args.solo_paso in (0, 3):
            n_pedir = math.ceil(falta * 1.3)
            n3 = paso3_brave(carpeta, nombre, n_pedir)
            nuevos_total += n3
            if n3:
                print(f"  Paso 3: +{n3} clips de Brave")

        disponibles = slots_disponibles(carpeta)
        falta = necesita - disponibles
        estado = "cubierto" if falta <= 0 else f"FALTAN {falta}"
        resumen.append((nombre, necesita, disponibles, estado))

    # ── Resumen final ────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  RESUMEN")
    print(f"  {'Artista':<28} {'Necesita':>9} {'Tiene':>6} {'Estado'}")
    print(f"  {'─'*55}")
    for nombre, nec, tiene, estado in resumen:
        color = VERDE if "cubierto" in estado or "paso" in estado else ROJO
        print(f"  {nombre:<28} {nec:>9} {tiene:>6}  {color}{estado}{RESET}")

    print()
    ok("Listo — correr harvester_clips_farandula.py y dashboard_farandula.py para aprobar")


if __name__ == "__main__":
    main()
