#!/usr/bin/env python3
"""
generar_timeline_canal.py — Motor genérico de planificación visual.

Lee _config/<canal>.json → extrae contexto y triggers del canal
→ llama a Gemini por lotes → genera 05-montaje/timeline.json

Uso:
    python3 generar_timeline_canal.py <carpeta_video> --canal botica
    python3 generar_timeline_canal.py riqueza/victoria_ruffo/ --canal riqueza
    python3 generar_timeline_canal.py futbol/lamine_yamal/ --canal futbol

Si se omite --canal, infiere el canal del nombre del directorio padre.
Requiere ~/.openrouter_key
"""

import sys, re, json, pathlib, time, os, argparse
import urllib.request, urllib.error
from timeline_prompt_fixer import auto_fix_prompts

BATCH_SECONDS = 90
MAX_SEG_SECS  = 8.0
MIN_SEG_SECS  = 2.0

HOME        = pathlib.Path.home()
KEY_FILE    = HOME / ".openrouter_key"
OR_MODEL    = "google/gemini-2.5-flash-lite"
OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
CANALES_DIR = pathlib.Path(__file__).parent
CONFIG_DIR  = CANALES_DIR / "_config"

# ── Cargar config del canal ───────────────────────────────────────────────────

def cargar_config(canal: str) -> dict:
    cfg_path = CONFIG_DIR / f"{canal}.json"
    if not cfg_path.exists():
        print(f"ERROR: No existe {cfg_path}")
        print(f"  Canales disponibles: {[f.stem for f in CONFIG_DIR.glob('*.json')]}")
        sys.exit(1)
    return json.loads(cfg_path.read_text(encoding="utf-8"))

def inferir_canal(carpeta: pathlib.Path) -> str:
    """Infiere el canal del nombre del directorio padre."""
    padre = carpeta.parent.name
    cfg_path = CONFIG_DIR / f"{padre}.json"
    if cfg_path.exists():
        return padre
    print(f"ERROR: No se pudo inferir canal desde '{padre}'. Usa --canal <nombre>")
    sys.exit(1)

# ── Construir system prompt desde config ──────────────────────────────────────

def build_system_prompt(cfg: dict, video_name: str) -> str:
    planner = cfg.get("timeline_planner", {})
    channel_context   = planner.get("channel_context", "A Spanish-language YouTube channel.")
    trigger_types     = planner.get("trigger_types_description", "")
    image_style       = planner.get("image_style", "Cinematic hyperrealistic photo, dramatic lighting, 16:9")
    veo_note          = planner.get("veo_prompt_note", "")
    cover_mode        = planner.get("cover_mode", "full")
    harvester         = cfg.get("harvester", {})
    prompt_suffix     = harvester.get("prompt_suffix", "")

    cover_instruction = (
        "Cover the ENTIRE narration window continuously — every second must have a visual."
        if cover_mode == "full"
        else "Only generate inserts for the specific trigger types listed. Leave gaps where not applicable."
    )

    return f"""You are a Visual Timeline Planner for a YouTube channel.

CHANNEL: {channel_context}
VIDEO: {video_name}

YOUR TASK:
Read the SRT narration and plan image inserts. {cover_instruction}

🔴 MANDATORY OPENING PLACE RULE: If the VERY FIRST ENTRY of the FIRST BATCH contains a city or location name — you MUST generate a place/location insert at start_seconds=0 showing that exact city/place. NEVER skip the opening city even if it appears in a date line. The city is ALWAYS the first trigger when it appears at t=0.

TRIGGER TYPES TO DETECT:
{trigger_types}

SEGMENT RULES:
- Duration: 3–8 seconds per segment. Never exceed 8s. Never below 2s.
- No overlaps ever. Segments must be contiguous.
- First segment.start_seconds = batch_start exactly.
- Last segment.end_seconds = batch_end exactly.
- Group 1–2 consecutive SRT entries per segment maximum.

IMAGE PROMPT STYLE:
Base style: {image_style}
Always append: "{prompt_suffix}"
Write ALL image prompts in English. Be specific and cinematic.
Never include real people's faces. Never include text in the image.

VEO PROMPT (camera movement only):
{veo_note}
For segments after the first 90 seconds: veo_prompt = ""

OUTPUT — valid JSON only, no markdown fences:
{{
  "visual_timeline": [
    {{
      "segment_id": 1,
      "source": "flow",
      "start_seconds": 0.0,
      "end_seconds": 6.5,
      "duration": 6.5,
      "scene_description_es": "Descripción en español de la escena visual",
      "ia_prompt": "Cinematic hyperrealistic photo of ..., {prompt_suffix}",
      "veo_prompt": "Slow macro zoom into subject, dramatic side light",
      "covers_text": "texto exacto del SRT que cubre este segmento",
      "trigger_type": "planta|afeccion|preparacion|ciencia|historia|lugar|generico"
    }}
  ]
}}"""

USER_TEMPLATE = """BATCH {batch_number} of {total_batches}
TIME WINDOW: {batch_start}s → {batch_end}s
VIDEO: {video_name}

SRT ENTRIES:
{sentences_json}

RULES:
1. Use EXACT timestamps from the SRT ("t" = start, "end" = end). Never invent timestamps.
2. start_seconds = first entry's "t", end_seconds = last entry's "end".
3. Cover this entire time window — no gaps.
4. Max 8s per segment. Min 2s.
5. 1–2 consecutive SRT entries per segment maximum.

JSON only."""

# ── Parsing ───────────────────────────────────────────────────────────────────

def ts_to_sec(ts):
    ts = ts.strip().replace(',', '.')
    p = ts.split(':')
    return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])

def parse_srt(srt_path, max_entry_secs=8.0):
    content = srt_path.read_text(encoding='utf-8')
    blocks  = re.split(r'\n\n+', content.strip())
    entries = []
    for block in blocks:
        lines = [l for l in block.strip().split('\n') if l.strip()]
        if len(lines) < 3 or '-->' not in lines[1]:
            continue
        times = lines[1].split('-->')
        start = ts_to_sec(times[0])
        end   = ts_to_sec(times[1])
        text  = ' '.join(lines[2:]).strip()
        if not text or end <= start:
            continue
        duration = end - start
        if duration <= max_entry_secs:
            entries.append({'start': round(start, 3), 'end': round(end, 3), 'text': text})
        else:
            n_chunks = int(duration / max_entry_secs) + 1
            chunk_dur = duration / n_chunks
            words = text.split()
            words_per_chunk = max(1, len(words) // n_chunks)
            for i in range(n_chunks):
                c_start = start + i * chunk_dur
                c_end   = start + (i + 1) * chunk_dur
                c_words = words[i * words_per_chunk: (i + 1) * words_per_chunk] or words[-1:]
                entries.append({
                    'start': round(c_start, 3),
                    'end':   round(min(c_end, end), 3),
                    'text':  ' '.join(c_words)
                })
    return entries

def make_batches(entries, batch_seconds=BATCH_SECONDS):
    batches, current = [], []
    for entry in entries:
        current.append(entry)
        if current[-1]['end'] - current[0]['start'] >= batch_seconds:
            batches.append(current)
            current = []
    if current:
        batches.append(current)
    return batches

def extract_json(text):
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text, flags=re.MULTILINE)
    return json.loads(text)

# ── Llamada a OpenRouter ──────────────────────────────────────────────────────

def call_openrouter(api_key, system_prompt, video_name, batch, batch_num, total_batches, retries=3):
    batch_start = batch[0]['start']
    batch_end   = batch[-1]['end']

    sentences_json = json.dumps(
        [{'t': e['start'], 'end': e['end'], 'text': e['text']} for e in batch],
        ensure_ascii=False, indent=2
    )

    user_msg = USER_TEMPLATE.format(
        batch_number=batch_num,
        total_batches=total_batches,
        batch_start=batch_start,
        batch_end=batch_end,
        video_name=video_name,
        sentences_json=sentences_json,
    )

    payload = json.dumps({
        "model": OR_MODEL,
        "max_tokens": 8192,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_msg},
        ]
    }).encode()

    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                OR_ENDPOINT,
                data=payload,
                headers={
                    "Content-Type":  "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer":  "https://la-botica-ancestral.canal",
                }
            )
            with urllib.request.urlopen(req, timeout=90) as r:
                resp = json.loads(r.read())
            text     = resp["choices"][0]["message"]["content"]
            data     = extract_json(text)
            segments = data.get('visual_timeline', [])
            if segments:
                return segments
            print(f"    ⚠ Respuesta vacía — reintento {attempt+1}")
        except json.JSONDecodeError as e:
            print(f"    ⚠ JSON inválido intento {attempt+1}: {e}")
            if attempt < retries - 1:
                time.sleep(3)
        except Exception as e:
            print(f"    ⚠ Error intento {attempt+1}: {e}")
            if attempt < retries - 1:
                time.sleep(5)
    return []

# ── Sanitizar timeline ────────────────────────────────────────────────────────

def sanitize_timeline(segments):
    if not segments:
        return segments
    segments = sorted(segments, key=lambda s: s['start_seconds'])
    if segments and segments[0]['start_seconds'] < 20:
        dur = segments[0]['end_seconds'] - segments[0]['start_seconds']
        segments[0]['start_seconds'] = 0
        segments[0]['end_seconds'] = round(dur, 3)
        segments[0]['duration'] = round(dur, 3)
    fixes = []
    for s in segments:
        duration = s['end_seconds'] - s['start_seconds']
        if duration > MAX_SEG_SECS:
            old_end = s['end_seconds']
            s['end_seconds'] = round(s['start_seconds'] + MAX_SEG_SECS, 3)
            s['duration'] = MAX_SEG_SECS
            fixes.append(f"  ⚠ SEG {s['segment_id']}: {duration:.1f}s → {MAX_SEG_SECS}s")
        else:
            s['duration'] = round(duration, 3)
    for i in range(len(segments) - 1):
        cur, nxt = segments[i], segments[i + 1]
        if cur['end_seconds'] > nxt['start_seconds']:
            old_end = cur['end_seconds']
            cur['end_seconds'] = round(nxt['start_seconds'], 3)
            cur['duration']    = round(cur['end_seconds'] - cur['start_seconds'], 3)
            fixes.append(f"  ⚠ OVERLAP SEG {cur['segment_id']}→{nxt['segment_id']}")
    # Extender segmentos con duración < 3s (mínimo viable para zoompan)
    MIN_DUR_SECS = 3.0
    for i, s in enumerate(segments):
        duration = s['end_seconds'] - s['start_seconds']
        if duration < MIN_DUR_SECS:
            max_end = segments[i + 1]['start_seconds'] - 0.001 if i + 1 < len(segments) else s['start_seconds'] + MIN_DUR_SECS
            new_end = min(round(s['start_seconds'] + MIN_DUR_SECS, 3), max_end)
            if new_end - s['start_seconds'] >= 1.0:
                fixes.append(f"  ⚠ SEG {s['segment_id']}: {duration:.1f}s → {new_end - s['start_seconds']:.1f}s (extendido mínimo 3s)")
                s['end_seconds'] = new_end
                s['duration']    = round(new_end - s['start_seconds'], 3)
            else:
                s['_delete'] = True
                fixes.append(f"  ⚠ SEG {s['segment_id']} eliminado ({duration:.1f}s < 3s sin espacio)")
    segments = [s for s in segments if not s.get('_delete')]
    if fixes:
        print(f"\n{'─'*62}")
        print(f"  sanitize: {len(fixes)} corrección(es)")
        for f in fixes:
            print(f)
        print(f"{'─'*62}\n")
    else:
        print(f"\n  ✓ Sin overlaps, todas las duraciones ≤ {MAX_SEG_SECS}s")
    return segments

def fill_gaps(segments):
    if not segments:
        return segments
    filled = [segments[0]]
    extra_segs = []
    for i in range(1, len(segments)):
        prev = filled[-1]
        cur  = segments[i]
        gap  = round(cur['start_seconds'] - prev['end_seconds'], 3)
        if gap <= 0:
            filled.append(cur)
            continue
        if gap <= 4.0:
            prev['end_seconds'] = cur['start_seconds']
            prev['duration']    = round(prev['end_seconds'] - prev['start_seconds'], 3)
        else:
            while gap > 0:
                chunk = min(gap, MAX_SEG_SECS)
                new_seg = dict(prev)
                new_seg['segment_id']    = 9000 + len(extra_segs)
                new_seg['start_seconds'] = prev['end_seconds']
                new_seg['end_seconds']   = round(prev['end_seconds'] + chunk, 3)
                new_seg['duration']      = round(chunk, 3)
                extra_segs.append(new_seg)
                filled.append(new_seg)
                prev = new_seg
                gap  = round(cur['start_seconds'] - prev['end_seconds'], 3)
        filled.append(cur)
    if extra_segs:
        print(f"  fill_gaps: {len(extra_segs)} segmento(s) de relleno")
    for i, s in enumerate(filled, 1):
        s['segment_id'] = i
    return filled

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Planificador visual genérico por canal")
    parser.add_argument("carpeta", help="Carpeta del video")
    parser.add_argument("--canal", help="Nombre del canal (ej: botica, riqueza, futbol)")
    args = parser.parse_args()

    carpeta  = pathlib.Path(args.carpeta)
    canal    = args.canal or inferir_canal(carpeta)
    cfg      = cargar_config(canal)

    nombre   = carpeta.name
    srt_file = carpeta / f"{nombre}.srt"
    out_dir  = carpeta / "05-montaje"
    out_file = out_dir / "timeline.json"

    out_dir.mkdir(parents=True, exist_ok=True)

    if not srt_file.exists():
        print(f"ERROR: No existe {srt_file}")
        sys.exit(1)

    api_key = ""
    if KEY_FILE.exists():
        api_key = KEY_FILE.read_text().strip()
    elif os.environ.get('OPENROUTER_API_KEY'):
        api_key = os.environ['OPENROUTER_API_KEY']
    else:
        print(f"ERROR: Sin API key en {KEY_FILE}"); sys.exit(1)

    video_name    = nombre.replace('_', ' ').title()
    system_prompt = build_system_prompt(cfg, video_name)

    nombre_display = cfg.get("nombre_display", canal.upper())
    print(f"\n{'═'*62}")
    print(f"  TIMELINE PLANNER — {video_name.upper()}")
    print(f"  Canal: {nombre_display} ({canal})")
    print(f"{'═'*62}")

    entries = parse_srt(srt_file)
    if not entries:
        print("ERROR: SRT vacío"); sys.exit(1)

    total_duration = entries[-1]['end']
    max_batch = cfg.get("timeline_planner", {}).get("max_batch_seconds", BATCH_SECONDS)
    batches       = make_batches(entries, max_batch)
    total_batches = len(batches)

    print(f"  SRT:      {len(entries)} entradas")
    print(f"  Duración: {total_duration:.1f}s  ({total_duration/60:.1f} min)")
    print(f"  Lotes:    {total_batches} × ~{max_batch}s")
    print()

    all_segments    = []
    segment_counter = 1

    for i, batch in enumerate(batches, 1):
        b_start = batch[0]['start']
        b_end   = batch[-1]['end']
        print(f"  [{i:02d}/{total_batches}] {b_start:.1f}s → {b_end:.1f}s  ({len(batch)} entradas)...", end='', flush=True)

        t0       = time.time()
        segments = call_openrouter(api_key, system_prompt, video_name, batch, i, total_batches)
        elapsed  = time.time() - t0

        for s in segments:
            if 'start' in s and 'start_seconds' not in s:
                s['start_seconds'] = s.pop('start')
            if 'end' in s and 'end_seconds' not in s:
                s['end_seconds'] = s.pop('end')
            if 'end_seconds' not in s and 'duration' in s and 'start_seconds' in s:
                s['end_seconds'] = round(s['start_seconds'] + s['duration'], 3)
            s['segment_id'] = segment_counter
            segment_counter += 1

        all_segments.extend(segments)
        print(f" {len(segments)} segmentos ({elapsed:.1f}s)")

        if i < total_batches:
            time.sleep(1)

    if not all_segments:
        print("ERROR: No se generaron segmentos"); sys.exit(1)

    all_segments = sanitize_timeline(all_segments)
    all_segments = fill_gaps(all_segments)

    out_file.write_text(
        json.dumps({"visual_timeline": all_segments}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\n  ✓ timeline.json → {out_file}")
    print(f"  Total segmentos: {len(all_segments)}")

    sources = {}
    for s in all_segments:
        src = s.get('source', '?')
        sources[src] = sources.get(src, 0) + 1
    print(f"\n  Fuentes:")
    for src, count in sorted(sources.items(), key=lambda x: -x[1]):
        print(f"    {src:<20} {count:3d} segmentos ({count/len(all_segments)*100:.0f}%)")

    print(f"\n  Siguiente paso:")
    print(f"  python3 harvester_timeline.py {args.carpeta} --canal {canal}")

if __name__ == "__main__":
    main()
