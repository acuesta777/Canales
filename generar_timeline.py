#!/usr/bin/env python3
"""
generar_timeline.py — Planificador visual completo para videos de fútbol.
Lee el SRT del jugador → llama a Claude Haiku por lotes → genera visual_timeline.json

Uso: python3 /Users/anyelocuesta/Downloads/Canales/generar_timeline.py <carpeta_jugador>

Requiere ~/.anthropic_key  o  ANTHROPIC_API_KEY en el entorno.
"""

import sys, re, json, pathlib, time, os
import anthropic

BATCH_SECONDS = 90    # segundos de audio por lote enviado a Claude
MAX_SEG_SECS  = 8.0   # ningún segmento puede superar este tiempo
MIN_SEG_SECS  = 1.0   # ningún segmento puede ser menor a este tiempo

# ──────────────────────────────────────────────────────────────────────────────
# PROMPTS
# ──────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a Visual Content Planner for a Spanish-language football YouTube channel.
The channel produces cinematic, emotional, biographical videos about footballers.
Tone is nostalgic, warm, and dramatic — targeting Latin American football fans.

━━━ TASK ━━━
You receive timestamped SRT entries from a football video narration.
For each entry, generate AT LEAST one visual segment with a matching image prompt.
Split entries when the visual context changes significantly.

━━━ CORE RULES ━━━
1. Every SRT entry gets AT LEAST one segment
2. No segment may exceed 8.0 seconds — split if needed
3. No segment may be shorter than 1.0 seconds
4. ZERO GAPS: segment N+1 must start exactly where segment N ended
5. First segment.start_seconds = EXACTLY batch_start (float)
6. Last segment.end_seconds = EXACTLY batch_end (float)
7. covers_sentences must list the actual text phrases from the SRT entries it covers

🔴 MANDATORY OPENING PLACE RULE: If the VERY FIRST ENTRY of the FIRST BATCH contains a city or location name — you MUST generate an "estadio" insert at start_seconds=0 showing that exact city/place. NEVER skip the opening city even if it appears in a date line. The city is ALWAYS the first trigger when it appears at t=0.

━━━ VISUAL TYPES ━━━
Classify each segment as one of:
- "jugador"  — Player is the main focus: action, celebration, dribbling, portrait, training
- "estadio"  — Stadium interior/exterior, city skyline, neighborhood, named location
- "escena"   — Contextual: family moment, childhood, concept, emotion, historical reference

━━━ WHEN TO SPLIT AN ENTRY ━━━
- Two or more distinct scenes described in one entry
- Contrast phrase (pero, sin embargo, aunque, mientras, en cambio)
- Entry spans > 8 seconds
- Clear tonal shift mid-entry (joy → sadness, action → reflection)

━━━ IMAGE PROMPTS ━━━
Write in English. Be specific, cinematic, and avoid naming real people's faces:
- jugador: "Young footballer in FC Barcelona blue and red jersey celebrating, arms wide open, Camp Nou"
- estadio: "Wide aerial view of Camp Nou stadium at sunset, Barcelona skyline in background"
- escena: "Boy in a working-class neighborhood kicking a football against a graffiti wall, golden hour"

ALWAYS append to every image_prompt:
"Cinematic hyperrealistic photography, dramatic lighting, ultra detailed, 16:9 aspect ratio, no text, no watermarks"

━━━ VIDEO PROMPTS (Ken Burns — first 120 seconds only) ━━━
For start_seconds < 120: write a subtle Ken Burns description, max 20 words
For start_seconds >= 120: video_prompt must be ""
Options: "Slow zoom in on center", "Gentle pan from left to right", "Very slow zoom out from top-right corner", "Slow zoom in on face region"
BANNED: camera cuts, transitions, any fast movement, character animation, text

━━━ ZOOM REGION ━━━
One of: "center" | "face" | "top-left" | "top-right" | "bottom-left" | "bottom-right" | "wide"
ken_burns_effect: 1 if video_prompt is non-empty, else 0

━━━ SEARCH QUERY ━━━
Specific terms to find a real image online. Include player name only when it makes sense.
Examples: "lamine yamal gol eurocopa 2024", "camp nou estadio exterior", "niño rocafonda barrio barcelona"

━━━ OUTPUT FORMAT ━━━
Respond with valid JSON only — no markdown fences, no explanation, no extra text.
{
  "visual_timeline": [
    {
      "segment_id": 1,
      "type": "scene",
      "visual_type": "jugador|estadio|escena",
      "start_seconds": 0.0,
      "end_seconds": 5.2,
      "duration": 5.2,
      "covers_sentences": ["phrase one...", "phrase two..."],
      "scene_description": "Descripción en español de lo que se ve en pantalla",
      "image_prompt": "English prompt for image generation..., Cinematic hyperrealistic photography, dramatic lighting, ultra detailed, 16:9 aspect ratio, no text, no watermarks",
      "video_prompt": "Slow zoom in on center",
      "zoom_region": "center",
      "ken_burns_effect": 1,
      "search_query": "specific search terms here"
    }
  ]
}"""

USER_TEMPLATE = """BATCH {batch_number} of {total_batches}
TIME WINDOW: {batch_start}s → {batch_end}s  ({batch_duration:.1f}s total)
PLAYER: {player_name}

SRT ENTRIES IN THIS BATCH:
{sentences_json}

━━━ YOUR JOB ━━━
Create segments that cover EXACTLY {batch_start}s to {batch_end}s with zero gaps.
- First segment.start_seconds = {batch_start}
- Last segment.end_seconds = {batch_end}
- scene_description MUST be in Spanish
- search_query must be specific enough to find a real image
- JSON only — no explanations, no markdown"""

# ──────────────────────────────────────────────────────────────────────────────
# PARSEO SRT
# ──────────────────────────────────────────────────────────────────────────────

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

# ──────────────────────────────────────────────────────────────────────────────
# BATCHING
# ──────────────────────────────────────────────────────────────────────────────

def make_batches(entries: list, batch_seconds: float = BATCH_SECONDS) -> list:
    """Agrupa entradas SRT en lotes de ~batch_seconds segundos."""
    batches = []
    current = []
    for entry in entries:
        current.append(entry)
        if current[-1]['end'] - current[0]['start'] >= batch_seconds:
            batches.append(current)
            current = []
    if current:
        batches.append(current)
    return batches

# ──────────────────────────────────────────────────────────────────────────────
# LLAMADA A CLAUDE
# ──────────────────────────────────────────────────────────────────────────────

def extract_json(text: str) -> dict:
    text = text.strip()
    # Quitar fences de markdown si Claude los pone
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text, flags=re.MULTILINE)
    return json.loads(text)

def call_claude(client, player_name: str, batch: list, batch_num: int,
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
        player_name=player_name,
        sentences_json=sentences_json,
    )

    for attempt in range(retries):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=8192,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            data = extract_json(response.content[0].text)
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

# ──────────────────────────────────────────────────────────────────────────────
# VALIDACIÓN Y CORRECCIÓN
# ──────────────────────────────────────────────────────────────────────────────

def validate_batch_segments(segments: list, batch_start: float, batch_end: float) -> list:
    """
    Corrige gaps y overlaps entre segmentos de un lote.
    No modifica el primer ni el último timestamp de forma radical.
    """
    if not segments:
        return segments

    # Forzar que el primer empiece en batch_start
    segments[0]['start_seconds'] = round(batch_start, 3)

    # Cerrar gaps entre segmentos consecutivos
    for i in range(1, len(segments)):
        expected_start = segments[i-1]['end_seconds']
        segments[i]['start_seconds'] = round(expected_start, 3)

    # Forzar que el último termine en batch_end
    segments[-1]['end_seconds'] = round(batch_end, 3)

    # Recalcular duraciones
    for s in segments:
        s['duration'] = round(s['end_seconds'] - s['start_seconds'], 3)

    return segments

# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 generar_timeline.py <carpeta_jugador>")
        print("     Ejemplo: python3 generar_timeline.py futbol/lamine_yamal")
        sys.exit(1)

    carpeta = pathlib.Path(sys.argv[1])
    nombre  = carpeta.name
    srt_file = carpeta / f"{nombre}.srt"
    out_file = carpeta / "visual_timeline.json"

    if not srt_file.exists():
        print(f"ERROR: No existe {srt_file}")
        sys.exit(1)

    # Clave API: archivo > variable de entorno
    key_path = pathlib.Path.home() / '.anthropic_key'
    api_key = ''
    if key_path.exists() and key_path.stat().st_size > 0:
        api_key = key_path.read_text().strip()
    elif os.environ.get('ANTHROPIC_API_KEY'):
        api_key = os.environ['ANTHROPIC_API_KEY']
    else:
        print("ERROR: No se encontró clave de API.")
        print("  Opción 1: echo 'sk-ant-...' > ~/.anthropic_key")
        print("  Opción 2: export ANTHROPIC_API_KEY='sk-ant-...'")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    player_name = nombre.replace('_', ' ').title()

    print(f"\n{'═'*62}")
    print(f"  VISUAL TIMELINE PLANNER — {player_name.upper()}")
    print(f"{'═'*62}")

    entries = parse_srt(srt_file)
    if not entries:
        print("ERROR: SRT vacío o formato incorrecto"); sys.exit(1)

    total_duration = entries[-1]['end']
    print(f"  SRT:      {len(entries)} entradas")
    print(f"  Duración: {total_duration:.1f}s  ({total_duration/60:.1f} min)")

    batches = make_batches(entries, BATCH_SECONDS)
    total_batches = len(batches)
    print(f"  Lotes:    {total_batches} × ~{BATCH_SECONDS}s")
    print()

    all_segments = []
    segment_counter = 1

    for i, batch in enumerate(batches, 1):
        b_start = batch[0]['start']
        b_end   = batch[-1]['end']
        print(f"  [{i:02d}/{total_batches}] {b_start:.1f}s → {b_end:.1f}s  ({len(batch)} entradas) ...", end='', flush=True)

        t0 = time.time()
        segments = call_claude(client, player_name, batch, i, total_batches)
        elapsed = time.time() - t0

        if not segments:
            print(f" ✗ Sin resultado (se omite este lote)")
            continue

        # Validar y corregir gaps
        segments = validate_batch_segments(segments, b_start, b_end)

        # Reasignar IDs secuenciales
        for seg in segments:
            seg['segment_id'] = segment_counter
            segment_counter += 1
            all_segments.append(seg)

        print(f" ✓  {len(segments)} segs  ({elapsed:.1f}s)")

        if i < total_batches:
            time.sleep(0.5)

    # ── Guardar resultado ─────────────────────────────────────────────────────
    result = {'visual_timeline': all_segments, 'meta': {
        'player': player_name,
        'total_segments': len(all_segments),
        'total_duration_s': round(total_duration, 1),
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }}
    out_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    # ── Resumen ───────────────────────────────────────────────────────────────
    print(f"\n{'═'*62}")
    print(f"  RESUMEN FINAL")
    print(f"{'═'*62}")
    print(f"  Segmentos totales: {len(all_segments)}")

    type_counts: dict = {}
    for s in all_segments:
        vt = s.get('visual_type', 'desconocido')
        type_counts[vt] = type_counts.get(vt, 0) + 1
    for vt, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        pct = cnt / len(all_segments) * 100
        print(f"  - {vt:<10} {cnt:3d} segmentos  ({pct:.0f}%)")

    # Segmentos con Ken Burns
    kb = sum(1 for s in all_segments if s.get('ken_burns_effect') == 1)
    print(f"\n  Ken Burns activo (< 120s): {kb} segmentos")
    print(f"\n  ✓ Guardado: {out_file}")
    print()


if __name__ == '__main__':
    main()
