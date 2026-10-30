#!/usr/bin/env python3
"""
extraer_clips_video.py — Descarga un video de YouTube y extrae clips limpios.

Hace automáticamente:
  1. Descarga el video (1080p, cookies Brave)
  2. Detecta logo en esquina superior derecha (primer frame)
  3. Corta en clips de 5s
  4. Aplica: crop logo + crop subtítulos + corrección de color + re-encode
  5. Guarda N clips en la carpeta destino (sin borrar lo que ya existe)

Uso:
  python3 extraer_clips_video.py <youtube_url> <carpeta_destino> [opciones]

Ejemplos:
  python3 extraer_clips_video.py "https://youtube.com/watch?v=XXX" "iCloud/Artistas/Chupitos"
  python3 extraer_clips_video.py "https://youtube.com/watch?v=XXX" "iCloud/Artistas/Chupitos" --clips 50
  python3 extraer_clips_video.py "https://youtube.com/watch?v=XXX" "iCloud/Artistas/Chupitos" --desde 120 --hasta 480
  python3 extraer_clips_video.py "https://youtube.com/watch?v=XXX" "iCloud/Artistas/Chupitos" --clips 40 --prefix rogelio

Opciones:
  --clips N       Cuántos clips guardar (default: 50)
  --desde S       Segundo de inicio en el video (default: 0)
  --hasta S       Segundo de fin en el video (default: fin del video)
  --prefix STR    Prefijo del nombre de archivo (default: clip)
  --no-color      No aplicar corrección de color
  --clip-dur S    Duración de cada clip en segundos (default: 5)
"""

import sys, os, re, json, random, subprocess, pathlib, argparse, tempfile, shutil

YTDLP   = "/opt/homebrew/bin/yt-dlp"
FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"

CLIP_DUR    = 5      # segundos por clip
LOGO_X_PCT  = 0.85  # si hay texto en el X% derecho del frame → es logo
LOGO_H_PCT  = 0.08  # altura del logo en % del frame
SUB_H_PX    = 80    # píxeles a cortar de abajo para subtítulos
COLOR_FIX   = "eq=contrast=1.2:saturation=1.3:gamma=0.95,unsharp=3:3:0.3"


def run(cmd, timeout=60, capture=True):
    return subprocess.run(cmd, capture_output=capture, timeout=timeout)


def get_video_info(path):
    r = run([FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-show_entries", "format=duration",
             "-of", "json", str(path)], timeout=15)
    d = json.loads(r.stdout)
    w = int(d["streams"][0]["width"])
    h = int(d["streams"][0]["height"])
    dur = float(d["format"]["duration"])
    return w, h, dur


def detectar_logo(video_path, w, h):
    """
    Extrae el primer frame y detecta si hay logo en la esquina superior derecha.
    Devuelve (logo_x, logo_y, logo_w, logo_h) o None si no detecta nada.
    Heurística: si los píxeles de la esquina superior derecha son muy brillantes
    o muy blancos (texto blanco sobre fondo oscuro), hay logo.
    """
    tmp = pathlib.Path(tempfile.mktemp(suffix=".jpg"))
    run([FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-i", str(video_path), "-vframes", "1", str(tmp)], timeout=15)
    if not tmp.exists():
        return None

    # Zona probable del logo: esquina sup-der (15% ancho, 8% alto)
    logo_x = int(w * LOGO_X_PCT)
    logo_y = 0
    logo_w = w - logo_x
    logo_h = int(h * LOGO_H_PCT)

    try:
        from PIL import Image, ImageStat
        img  = Image.open(tmp).convert("L")  # escala de grises
        crop = img.crop((logo_x, logo_y, w, logo_h))
        mean = ImageStat.Stat(crop).mean[0]
        tmp.unlink(missing_ok=True)
        # Si hay píxeles muy brillantes en esa zona → probable logo blanco
        if mean > 160:
            print(f"  Logo detectado en esquina sup-der (brillo medio={mean:.0f})")
            return logo_x, logo_y, logo_w, logo_h
        else:
            print(f"  Sin logo detectado (brillo={mean:.0f})")
            return None
    except ImportError:
        tmp.unlink(missing_ok=True)
        # Sin PIL: asumir que hay logo y aplicar crop conservador
        print("  PIL no disponible — aplicando crop de logo por defecto")
        return int(w * 0.85), 0, int(w * 0.15), int(h * 0.08)


def construir_vfilter(w, h, logo_region, apply_color, blur_logo=False):
    """
    Construye el filtro ffmpeg:
    1. Corrección de color (opcional)
    2a. blur_logo=False (default): crop elimina el logo de la derecha y subtítulos de abajo
    2b. blur_logo=True: aplica blur gaussiano sobre la zona del logo (preserva composición)
    3. Scale a 1280px de ancho manteniendo proporción par
    """
    parts = []

    if apply_color:
        parts.append(COLOR_FIX)

    crop_h = h - SUB_H_PX

    if blur_logo and logo_region:
        lx, ly, lw, lh = logo_region
        # Blur gaussiano sobre la esquina superior derecha (zona del logo)
        # Formato: [in]split[orig][blur];[blur]crop=lw:lh:lx:ly,boxblur=20:5[blurred];[orig][blurred]overlay=lx:ly
        blur_filter = (
            f"[0:v]split[orig][blur];"
            f"[blur]crop={lw}:{lh}:{lx}:{ly},boxblur=20:5[blurred];"
            f"[orig][blurred]overlay={lx}:{ly}[blurred_full];"
            f"[blurred_full]crop={w}:{crop_h}:0:0"
        )
        # Devolver como filtergraph complejo — el llamador detecta el punto y coma
        parts.append(blur_filter)
    else:
        if logo_region and not blur_logo:
            lx, ly, lw, lh = logo_region
            crop_w = lx
        else:
            crop_w = w
        parts.append(f"crop={crop_w}:{crop_h}:0:0")

    # Scale a 1280 de ancho, alto par
    out_w = 1280
    crop_w_final = w if blur_logo else (logo_region[0] if logo_region else w)
    out_h = int(crop_h * out_w / crop_w_final)
    if out_h % 2 != 0:
        out_h += 1
    parts.append(f"scale={out_w}:{out_h}")

    return ",".join(parts)


def _run_ytdlp_download(url, dest_path, player_client, extra_args=None):
    cmd = [YTDLP, "--cookies-from-browser", "brave",
           "--extractor-args", f"youtube:player_client={player_client}",
           "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]",
           "--merge-output-format", "mp4",
           "-o", str(dest_path), "-q", "--no-playlist"]
    if extra_args:
        cmd += extra_args
    cmd.append(url)
    subprocess.run(cmd, timeout=600)
    p = pathlib.Path(str(dest_path))
    if p.exists():
        return p
    for ext in [".mp4", ".webm", ".mkv"]:
        q = pathlib.Path(str(dest_path).replace(".mp4", ext))
        if q.exists():
            return q
    return None


MIN_BYTES_PER_SEC = 1500  # <1.5 KB/s = descarga corrupta → reintentar


def descargar_video(url, dest_path, desde=None, hasta=None):
    print(f"  Descargando: {url}")
    extra = []
    if desde or hasta:
        section = f"*{int(desde or 0)}-{int(hasta)}" if hasta else f"*{int(desde)}-inf"
        extra = ["--download-sections", section]

    # Intento 1: player_client=web
    p = _run_ytdlp_download(url, dest_path, "web", extra)

    # Validar tamaño mínimo: si el archivo es sospechosamente pequeño, reintentar con ios
    if p and p.exists():
        try:
            dur_s = float(subprocess.run(
                [FFPROBE, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
                capture_output=True, text=True, timeout=15
            ).stdout.strip() or "0")
            size_b = p.stat().st_size
            if dur_s > 30 and size_b < dur_s * MIN_BYTES_PER_SEC:
                print(f"  ⚠ Archivo sospechoso ({size_b//1024}KB para {int(dur_s)}s), reintentando con tv_embedded...")
                p.unlink(missing_ok=True)
                p = _run_ytdlp_download(url, dest_path, "tv_embedded", extra)
        except Exception:
            pass

    return p if (p and p.exists()) else None


def cortar_clips(video_path, clips_dir, clip_dur, desde=None, hasta=None, force_reencode=False):
    print(f"  Cortando en segmentos de {clip_dur}s...")
    clips_dir.mkdir(parents=True, exist_ok=True)
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    if desde is not None:
        cmd += ["-ss", str(int(desde))]
    if hasta is not None:
        cmd += ["-to", str(int(hasta))]
    if force_reencode:
        # Duración exacta: re-encoding forzando keyframes cada clip_dur segundos
        cmd += ["-i", str(video_path),
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
                "-c:a", "aac", "-b:a", "128k",
                "-f", "segment", "-segment_time", str(clip_dur),
                "-segment_time_delta", "0.05",
                "-force_key_frames", f"expr:gte(t,n_forced*{clip_dur})",
                "-reset_timestamps", "1",
                str(clips_dir / "raw_%04d.mp4")]
    else:
        # Corte rápido en keyframes (comportamiento original)
        cmd += ["-i", str(video_path),
                "-c", "copy",
                "-f", "segment", "-segment_time", str(clip_dur), "-reset_timestamps", "1",
                str(clips_dir / "raw_%04d.mp4")]
    subprocess.run(cmd, capture_output=True, timeout=1800)
    clips = sorted(clips_dir.glob("raw_*.mp4"))
    print(f"  {len(clips)} clips raw generados")
    return clips


MIN_BRIGHTNESS = 20   # brillo promedio mínimo (0-255); bajo esto = negro
STATIC_DIFF    = 3    # diferencia media entre frame@1s y frame@4s; bajo esto = estático

def _get_gray_frame(clip, t):
    """Extrae un frame en escala de grises 64x36 como bytes."""
    r = subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error",
        "-ss", str(t), "-i", str(clip),
        "-vframes", "1", "-vf", "scale=64:36",
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"
    ], capture_output=True, timeout=10)
    return bytes(r.stdout) if r.returncode == 0 else b""

def clip_valido(clip):
    """Devuelve (True, motivo) si el clip pasa los filtros de negro y estático."""
    f_mid = _get_gray_frame(clip, 2.5)
    if not f_mid or len(f_mid) < 100:
        return False, "sin frames"
    brightness = sum(f_mid) / len(f_mid)
    if brightness < MIN_BRIGHTNESS:
        return False, f"negro (brillo={brightness:.1f})"
    f1 = _get_gray_frame(clip, 1.0)
    f2 = _get_gray_frame(clip, 4.0)
    if f1 and f2 and len(f1) == len(f2):
        diff = sum(abs(a - b) for a, b in zip(f1, f2)) / len(f1)
        if diff < STATIC_DIFF:
            return False, f"estático (diff={diff:.1f})"
    return True, "ok"

def procesar_clips(raw_clips, destino, vfilter, prefix, max_clips):
    print(f"  Procesando {min(len(raw_clips), max_clips)} clips...")
    destino = pathlib.Path(destino)
    destino.mkdir(parents=True, exist_ok=True)

    existing = sorted(destino.glob(f"{prefix}_*.mp4"))
    start_n  = len(existing) + 1

    guardados   = 0
    rechazados  = 0
    n           = start_n
    for i, clip in enumerate(raw_clips):
        if guardados >= max_clips:
            break
        valido, motivo = clip_valido(clip)
        if not valido:
            rechazados += 1
            continue
        out = destino / f"{prefix}_{n:04d}.mp4"
        n  += 1
        # Filtergraph complejo (blur-logo) usa -filter_complex + -map; simple usa -vf
        if ";" in vfilter:
            cmd = [
                FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(clip),
                "-filter_complex", vfilter,
                "-map", "[blurred_full]",
                "-vf", f"scale={1280}:-2",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                "-movflags", "+faststart",
                "-an", str(out)
            ]
        else:
            cmd = [
                FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                "-i", str(clip),
                "-vf", vfilter,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
                "-movflags", "+faststart",
                "-an", str(out)
            ]
        subprocess.run(cmd, capture_output=True, timeout=180)
        if out.exists() and out.stat().st_size > 5000:
            guardados += 1
        if guardados % 25 == 0 and guardados > 0:
            print(f"    {guardados}/{min(len(raw_clips), max_clips)}...")

    if rechazados:
        print(f"  Filtrados: {rechazados} clips (negros/estáticos)")
    return guardados


def main():
    p = argparse.ArgumentParser(description="Extraer clips limpios de un video de YouTube")
    p.add_argument("url",    help="URL del video de YouTube")
    p.add_argument("destino", help="Carpeta destino para los clips")
    p.add_argument("--clips",    type=int,   default=50,    help="Cuántos clips guardar (default: 50)")
    p.add_argument("--desde",    type=float, default=None,  help="Segundo de inicio")
    p.add_argument("--hasta",    type=float, default=None,  help="Segundo de fin")
    p.add_argument("--prefix",   type=str,   default="clip", help="Prefijo del nombre de archivo")
    p.add_argument("--clip-dur", type=int,   default=5,     help="Duración de cada clip en segundos")
    p.add_argument("--no-color",       action="store_true", help="No aplicar corrección de color")
    p.add_argument("--local-video",    type=str, default=None, help="Usar este archivo local en lugar de descargar")
    p.add_argument("--force-reencode", action="store_true", help="Re-encoding para duración exacta (Farandula)")
    p.add_argument("--blur-logo",      action="store_true", help="Blur gaussiano sobre logo en vez de crop (para URL1/fallback)")
    args = p.parse_args()

    destino = pathlib.Path(args.destino)
    print(f"\n{'='*55}")
    print(f"  extraer_clips_video.py")
    print(f"  URL:     {args.url}")
    print(f"  Destino: {destino}")
    print(f"  Clips:   {args.clips} × {args.clip_dur}s  |  Prefix: {args.prefix}")
    if args.desde or args.hasta:
        print(f"  Rango:   {args.desde or 0}s → {args.hasta or 'fin'}s")
    print(f"{'='*55}\n")

    with tempfile.TemporaryDirectory(prefix="extrae_clips_") as tmp:
        tmp = pathlib.Path(tmp)

        # 1. Descargar (o usar video local)
        print("[1/4] Descargando video...")
        if args.local_video:
            local = pathlib.Path(args.local_video)
            if not local.exists():
                print(f"✗ No existe el archivo local: {local}")
                sys.exit(1)
            video = local
            print(f"  ✓ usando local: {local.name} ({local.stat().st_size / 1e6:.0f} MB)")
        else:
            video = descargar_video(args.url, tmp / "video.mp4", args.desde, args.hasta)
            if not video or not video.exists():
                print("✗ Error al descargar el video")
                sys.exit(1)
            print(f"  ✓ {video.name} ({video.stat().st_size / 1e6:.0f} MB)")
            # Backup automático en iCloud/yt usando el nombre de la carpeta destino
            yt_backup = pathlib.Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/yt"
            if yt_backup.exists():
                nombre_backup = pathlib.Path(args.destino).name + ".mp4"
                backup_path = yt_backup / nombre_backup
                if not backup_path.exists():
                    import shutil
                    shutil.copy2(video, backup_path)
                    print(f"  ✓ Backup guardado: iCloud/yt/{nombre_backup}")

        # 2. Info + detectar logo
        print("[2/4] Analizando video...")
        w, h, dur = get_video_info(video)
        print(f"  Resolución: {w}x{h}  |  Duración: {dur:.0f}s")
        logo_region = detectar_logo(video, w, h)

        # 3. Construir filtro
        vfilter = construir_vfilter(w, h, logo_region, not args.no_color, blur_logo=args.blur_logo)
        if args.blur_logo:
            print(f"  Modo: blur-logo (URL fallback — preserva composición)")
        print(f"  Filtro: {vfilter[:80]}...")

        # 4. Cortar en clips raw
        print("[3/4] Cortando clips...")
        clips_dir = tmp / "clips"
        raw_clips = cortar_clips(video, clips_dir, args.clip_dur,
                                  desde=args.desde if args.local_video else None,
                                  hasta=args.hasta if args.local_video else None,
                                  force_reencode=args.force_reencode)
        if not raw_clips:
            print("✗ No se generaron clips")
            sys.exit(1)

        # Mezclar aleatoriamente para variedad
        random.shuffle(raw_clips)

        # 5. Procesar y guardar
        print("[4/4] Procesando y guardando...")
        guardados = procesar_clips(raw_clips, destino, vfilter, args.prefix, args.clips)

    print(f"\n{'='*55}")
    print(f"  ✓ {guardados} clips guardados en:")
    print(f"  {destino}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
