#!/usr/bin/env python3
"""
extraer_fotos_video_ref.py — Extrae fotos de un video de referencia, las anima con zoompan y guarda solo MP4.

Uso:
  python3 extraer_fotos_video_ref.py "https://youtube.com/watch?v=XXX" \
      "Kevin Hagen:145:285" "Merlin Olsen:285:463" "Richard Bull:463:617"

  O con timestamps automáticos desde el SRT (busca "puesto número N" + nombre):
  python3 extraer_fotos_video_ref.py "https://youtube.com/watch?v=XXX" \
      "Kevin Hagen" "Merlin Olsen" "Richard Bull"

Parámetros:
  - URL del video de referencia
  - Artistas con timestamps opcionales (nombre:inicio:fin en segundos)

Resultado:
  - iCloud/Artistas/[Nombre]/ con clips _zp.mp4 con zoompan animado
  - Las fotos JPG se eliminan al terminar
"""
import sys, re, pathlib, subprocess, shutil, tempfile, argparse
from PIL import Image, ImageStat, ImageFilter

ICLOUD      = pathlib.Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
ICLOUD_ART  = ICLOUD / "Artistas"
ICLOUD_YT   = ICLOUD / "yt"
YTDLP       = "/opt/homebrew/bin/yt-dlp"
FFMPEG      = "ffmpeg"
BRILLO_MIN  = 30    # frames con brillo < esto se descartan (negros/transiciones)
FOTO_CADA   = 4     # 1 foto cada N segundos
CLIP_DUR    = 7.0
FPS         = 25
ANCHO, ALTO = 1920, 1080

# z=1.5 FIJO — pan ~16.7% del frame (visible y energético)
_Z = 1.5
_F = int(FPS * CLIP_DUR)
ZOOM_EXPRS = [
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(on/{_F})':y='ih/2-(ih/{_Z}/2)':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(1-on/{_F})':y='ih/2-(ih/{_Z}/2)':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",
    f"zoompan=z='{_Z}':x='iw/2-(iw/{_Z}/2)':y='(ih-ih/{_Z})*0.5*(on/{_F})':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",
    f"zoompan=z='{_Z}':x='iw/2-(iw/{_Z}/2)':y='(ih-ih/{_Z})*0.5*(1-on/{_F})':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(on/{_F})':y='(ih-ih/{_Z})*0.5*(on/{_F})':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(1-on/{_F})':y='(ih-ih/{_Z})*0.5*(1-on/{_F})':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(on/{_F})':y='(ih-ih/{_Z})*0.5*(1-on/{_F})':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(1-on/{_F})':y='(ih-ih/{_Z})*0.5*(on/{_F})':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",
]


def descargar_video(url):
    """Descarga el video a iCloud/yt/ si no existe. Retorna ruta local."""
    # Obtener título para nombre de archivo
    r = subprocess.run(
        [YTDLP, "--cookies-from-browser", "brave",
         "--extractor-args", "youtube:player_client=web",
         "--skip-download", "--print", "%(id)s"],
        capture_output=True, text=True
    )
    vid_id = r.stdout.strip().split('\n')[0] if r.returncode == 0 else "ref"
    dest = ICLOUD_YT / f"ref_{vid_id}.mp4"
    if dest.exists():
        print(f"  ✓ Video ya en iCloud/yt/{dest.name}")
        return dest
    print(f"  ⬇ Descargando video de referencia...")
    subprocess.run([
        YTDLP, "--cookies-from-browser", "brave",
        "--extractor-args", "youtube:player_client=web",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
        "--merge-output-format", "mp4",
        "-o", str(dest), url
    ], check=True)
    print(f"  ✓ Guardado en iCloud/yt/{dest.name}")
    return dest


def detectar_timestamps_srt(url):
    """Descarga SRT y detecta timestamps de secciones 'puesto número N'."""
    print("  Descargando SRT para detectar timestamps...")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([
            YTDLP, "--cookies-from-browser", "brave",
            "--extractor-args", "youtube:player_client=tv_embedded",
            "--write-auto-subs", "--sub-lang", "es",
            "--skip-download", "-o", f"{tmp}/ref", url
        ], capture_output=True)
        vtt_files = list(pathlib.Path(tmp).glob("*.vtt"))
        if not vtt_files:
            return {}
        text = vtt_files[0].read_text()

    def srt_time(t):
        t = t.replace(',', '.').strip()
        h, m, s = t.split(':')
        return float(h)*3600 + float(m)*60 + float(s)

    blocks = text.strip().split('\n\n')
    # Detectar inicio de cada sección
    secciones = []
    for block in blocks:
        if '-->' not in block:
            continue
        lines = block.strip().split('\n')
        time_line = next(l for l in lines if '-->' in l)
        start = srt_time(time_line.split('-->')[0])
        content = re.sub(r'<[^>]+>', '', ' '.join(lines[2:])).lower()
        if 'puesto número' in content or 'puesto numero' in content:
            secciones.append(start)

    return secciones


def extraer_frames(video_path, inicio, fin, tmp_dir):
    """Extrae frames cada FOTO_CADA segundos, retorna lista de paths."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = str(tmp_dir / "frame_%04d.jpg")
    subprocess.run([
        FFMPEG, "-y", "-ss", str(inicio), "-to", str(fin),
        "-i", str(video_path),
        "-vf", f"fps=1/{FOTO_CADA},scale={ANCHO}:{ALTO}",
        "-q:v", "2", out
    ], capture_output=True, timeout=300)
    return sorted(tmp_dir.glob("frame_*.jpg"))


def aplicar_blur(img_path):
    """Aplica blur en zona de subtítulos y logo. Retorna imagen PIL."""
    img = Image.open(img_path)
    w, h = img.size
    # Subtítulos: últimos 180px
    sub_box = (0, h-180, w, h)
    img.paste(img.crop(sub_box).filter(ImageFilter.GaussianBlur(25)), sub_box)
    # Logo sup-izq
    logo_box = (0, 0, 250, 80)
    img.paste(img.crop(logo_box).filter(ImageFilter.GaussianBlur(20)), logo_box)
    return img


def foto_a_mp4(foto_path, out_mp4, variacion):
    """Convierte una foto JPG a MP4 con fondo blur fill + zoompan."""
    zoom_expr = ZOOM_EXPRS[variacion % len(ZOOM_EXPRS)]
    fc = (
        f"[0:v]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=decrease,"
        f"pad={ANCHO}:{ALTO}:(ow-iw)/2:(oh-ih)/2[img];"
        f"[0:v]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,"
        f"crop={ANCHO}:{ALTO},boxblur=20:5[bg];"
        f"[bg][img]overlay=(W-w)/2:(H-h)/2[base];"
        f"[base]{zoom_expr}[out]"
    )
    subprocess.run([
        FFMPEG, "-y", "-loop", "1", "-i", str(foto_path),
        "-filter_complex", fc,
        "-map", "[out]",
        "-t", str(CLIP_DUR),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "26",
        "-pix_fmt", "yuv420p",
        str(out_mp4)
    ], capture_output=True, timeout=120)


def procesar_artista(nombre, inicio, fin, video_path):
    dest = ICLOUD_ART / nombre
    dest.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = pathlib.Path(tmp) / "frames"
        print(f"\n  [{nombre}] Extrayendo frames {inicio}s → {fin}s...")
        frames = extraer_frames(video_path, inicio, fin, tmp_dir)
        print(f"  [{nombre}] {len(frames)} frames extraídos")

        buenos = 0
        for i, foto in enumerate(sorted(frames)):
            # Filtrar negros
            brillo = ImageStat.Stat(Image.open(foto).convert("L")).mean[0]
            if brillo < BRILLO_MIN:
                continue

            # Aplicar blur
            img_blur = aplicar_blur(foto)
            foto_blur = tmp_dir / f"blur_{i:04d}.jpg"
            img_blur.save(foto_blur, "JPEG", quality=92)

            # Convertir a MP4 con zoompan
            out_mp4 = dest / f"{nombre.replace(' ','_').lower()}_{buenos+1:04d}_zp.mp4"
            foto_a_mp4(foto_blur, out_mp4, buenos)
            if out_mp4.exists() and out_mp4.stat().st_size > 1000:
                buenos += 1
            else:
                out_mp4.unlink(missing_ok=True)

    # Eliminar JPGs de la carpeta destino (si quedaron de antes)
    for jpg in dest.glob("*.jpg"):
        jpg.unlink()

    print(f"  [{nombre}] ✅ {buenos} clips MP4 con zoompan")
    return buenos


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="URL del video de referencia")
    parser.add_argument("artistas", nargs="+",
                        help="Artistas: 'Nombre' o 'Nombre:inicio:fin'")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"extraer_fotos_video_ref.py")
    print(f"{'='*60}")

    # Descargar video
    print("\n📥 Preparando video de referencia...")
    video_path = descargar_video(args.url)

    # Parsear artistas con o sin timestamps
    artistas_con_ts = []
    artistas_sin_ts = []
    for a in args.artistas:
        partes = a.split(':')
        if len(partes) == 3:
            artistas_con_ts.append((partes[0], float(partes[1]), float(partes[2])))
        else:
            artistas_sin_ts.append(a)

    # Detectar timestamps automáticamente si hay artistas sin ellos
    if artistas_sin_ts:
        print("\n🔍 Detectando timestamps desde SRT...")
        secciones = detectar_timestamps_srt(args.url)
        if secciones:
            print(f"  {len(secciones)} secciones detectadas: {[f'{s:.0f}s' for s in secciones]}")
            # Asignar secciones en orden inverso (el video va de 10 a 1)
            for i, nombre in enumerate(artistas_sin_ts):
                if i < len(secciones):
                    inicio = secciones[i]
                    fin = secciones[i+1] if i+1 < len(secciones) else inicio + 180
                    artistas_con_ts.append((nombre, inicio, fin))
                else:
                    print(f"  ⚠️  No se encontró timestamp para {nombre}")
        else:
            print("  ⚠️  No se pudo detectar timestamps automáticamente")
            print("  Usa el formato: 'Nombre:inicio_segundos:fin_segundos'")
            sys.exit(1)

    # Procesar cada artista
    print(f"\n🎬 Procesando {len(artistas_con_ts)} artistas...")
    total = 0
    for nombre, inicio, fin in artistas_con_ts:
        clips = procesar_artista(nombre, inicio, fin, video_path)
        total += clips

    print(f"\n{'='*60}")
    print(f"✅ LISTO — {total} clips MP4 generados en total")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
