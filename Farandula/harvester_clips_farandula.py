#!/usr/bin/env python3
"""
harvester_clips_farandula.py — Pre-selecciona exactamente los clips que el render
va a usar por artista y los guarda en dashboard_meta.json.

- Lee timestamps.json para saber duración de cada segmento
- Lee audio.srt para asociar texto a cada slot de clip
- Pre-selecciona N clips (= ceil(duracion / SHOT_DUR)) de la carpeta iCloud
- El dashboard muestra esos N clips en orden → el render los usa exactamente así

Uso:
  python3 harvester_clips_farandula.py "VIVIENDO DE FAVOR TELEVISA/"
"""

import sys, json, math, random, pathlib, unicodedata, subprocess, re
from icloud_match import buscar_carpeta_icloud as _buscar_carpeta_segura

FFPROBE  = "/opt/homebrew/bin/ffprobe"
HOME     = pathlib.Path.home()
ICLOUD   = HOME / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"
SHOT_DUR = 7.5   # duración de cada slot (igual que en el render)
EXTRA    = 3     # slots extra por si el render necesita más


def norm(text):
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def buscar_carpeta_icloud(nombre):
    return _buscar_carpeta_segura(nombre)


def get_duration(path):
    # Clips extraídos con --clip-dur 5 → siempre 5.0s; _zp.mp4 → 7.0s
    p = pathlib.Path(path)
    if "_zp" in p.stem:
        return 7.0
    return 5.0


def get_dims(path):
    # Todos los clips son 1920×1080 (extraídos con extraer_clips_video.py)
    return 1920, 1080


def validar_aspecto(path, min_ratio=1.0, max_ratio=2.5):
    w, h = get_dims(path)
    if h == 0:
        return True
    return min_ratio <= w / h <= max_ratio


# ── SRT parser ──────────────────────────────────────────────────────────────

def parse_srt(srt_path):
    """Devuelve lista de {start, end, text} en segundos."""
    entries = []
    content = pathlib.Path(srt_path).read_text(encoding="utf-8", errors="replace")
    blocks  = re.split(r'\n\s*\n', content.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        # Línea de tiempo: "00:00:04,523 --> 00:00:08,431"
        m = re.match(r'(\d+:\d+:\d+[,\.]\d+)\s+-->\s+(\d+:\d+:\d+[,\.]\d+)', lines[1])
        if not m:
            continue
        def to_s(t):
            t = t.replace(',', '.')
            h, mi, s = t.split(':')
            return int(h)*3600 + int(mi)*60 + float(s)
        entries.append({
            "start": to_s(m.group(1)),
            "end":   to_s(m.group(2)),
            "text":  " ".join(lines[2:]).strip(),
        })
    return entries


def get_text_in_range(srt_entries, t_start, t_end):
    """Texto del SRT que cae dentro del rango [t_start, t_end]."""
    parts = []
    for e in srt_entries:
        if e["end"] < t_start:
            continue
        if e["start"] > t_end:
            break
        parts.append(e["text"])
    return " ".join(parts)


# ── Pre-selección de clips ──────────────────────────────────────────────────

def pre_seleccionar_clips(carpeta, num_slots, usados_global=None):
    """
    Elige exactamente num_slots clips de la carpeta sin repetir paths
    que ya estén asignados en otras secciones (usados_global).
    Prioridad: mp4 raw > imágenes con aspecto válido > mp4 con _zp
    Solo recicla dentro de la misma sección cuando no queda otra opción.
    """
    if usados_global is None:
        usados_global = set()

    all_mp4  = sorted(carpeta.glob("*.mp4"))
    raw_mp4  = [f for f in all_mp4
                if "_zp" not in f.stem and not f.stem.startswith(("tmp", "flow"))]
    zp_mp4   = [f for f in all_mp4 if "_zp" in f.stem]
    imgs_all = [f for f in carpeta.iterdir()
                if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')]
    imgs     = [f for f in imgs_all if validar_aspecto(f)]

    # Pool principal: raw_mp4 > _zp (si hay _zp, ignorar imágenes raw — ya están convertidas)
    # Las imágenes solo se usan si NO existe ningún _zp en la carpeta
    if raw_mp4:
        pool_base = raw_mp4
    elif zp_mp4:
        pool_base = zp_mp4
    else:
        pool_base = imgs

    # Excluir los ya usados globalmente
    pool_base_libre = [f for f in pool_base if str(f) not in usados_global]
    pool_base_todos = list(pool_base)  # fallback si no alcanza

    # Doble shuffle: primero aleatorio, luego corta y reordena mitades
    pool = list(pool_base_libre)
    random.shuffle(pool)
    mid = len(pool) // 2
    pool = pool[mid:] + pool[:mid]  # rota mitades para mayor variedad entre videos
    random.shuffle(pool)
    selected = []
    used_local = set()  # paths usados en esta sección

    for _ in range(num_slots):
        if not pool:
            # Se agotaron los libres — reciclar solo dentro de esta sección
            pool = [f for f in pool_base_todos if str(f) not in used_local]
            if not pool:
                pool = list(pool_base_todos)
            random.shuffle(pool)

        for i, f in enumerate(pool):
            if str(f) not in used_local:
                used_local.add(str(f))
                usados_global.add(str(f))
                selected.append(pool.pop(i))
                break
        else:
            f = pool.pop(0)
            used_local.add(str(f))
            usados_global.add(str(f))
            selected.append(f)

    return selected


# ── Sección Hook ─────────────────────────────────────────────────────────────

def scan_hook(video_folder, seg, srt_entries):
    hook_dir = video_folder / "hook_images"
    tl_file  = video_folder / "hook_timeline.json"

    clips = {}
    if hook_dir.exists():
        # Leer duración por imagen del timeline
        dur_map = {}
        if tl_file.exists():
            segs = json.loads(tl_file.read_text())["visual_timeline"]
            for s in segs:
                dur_map[s["segment_id"]] = s["duration"]

        imgs = sorted(hook_dir.glob("hook_[0-9]*.jpg"))
        abs_start = seg["start"]
        cursor = 0.0
        for i, img in enumerate(imgs):
            sid     = int(re.search(r'(\d+)', img.stem).group(1))
            dur_img = dur_map.get(sid, SHOT_DUR)
            t_abs   = abs_start + cursor
            text    = get_text_in_range(srt_entries, t_abs, t_abs + dur_img)
            w, h    = get_dims(img)
            clips[img.name] = {
                "slot":     i,
                "estado":   "pendiente",
                "tipo":     "imagen",
                "path":     str(img),
                "duration": dur_img,
                "slot_start": round(cursor, 2),
                "slot_end":   round(cursor + dur_img, 2),
                "srt_text": text,
                "width":    w,
                "height":   h,
            }
            cursor += dur_img

    return clips


# ── Queries e ia_prompts por slot ────────────────────────────────────────────

def build_search_query(nombre_display, srt_text):
    """
    Genera un query de Brave específico combinando nombre + contexto del SRT.
    Extrae palabras clave relevantes del texto narrado.
    """
    # Palabras stop en español que no aportan al query
    stop = {'el','la','los','las','un','una','y','de','en','que','se','su','con',
            'por','para','del','al','no','le','lo','era','fue','es','son','han',
            'sus','una','pero','como','más','muy','cuando','todo','esto','esta',
            'ese','esa','eso','hay','ya','si','porque','donde','quien','siendo'}
    words = re.findall(r'\b[a-záéíóúüñ]{4,}\b', srt_text.lower())
    keywords = [w for w in words if w not in stop][:4]
    base = f"{nombre_display} comediante actor Mexico television"
    if keywords:
        base += " " + " ".join(keywords)
    return base


def build_ia_prompt(nombre_display, srt_text, slot_start):
    """
    Genera ia_prompt para Flow/IA basado en el contexto del SRT en ese momento.
    """
    # Extraer tema principal del SRT
    srt_short = srt_text[:120] if srt_text else ""
    return (
        f"Photorealistic scene of Mexican TV entertainer {nombre_display}, "
        f"1980s Televisa Mexico studio setting, professional lighting, no text, "
        f"cinematic composition. Context: {srt_short}"
    )


# ── Sección Artista ───────────────────────────────────────────────────────────

def scan_artista(seg, srt_entries, existing_clips=None, usados_global=None):
    nombre    = seg["name"]
    duracion  = seg["duration"]
    abs_start = seg["start"]
    nombre_display = nombre.title()

    carpeta = buscar_carpeta_icloud(nombre)
    if not carpeta:
        print(f"    ⚠ No se encontró carpeta iCloud para: {nombre}")
        return {}, None

    print(f"    ✓ iCloud: {carpeta.name}")

    # Contar disponibles para informar
    all_mp4 = [f for f in carpeta.glob("*.mp4")
                if "_zp" not in f.stem and not f.stem.startswith(("tmp","flow"))]
    imgs    = [f for f in carpeta.iterdir()
               if f.suffix.lower() in ('.jpg','.jpeg','.png','.webp') and validar_aspecto(f)]
    disponibles = len(all_mp4) + len(imgs)

    # Slots necesarios
    num_slots = math.ceil(duracion / SHOT_DUR) + EXTRA
    reciclados = max(0, num_slots - disponibles)
    if reciclados > 0:
        print(f"    ⚠ Solo {disponibles} media disponibles para {num_slots} slots → {reciclados} se reciclarán")

    # Si ya existían clips aprobados/rechazados, preservarlos
    prev = existing_clips or {}
    prev_aprobados  = {k: v for k, v in prev.items() if v.get("estado") == "aprobado"}
    prev_rechazados = {k: v for k, v in prev.items() if v.get("estado") == "rechazado"}

    # Pre-seleccionar clips frescos sin repetir paths ya usados en otras secciones
    seleccionados = pre_seleccionar_clips(carpeta, num_slots, usados_global=usados_global)

    clips = {}
    for i, path in enumerate(seleccionados):
        slot_start = round(i * SHOT_DUR, 2)
        slot_end   = round(min((i + 1) * SHOT_DUR, duracion), 2)
        t_abs      = abs_start + slot_start
        text       = get_text_in_range(srt_entries, t_abs, t_abs + SHOT_DUR)
        dur        = get_duration(path) if path.suffix == ".mp4" else 0
        w, h       = get_dims(path)

        # Query específico por slot para Brave y Flow
        search_query = build_search_query(nombre_display, text)
        ia_prompt    = build_ia_prompt(nombre_display, text, slot_start)

        # Clave única por slot — permite reciclar el mismo archivo en varios slots
        slot_key  = f"slot{i:03d}_{path.name}"
        reciclado = any(v.get("path") == str(path) for v in clips.values())

        # Preservar estado si ya existía esta clave
        estado = "pendiente"
        if slot_key in prev_aprobados:
            estado = "aprobado"
        elif slot_key in prev_rechazados:
            estado = "rechazado"

        clips[slot_key] = {
            "slot":         i,
            "estado":       estado,
            "tipo":         "video" if path.suffix == ".mp4" else "imagen",
            "path":         str(path),
            "orig_name":    path.name,
            "reciclado":    reciclado,
            "duration":     dur,
            "slot_start":   slot_start,
            "slot_end":     slot_end,
            "srt_text":     text,
            "search_query": search_query,
            "ia_prompt":    ia_prompt,
            "width":        w,
            "height":       h,
            "fuente":       "icloud",
        }

    total_dur = num_slots * SHOT_DUR
    print(f"    → {num_slots} slots ({total_dur:.0f}s pre-seleccionados para {duracion:.0f}s de segmento)")
    return clips, carpeta.name


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 harvester_clips_farandula.py <carpeta_video>")
        sys.exit(1)

    video_folder = pathlib.Path(sys.argv[1])

    # Semilla única por video: nombre de carpeta + fecha + hora — diferente en cada ejecución
    import time as _time
    _seed = hash(str(video_folder.resolve()) + str(int(_time.time() / 3600))) & 0xFFFFFFFF
    random.seed(_seed)

    if not video_folder.exists():
        print(f"✗ No existe: {video_folder}")
        sys.exit(1)

    ts_file  = video_folder / "timestamps.json"
    srt_file = video_folder / "audio.srt"

    if not ts_file.exists():
        print(f"✗ No existe timestamps.json en {video_folder}")
        sys.exit(1)

    timestamps  = json.loads(ts_file.read_text())
    srt_entries = parse_srt(srt_file) if srt_file.exists() else []
    if srt_entries:
        print(f"  SRT: {len(srt_entries)} entradas cargadas")

    meta_file = video_folder / "dashboard_meta.json"
    existing  = {}
    if meta_file.exists():
        try:
            existing = json.loads(meta_file.read_text())
        except Exception:
            existing = {}

    meta = {}
    usados_global = set()  # paths en uso en todo el timeline

    for seg in timestamps:
        label     = seg["label"]
        is_hook   = seg.get("is_hook", False)
        is_cierre = seg.get("is_cierre", False)

        if is_cierre:
            continue

        print(f"\n  [{label}]  {seg['duration']:.1f}s")

        if is_hook:
            clips = scan_hook(video_folder, seg, srt_entries)
            meta[label] = {
                "nombre":   seg["name"],
                "is_hook":  True,
                "duration": seg["duration"],
                "clips":    clips,
            }
        else:
            prev_clips = existing.get(label, {}).get("clips", {})
            clips, icloud_name = scan_artista(seg, srt_entries, existing_clips=prev_clips,
                                              usados_global=usados_global)
            meta[label] = {
                "nombre":      seg["name"],
                "is_hook":     False,
                "duration":    seg["duration"],
                "icloud_name": icloud_name or "",
                "clips":       clips,
            }

    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    print(f"\n✓ dashboard_meta.json → {meta_file}")
    total_clips = sum(len(s["clips"]) for s in meta.values())
    total_segs  = len(meta)
    print(f"  {total_segs} secciones, {total_clips} clips pre-seleccionados")
    print(f"\n  Ahora corre: python3 dashboard_farandula.py \"{video_folder}\"")


if __name__ == "__main__":
    main()
