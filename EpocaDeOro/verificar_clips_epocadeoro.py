#!/usr/bin/env python3
"""
verificar_clips_epocadeoro.py — PASO 0 del pipeline La Verdad Dorada.

Verifica si hay suficientes clips en iCloud para cada artista del video.
Si hay déficit, muestra la tabla y espera que el usuario pase URLs de YouTube.

Uso:
  python3 verificar_clips_epocadeoro.py "Lupe Velez" "Andrea Palma" "Miroslava"
  python3 verificar_clips_epocadeoro.py --desde-artistas artistas.txt

Duración esperada por artista: ~230s
Slots necesarios: ceil(230 / 7.5) + 3 = 34
"""

import sys, math, pathlib, unicodedata, subprocess, argparse

FFPROBE  = "/opt/homebrew/bin/ffprobe"
YTDLP    = "/opt/homebrew/bin/yt-dlp"
HOME     = pathlib.Path.home()
ICLOUD   = HOME / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"

SHOT_DUR      = 7.5
DUR_ARTISTA   = 230
SLOTS_NEEDED  = math.ceil(DUR_ARTISTA / SHOT_DUR) + 3   # 34

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
NEGRITA  = "\033[1m"
RESET    = "\033[0m"


def norm(text):
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def buscar_carpeta_icloud(nombre):
    if not ICLOUD.exists():
        return None
    nombre_n = norm(nombre)
    partes   = nombre_n.split()

    for d in ICLOUD.iterdir():
        if not d.is_dir(): continue
        if norm(d.name) == nombre_n: return d

    for d in ICLOUD.iterdir():
        if not d.is_dir(): continue
        dn = norm(d.name)
        if nombre_n in dn or dn in nombre_n: return d

    apellido = partes[-1] if partes else ""
    if len(apellido) >= 5:
        for d in ICLOUD.iterdir():
            if not d.is_dir(): continue
            if apellido in norm(d.name).split(): return d

    return None


def contar_clips(carpeta):
    if not carpeta or not carpeta.exists():
        return 0, 0
    mp4s = [f for f in carpeta.glob("*.mp4") if "_zp" not in f.stem]
    imgs = [f for f in carpeta.iterdir()
            if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')]
    return len(mp4s), len(imgs)


def descargar_clips(nombre, url, n_clips, carpeta):
    """Llama a extraer_clips_video.py para descargar clips del artista."""
    canales_dir = pathlib.Path(__file__).parent.parent
    script      = canales_dir / "extraer_clips_video.py"
    if not script.exists():
        print(f"  {ROJO}✗ No se encontró extraer_clips_video.py en {canales_dir}{RESET}")
        return False

    cmd = [
        "python3", str(script), url, str(carpeta),
        "--clips", str(n_clips),
        "--prefix", norm(nombre.split()[0]),
        "--extractor-args", "youtube:player_client=web",
    ]
    print(f"  Descargando {n_clips} clips de: {url}")
    r = subprocess.run(cmd, timeout=900)
    return r.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Verificar clips iCloud para artistas")
    parser.add_argument("artistas", nargs="*", help="Nombres de artistas")
    parser.add_argument("--desde-artistas", metavar="FILE",
                        help="Archivo .txt con un artista por línea")
    args = parser.parse_args()

    nombres = list(args.artistas)
    if args.desde_artistas:
        f = pathlib.Path(args.desde_artistas)
        if f.exists():
            nombres += [l.strip() for l in f.read_text().splitlines() if l.strip()]

    if not nombres:
        print("Uso: python3 verificar_clips_epocadeoro.py 'Artista 1' 'Artista 2' ...")
        sys.exit(1)

    print(f"\n{NEGRITA}{'='*70}")
    print(f"  VERIFICADOR DE CLIPS — La Verdad Dorada")
    print(f"  Slots necesarios por artista: {SLOTS_NEEDED} ({DUR_ARTISTA}s ÷ {SHOT_DUR}s + 3 extra)")
    print(f"{'='*70}{RESET}\n")

    print(f"  {'#':<3} {'Artista':<30} {'Carpeta iCloud':<28} {'MP4':>5} {'Imgs':>5} {'Estado'}")
    print(f"  {'─'*3} {'─'*30} {'─'*28} {'─'*5} {'─'*5} {'─'*20}")

    deficits = []

    for i, nombre in enumerate(nombres, 1):
        carpeta = buscar_carpeta_icloud(nombre)
        mp4s, imgs = contar_clips(carpeta)
        total = mp4s + imgs

        if not carpeta:
            estado = f"{ROJO}✗ SIN CARPETA{RESET}"
            carpeta_name = "—"
        elif total >= SLOTS_NEEDED:
            estado = f"{VERDE}✓ OK{RESET}"
            carpeta_name = carpeta.name
        else:
            deficit = SLOTS_NEEDED - total
            estado = f"{AMARILLO}⚠ FALTAN {deficit}{RESET}"
            carpeta_name = carpeta.name
            deficits.append({
                "nombre":   nombre,
                "carpeta":  carpeta,
                "mp4s":     mp4s,
                "imgs":     imgs,
                "total":    total,
                "deficit":  deficit,
                "clips_a_bajar": math.ceil(deficit * 1.3),  # 30% extra para rechazos
            })

        print(f"  {i:<3} {nombre:<30} {carpeta_name:<28} {mp4s:>5} {imgs:>5} {estado}")

    print()

    if not deficits:
        print(f"  {VERDE}✓ Todos los artistas tienen clips suficientes — puedes escribir el guion{RESET}\n")
        sys.exit(0)

    # Mostrar artistas con déficit y pedir URLs
    print(f"  {AMARILLO}Artistas con déficit de clips:{RESET}\n")
    for d in deficits:
        clips_extra = d['clips_a_bajar']
        print(f"  {NEGRITA}{d['nombre']}{RESET}")
        print(f"    Tiene: {d['total']} | Necesita: {SLOTS_NEEDED} | Bajar: {clips_extra} clips")

        url = input(f"    URL YouTube para '{d['nombre']}' (Enter para saltar): ").strip()
        if not url:
            print(f"    {AMARILLO}Saltado — se reciclarán clips en el render{RESET}")
            continue

        # Crear carpeta en iCloud si no existe
        carpeta = d["carpeta"]
        if not carpeta:
            carpeta = ICLOUD / d["nombre"]
            carpeta.mkdir(parents=True, exist_ok=True)
            print(f"    Carpeta creada: {carpeta}")

        ok = descargar_clips(d["nombre"], url, clips_extra, carpeta)
        if ok:
            mp4s_new, _ = contar_clips(carpeta)
            print(f"    {VERDE}✓ Ahora tiene {mp4s_new} MP4 en iCloud{RESET}")
        else:
            print(f"    {ROJO}✗ Descarga falló — revisar URL o conexión{RESET}")

    print(f"\n  ✓ Verificación completa — puedes escribir el guion\n")


if __name__ == "__main__":
    main()
