#!/usr/bin/env python3
"""
render_epocadeoro.py — Render modular por segmento.

Uso:
  python3 render_epocadeoro.py hook                  # render solo el hook
  python3 render_epocadeoro.py artist LUPE_VELEZ     # render solo un artista
  python3 render_epocadeoro.py final                 # une todos los renders
  python3 render_epocadeoro.py all                   # hook + todos artistas + final

Renders parciales → Video-NNN/_renders/
  00_hook.mp4
  01_LUPE_VELEZ.mp4
  ...
Final → Video-NNN/output.mp4
"""

import sys, subprocess, pathlib, shutil, json, math, random

# ─── Configuración ────────────────────────────────────────────────────────────
FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
W, H, FPS = 1920, 1080, 30

BASE   = pathlib.Path("/Users/anyelocuesta/Downloads/Canales/EpocaDeOro")
FOLDER = BASE / "Video-001 Murieron en la Miseria"
AUDIO  = FOLDER / "audio.mp3"
RENDERS_DIR = FOLDER / "_renders"
OUTPUT = FOLDER / "output.mp4"

HOOK_RENDER  = BASE / "hook-motion/renders/hook_card_audio.mp4"
ICLOUD       = pathlib.Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"
TIMESTAMPS  = FOLDER / "timestamps.json"
STATE_FILE  = FOLDER / "dashboard_state.json"

VERDE   = "\033[92m"; ROJO = "\033[91m"; RESET = "\033[0m"; NEG = "\033[1m"

# ─── Utilidades ───────────────────────────────────────────────────────────────
def run(cmd, timeout=600, label=""):
    tag = f"[{label}] " if label else ""
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        print(f"{ROJO}{tag}ERROR:\n{r.stderr.decode()[-600:]}{RESET}")
        sys.exit(1)
    return r

def probe_dur(path):
    r = subprocess.run([FFPROBE,"-v","error","-show_entries","format=duration",
                        "-of","csv=p=0",str(path)], capture_output=True, text=True)
    return float(r.stdout.strip() or 0)

def banner(txt):
    print(f"\n{NEG}{'─'*60}\n  {txt}\n{'─'*60}{RESET}")

def load_timestamps():
    return json.loads(TIMESTAMPS.read_text())

def load_state():
    if not STATE_FILE.exists():
        print(f"{ROJO}✗ No hay dashboard_state.json. Aprueba primero en http://localhost:5005{RESET}")
        sys.exit(1)
    s = json.loads(STATE_FILE.read_text())
    if not s.get("approved"):
        print(f"{ROJO}✗ Dashboard no aprobado.{RESET}")
        sys.exit(1)
    return s

# ─── MODO HOOK ────────────────────────────────────────────────────────────────
def _pick_hook_clips(timestamps, hook_dur, clip_dur=5.0):
    """
    Devuelve lista de clips para el hook.
    Regla: 1 clip por artista distinto, rotando aleatoriamente.
    Se agotan todos antes de repetir. Se repite hasta cubrir hook_dur.
    """
    import unicodedata as _uni

    def norm(t):
        t = _uni.normalize("NFD", t.lower())
        return "".join(c for c in t if _uni.category(c) != "Mn")

    def find_folder(nombre, hint=None):
        if hint:
            p = ICLOUD / hint
            if p.exists(): return p
        n = norm(nombre)
        for d in ICLOUD.iterdir():
            if d.is_dir() and norm(d.name) == n: return d
        for d in ICLOUD.iterdir():
            if d.is_dir() and n in norm(d.name): return d
        ap = n.split()[-1]
        if len(ap) > 3:
            for d in ICLOUD.iterdir():
                if d.is_dir() and ap in norm(d.name): return d
        return None

    artists = [t for t in timestamps if not t.get("is_hook") and not t.get("is_cierre")]

    # 1 clip aleatorio por artista
    pool = []
    for art in artists:
        folder = find_folder(art["name"], art.get("icloud_folder"))
        if not folder: continue
        clips = [f for f in folder.glob("*.mp4") if "_zp" not in f.stem and "_backup" not in str(f)]
        if clips:
            pool.append(random.choice(clips))

    if not pool:
        return []

    # Rotar hasta cubrir la duración
    n_needed = math.ceil(hook_dur / clip_dur)
    result = []
    bag = list(pool)
    random.shuffle(bag)
    while len(result) < n_needed:
        if not bag:
            bag = list(pool)
            random.shuffle(bag)
        result.append(bag.pop())
    return result[:n_needed]


def render_hook():
    """Renderiza el hook con segmentos de duración variable — Flow en su segundo exacto."""
    banner("HOOK")
    RENDERS_DIR.mkdir(exist_ok=True)
    dest = RENDERS_DIR / "00_hook.mp4"

    timestamps = load_timestamps()
    hook_ts    = next((t for t in timestamps if t.get("is_hook")), None)
    hook_dur   = hook_ts["duration"] if hook_ts else 23.6
    hook_start = hook_ts["start"]    if hook_ts else 0.0

    # hook_sequence.json — fotos y clips YT
    seq_file  = FOLDER / "hook_sequence.json"
    hook_seq  = json.loads(seq_file.read_text()) if seq_file.exists() else []
    fotos_seq = [s for s in hook_seq if s.get("type") == "foto"]
    clips_seq = [s for s in hook_seq if s.get("type") == "clip"]

    # Segmentos Flow del hook_timeline (duración y posición exactas)
    flow_dir  = FOLDER / "05-montaje" / "flow_images"
    flow_segs = []  # [{start, end, dur, path}] ordenados por start
    tl_path   = FOLDER / "hook_timeline.json"
    if tl_path.exists():
        for seg in json.loads(tl_path.read_text()).get("visual_timeline", []):
            if seg.get("type") != "flow":
                continue
            zp = flow_dir / f"flow_{seg['segment_id']:03d}_zp.mp4"
            if zp.exists():
                flow_segs.append({"start": seg["start_seconds"] - hook_start,
                                   "end":   seg["end_seconds"]   - hook_start,
                                   "dur":   seg["end_seconds"]   - seg["start_seconds"],
                                   "path":  zp})
                print(f"  → Flow: {seg['start_seconds']}s–{seg['end_seconds']}s  ({seg['end_seconds']-seg['start_seconds']:.1f}s)")
    flow_segs.sort(key=lambda s: s["start"])

    # Construir timeline de segmentos: gaps entre flow_segs se rellenan con fotos/clips
    # Ejemplo con flow en 7-11s:  [0-7s filler] [7-11s Flow] [11-23.6s filler]
    TMP = RENDERS_DIR / "_tmp_hook"
    TMP.mkdir(parents=True, exist_ok=True)

    vf_clip = (f"hflip,scale={int(W*1.1)}:{int(H*1.1)}:force_original_aspect_ratio=increase"
               f":flags=lanczos,crop={W}:{H}:(iw-ow)/2:(ih-oh)/2,hue=s=0,eq=contrast=1.05")

    def render_seq_item(slot, t_start, t_end, seg_name):
        """Renderiza un item de hook_sequence (foto o clip) con la duración exacta del gap."""
        dur = min(5.0, t_end - t_start)
        if dur < 0.1:
            return None
        out = TMP / f"{seg_name}.mp4"
        if slot["type"] == "foto":
            ph = pathlib.Path(slot.get("photo_path", ""))
            if ph.exists():
                _render_photo_card(ph, None, None, out, dur=dur, tmp_dir=TMP, slide_from="right")
                print(f"    [{seg_name}] {t_start:.1f}s–{t_start+dur:.1f}s → FOTO ({ph.name})")
                return out
        # clip YT
        c = pathlib.Path(slot.get("path", ""))
        if c.exists():
            run([FFMPEG,"-y","-ss","0","-t",str(dur),"-i",str(c),
                 "-vf",vf_clip,"-t",str(dur),"-r",str(FPS),
                 "-c:v","libx264","-preset","ultrafast","-crf","23","-an",
                 "-pix_fmt","yuv420p",str(out),"-loglevel","error"], timeout=120)
            print(f"    [{seg_name}] {t_start:.1f}s–{t_start+dur:.1f}s → clip ({c.name[:40]})")
            return out
        return None

    # Distribuir hook_sequence entre los gaps del timeline:
    # Cada item ocupa hasta 5s. Los gaps se rellenan en orden de dashboard.
    # Si el gap es menor que 5s, el item se recorta. Si sobra gap, se cicla la secuencia.
    segs = []
    seq_cursor = 0   # índice en hook_seq (cicla)
    time_cursor = 0.0
    fi = 0

    for fseg in flow_segs:
        # Rellena el gap antes del flow con items del hook_sequence en orden
        gap_start = time_cursor
        gap_end   = fseg["start"]
        i = 0
        t = gap_start
        while t < gap_end - 0.05:
            slot = hook_seq[seq_cursor % len(hook_seq)]
            seg_name = f"pre{fi}_{i:03d}"
            out = render_seq_item(slot, t, gap_end, seg_name)
            if out and out.exists():
                dur_actual = min(5.0, gap_end - t)
                segs.append(out)
                t += dur_actual
            seq_cursor += 1
            i += 1

        # Flow exacto
        out = TMP / f"flow_{fi:03d}.mp4"
        run([FFMPEG,"-y","-t",str(fseg["dur"]),"-i",str(fseg["path"]),
             "-vf",f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}",
             "-t",str(fseg["dur"]),"-r",str(FPS),
             "-c:v","libx264","-preset","ultrafast","-crf","22","-an",
             "-pix_fmt","yuv420p",str(out),"-loglevel","error"], timeout=120)
        segs.append(out)
        print(f"    [flow_{fi:03d}] {fseg['start']:.1f}s–{fseg['end']:.1f}s → FLOW IA ({fseg['path'].name})")
        time_cursor = fseg["end"]; fi += 1

    # Rellena el gap final con items del hook_sequence en orden
    t = time_cursor
    i = 0
    while t < hook_dur - 0.05:
        slot = hook_seq[seq_cursor % len(hook_seq)]
        seg_name = f"post_{i:03d}"
        out = render_seq_item(slot, t, hook_dur, seg_name)
        if out and out.exists():
            dur_actual = min(5.0, hook_dur - t)
            segs.append(out)
            t += dur_actual
        seq_cursor += 1
        i += 1

    if not segs:
        print(f"{ROJO}✗ Sin segmentos para el hook{RESET}")
        sys.exit(1)

    # Concat
    print(f"\n  Concatenando {len(segs)} segmentos…", end=" ", flush=True)
    concat_txt = TMP / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in segs))
    body_raw = TMP / "body_raw.mp4"
    run([FFMPEG,"-y","-f","concat","-safe","0","-i",str(concat_txt),
         "-c:v","libx264","-preset","ultrafast","-crf","22",
         "-pix_fmt","yuv420p","-an",str(body_raw),"-loglevel","error"])
    print(f"{VERDE}✓  {probe_dur(body_raw):.1f}s{RESET}")

    # Audio
    print(f"  Agregando audio (offset {hook_start}s)…", end=" ", flush=True)
    run([FFMPEG,"-y","-i",str(body_raw),
         "-ss",str(hook_start),"-t",str(hook_dur),"-i",str(AUDIO),
         "-c:v","copy","-c:a","aac","-b:a","192k","-shortest",
         str(dest),"-loglevel","error"])
    shutil.rmtree(TMP, ignore_errors=True)

    dur_out = probe_dur(dest)
    size    = dest.stat().st_size / 1024 / 1024
    print(f"  {VERDE}✓ 00_hook.mp4  →  {dur_out:.1f}s  {size:.1f} MB{RESET}")
    print(f"  → {dest}")
    return dest

# ─── MODO ARTIST ──────────────────────────────────────────────────────────────
def _render_photo_card(photo_path, badge_line1, badge_line2, out_mp4, dur=5.0, tmp_dir=None, slide_from="right"):
    """
    Genera un clip HyperFrames-style con una foto:
      - Fondo negro + cuadrícula
      - Foto encuadrada (borde blanco, B&N) que entra deslizándose desde slide_from ("left"|"right")
      - Badge dorado con 2 líneas (o solo 1 si badge_line2 es None)
    Retorna out_mp4 (Path).
    """
    from PIL import Image, ImageDraw, ImageFont

    td = tmp_dir or out_mp4.parent
    frames_dir = td / f"_pcard_{out_mp4.stem}"
    frames_dir.mkdir(parents=True, exist_ok=True)

    # Fuentes
    GOLD = (201, 162, 39)
    try:
        font_num  = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Black.ttf", 30)
        font_name = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Black.ttf", 46)
    except Exception:
        font_num = font_name = ImageFont.load_default()

    # Cargar foto y convertir a B&N
    try:
        photo = Image.open(str(photo_path)).convert("RGB")
        # Redimensionar respetando orientación: max 1382×842
        MAX_W, MAX_H = 1382, 842
        ratio = min(MAX_W / photo.width, MAX_H / photo.height)
        if ratio < 1.0:
            nw, nh = int(photo.width * ratio), int(photo.height * ratio)
            photo = photo.resize((nw, nh), Image.LANCZOS)
        # B&N
        from PIL import ImageEnhance
        photo = ImageEnhance.Contrast(photo.convert("L").convert("RGB")).enhance(1.1)
    except Exception:
        photo = None

    TOTAL_FRAMES = int(dur * FPS)
    GRID_STEP    = 60
    BORDER_W     = 10
    SLIDE_IN_DUR = 0.55   # segundos que dura el slide-in

    def ease_out(t): return 1 - (1-t)**3
    def ease_in_out(t): return t*t*(3-2*t)

    for fi in range(TOTAL_FRAMES):
        t = fi / FPS

        img = Image.new("RGB", (W, H), (13, 13, 13))
        draw = ImageDraw.Draw(img)

        # Cuadrícula animada (drift continuo)
        drift_x = int(-40 * (t / dur))
        drift_y = int(-28 * (t / dur))
        for gx in range(-GRID_STEP + (drift_x % GRID_STEP), W + GRID_STEP, GRID_STEP):
            draw.line([(gx, 0), (gx, H)], fill=(30, 30, 30))
        for gy in range(-GRID_STEP + (drift_y % GRID_STEP), H + GRID_STEP, GRID_STEP):
            draw.line([(0, gy), (W, gy)], fill=(30, 30, 30))

        # Foto con slide-in desde slide_from
        if photo:
            pw, ph = photo.size
            px_final = (W - pw) // 2
            py = (H - ph) // 2

            # Slide-in: la foto entra desde fuera de pantalla
            if t < SLIDE_IN_DUR:
                progress = ease_out(t / SLIDE_IN_DUR)
                offset = int((1.0 - progress) * (W + pw))  # distancia fuera de pantalla
                if slide_from == "right":
                    px = px_final + int((1.0 - progress) * (W - px_final + pw // 2))
                    px = min(px, W + pw)  # no se pase del borde derecho
                else:  # left
                    px = px_final - int((1.0 - progress) * (px_final + pw // 2 + W // 4))
                    px = max(px, -pw)
            else:
                # Ya llegó — pequeño pan sutil continuo
                pan = int(ease_out(min(1.0, (t - SLIDE_IN_DUR) / (dur - SLIDE_IN_DUR))) * 8)
                px = px_final + (pan if slide_from == "right" else -pan)

            # Borde blanco
            draw.rectangle([px - BORDER_W, py - BORDER_W,
                             px + pw + BORDER_W, py + ph + BORDER_W],
                            fill=(220, 220, 220))
            # Clip para no salir del canvas
            if px < W and px + pw > 0:
                src_x = max(0, -px)
                dst_x = max(0, px)
                paste_w = min(pw - src_x, W - dst_x)
                if paste_w > 0:
                    crop = photo.crop((src_x, 0, src_x + paste_w, ph))
                    img.paste(crop, (dst_x, py))

        # Badge dorado con texto — aparece después del slide-in
        if badge_line1 and t > SLIDE_IN_DUR:
            badge_prog = ease_out(min(1.0, (t - SLIDE_IN_DUR) / 0.4))
            b1 = badge_line1.upper()
            b2 = badge_line2.upper() if badge_line2 else None

            # Medir texto
            bb1 = draw.textbbox((0,0), b1, font=font_num)
            w1 = bb1[2]-bb1[0]
            bw = w1 + 80

            if b2:
                bb2 = draw.textbbox((0,0), b2, font=font_name)
                w2 = bb2[2]-bb2[0]
                bw = max(bw, w2 + 80)
                bh = 80
            else:
                bh = 48

            # Badge sube desde abajo
            by_final = H - 200
            by = int(by_final + (1.0 - badge_prog) * 60)
            bx = W // 2 - bw // 2

            # Fondo dorado (con alpha visual via blending simple)
            draw.rectangle([bx, by, bx+bw, by+bh], fill=(*GOLD,))
            draw.rectangle([bx, by-4, bx+bw, by-2], fill=(*GOLD,))

            # Textos
            if b2:
                draw.text((bx + 40, by + 8), b1, font=font_num, fill=(255,255,255))
                draw.text((bx + 40, by + 36), b2, font=font_name, fill=(255,255,255))
            else:
                draw.text((bx + 40, by + 12), b1, font=font_num, fill=(255,255,255))

        img.save(str(frames_dir / f"f{fi:05d}.jpg"), quality=90)

    run([FFMPEG,"-y","-framerate",str(FPS),"-i",str(frames_dir/"f%05d.jpg"),
         "-c:v","libx264","-preset","ultrafast","-crf","22",
         "-pix_fmt","yuv420p","-an",str(out_mp4),"-loglevel","error"],
        timeout=120)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return out_mp4


def _render_clip_in_frame(clip_path, out_mp4, dur=5.0, tmp_dir=None):
    """
    Clip de video dentro de encuadre HyperFrames (grid + borde blanco). Sin texto.
    """
    from PIL import Image, ImageDraw

    td = tmp_dir or out_mp4.parent
    frames_dir = td / f"_cframe_{out_mp4.stem}"
    frames_dir.mkdir(parents=True, exist_ok=True)

    BORDER_W  = 12
    INNER_W   = int(W * 0.85)
    INNER_H   = int(H * 0.85)
    ix = (W - INNER_W) // 2
    iy = (H - INNER_H) // 2
    GRID_STEP = 60
    TOTAL_F   = int(dur * FPS)

    # Extraer frames del clip de video
    clip_frames_dir = td / f"_cf_src_{out_mp4.stem}"
    clip_frames_dir.mkdir(parents=True, exist_ok=True)
    run([FFMPEG,"-y","-ss","0","-t",str(dur),"-i",str(clip_path),
         "-vf",f"scale={INNER_W}:{INNER_H}:force_original_aspect_ratio=increase,crop={INNER_W}:{INNER_H},hue=s=0,eq=contrast=1.05",
         "-r",str(FPS),str(clip_frames_dir/"v%05d.jpg"),"-loglevel","error"], timeout=60)
    clip_frames = sorted(clip_frames_dir.glob("v*.jpg"))

    for fi in range(TOTAL_F):
        base = Image.new("RGB", (W, H), (13, 13, 13))
        draw = ImageDraw.Draw(base)
        t = fi / FPS

        # Cuadrícula
        drift_x = int(-40 * t / dur)
        drift_y = int(-28 * t / dur)
        for gx in range(-GRID_STEP + (drift_x % GRID_STEP), W + GRID_STEP, GRID_STEP):
            draw.line([(gx, 0), (gx, H)], fill=(30, 30, 30))
        for gy in range(-GRID_STEP + (drift_y % GRID_STEP), H + GRID_STEP, GRID_STEP):
            draw.line([(0, gy), (W, gy)], fill=(30, 30, 30))

        # Borde blanco + frame del clip
        draw.rectangle([ix-BORDER_W, iy-BORDER_W, ix+INNER_W+BORDER_W, iy+INNER_H+BORDER_W],
                        fill=(220, 220, 220))
        if clip_frames:
            cf = clip_frames[min(fi, len(clip_frames)-1)]
            frame_img = Image.open(cf).convert("RGB").resize((INNER_W, INNER_H))
            base.paste(frame_img, (ix, iy))

        base.save(str(frames_dir / f"f{fi:05d}.jpg"), quality=90)

    shutil.rmtree(clip_frames_dir, ignore_errors=True)
    run([FFMPEG,"-y","-framerate",str(FPS),"-i",str(frames_dir/"f%05d.jpg"),
         "-c:v","libx264","-preset","ultrafast","-crf","22",
         "-pix_fmt","yuv420p","-an",str(out_mp4),"-loglevel","error"], timeout=120)
    shutil.rmtree(frames_dir, ignore_errors=True)
    return out_mp4


def render_artist(artist_label):
    """
    Renderiza un artista con intercalado HyperFrames:
      - Inicia con foto animada: badge "Número X" + nombre
      - Cada 4 clips → foto animada (sin texto)
      - Cada 8 clips → clip en encuadre HyperFrames (sin texto)
      - Audio: slice de audio.mp3 en el timestamp del artista
    Si el artista no tiene fotos en dashboard_meta.json → cae al modo clásico (solo clips).
    """
    banner(f"ARTISTA — {artist_label}")

    META_FILE = FOLDER / "dashboard_meta.json"
    FOTOS_DIR = FOLDER / "fotos"

    # Timestamps
    timestamps = load_timestamps()
    art_ts = next((t for t in timestamps
                   if not t.get("is_hook") and not t.get("is_cierre")
                   and (t["label"].strip() == artist_label.strip()
                        or t["name"].upper() == artist_label.upper()
                        or t["label"].upper().replace(" ","_") == artist_label.upper().replace(" ","_"))),
                  None)
    if not art_ts:
        print(f"{ROJO}✗ Artista '{artist_label}' no encontrado en timestamps.json{RESET}")
        sys.exit(1)

    nombre_display = art_ts["name"]
    art_start = art_ts["start"]
    art_dur   = art_ts["duration"]
    artists_only = [t for t in timestamps if not t.get("is_hook") and not t.get("is_cierre")]
    idx = next(i for i, t in enumerate(artists_only) if t["label"] == art_ts["label"])
    num_artista = idx + 1  # controla el prefijo del archivo (orden en el video, 1→N)

    # Número del badge — lo que el audio dice ("Número N, NOMBRE")
    badge_num = num_artista  # fallback: mismo que posición
    srt_path = FOLDER / "audio.srt"
    if srt_path.exists():
        import re, unicodedata
        def _strip(s):
            return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
        srt_norm = _strip(srt_path.read_text(encoding="utf-8", errors="ignore")).upper()
        first_word = _strip(nombre_display.split()[0]).upper()
        for m in re.finditer(r'NUMERO\s+(\d+)', srt_norm):
            if first_word in srt_norm[m.start():m.start()+80]:
                badge_num = int(m.group(1))
                break

    # Clips aprobados — orden del dashboard (dashboard_meta.json, por slot)
    if not META_FILE.exists():
        print(f"{ROJO}✗ No hay dashboard_meta.json{RESET}"); sys.exit(1)
    meta_all = json.loads(META_FILE.read_text())
    art_meta = meta_all.get(artist_label, {})
    clips_dict = art_meta.get("clips", {})
    if not clips_dict:
        print(f"{ROJO}✗ Sin clips en dashboard_meta para {artist_label}{RESET}"); sys.exit(1)
    # Ordenar por número de slot y excluir rechazados
    rejected = set(art_meta.get("rejected_clips", {}).keys()) | set(art_meta.get("deleted_yt_clips", {}).keys())
    sorted_clips = sorted(clips_dict.items(), key=lambda kv: kv[1].get("slot", 0))
    approved_clips = []
    for k, v in sorted_clips:
        if k in rejected: continue
        p = pathlib.Path(v.get("path") or v.get("filename") or k)
        if not p.exists():
            # intentar reconstruir desde iCloud
            fname = k.split("/")[-1].lstrip("slot000_repl_").lstrip("slot001_") if "/" not in k else k.split("/")[-1]
            # buscar en iCloud
            for d in ICLOUD.iterdir():
                candidate = d / fname
                if candidate.exists(): p = candidate; break
        if p.exists():
            approved_clips.append(p)
    if not approved_clips:
        print(f"{ROJO}✗ Sin clips válidos para {artist_label}{RESET}"); sys.exit(1)
        sys.exit(1)

    # Fotos del artista (desde dashboard_meta.json)
    artist_photos = []
    if META_FILE.exists():
        meta = json.loads(META_FILE.read_text())
        art_meta = meta.get(artist_label, {})
        for pname, pinfo in art_meta.get("photos", {}).items():
            p = pathlib.Path(pinfo["path"])
            if p.exists():
                artist_photos.append(p)
    has_photos = len(artist_photos) > 0

    SLOT_DUR = 5.0

    # Flow segments del artista — ordenados por segundo absoluto (igual que el dashboard)
    flow_segs_sorted = []
    tl_path = FOLDER / "05-montaje" / "timeline.json"
    flow_dir = FOLDER / "05-montaje" / "flow_images"
    if tl_path.exists():
        tl = json.loads(tl_path.read_text())
        for seg in tl.get("visual_timeline", []):
            if seg.get("artist_label", "") != artist_label:
                continue
            seg_id  = seg["segment_id"]
            zp_path = flow_dir / f"flow_{seg_id:03d}_zp.mp4"
            if not zp_path.exists():
                print(f"  ⚠ Flow {seg_id} sin zp.mp4 — saltado")
                continue
            if seg["end_seconds"] <= art_start or seg["start_seconds"] >= art_start + art_dur:
                continue
            flow_segs_sorted.append({
                "seg_id":      seg_id,
                "path":        zp_path,
                "slot_start":  seg["start_seconds"],   # absoluto
                "slot_end":    seg["end_seconds"],
                "dur":         seg["end_seconds"] - seg["start_seconds"],
            })
            print(f"  → Flow {seg_id}: {seg['start_seconds']:.1f}s–{seg['end_seconds']:.1f}s  ({seg['end_seconds']-seg['start_seconds']:.1f}s)")
    flow_segs_sorted.sort(key=lambda s: s["slot_start"])

    safe_label = art_ts["label"].replace(" ", "_")
    num_prefix = f"{num_artista:02d}"
    out_file   = RENDERS_DIR / f"{num_prefix}_{safe_label}.mp4"
    TMP = RENDERS_DIR / f"_tmp_{safe_label}"
    TMP.mkdir(parents=True, exist_ok=True)

    print(f"  Artista:   {nombre_display}  (Número {badge_num})")
    print(f"  Inicio:    {art_start}s  |  Duración: {art_dur:.1f}s")
    print(f"  Clips:     {len(approved_clips)}")
    print(f"  Fotos:     {len(artist_photos)}" + (" (intercalado HyperFrames activo)" if has_photos else " (modo clásico)"))

    # ─────────────────────────────────────────────────────────────────────────
    # Construir orden de clips igual que el dashboard (_build_combined):
    # cursor en segundos absolutos — flows se insertan cuando cursor >= slot_start
    # ─────────────────────────────────────────────────────────────────────────
    segs = []

    def _render_clip_bw(c, out_seg, dur):
        vf = (f"hflip,"
              f"scale={int(W*1.1)}:{int(H*1.1)}:force_original_aspect_ratio=increase:flags=lanczos,"
              f"crop={W}:{H}:(iw-ow)/2:(ih-oh)/2,"
              f"hue=s=0,eq=contrast=1.05")
        run([FFMPEG,"-y","-ss","0","-t",str(dur),"-i",str(c),
             "-vf",vf,"-t",str(dur),"-r",str(FPS),
             "-c:v","libx264","-preset","ultrafast","-crf","23","-an",
             "-pix_fmt","yuv420p",str(out_seg),"-loglevel","error"], timeout=120)

    def _render_flow(fw, out_seg):
        run([FFMPEG,"-y","-t",str(fw["dur"]),"-i",str(fw["path"]),
             "-vf",f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H}",
             "-t",str(fw["dur"]),"-r",str(FPS),
             "-c:v","libx264","-preset","ultrafast","-crf","22","-an",
             "-pix_fmt","yuv420p",str(out_seg),"-loglevel","error"], timeout=120)

    if not has_photos:
        # ── Modo clásico: clips B&W + card intro con primer clip + badge ──
        n_slots = max(1, round(art_dur / SLOT_DUR))
        print(f"\n  Procesando {n_slots} clips B&W…")
        clip_idx = 0
        for i in range(n_slots):
            dur = min(SLOT_DUR, art_dur - i * SLOT_DUR)
            if dur <= 0: break
            c = approved_clips[clip_idx % len(approved_clips)]
            out_seg = TMP / f"seg_{i:03d}.mp4"
            if i == 0:
                # Card intro animada: fondo oscuro + cuadrícula + badge slide-in (igual que HyperFrames pero sin foto)
                _render_photo_card(None, f"NÚMERO {badge_num}", nombre_display, out_seg, dur, TMP, slide_from="right")
                print(f"    [card 1] → INTRO ANIMADA (Número {badge_num} · {nombre_display})")
            else:
                _render_clip_bw(c, out_seg, dur)
            segs.append(out_seg)
            clip_idx += 1

    else:
        # ── Modo HyperFrames — mismo orden que el dashboard ───────────────
        # Cursor en segundos ABSOLUTOS, igual que _build_combined del dashboard
        cursor        = art_start
        yi            = 0          # índice en approved_clips
        photo_idx     = 0
        yt_since_photo = 0
        slide_cycle   = 0
        special_cycle = 0          # 0=foto, 1=frame_clip, alternando
        seg_i         = 0

        def next_seg():
            nonlocal seg_i
            p = TMP / f"seg_{seg_i:03d}.mp4"
            seg_i += 1
            return p

        # Foto intro
        out_seg = next_seg()
        direction = "right"; slide_cycle = 1
        print(f"    [card 1] → FOTO INTRO (Número {badge_num} · {nombre_display}) [{direction}]")
        _render_photo_card(artist_photos[0], f"NÚMERO {badge_num}", nombre_display, out_seg, SLOT_DUR, TMP, slide_from=direction)
        segs.append(out_seg)
        photo_idx = 1
        cursor += SLOT_DUR

        for fw in flow_segs_sorted:
            f_start = fw["slot_start"]
            # Rellenar con clips YT hasta llegar al segundo del flow
            while cursor < f_start - 0.1 and yi < len(approved_clips):
                c = approved_clips[yi]; yi += 1
                out_seg = next_seg()
                dur = min(SLOT_DUR, (art_start + art_dur) - cursor)
                if dur <= 0.1: break
                _render_clip_bw(c, out_seg, dur)
                segs.append(out_seg)
                print(f"    [card {seg_i}] → clip ({c.name[:45]})")
                cursor += SLOT_DUR
                yt_since_photo += 1
                if yt_since_photo % 4 == 0 and photo_idx < len(artist_photos):
                    out_seg = next_seg()
                    if special_cycle == 0:
                        direction = "left" if slide_cycle % 2 == 0 else "right"
                        slide_cycle += 1
                        print(f"    [card {seg_i}] → FOTO animada [{direction}]")
                        _render_photo_card(artist_photos[photo_idx], None, None, out_seg, SLOT_DUR, TMP, slide_from=direction)
                    else:
                        c2 = approved_clips[yi % len(approved_clips)]
                        print(f"    [card {seg_i}] → CLIP EN FRAME")
                        _render_clip_in_frame(c2, out_seg, SLOT_DUR, TMP)
                    special_cycle = 1 - special_cycle
                    segs.append(out_seg)
                    photo_idx += 1
                    cursor += SLOT_DUR
            # Insertar flow
            out_seg = next_seg()
            print(f"    [card {seg_i}] → FLOW IA ({fw['path'].name}, {fw['dur']:.1f}s)")
            _render_flow(fw, out_seg)
            segs.append(out_seg)
            cursor = fw["slot_end"]

        # Clips restantes hasta completar duración
        while yi < len(approved_clips) and cursor < art_start + art_dur - 0.1:
            c = approved_clips[yi]; yi += 1
            out_seg = next_seg()
            dur = min(SLOT_DUR, (art_start + art_dur) - cursor)
            if dur <= 0.1: break
            _render_clip_bw(c, out_seg, dur)
            segs.append(out_seg)
            print(f"    [card {seg_i}] → clip ({c.name[:45]})")
            cursor += SLOT_DUR
            yt_since_photo += 1
            if yt_since_photo % 4 == 0 and photo_idx < len(artist_photos) and cursor < art_start + art_dur - 0.1:
                out_seg = next_seg()
                if special_cycle == 0:
                    direction = "left" if slide_cycle % 2 == 0 else "right"
                    slide_cycle += 1
                    print(f"    [card {seg_i}] → FOTO animada [{direction}]")
                    _render_photo_card(artist_photos[photo_idx], None, None, out_seg, SLOT_DUR, TMP, slide_from=direction)
                else:
                    c2 = approved_clips[yi % len(approved_clips)]
                    print(f"    [card {seg_i}] → CLIP EN FRAME")
                    _render_clip_in_frame(c2, out_seg, SLOT_DUR, TMP)
                special_cycle = 1 - special_cycle
                segs.append(out_seg)
                photo_idx += 1
                cursor += SLOT_DUR

        print(f"\n  Total cards renderizados: {len(segs)}")

    # ── Concat cuerpo ──────────────────────────────────────────────────────
    print(f"\n  Concatenando {len(segs)} segmentos…", end=" ", flush=True)
    concat_txt = TMP / "concat.txt"
    concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in segs))
    body_raw = TMP / "body_raw.mp4"
    run([FFMPEG,"-y","-f","concat","-safe","0","-i",str(concat_txt),
         "-c:v","libx264","-preset","ultrafast","-crf","22",
         "-pix_fmt","yuv420p","-an",str(body_raw),"-loglevel","error"])
    print(f"{VERDE}✓  {probe_dur(body_raw):.1f}s{RESET}")

    # Recortar body a art_dur exacto (fotos/flows pueden excederlo)
    body_dur = probe_dur(body_raw)
    if body_dur > art_dur + 0.1:
        body_trimmed = TMP / "body_trimmed.mp4"
        run([FFMPEG,"-y","-i",str(body_raw),"-t",str(art_dur),
             "-c:v","copy","-an",str(body_trimmed),"-loglevel","error"])
        body_raw = body_trimmed
        body_dur = art_dur

    print(f"  Agregando audio (offset {art_start}s)…", end=" ", flush=True)
    run([FFMPEG,"-y",
         "-i",str(body_raw),
         "-ss",str(art_start),"-t",str(body_dur),"-i",str(AUDIO),
         "-c:v","copy","-c:a","aac","-b:a","192k","-shortest",
         str(out_file),"-loglevel","error"])
    dur_f  = probe_dur(out_file)
    size_f = out_file.stat().st_size/1024/1024
    print(f"{VERDE}✓  {dur_f:.1f}s  {size_f:.1f} MB{RESET}")

    # ── Validador de audio ────────────────────────────────────────────────────
    # Verifica que el audio empiece y termine dentro del segmento del artista
    def audio_rms(path, ss, t):
        r = subprocess.run(
            [FFMPEG,"-ss",str(ss),"-t",str(t),"-i",str(path),
             "-af","astats=metadata=1:reset=1","-f","null","-"],
            capture_output=True, text=True)
        for line in r.stderr.splitlines():
            if "RMS level dB" in line:
                try: return float(line.split()[-1])
                except: pass
        return None

    rms_start = audio_rms(out_file, 0.5, 2.0)
    rms_end   = audio_rms(out_file, dur_f - 3.0, 2.5)
    ok_start = rms_start is not None and rms_start > -60
    ok_end   = rms_end   is not None and rms_end   > -60
    print(f"  Audio inicio: {f'{rms_start:.1f} dB' if rms_start else 'N/A'}  {'✓' if ok_start else '✗ SIN AUDIO'}")
    print(f"  Audio final:  {f'{rms_end:.1f} dB'   if rms_end   else 'N/A'}  {'✓' if ok_end   else '✗ SIN AUDIO — últimos 3s mudos'}")
    if not ok_end:
        print(f"  {ROJO}⚠ ADVERTENCIA: el segmento termina sin audio{RESET}")

    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n  {VERDE}✓ {out_file.name}{RESET}  →  {out_file}")
    return out_file

# ─── MODO FINAL ───────────────────────────────────────────────────────────────
def render_final():
    banner("RENDER FINAL — concat")
    # De cada label (00_hook, 01_JORGE…) quedarse solo con el MÁS RECIENTE
    all_parts = sorted(RENDERS_DIR.glob("[0-9][0-9]_*.mp4"))
    seen_labels = {}
    for p in all_parts:
        # Extraer label ignorando el prefijo numérico de versión
        # ej: "01_01_JORGE_MISTRAL" → label = "01_JORGE_MISTRAL"
        parts_name = p.stem  # "01_01_JORGE_MISTRAL"
        tokens = parts_name.split("_", 1)  # ["01", "01_JORGE_MISTRAL"]
        label = tokens[1] if len(tokens) > 1 else parts_name
        # Guardar solo el más reciente (mayor mtime)
        if label not in seen_labels or p.stat().st_mtime > seen_labels[label].stat().st_mtime:
            seen_labels[label] = p
    parts = sorted(seen_labels.values(), key=lambda p: p.name)
    if not parts:
        print(f"{ROJO}✗ No hay renders en {RENDERS_DIR}{RESET}")
        sys.exit(1)

    print(f"  Segmentos encontrados ({len(parts)}):")
    for p in parts:
        dur = probe_dur(p)
        size = p.stat().st_size/1024/1024
        print(f"    {p.name}  {dur:.1f}s  {size:.1f} MB")

    concat_txt = RENDERS_DIR / "_final_concat.txt"
    concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in parts))

    # filter_complex concat normaliza timestamps (evita corrupción con HyperFrames)
    print(f"\n  Concatenando → output.mp4…", end=" ", flush=True)
    inputs = []
    for p in parts:
        inputs += ["-i", str(p)]
    n = len(parts)
    # setsar=1 normaliza SAR antes del concat (algunos clips tienen SAR no-cuadrado)
    fc = "".join(f"[{i}:v]setsar=1[v{i}];[{i}:a]anull[a{i}];" for i in range(n))
    fc += "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
    run([FFMPEG,"-y"] + inputs +
        ["-filter_complex", fc,
         "-map","[v]","-map","[a]",
         "-c:v","libx264","-preset","ultrafast","-crf","20",
         "-c:a","aac","-b:a","192k",
         "-pix_fmt","yuv420p","-movflags","+faststart",
         str(OUTPUT),"-loglevel","error"], timeout=600)
    dur_f  = probe_dur(OUTPUT)
    size_f = OUTPUT.stat().st_size/1024/1024
    print(f"{VERDE}✓{RESET}")
    print(f"\n{NEG}{VERDE}{'='*60}")
    print(f"  ✓  output.mp4")
    print(f"  Duración: {dur_f:.1f}s  ({dur_f/60:.1f} min)  |  {size_f:.1f} MB")
    print(f"  {OUTPUT}")
    print(f"{'='*60}{RESET}\n")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    mode = sys.argv[1].lower()
    RENDERS_DIR.mkdir(exist_ok=True)

    if mode == "hook":
        render_hook()

    elif mode == "artist":
        if len(sys.argv) < 3:
            print(f"{ROJO}Uso: python3 render_epocadeoro.py artist LABEL_ARTISTA{RESET}")
            # Mostrar artistas disponibles
            ts = load_timestamps()
            print("Artistas disponibles:")
            for t in ts:
                if not t.get("is_hook") and not t.get("is_cierre"):
                    print(f"  {t['label']}")
            sys.exit(1)
        render_artist(sys.argv[2])

    elif mode == "final":
        render_final()

    elif mode == "all":
        render_hook()
        ts = load_timestamps()
        for t in ts:
            if not t.get("is_hook") and not t.get("is_cierre"):
                render_artist(t["label"])
        render_final()

    else:
        print(f"{ROJO}Modo desconocido: {mode}{RESET}")
        print("Modos: hook | artist LABEL | final | all")
        sys.exit(1)
