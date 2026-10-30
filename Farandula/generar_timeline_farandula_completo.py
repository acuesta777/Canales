#!/usr/bin/env python3
"""
generar_timeline_farandula_completo.py — Timeline COMPLETO para Farandula Mono.

Para el caso en que NO hay clips de YouTube adicionales:
Lee el SRT (primeros 10 min) → agrupa en chunks de 4-8s →
Gemini genera un ia_prompt para CADA chunk (sin filtro de triggers) →
genera hook_timeline.json con cobertura total del primer tramo.

Diferencia con generar_timeline_farandula_mono.py:
  - Mono:      Gemini detecta 2-4 triggers por batch (90s) → ~20 segmentos
  - Completo:  Gemini genera prompt para CADA chunk → ~60-80 segmentos (cobertura total)

Uso:
    python3 Farandula/generar_timeline_farandula_completo.py "Farandula/NOMBRE/"
"""

import sys, re, json, pathlib, time, os
import urllib.request, urllib.error

CHUNK_TARGET_SECS = 6.0   # duración objetivo por chunk
MAX_CLIP_SECS     = 8.0
MIN_SEG_SECS      = 3.0
MAX_SRT_SECS      = 600   # primeros 10 min
BATCH_CHUNKS      = 12    # chunks por llamada a Gemini (~72s de narración)

HOME        = pathlib.Path.home()
KEY_FILE    = HOME / ".openrouter_key"
OR_MODEL    = "google/gemini-2.5-flash-lite"
OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a Visual Timeline Planner for a Spanish-language YouTube documentary channel called "Farandula" — about the hidden lives of Latin American celebrities.

YOUR JOB: For each narration chunk provided, generate ONE cinematic AI image prompt in English that visually represents what the narrator is saying. Cover EVERY chunk — do not skip any.

ERA RULES for ia_prompt prefix:
- Before 1960: prefix with "black and white, film grain, silver gelatin photography, period-accurate"
- 1960–1989: prefix with "vintage warm color, faded film look, period-accurate"
- 1990–2010: prefix with "realistic documentary photograph, warm tones"
- 2010+: prefix with "modern realistic photograph, natural light"

VISUAL RULES — ABSOLUTE:
- NEVER show real people's faces — use silhouettes, back views, or no people at all
- NEVER show readable text, letters, signs, or words in the scene
- Always end every ia_prompt with: "cinematic lighting, no text, no letters, no words, no faces visible"
- Be specific: include location name, era, objects, atmosphere
- No fantasy, no illustrations — photorealistic always

CATEGORY GUIDE (use these to pick visuals that match the narration):
- Poverty / humble origins → modest houses, dirt streets, barefoot children (no faces), simple kitchens
- Success / fame → packed venues seen from behind, empty stages with spotlights, marquee signs
- Money / finances → stacks of bills, empty wallets, debt papers, counting hands (no faces)
- Romance → silhouette of partner from behind in doorway or window — adapt gender to match the story
- Hospital / health → empty corridors, ambulance entrance, medical equipment, tired staff silhouettes
- Death / funeral → closed coffin, cemetery at dusk, mourners in black (no faces), white flowers
- Legal / documents → official papers, rubber stamps, manila envelopes, notary desks
- City / neighborhood → aerial or street views of that specific city in the correct era
- Boxing / sport → empty ring with spotlight, gloves on a stool, training gym, crowd from behind
- TV / media → vintage studio cameras, clapper board, broadcast booth with monitors
- Music / concert → empty stage with lights, instruments, concert hall from the back
- Childhood → dusty schoolyard, old bicycle, children playing (no faces), family table (no faces)
- Scandal / fall → empty theater, rusted locks, forgotten newspaper, dark dressing room

OUTPUT FORMAT — valid JSON only:
{
  "visual_timeline": [
    {
      "segment_id": 1,
      "trigger_type": "CIUDAD",
      "start_seconds": 4.8,
      "end_seconds": 10.8,
      "duration": 6.0,
      "source": "flow",
      "ia_prompt": "black and white, film grain, silver gelatin photography, period-accurate, aerial view of Panama City in the 1950s, El Chorrillo neighborhood with wooden houses packed together, narrow streets, Casco Antiguo visible in the distance, cinematic lighting, no text, no letters, no words, no faces visible",
      "scene_description": "Narrator describes El Chorrillo neighborhood where Durán was born"
    }
  ]
}

TRIGGER TYPES (use the closest match — pick ONE per segment):
"POBREZA", "HOSPITAL", "ROMANCE", "FUNERAL", "ENFERMEDAD", "CAIDA", "FAMA", "TELEVISION", "PRENSA", "CIUDAD", "INTERIOR", "DOCUMENTO", "DINERO", "CINE", "RADIO", "CONCIERTO", "ACCIDENTE", "DEPORTE", "INFANCIA", "MUSICA"

RULES:
- Generate exactly ONE entry per chunk in the input — do NOT skip chunks
- source is ALWAYS "flow"
- Keep start_seconds and end_seconds from the chunk boundaries I give you
- duration = end_seconds - start_seconds"""

USER_TEMPLATE = """BATCH {batch_number} of {total_batches}
CELEBRITY/VIDEO: {video_name}

Generate ONE visual for EACH of the following narration chunks.
Do NOT skip any chunk. Output exactly {chunk_count} entries.

CHUNKS:
{chunks_json}

Return valid JSON with visual_timeline array containing exactly {chunk_count} entries."""


def ts_to_sec(ts):
    ts = ts.strip().replace(',', '.')
    p = ts.split(':')
    return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])


def parse_srt(srt_path):
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
        if start >= MAX_SRT_SECS:
            break
        text = ' '.join(lines[2:]).strip()
        entries.append({"t": round(start, 3), "end": round(min(end, MAX_SRT_SECS), 3), "text": text})
    return entries


def group_into_chunks(entries):
    """Agrupa entradas SRT en chunks de ~CHUNK_TARGET_SECS."""
    chunks = []
    cur_texts = []
    cur_start = None
    cur_end   = None

    for e in entries:
        if cur_start is None:
            cur_start = e['t']

        cur_texts.append(e['text'])
        cur_end = e['end']

        if (cur_end - cur_start) >= CHUNK_TARGET_SECS:
            chunks.append({
                "start": round(cur_start, 1),
                "end":   round(min(cur_end, MAX_SRT_SECS), 1),
                "text":  ' '.join(cur_texts)
            })
            cur_texts = []
            cur_start = None
            cur_end   = None

    # Último chunk residual
    if cur_texts and cur_start is not None:
        dur = cur_end - cur_start
        if dur >= MIN_SEG_SECS:
            chunks.append({
                "start": round(cur_start, 1),
                "end":   round(min(cur_end, MAX_SRT_SECS), 1),
                "text":  ' '.join(cur_texts)
            })

    return chunks


def make_batches(chunks, batch_size):
    return [chunks[i:i+batch_size] for i in range(0, len(chunks), batch_size)]


VALID_TRIGGERS = {
    "POBREZA","HOSPITAL","ROMANCE","FUNERAL","ENFERMEDAD",
    "CAIDA","FAMA","TELEVISION","PRENSA","CIUDAD","INTERIOR","DOCUMENTO",
    "DINERO","CINE","RADIO","CONCIERTO","ACCIDENTE","DEPORTE","INFANCIA","MUSICA"
}


def call_openrouter(api_key, video_name, chunks, batch_num, total_batches):
    chunks_json = json.dumps([
        {"chunk_id": i+1, "start_seconds": c["start"], "end_seconds": c["end"], "narration": c["text"]}
        for i, c in enumerate(chunks)
    ], ensure_ascii=False)

    payload = json.dumps({
        "model": OR_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(
                batch_number=batch_num,
                total_batches=total_batches,
                video_name=video_name,
                chunk_count=len(chunks),
                chunks_json=chunks_json
            )}
        ],
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
    }).encode()

    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                OR_ENDPOINT,
                data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                    "HTTP-Referer":  "https://github.com/farandula-mono",
                    "X-Title":       "Farandula Completo Timeline",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read())
            raw    = data['choices'][0]['message']['content']
            parsed = json.loads(raw)
            return parsed.get('visual_timeline', [])
        except Exception as e:
            print(f"    Intento {attempt}/3 fallido: {e}")
            if attempt < 3:
                time.sleep(3 * attempt)
    return []


def sanitize_and_fill(segments, chunks):
    """
    Asegura cobertura completa: si Gemini saltó algún chunk, lo rellenamos
    con un prompt genérico basado en el texto de narración.
    """
    # Indexar por start_seconds aproximado
    covered = {round(s['start_seconds'], 0) for s in segments}

    for c in chunks:
        key = round(c['start'], 0)
        if key not in covered:
            # Chunk sin cobertura — prompt genérico
            era_prefix = "black and white, film grain, silver gelatin photography, period-accurate"
            segments.append({
                "trigger_type":     "INTERIOR",
                "start_seconds":    c['start'],
                "end_seconds":      c['end'],
                "duration":         round(c['end'] - c['start'], 1),
                "source":           "flow",
                "ia_prompt":        f"{era_prefix}, empty dimly lit room, atmospheric shadows, cinematic lighting, no text, no letters, no words, no faces visible",
                "scene_description": c['text'][:80]
            })

    # Ordenar
    segments = sorted(segments, key=lambda s: s['start_seconds'])

    # Cap duración y normalizar trigger_type
    for s in segments:
        if s['end_seconds'] - s['start_seconds'] > MAX_CLIP_SECS:
            s['end_seconds'] = round(s['start_seconds'] + MAX_CLIP_SECS, 1)
        tt = s.get('trigger_type', 'INTERIOR').upper()
        if tt not in VALID_TRIGGERS:
            tt = 'INTERIOR'
        s['trigger_type'] = tt

    # Filtrar muy cortos
    segments = [s for s in segments if (s['end_seconds'] - s['start_seconds']) >= MIN_SEG_SECS]

    # Dedup por prompt
    seen, unique = set(), []
    for s in segments:
        key = s.get('ia_prompt', '').strip().lower()[:80]
        if key not in seen:
            seen.add(key)
            unique.append(s)
    segments = unique

    # Cap duro: ningún segmento > 8s
    for s in segments:
        if s['end_seconds'] - s['start_seconds'] > MAX_CLIP_SECS:
            s['end_seconds'] = round(s['start_seconds'] + MAX_CLIP_SECS, 1)

    # CERRAR GAPS: recorrer de 0 a MAX_SRT_SECS llenando todo
    # Si hay gap entre cur.end y nxt.start → crear fillers de hasta 8s
    result = []
    cursor = segments[0]['start_seconds']

    for i, s in enumerate(segments):
        # Gap antes de este segmento → rellenar con fillers
        while round(s['start_seconds'] - cursor, 2) >= MIN_SEG_SECS:
            prev = result[-1] if result else s
            filler_end = min(cursor + MAX_CLIP_SECS, s['start_seconds'])
            result.append({
                'trigger_type':     prev['trigger_type'],
                'start_seconds':    round(cursor, 1),
                'end_seconds':      round(filler_end, 1),
                'source':           'flow',
                'ia_prompt':        prev['ia_prompt'],
                'scene_description': prev.get('scene_description', '')
            })
            cursor = filler_end

        # Ajustar start al cursor si hay mini-overlap/gap < MIN_SEG_SECS
        s['start_seconds'] = round(cursor, 1)
        if s['end_seconds'] - s['start_seconds'] > MAX_CLIP_SECS:
            s['end_seconds'] = round(s['start_seconds'] + MAX_CLIP_SECS, 1)

        result.append(s)
        cursor = s['end_seconds']

    # Rellenar hasta el final del tramo
    while round(MAX_SRT_SECS - cursor, 2) >= MIN_SEG_SECS:
        prev = result[-1]
        filler_end = min(cursor + MAX_CLIP_SECS, MAX_SRT_SECS)
        result.append({
            'trigger_type':     prev['trigger_type'],
            'start_seconds':    round(cursor, 1),
            'end_seconds':      round(filler_end, 1),
            'source':           'flow',
            'ia_prompt':        prev['ia_prompt'],
            'scene_description': prev.get('scene_description', '')
        })
        cursor = filler_end

    segments = result

    # Recalcular duración final
    for s in segments:
        s['duration'] = round(s['end_seconds'] - s['start_seconds'], 1)

    # Filtrar muy cortos
    segments = [s for s in segments if s['duration'] >= MIN_SEG_SECS]

    return segments


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 Farandula/generar_timeline_farandula_completo.py 'Farandula/NOMBRE/'")
        sys.exit(1)

    carpeta  = pathlib.Path(sys.argv[1])
    nombre   = carpeta.name
    srt_file = None
    for candidate in [carpeta / f"{nombre}.srt", carpeta / "audio.srt",
                      next(iter(carpeta.glob("*.srt")), None)]:
        if candidate and pathlib.Path(candidate).exists():
            srt_file = pathlib.Path(candidate)
            break
    if not srt_file:
        print(f"ERROR: No hay .srt en {carpeta}")
        sys.exit(1)

    out_file = carpeta / "hook_timeline.json"

    api_key = ""
    if KEY_FILE.exists():
        api_key = KEY_FILE.read_text().strip()
    elif os.environ.get('OPENROUTER_API_KEY'):
        api_key = os.environ['OPENROUTER_API_KEY']
    else:
        print(f"ERROR: Sin API key en {KEY_FILE}"); sys.exit(1)

    video_name = nombre.replace('-', ' ').replace('_', ' ').title()

    print(f"\n{'═'*62}")
    print(f"  TIMELINE COMPLETO — {video_name.upper()}")
    print(f"  SRT: {srt_file.name} (primeros {MAX_SRT_SECS}s)")
    print(f"  Modo: COBERTURA TOTAL — prompt para cada ~{CHUNK_TARGET_SECS}s")
    print(f"{'═'*62}\n")

    entries = parse_srt(srt_file)
    if not entries:
        print("ERROR: SRT vacío o no parseable"); sys.exit(1)

    print(f"  SRT: {len(entries)} entradas hasta {MAX_SRT_SECS}s")

    chunks = group_into_chunks(entries)
    print(f"  Chunks: {len(chunks)} × ~{CHUNK_TARGET_SECS}s")

    batches       = make_batches(chunks, BATCH_CHUNKS)
    total_batches = len(batches)
    print(f"  Batches: {total_batches} × {BATCH_CHUNKS} chunks\n")

    all_segments    = []
    segment_counter = 1

    for i, batch in enumerate(batches, 1):
        b_start = batch[0]['start']
        b_end   = batch[-1]['end']
        print(f"  [{i:02d}/{total_batches}] {b_start:.1f}s → {b_end:.1f}s  ({len(batch)} chunks)...", end='', flush=True)

        t0       = time.time()
        segments = call_openrouter(api_key, video_name, batch, i, total_batches)
        elapsed  = time.time() - t0

        if segments:
            for s in segments:
                s['segment_id'] = segment_counter
                s['source']     = 'flow'
                segment_counter += 1
            all_segments.extend(segments)
            print(f" {len(segments)} segmentos ({elapsed:.1f}s)")
        else:
            print(f" ⚠ Sin segmentos ({elapsed:.1f}s)")

        if i < total_batches:
            time.sleep(1)

    if not all_segments:
        print("ERROR: Gemini no generó ningún segmento.")
        sys.exit(1)

    all_segments = sanitize_and_fill(all_segments, chunks)

    for i, s in enumerate(all_segments, 1):
        s['segment_id'] = i

    out_file.write_text(
        json.dumps({"visual_timeline": all_segments}, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )

    print(f"\n{'─'*62}")
    print(f"  ✓ {len(all_segments)} segmentos → {out_file}")
    print(f"\n  PRÓXIMO PASO:")
    print(f"  → python3 Farandula/harvester_farandula.py '{carpeta}/' --solo-hook")
    print(f"{'─'*62}\n")


if __name__ == "__main__":
    main()
