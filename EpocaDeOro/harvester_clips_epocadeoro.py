#!/usr/bin/env python3
"""
harvester_clips_epocadeoro.py — Pre-selecciona clips por artista
y genera dashboard_meta.json para el canal La Verdad Dorada.

- Lee timestamps.json para saber duración de cada artista (~230s)
- Busca clips en iCloud/Artistas/<nombre>/
- Pre-selecciona ceil(duracion / 7.5) + 3 slots por artista
- El dashboard muestra esos clips → el render los usa en ese orden

Uso: python3 harvester_clips_epocadeoro.py "Video-001 Murieron en la Miseria/"
"""

import sys, json, math, random, pathlib, unicodedata, re, subprocess

FFPROBE  = "/opt/homebrew/bin/ffprobe"
HOME     = pathlib.Path.home()
ICLOUD   = HOME / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"
SHOT_DUR = 7.5
EXTRA    = 3


def norm(text):
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def buscar_carpeta_icloud(nombre):
    """Matching fuzzy para encontrar la carpeta del artista en iCloud."""
    if not ICLOUD.exists():
        return None
    nombre_n = norm(nombre)
    partes   = nombre_n.split()

    # 1. Exacto
    for d in ICLOUD.iterdir():
        if not d.is_dir(): continue
        if norm(d.name) == nombre_n:
            return d

    # 2. Nombre completo contenido
    for d in ICLOUD.iterdir():
        if not d.is_dir(): continue
        dn = norm(d.name)
        if nombre_n in dn or dn in nombre_n:
            return d

    # 3. Apellido exacto (mín 5 chars para evitar falsos positivos)
    apellido = partes[-1] if partes else ""
    if len(apellido) >= 5:
        for d in ICLOUD.iterdir():
            if not d.is_dir(): continue
            words = norm(d.name).split()
            if apellido in words:
                return d

    return None


def get_duration(path):
    if "_zp" in pathlib.Path(path).stem:
        return 7.0
    return 5.0


def validar_aspecto(path):
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10
        )
        parts = r.stdout.strip().split(",")
        if len(parts) < 2: return True
        w, h = int(parts[0]), int(parts[1])
        return h > 0 and 1.0 <= w/h <= 2.5
    except Exception:
        return True


def parse_srt(srt_path):
    entries = []
    content = pathlib.Path(srt_path).read_text(encoding="utf-8", errors="replace")
    blocks  = re.split(r'\n\s*\n', content.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3: continue
        m = re.match(r'(\d+:\d+:\d+[,\.]\d+)\s+-->\s+(\d+:\d+:\d+[,\.]\d+)', lines[1])
        if not m: continue
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
    parts = []
    for e in srt_entries:
        if e["end"] < t_start: continue
        if e["start"] > t_end: break
        parts.append(e["text"])
    return " ".join(parts)


def pre_seleccionar_clips(carpeta, num_slots, usados_global=None):
    """Elige num_slots clips sin repetir paths ya usados en otras secciones."""
    if usados_global is None:
        usados_global = set()

    all_mp4  = sorted(carpeta.glob("*.mp4"))
    raw_mp4  = [f for f in all_mp4 if "_zp" not in f.stem and not f.stem.startswith(("tmp", "flow"))]
    zp_mp4   = [f for f in all_mp4 if "_zp" in f.stem]
    imgs_all = [f for f in carpeta.iterdir() if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')]
    imgs     = [f for f in imgs_all if validar_aspecto(f)]

    if raw_mp4:
        pool_base = raw_mp4
    elif zp_mp4:
        pool_base = zp_mp4
    else:
        pool_base = imgs

    pool_libre = [f for f in pool_base if str(f) not in usados_global]
    pool_todos = list(pool_base)

    pool = list(pool_libre)
    random.shuffle(pool)
    mid  = len(pool) // 2
    pool = pool[mid:] + pool[:mid]
    random.shuffle(pool)

    selected  = []
    used_local = set()

    for _ in range(num_slots):
        if not pool:
            pool = [f for f in pool_todos if str(f) not in used_local]
            if not pool:
                pool = list(pool_todos)
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


def scan_artista(seg, srt_entries, existing_clips=None, usados_global=None):
    nombre    = seg["name"]
    duracion  = seg["duration"]
    abs_start = seg["start"]

    carpeta = buscar_carpeta_icloud(nombre)
    if not carpeta:
        print(f"    ⚠ No se encontró carpeta iCloud para: {nombre}")
        return {}, None

    print(f"    ✓ iCloud: {carpeta.name}")

    all_mp4     = [f for f in carpeta.glob("*.mp4") if "_zp" not in f.stem]
    imgs        = [f for f in carpeta.iterdir() if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')]
    disponibles = len(all_mp4) + len(imgs)
    num_slots   = math.ceil(duracion / SHOT_DUR) + EXTRA

    if disponibles < num_slots:
        print(f"    ⚠ Solo {disponibles} media para {num_slots} slots — se reciclarán clips")

    prev            = existing_clips or {}
    seleccionados   = pre_seleccionar_clips(carpeta, num_slots, usados_global=usados_global)

    clips = {}
    for i, path in enumerate(seleccionados):
        slot_start = round(i * SHOT_DUR, 2)
        slot_end   = round(min((i + 1) * SHOT_DUR, duracion), 2)
        t_abs      = abs_start + slot_start
        text       = get_text_in_range(srt_entries, t_abs, t_abs + SHOT_DUR)
        dur        = get_duration(path) if path.suffix == ".mp4" else 0

        slot_key  = f"slot{i:03d}_{path.name}"
        reciclado = any(v.get("path") == str(path) for v in clips.values())

        estado = "pendiente"
        if slot_key in prev and prev[slot_key].get("estado") in ("aprobado", "rechazado"):
            estado = prev[slot_key]["estado"]

        clips[slot_key] = {
            "slot":       i,
            "estado":     estado,
            "tipo":       "video" if path.suffix == ".mp4" else "imagen",
            "path":       str(path),
            "orig_name":  path.name,
            "reciclado":  reciclado,
            "duration":   dur,
            "slot_start": slot_start,
            "slot_end":   slot_end,
            "srt_text":   text,
            "fuente":     "icloud",
        }

    print(f"    → {num_slots} slots ({num_slots * SHOT_DUR:.0f}s) para {duracion:.0f}s de segmento")
    return clips, carpeta.name


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 harvester_clips_epocadeoro.py <carpeta_video>")
        sys.exit(1)

    video_folder = pathlib.Path(sys.argv[1])

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

    meta          = {}
    usados_global = set()

    for seg in timestamps:
        label     = seg["label"]
        is_cierre = seg.get("is_cierre", False)
        is_hook   = seg.get("is_hook", False)

        if is_cierre:
            continue

        if is_hook:
            print(f"\n  [{label}] HOOK — {seg['duration']:.1f}s (sin clips, solo locución)")
            meta[label] = {
                "nombre":   seg["name"],
                "is_hook":  True,
                "duration": seg["duration"],
                "clips":    {},
            }
            continue

        print(f"\n  [{label}]  {seg['duration']:.1f}s")
        prev_clips = existing.get(label, {}).get("clips", {})
        clips, icloud_name = scan_artista(seg, srt_entries,
                                          existing_clips=prev_clips,
                                          usados_global=usados_global)
        meta[label] = {
            "nombre":      seg["name"],
            "is_hook":     False,
            "duration":    seg["duration"],
            "icloud_name": icloud_name or "",
            "clips":       clips,
        }

    tmp = str(meta_file) + ".tmp"
    pathlib.Path(tmp).write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    pathlib.Path(tmp).replace(meta_file)

    print(f"\n✓ dashboard_meta.json → {meta_file}")
    total_clips = sum(len(s["clips"]) for s in meta.values())
    print(f"  {len(meta)} secciones, {total_clips} clips pre-seleccionados")
    print(f"\n  Ahora corre: python3 EpocaDeOro/dashboard_epocadeoro.py \"{video_folder}\"")


if __name__ == "__main__":
    main()
