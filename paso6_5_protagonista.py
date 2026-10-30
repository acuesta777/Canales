#!/usr/bin/env python3
"""
paso6_5_protagonista.py — PASO 6.5: Fotos del protagonista en el timeline.

Detecta en el SRT cada línea donde se menciona el nombre del protagonista,
genera clips blur+zoom de esa foto (5s) y los inserta en timeline.json +
metadata.json como segmentos aprobados.

Uso:
    python3 paso6_5_protagonista.py <carpeta_video> [--nombre "José Alfredo"] [--foto foto.jpg] [--contact-sheet grid.jpg --grid 3x3]

Si --nombre se omite, lo extrae del slug de la carpeta (kebab → título).
Si --foto / --contact-sheet se omiten, los busca en 00-research/.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys
import unicodedata

FFMPEG = "/opt/homebrew/bin/ffmpeg"
CANALES_DIR = pathlib.Path(__file__).parent


def normalize(text: str) -> str:
    """Elimina acentos y pasa a minúsculas para comparación flexible."""
    return unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode().lower()


def parse_srt_time(t: str) -> float:
    """'00:01:23,456' → segundos float."""
    h, m, rest = t.split(":")
    s, ms = rest.replace(",", ".").split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def load_srt(srt_path: pathlib.Path) -> list[dict]:
    """Devuelve lista de {start, end, text} para los primeros 10 min."""
    blocks = []
    content = srt_path.read_text(encoding="utf-8")
    for block in re.split(r"\n{2,}", content.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        time_line = lines[1]
        if "-->" not in time_line:
            continue
        start_str, end_str = time_line.split("-->")
        start = parse_srt_time(start_str.strip())
        if start > 600:  # solo primeros 10 min
            break
        end = parse_srt_time(end_str.strip())
        text = " ".join(lines[2:])
        blocks.append({"start": start, "end": end, "text": text})
    return blocks


def extract_contact_sheet(sheet_path: pathlib.Path, grid: str, out_dir: pathlib.Path) -> list[pathlib.Path]:
    """Recorta el contact sheet en celdas individuales. grid='3x3', '2x4', etc."""
    cols, rows = [int(x) for x in grid.lower().split("x")]
    out_dir.mkdir(parents=True, exist_ok=True)

    # Obtener dimensiones de la imagen
    probe = subprocess.run(
        [FFMPEG, "-i", str(sheet_path), "-vframes", "1", "-f", "null", "-"],
        capture_output=True, text=True
    )
    m = re.search(r"(\d{3,5})x(\d{3,5})", probe.stderr)
    if not m:
        print(f"  ERROR: no se pudo leer dimensiones de {sheet_path}", file=sys.stderr)
        return []
    W, H = int(m.group(1)), int(m.group(2))
    cell_w = W // cols
    cell_h = H // rows

    fotos = []
    idx = 0
    for row in range(rows):
        for col in range(cols):
            x = col * cell_w
            y = row * cell_h
            out_jpg = out_dir / f"protagonista_{idx+1:02d}.jpg"
            if not out_jpg.exists():
                subprocess.run([
                    FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(sheet_path),
                    "-vf", f"crop={cell_w}:{cell_h}:{x}:{y}",
                    str(out_jpg)
                ], check=True)
            fotos.append(out_jpg)
            idx += 1
    print(f"  ✅ {len(fotos)} fotos extraídas de {sheet_path.name} ({grid})")
    return fotos


def make_protagonist_clip(foto: pathlib.Path, dst: pathlib.Path, dur: float, index: int) -> bool:
    """
    Genera clip con blur de fondo + portrait centrado + zoom suave.
    Técnica dos-pasos: BG (blur full) + FG (portrait escalado) compuestos.
    """
    if dst.exists():
        print(f"  ⏭  ya existe {dst.name}")
        return True

    dst.parent.mkdir(parents=True, exist_ok=True)
    frames = int(dur * 25)

    # Zoom suave: de 1.0 a 1.08 (sutil, solo movimiento, no agresivo)
    scale_expr = f"1.0+0.08*(on/{frames})"

    # BG: imagen escalada a 1920x1080, blur fuerte
    # FG: imagen escalada a altura 900 (deja margen), centrada
    # Overlay compuesto
    vf = (
        f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,gblur=sigma=25[bg];"
        f"[0:v]scale=-1:900,zoompan=z='{scale_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s=1920x1080:fps=25,setsar=1:1[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )

    r = subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-i", str(foto),
        "-vf", vf,
        "-t", str(dur),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-r", "25",
        str(dst)
    ])
    if r.returncode != 0:
        print(f"  ERROR generando {dst.name}", file=sys.stderr)
        return False
    print(f"  ✅ {dst.name} ({dur:.1f}s)")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("carpeta", help="Carpeta del video, ej: secretos-mexicanos/jose-alfredo-jimenez/")
    ap.add_argument("--nombre", help="Nombre(s) a buscar en el SRT, ej: 'José Alfredo'")
    ap.add_argument("--foto", help="Foto individual del protagonista (JPG/PNG)")
    ap.add_argument("--contact-sheet", dest="contact_sheet", help="Contact sheet con múltiples fotos")
    ap.add_argument("--grid", default="3x3", help="Grid del contact sheet (default: 3x3)")
    ap.add_argument("--dur", type=float, default=5.0, help="Duración de cada clip de foto (default: 5s)")
    args = ap.parse_args()

    video_dir = pathlib.Path(args.carpeta)
    if not video_dir.is_absolute():
        video_dir = CANALES_DIR / video_dir
    if not video_dir.exists():
        print(f"ERROR: no existe {video_dir}", file=sys.stderr)
        sys.exit(1)

    slug = video_dir.name
    canal = video_dir.parent.name

    # --- Nombre del protagonista ---
    if args.nombre:
        nombre = args.nombre
    else:
        # Slug a título: jose-alfredo-jimenez → Jose Alfredo Jimenez
        nombre = slug.replace("-", " ").title()
        print(f"  Usando nombre: '{nombre}' (del slug). Usa --nombre para sobrescribir.")

    # Variantes de búsqueda: nombre completo, primer nombre, apellido
    partes = nombre.split()
    buscar = [nombre] + partes  # ej: ["José Alfredo Jiménez", "José", "Alfredo", "Jiménez"]
    # Para apellidos compuestos como "Jiménez", incluir también sin acento
    buscar_norm = [normalize(b) for b in buscar]

    # --- SRT ---
    srt_candidates = list(video_dir.glob("02-locucion/*.srt")) + list(video_dir.glob("*.srt"))
    if not srt_candidates:
        print("ERROR: no se encontró archivo .srt", file=sys.stderr)
        sys.exit(1)
    srt_path = srt_candidates[0]
    print(f"  SRT: {srt_path.name}")

    bloques = load_srt(srt_path)
    print(f"  Bloques SRT (≤10min): {len(bloques)}")

    # Detectar menciones: al menos una parte del nombre
    menciones = []
    for b in bloques:
        txt_norm = normalize(b["text"])
        if any(n in txt_norm for n in buscar_norm):
            menciones.append(b)

    if not menciones:
        print(f"  ⚠️  No se encontraron menciones de '{nombre}' en el SRT.")
        print("     Usa --nombre para especificar exactamente cómo aparece en el guion.")
        sys.exit(0)

    print(f"  Menciones encontradas: {len(menciones)}")

    # --- Fotos del protagonista ---
    research_dir = video_dir / "00-research"
    fotos_dir = video_dir / "03-imagenes" / "protagonista_fotos"

    fotos: list[pathlib.Path] = []

    if args.foto:
        foto_path = pathlib.Path(args.foto)
        if not foto_path.is_absolute():
            foto_path = CANALES_DIR / foto_path
        if not foto_path.exists():
            print(f"ERROR: no existe {foto_path}", file=sys.stderr)
            sys.exit(1)
        fotos = [foto_path]

    elif args.contact_sheet:
        sheet_path = pathlib.Path(args.contact_sheet)
        if not sheet_path.is_absolute():
            sheet_path = CANALES_DIR / sheet_path
        fotos = extract_contact_sheet(sheet_path, args.grid, fotos_dir)

    else:
        # Buscar automáticamente en 00-research/
        candidatos = list(research_dir.glob("contact_sheet*.*")) + \
                     list(research_dir.glob("contact*.*")) + \
                     list(research_dir.glob("protagonista*.*"))
        if candidatos:
            sheet = candidatos[0]
            print(f"  Contact sheet encontrado: {sheet.name}")
            fotos = extract_contact_sheet(sheet, args.grid, fotos_dir)
        else:
            # Buscar fotos sueltas
            fotos = sorted(research_dir.glob("*.jpg")) + sorted(research_dir.glob("*.jpeg")) + \
                    sorted(research_dir.glob("*.png"))
            fotos = [f for f in fotos if "contact" not in f.name.lower()][:10]
            if fotos:
                print(f"  {len(fotos)} fotos sueltas encontradas en 00-research/")
            else:
                print("  ERROR: no se encontraron fotos. Usa --foto o --contact-sheet", file=sys.stderr)
                sys.exit(1)

    if not fotos:
        print("  ERROR: no hay fotos disponibles", file=sys.stderr)
        sys.exit(1)

    print(f"  Pool de fotos: {len(fotos)}")

    # --- Cargar timeline y metadata ---
    timeline_path = video_dir / "05-montaje" / "timeline.json"
    metadata_path = video_dir / "metadata.json"

    timeline = json.loads(timeline_path.read_text())
    metadata = json.loads(metadata_path.read_text())

    segs_existentes = timeline["visual_timeline"]
    max_id = max((s["segment_id"] for s in segs_existentes), default=0)

    # Set de rangos ocupados (start, end) para no chocar con flow existente
    ocupados = [(s["start_seconds"], s["end_seconds"]) for s in segs_existentes]

    def choca(t_start: float, t_end: float) -> bool:
        for os, oe in ocupados:
            if t_start < oe and t_end > os:
                return True
        return False

    imagenes_dir = video_dir / "03-imagenes"
    footage = metadata.get("footage", {})

    nuevos_segs = []
    foto_idx = 0
    clip_idx = max_id

    for mencion in menciones:
        t_start = mencion["start"]
        t_end = mencion["end"]
        dur_seg = round(t_end - t_start, 3)

        # Usar duración real del segmento, mínimo 2s, máximo 8s
        dur_clip = max(2.0, min(dur_seg, 8.0))

        if choca(t_start, t_end):
            print(f"  ⏭  {t_start:.1f}s–{t_end:.1f}s ya cubierto — saltando")
            continue

        foto = fotos[foto_idx % len(fotos)]
        foto_idx += 1
        clip_idx += 1

        clip_name = f"flow_{clip_idx:04d}_zp.mp4"
        clip_path = imagenes_dir / clip_name

        print(f"  → seg {clip_idx}: {t_start:.1f}s–{t_end:.1f}s | {foto.name} | {dur_clip:.1f}s")

        ok = make_protagonist_clip(foto, clip_path, dur_clip, clip_idx)
        if not ok:
            clip_idx -= 1
            continue

        # Agregar a ocupados para evitar colisiones entre menciones
        ocupados.append((t_start, t_end))

        # Nuevo segmento para timeline.json
        nuevo_seg = {
            "segment_id": clip_idx,
            "trigger_type": "PROTAGONISTA",
            "start_seconds": int(round(t_start)),
            "end_seconds": int(round(t_end)),
            "duration": int(round(dur_clip)),
            "source": "flow",
            "brave_query": "",
            "ia_prompt": f"Foto del protagonista {nombre} — contacto visual directo",
            "scene_description": f"SRT menciona a {nombre}: \"{mencion['text'][:80]}\""
        }
        nuevos_segs.append(nuevo_seg)

        # Nuevo entry para metadata.json footage
        footage[clip_name] = {
            "segment_id": clip_idx,
            "trigger": "PROTAGONISTA",
            "ia_prompt": nuevo_seg["ia_prompt"],
            "start_time": int(round(t_start)),
            "duration": dur_clip,
            "source": "flow",
            "path": f"{canal}/{slug}/03-imagenes/{clip_name}",
            "estado": "aprobado"
        }

    if not nuevos_segs:
        print("  ⚠️  No se generó ningún clip nuevo (todas las menciones ya estaban cubiertas).")
        sys.exit(0)

    # Agregar al timeline y reordenar por start_seconds
    segs_existentes.extend(nuevos_segs)
    segs_existentes.sort(key=lambda s: s["start_seconds"])

    # Reasignar segment_id secuencial tras el sort
    for i, s in enumerate(segs_existentes, 1):
        s["segment_id"] = i

    timeline["visual_timeline"] = segs_existentes

    # Guardar
    timeline_path.write_text(json.dumps(timeline, indent=2, ensure_ascii=False))
    metadata["footage"] = footage
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

    print(f"\n  ✅ PASO 6.5 completo: {len(nuevos_segs)} clips del protagonista agregados.")
    print(f"     Reinicia el dashboard para ver los nuevos clips.")
    print(f"\n  Clips generados:")
    for s in nuevos_segs:
        print(f"     flow_{s['segment_id']:04d}_zp.mp4 — {s['start_seconds']}s–{s['end_seconds']}s")


if __name__ == "__main__":
    main()
