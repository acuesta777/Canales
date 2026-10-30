#!/usr/bin/env python3
"""
Convierte fotos a clips MP4 con:
- Fondo blur fill 16:9 (imagen escalada y difuminada para rellenar 1920x1080)
- Imagen original centrada sin recortar
- Zoompan animado (8 variaciones, rotando)
- Sin pixelado — siempre blur fill

Uso: python3 fotos_a_clips.py "Nombre Artista"
"""
import pathlib, subprocess, sys, os, unicodedata, re
from icloud_match import buscar_carpeta_icloud as _buscar_carpeta_segura

ICLOUD_ART = pathlib.Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"
CLIP_DUR   = 7.0   # segundos por clip
FPS        = 25
ANCHO      = 1920
ALTO       = 1080

# 8 variaciones de zoompan — z=1.5 FIJO (pan ~16.7% del frame, visible y energético)
_Z  = 1.5
_F  = int(FPS * CLIP_DUR)
ZOOM_EXPRS = [
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(on/{_F})':y='ih/2-(ih/{_Z}/2)':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",         # right
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(1-on/{_F})':y='ih/2-(ih/{_Z}/2)':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",       # left
    f"zoompan=z='{_Z}':x='iw/2-(iw/{_Z}/2)':y='(ih-ih/{_Z})*0.5*(on/{_F})':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",         # down
    f"zoompan=z='{_Z}':x='iw/2-(iw/{_Z}/2)':y='(ih-ih/{_Z})*0.5*(1-on/{_F})':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",       # up
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(on/{_F})':y='(ih-ih/{_Z})*0.5*(on/{_F})':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",       # diag_dr
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(1-on/{_F})':y='(ih-ih/{_Z})*0.5*(1-on/{_F})':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",  # diag_ul
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(on/{_F})':y='(ih-ih/{_Z})*0.5*(1-on/{_F})':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",   # diag_dl
    f"zoompan=z='{_Z}':x='(iw-iw/{_Z})*0.5*(1-on/{_F})':y='(ih-ih/{_Z})*0.5*(on/{_F})':d={_F}:s={ANCHO}x{ALTO}:fps={FPS}",   # diag_ur
]

def norm(s):
    s = unicodedata.normalize('NFD', s.lower())
    return re.sub(r'[^a-z0-9 ]', '', ''.join(c for c in s if unicodedata.category(c) != 'Mn'))

def buscar_carpeta(nombre):
    return _buscar_carpeta_segura(nombre)

def convertir_foto(foto_path, salida_path, variacion):
    """
    Convierte una foto a clip MP4 con blur fill 16:9 + zoompan.
    - Fondo: imagen escalada al fill 1920x1080 + boxblur fuerte
    - Frente: imagen escalada al fit dentro de 1920x1080, centrada
    - Zoompan aplicado al resultado final
    """
    zoom_expr = ZOOM_EXPRS[variacion % len(ZOOM_EXPRS)]

    # Paso 1: generar frame compuesto (blur fill + imagen encima) a resolución intermedia
    # Luego aplicar zoompan
    filtro = (
        # Fondo: escalar al fill 1920x1080 y difuminar
        f"[0:v]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,"
        f"crop={ANCHO}:{ALTO},"
        f"boxblur=20:5[bg];"
        # Frente: escalar al fit dentro de 1920x1080 manteniendo aspecto
        f"[0:v]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=decrease[fg];"
        # Overlay centrado
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[comp];"
        # Zoompan sobre el compuesto
        f"[comp]{zoom_expr},setsar=1[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(foto_path),
        "-filter_complex", filtro,
        "-map", "[out]",
        "-t", str(CLIP_DUR),
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "28",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        str(salida_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.returncode == 0, result.stderr

def main():
    nombre = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Rafael Inclán"
    carpeta = buscar_carpeta(nombre)

    if not carpeta:
        print(f"❌ No se encontró carpeta para: {nombre}")
        sys.exit(1)

    print(f"📁 Carpeta: {carpeta.name}")

    fotos = sorted([
        f for f in carpeta.iterdir()
        if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')
    ])

    if not fotos:
        print("❌ No hay fotos en la carpeta.")
        sys.exit(1)

    print(f"📸 Fotos encontradas: {len(fotos)}")
    print(f"🎬 Duración por clip: {CLIP_DUR}s | FPS: {FPS} | Resolución: {ANCHO}x{ALTO}")
    print()

    ok = 0
    fallos = []
    for i, foto in enumerate(fotos):
        nombre_clip = f"img_{i+1:03d}_zp.mp4"
        salida = carpeta / nombre_clip

        if salida.exists():
            print(f"  ⏭  {foto.name[:50]} → ya existe {nombre_clip}")
            ok += 1
            continue

        print(f"  [{i+1}/{len(fotos)}] {foto.name[:50]} → variación {i % len(ZOOM_EXPRS)} ...", end="", flush=True)
        exito, stderr = convertir_foto(foto, salida, i)

        if exito:
            size_mb = salida.stat().st_size / 1024 / 1024
            print(f" ✅ {size_mb:.1f}MB")
            ok += 1
        else:
            print(f" ❌ ERROR")
            fallos.append((foto.name, stderr[-200:]))

    print(f"\n{'='*50}")
    print(f"✅ Convertidos: {ok}/{len(fotos)}")
    if fallos:
        print(f"❌ Fallos: {len(fallos)}")
        for nombre_f, err in fallos:
            print(f"   {nombre_f}: {err}")

    # Contar clips existentes ahora
    clips_totales = len([f for f in carpeta.glob("*.mp4") if "_zp" in f.stem])
    print(f"\n📊 Total clips _zp en carpeta: {clips_totales}")
    print(f"ℹ️  Calcular cuántos hacen falta DESPUÉS del TTS: slots=ceil(duracion/7.5) + buffer 30%")

if __name__ == "__main__":
    main()
