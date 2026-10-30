#!/usr/bin/env python3
"""
generar_timeline_seduccion.py — Planificador visual para canal Enigma Estoica.

Lee el SRT del video → Claude Haiku analiza cada segmento → clasifica la fuente
de imagen → genera 05-montaje/timeline.json anclado al audio.

Fuentes posibles por segmento:
  - "ia_stickfigure" : imagen generada con muapi.ai (figuras de palito, fondo negro)
  - "pixabay"        : clip de video de Pixabay (ambiente, ciudad, naturaleza)
  - "brave_search"   : imagen real buscada en Brave (datos, lugares, personas reales)

Regla de prioridad:
  - Primeros 180s (3 min) → ia_stickfigure preferido para momentos clave
  - Resto → pixabay de relleno + ia para momentos de alto impacto emocional
  - Si la voz nombra algo verificable (dato, lugar, estudio) → brave_search

Uso:
    python3 generar_timeline_seduccion.py seduccion/7_errores/
"""

import sys, re, json, pathlib, time, os
import urllib.request, urllib.error
from timeline_prompt_fixer import auto_fix_prompts

# ── Config ────────────────────────────────────────────────────────────────────
BATCH_SECONDS   = 90      # segundos de SRT por lote enviado a Claude
MAX_SEG_SECS    = 8.0     # duración máxima de un segmento visual
MIN_SEG_SECS    = 2.0     # duración mínima
PRIORITY_WINDOW = 180     # primeros N segundos → prioridad ia_stickfigure

HOME             = pathlib.Path.home()
KEY_FILE         = HOME / ".openrouter_key"
OR_MODEL         = "google/gemini-2.5-flash-lite"
OR_ENDPOINT      = "https://openrouter.ai/api/v1/chat/completions"

# ── Prompts Claude ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a Visual Content Planner for a Spanish-language YouTube channel about male psychology and attraction. The channel is called "Enigma Estoica".

VISUAL STYLE: Minimalist stick figures (white lines on black background). Clean, expressive, educational. Think simple whiteboard animation aesthetic.

YOUR TASK:
Given timestamped SRT entries from a narration, create visual segments. Each segment needs:
1. An exact timestamp window (start → end)
2. A visual source classification
3. A specific prompt or search query

VISUAL SOURCES — choose the most appropriate:
- "ia_stickfigure": Generate with AI. Use for abstract concepts, psychological scenarios, social situations with stick figures. Prompts in English.
- "pixabay": Search free video clips. Use for ambient scenes: city streets, cafes, bars, nature, people walking (no faces needed). Search queries in English.
- "brave_search": Search real images. Use ONLY when the narration mentions a verifiable fact, study, statistic, or named place. Search queries in Spanish or English.

🔴 MANDATORY OPENING PLACE RULE: If the VERY FIRST ENTRY of the FIRST BATCH contains a city or location name — you MUST generate a brave_search insert at start_seconds=0 showing that exact city/place. NEVER skip the opening location even if it appears in a date line. The location is ALWAYS the first trigger when it appears at t=0.

CLASSIFICATION RULES:
- Psychological concepts (fear, confidence, belief systems) → ia_stickfigure
- Social scenarios (conversation, bar, party) → pixabay OR ia_stickfigure
- Named studies, statistics, real people → brave_search
- Abstract emotions, internal states → ia_stickfigure
- Urban environments, ambient atmosphere → pixabay
- First 180 seconds: prefer ia_stickfigure for maximum impact

STICK FIGURE PROMPT STYLE (ia_stickfigure only):
- White minimalist stick figures on pure black background
- Line art style, expressive poses, simple facial expressions (dots for eyes, curve for mouth)
- Include speech bubbles, thought bubbles, or action lines when relevant — any text INSIDE bubbles or signs must be in SPANISH (e.g. speech bubble saying "¿Cómo te fue?" not "How did it go?")
- Max 2-3 figures per scene
- Always end with: "white line art on black background, minimalist stick figure style, no color, high contrast"

SEGMENTATION RULES:
1. Every SRT entry gets AT LEAST one segment
2. No segment > 8.0 seconds — split if needed
3. No segment < 2.0 seconds
4. ZERO GAPS: segment N+1 starts exactly where N ended
5. First segment.start_seconds = batch_start (exact float)
6. Last segment.end_seconds = batch_end (exact float)

OUTPUT: Valid JSON only, no markdown, no explanation.
{
  "visual_timeline": [
    {
      "segment_id": 1,
      "source": "ia_stickfigure",
      "start_seconds": 0.0,
      "end_seconds": 6.5,
      "duration": 6.5,
      "scene_description_es": "Descripción en español de lo que se ve",
      "prompt_or_query": "English prompt or search query here... white line art on black background, minimalist stick figure style, no color, high contrast",
      "covers_text": "Exact phrase from the narration this segment covers",
      "emotional_beat": "contrast|hook|problem|insight|framework|resolution|cta",
      "priority": "high|medium|low"
    }
  ]
}"""

USER_TEMPLATE = """BATCH {batch_number} of {total_batches}
TIME WINDOW: {batch_start}s → {batch_end}s ({batch_duration:.1f}s)
VIDEO: {video_name}
PRIORITY WINDOW: first {priority_window}s = prefer ia_stickfigure

SRT ENTRIES:
{sentences_json}

Create segments covering EXACTLY {batch_start}s to {batch_end}s. Zero gaps.
JSON only."""

# ── Parseo SRT ────────────────────────────────────────────────────────────────

def ts_to_sec(ts: str) -> float:
    ts = ts.strip().replace(',', '.')
    parts = ts.split(':')
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])

def parse_srt(srt_path: pathlib.Path) -> list:
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
        if text and end > start:
            entries.append({'start': round(start, 3), 'end': round(end, 3), 'text': text})
    return entries

# ── Batching ──────────────────────────────────────────────────────────────────

def make_batches(entries: list, batch_seconds: float = BATCH_SECONDS) -> list:
    batches, current = [], []
    for entry in entries:
        current.append(entry)
        if current[-1]['end'] - current[0]['start'] >= batch_seconds:
            batches.append(current)
            current = []
    if current:
        batches.append(current)
    return batches

# ── Claude Haiku ──────────────────────────────────────────────────────────────

def extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text, flags=re.MULTILINE)
    return json.loads(text)

def call_openrouter(api_key: str, video_name: str, batch: list, batch_num: int,
                    total_batches: int, retries: int = 3) -> list:
    batch_start = batch[0]['start']
    batch_end   = batch[-1]['end']
    duration    = batch_end - batch_start

    sentences_json = json.dumps(
        [{'t': e['start'], 'end': e['end'], 'text': e['text']} for e in batch],
        ensure_ascii=False, indent=2
    )

    user_msg = USER_TEMPLATE.format(
        batch_number=batch_num,
        total_batches=total_batches,
        batch_start=batch_start,
        batch_end=batch_end,
        batch_duration=duration,
        video_name=video_name,
        priority_window=PRIORITY_WINDOW,
        sentences_json=sentences_json,
    )

    payload = json.dumps({
        "model": OR_MODEL,
        "max_tokens": 8192,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
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
                    "HTTP-Referer":  "https://enigmaestoica.canal",
                }
            )
            with urllib.request.urlopen(req, timeout=60) as r:
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

# ── Validación de gaps ────────────────────────────────────────────────────────

def validate_segments(segments: list, batch_start: float, batch_end: float) -> list:
    if not segments:
        return segments
    segments[0]['start_seconds'] = round(batch_start, 3)
    for i in range(1, len(segments)):
        segments[i]['start_seconds'] = round(segments[i-1]['end_seconds'], 3)
    segments[-1]['end_seconds'] = round(batch_end, 3)
    for s in segments:
        s['duration'] = round(s['end_seconds'] - s['start_seconds'], 3)
    return segments

# ── Resumen de fuentes ────────────────────────────────────────────────────────

def print_summary(segments: list):
    sources = {}
    for s in segments:
        src = s.get('source', 'desconocido')
        sources[src] = sources.get(src, 0) + 1

    print(f"\n  Distribución de fuentes:")
    for src, count in sorted(sources.items(), key=lambda x: -x[1]):
        pct = count / len(segments) * 100
        icon = {"ia_stickfigure": "🤖", "pixabay": "🎬", "brave_search": "🔍"}.get(src, "❓")
        print(f"    {icon} {src:<20} {count:3d} segmentos  ({pct:.0f}%)")

    high = sum(1 for s in segments if s.get('priority') == 'high')
    print(f"\n  Segmentos de alta prioridad: {high}")
    first_3min = [s for s in segments if s.get('start_seconds', 0) < 180]
    ia_first   = [s for s in first_3min if s.get('source') == 'ia_stickfigure']
    print(f"  Primeros 3 min: {len(first_3min)} segmentos, {len(ia_first)} con IA stick figure")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 generar_timeline_seduccion.py <carpeta_video>")
        sys.exit(1)

    carpeta   = pathlib.Path(sys.argv[1])
    nombre    = carpeta.name
    srt_file  = carpeta / f"{nombre}.srt"
    out_dir   = carpeta / "05-montaje"
    out_file  = out_dir / "timeline.json"

    out_dir.mkdir(parents=True, exist_ok=True)

    if not srt_file.exists():
        print(f"ERROR: No existe {srt_file}")
        sys.exit(1)

    # API key OpenRouter
    api_key = ""
    if KEY_FILE.exists():
        api_key = KEY_FILE.read_text().strip()
    elif os.environ.get('OPENROUTER_API_KEY'):
        api_key = os.environ['OPENROUTER_API_KEY']
    else:
        print(f"ERROR: Sin API key en {KEY_FILE}")
        sys.exit(1)

    video_name = nombre.replace('_', ' ').title()

    print(f"\n{'═'*62}")
    print(f"  TIMELINE PLANNER — {video_name.upper()}")
    print(f"  Canal: Enigma Estoica")
    print(f"{'═'*62}")

    entries = parse_srt(srt_file)
    if not entries:
        print("ERROR: SRT vacío"); sys.exit(1)

    total_duration = entries[-1]['end']
    print(f"  SRT:      {len(entries)} entradas")
    print(f"  Duración: {total_duration:.1f}s  ({total_duration/60:.1f} min)")
    print(f"  Ventana prioritaria (IA): primeros {PRIORITY_WINDOW}s")

    batches       = make_batches(entries, BATCH_SECONDS)
    total_batches = len(batches)
    print(f"  Lotes:    {total_batches} × ~{BATCH_SECONDS}s")
    print()

    all_segments    = []
    segment_counter = 1

    for i, batch in enumerate(batches, 1):
        b_start = batch[0]['start']
        b_end   = batch[-1]['end']
        print(f"  [{i:02d}/{total_batches}] {b_start:.1f}s → {b_end:.1f}s  ({len(batch)} entradas)...", end='', flush=True)

        t0       = time.time()
        segments = call_openrouter(api_key, video_name, batch, i, total_batches)
        elapsed  = time.time() - t0

        if not segments:
            print(f" ✗ Sin resultado (lote omitido)")
            continue

        segments = validate_segments(segments, b_start, b_end)

        for seg in segments:
            seg['segment_id'] = segment_counter
            segment_counter  += 1
            all_segments.append(seg)

        src_counts = {}
        for s in segments:
            k = s.get('source', '?')[:3]
            src_counts[k] = src_counts.get(k, 0) + 1
        src_str = ' '.join(f"{k}:{v}" for k, v in src_counts.items())
        print(f" ✓  {len(segments)} segs  [{src_str}]  ({elapsed:.1f}s)")

        if i < total_batches:
            time.sleep(0.5)

    # ── Guardar ───────────────────────────────────────────────────────────────
    result = {
        "meta": {
            "video":            nombre,
            "canal":            "Enigma Estoica",
            "total_segments":   len(all_segments),
            "total_duration_s": round(total_duration, 1),
            "generated_at":     time.strftime('%Y-%m-%d %H:%M:%S'),
            "sources": {
                "ia_stickfigure": sum(1 for s in all_segments if s.get('source') == 'ia_stickfigure'),
                "pixabay":        sum(1 for s in all_segments if s.get('source') == 'pixabay'),
                "brave_search":   sum(1 for s in all_segments if s.get('source') == 'brave_search'),
            }
        },
        "visual_timeline": all_segments
    }

    # Corregir micro-gaps (<2s) + redondear a enteros + cap 8s
    _segs_sorted = sorted(all_segments, key=lambda s: s["start_seconds"])
    for _i in range(1, len(_segs_sorted)):
        _prev_end = _segs_sorted[_i-1]["end_seconds"]
        _cur_start = _segs_sorted[_i]["start_seconds"]
        if 0 < _cur_start - _prev_end < 2.0:
            _segs_sorted[_i]["start_seconds"] = _prev_end
    for _s in _segs_sorted:
        _s["start_seconds"] = int(round(_s["start_seconds"]))
        _s["end_seconds"]   = int(round(_s["end_seconds"]))
        _s["duration"]      = min(_s["end_seconds"] - _s["start_seconds"], 8)
        _s["end_seconds"]   = _s["start_seconds"] + _s["duration"]
    result["visual_timeline"] = _segs_sorted

    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f"\n{'═'*62}")
    print(f"  RESUMEN FINAL")
    print(f"{'═'*62}")
    print_summary(all_segments)
    print(f"\n  ✓ Guardado: {out_file}")
    print(f"  Total segmentos: {len(all_segments)}")
    print()

if __name__ == '__main__':
    main()
