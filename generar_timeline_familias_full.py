#!/usr/bin/env python3
"""
generar_timeline_familias_full.py — Modo B: cobertura total para canal Familias de Riquezas.

Diferencias clave vs generar_timeline_riqueza.py (Modo A / triggers):
  - CUBRE CADA SEGUNDO de los primeros 10 minutos — sin huecos, sin filtro de triggers
  - Prompts hiperealistas con LOGOS REALES de las empresas de la familia
  - Segmentos 0-120s → marcados con "animate": true  (para VEO)
  - Segmentos 120-600s → marcados con "zoompan": true (para zoompan_clip.py)
  - Segmentos 600s+ → sin marca (clips YouTube del usuario)

Uso:
    python3 generar_timeline_familias_full.py familias/garza-sada/ --logos "OXXO,FEMSA,Heineken,Tecate"
    python3 generar_timeline_familias_full.py familias/slim/ --logos "Telmex,América Móvil,Claro"
"""

import sys, re, json, pathlib, time, os, argparse
import urllib.request, urllib.error
from timeline_prompt_fixer import auto_fix_prompts

BATCH_SECONDS = 60      # lotes más pequeños → prompts más precisos en cobertura total
MAX_SEG_SECS  = 8.0
MIN_SEG_SECS  = 1.5

class _NoCreditError(Exception):
    pass

HOME        = pathlib.Path.home()
KEY_FILE    = HOME / ".openrouter_key"
OR_MODEL    = "google/gemini-2.5-flash-lite"
OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a Visual Timeline Planner for a Spanish-language YouTube channel called "Familias de Riquezas" about wealthy Mexican dynasties.

YOUR MISSION: Create a COMPLETE visual coverage of the narration — every second must have an image. There are NO gaps.

🔴 MANDATORY OPENING PLACE RULE: If the VERY FIRST ENTRY of the FIRST BATCH contains a city or location name (e.g. "Monterrey", "Ciudad de México", "Guadalajara", any city, state or country) — you MUST generate a place insert at start_seconds=0 showing that exact city. NEVER skip the opening city even if it appears in a date line. The city is ALWAYS the first trigger when it appears at t=0.

COVERAGE RULES (strict):
1. Every SRT entry in the batch MUST produce at least one visual segment.
2. Segment duration: minimum 1.5s, maximum 8s. Split long entries into multiple segments.
3. Segments are CONTIGUOUS — each starts exactly where the previous ended.
4. The first segment starts at batch_start. The last segment ends at batch_end.
5. DO NOT skip any SRT entry. DO NOT leave any time gap.

PROMPT RULES — HYPERREALISTIC WITH BRAND LOGOS:
- All prompts in English.
- Always start with: "Cinematic hyperrealistic photo of"
- CRITICAL: When the narration mentions a specific company or product (OXXO, Heineken, Tecate, FEMSA, Tec de Monterrey, etc.), the prompt MUST include that brand's visual identity:
    • OXXO → "OXXO convenience store with the iconic red-and-white OXXO logo sign prominently displayed"
    • Heineken → "Heineken beer bottles with the green label and red star logo"
    • Tecate → "Tecate beer cans with the blue and silver Tecate logo"
    • FEMSA → "FEMSA corporate headquarters building with the FEMSA logo"
    • Tec de Monterrey → "Tecnológico de Monterrey campus with the Tec de Monterrey logo"
    • Cervecería Cuauhtémoc → "19th-century Mexican brewery building, historical, period-accurate"
    • Vitro → "glass manufacturing plant with industrial furnaces"
    • ALFA → "Mexican industrial conglomerate office building"
  If no specific brand is mentioned → use the era's visual context:
    - 1800–1939 → "sepia-toned, period-accurate, 1890s {pais} colonial architecture"
    - 1940–1969 → "vintage warm color, faded film look, 1950s {pais}"
    - 1970–1999 → "color photography, slightly warm, 1970s–1990s {pais}"
    - 2000+ → "full color vivid, crisp, hyperrealistic, modern {pais}"
- Never generic streets. Always specific subject: building, product, person (unnamed), or event.
- End every prompt with the era style + ", 16:9 aspect ratio"
- 50–80 words per prompt. Be specific. Real places, real logos, real products.

OUTPUT — MUST cover 100% of the batch time window. Output JSON only:
{
  "visual_timeline": [
    {
      "segment_id": 1,
      "source": "flow",
      "start_seconds": 0.5,
      "end_seconds": 6.0,
      "duration": 5.5,
      "scene_description_es": "Descripción en español de la escena",
      "ia_prompt": "Cinematic hyperrealistic photo of ..., 16:9 aspect ratio",
      "ia_prompt_en": "Same as ia_prompt",
      "video_prompt": "Static camera, scene nearly still, [describe ONE micro-movement: faint light shimmer on surface / dust particles floating / barely perceptible fabric movement / candle flame micro-flicker / leaves barely stirring]. No camera movement. No people walking. No talking.",
      "covers_text": "Texto exacto del SRT cubierto",
      "brand": "OXXO"
    }
  ]
}

The "brand" field: the specific company/product shown, or "" if none.
The "video_prompt" field: ALWAYS fill it. Describe the scene as nearly static with ONE subtle micro-movement appropriate to the subject:
- Store/building → faint light shimmer on signage, or flag barely stirring in breeze
- Beer bottles/products → condensation droplet forming on glass surface
- Newspaper/document → paper edge barely lifting in faint draft
- People (unnamed, back turned) → barely perceptible breathing, weight shift
- Industrial/factory → faint smoke wisps rising slowly
- Aerial/city → distant traffic lights changing color slowly
NEVER: camera pan, zoom, tilt, character walking, character talking, fast motion.
"""

USER_TEMPLATE = """LOTE {batch_number} de {total_batches}
VENTANA: {batch_start}s → {batch_end}s
VIDEO: {video_name}
LOGOS DISPONIBLES: {logos}

INSTRUCCIONES CRÍTICAS:
- Genera UN segmento por cada entrada SRT. Si la entrada dura más de 8s, divídela en 2 segmentos.
- El primer segmento comienza en EXACTAMENTE {batch_start}s
- El último segmento termina en EXACTAMENTE {batch_end}s
- CERO HUECOS entre segmentos
- SIEMPRE incluir el logo de la empresa si el texto la menciona

ENTRADAS SRT:
{sentences_json}

JSON únicamente."""

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
                c_words = words[i * words_per_chunk: (i + 1) * words_per_chunk]
                if not c_words:
                    c_words = words[-1:]
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

def call_openrouter(api_key, video_name, logos, batch, batch_num, total_batches, retries=3, pais="Mexico"):
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
        logos=logos,
        sentences_json=sentences_json,
    )

    payload = json.dumps({
        "model": OR_MODEL,
        "max_tokens": 16000,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.replace("{pais}", pais)},
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
                    "HTTP-Referer":  "https://familiasderiquezas.canal",
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
        except urllib.error.HTTPError as e:
            if e.code == 402:
                raise _NoCreditError()
            print(f"    ⚠ Error intento {attempt+1}: HTTP {e.code}: {e}")
            if attempt < retries - 1:
                time.sleep(5)
        except Exception as e:
            print(f"    ⚠ Error intento {attempt+1}: {e}")
            if attempt < retries - 1:
                time.sleep(5)

    # Si la API no responde después de reintentos: abortar, no silenciar
    print(f"\n  ✗ ERROR — La API falló {retries} veces seguidas en este lote.")
    print(f"  ✗ Abortando — revisa la conexión o el estado de OpenRouter.")
    sys.exit(1)

def sanitize_and_fill(segments, batch_start, batch_end):
    """Garantiza cobertura total: sin huecos, sin overlaps, sin clips > 8s."""
    if not segments:
        return segments

    # Normalizar keys
    for s in segments:
        if 'start' in s and 'start_seconds' not in s:
            s['start_seconds'] = s.pop('start')
        if 'end' in s and 'end_seconds' not in s:
            s['end_seconds'] = s.pop('end')
        if 'end_seconds' not in s and 'duration' in s:
            s['end_seconds'] = round(s['start_seconds'] + s['duration'], 3)

    segments = sorted(segments, key=lambda s: s['start_seconds'])
    if segments and segments[0]['start_seconds'] < 20:
        dur = segments[0]['end_seconds'] - segments[0]['start_seconds']
        segments[0]['start_seconds'] = 0
        segments[0]['end_seconds'] = round(dur, 3)
        segments[0]['duration'] = round(dur, 3)

    # Fijar inicio y fin del lote
    segments[0]['start_seconds'] = round(batch_start, 3)
    segments[-1]['end_seconds']  = round(batch_end, 3)

    # Cap duración a 8s
    for s in segments:
        dur = s['end_seconds'] - s['start_seconds']
        if dur > MAX_SEG_SECS:
            s['end_seconds'] = round(s['start_seconds'] + MAX_SEG_SECS, 3)
        s['duration'] = round(s['end_seconds'] - s['start_seconds'], 3)

    # Eliminar overlaps — NUNCA dejar duración < 1s
    MIN_SEG_SECS = 1.0
    for i in range(len(segments) - 1):
        if segments[i]['end_seconds'] > segments[i+1]['start_seconds']:
            new_end = round(segments[i+1]['start_seconds'], 3)
            # Solo recortar si queda duración mínima; si no, dejar solapado
            if new_end - segments[i]['start_seconds'] >= MIN_SEG_SECS:
                segments[i]['end_seconds'] = new_end
                segments[i]['duration']    = round(new_end - segments[i]['start_seconds'], 3)
            # Si recortar dejaría dur < 1s: no tocar este segmento,
            # el siguiente ya empieza en el mismo punto y eso es aceptable

    # Cerrar huecos: extender el anterior o insertar copia
    filled = [segments[0]]
    extras = []
    for i in range(1, len(segments)):
        prev = filled[-1]
        cur  = segments[i]
        gap  = round(cur['start_seconds'] - prev['end_seconds'], 3)
        if gap <= 0:
            filled.append(cur)
            continue
        if gap <= 3.0:
            prev['end_seconds'] = cur['start_seconds']
            prev['duration']    = round(prev['end_seconds'] - prev['start_seconds'], 3)
        else:
            while gap > 0:
                chunk = min(gap, MAX_SEG_SECS)
                new_seg = dict(prev)
                new_seg['start_seconds'] = prev['end_seconds']
                new_seg['end_seconds']   = round(prev['end_seconds'] + chunk, 3)
                new_seg['duration']      = round(chunk, 3)
                new_seg['scene_description_es'] = f"[relleno] {prev.get('scene_description_es','')[:50]}"
                extras.append(new_seg)
                filled.append(new_seg)
                prev = new_seg
                gap  = round(cur['start_seconds'] - prev['end_seconds'], 3)
        filled.append(cur)

    if extras:
        print(f"    ↳ {len(extras)} segmento(s) de relleno por hueco")

    return filled


def mark_mode_flags(segments):
    """Añade animate/zoompan según posición temporal."""
    for s in segments:
        t = s.get('start_seconds', 0)
        if t < 120:
            s['animate'] = True    # → VEO
            s.pop('zoompan', None)
        elif t < 600:
            s['zoompan'] = True    # → zoompan_clip.py
            s.pop('animate', None)
        else:
            s.pop('animate', None)
            s.pop('zoompan', None)
    return segments


def _guardar_pendientes(out_dir, completados, batches_restantes, next_seg_id, logos, video_name):
    """Guarda estado parcial para que Claude complete los prompts sin API."""
    estado = {
        "video_name": video_name,
        "logos": logos,
        "next_segment_id": next_seg_id,
        "completados": completados,
        "pendientes": batches_restantes,
    }
    p = out_dir / "srt_pendientes.json"
    p.write_text(json.dumps(estado, ensure_ascii=False, indent=2))
    print(f"  → Estado guardado en {p}")

def _mostrar_instrucciones_claude(out_dir):
    print()
    print("  ─────────────────────────────────────────────────────────")
    print("  INSTRUCCIONES PARA CONTINUAR SIN OPENROUTER:")
    print()
    print(f"  1. Di a Claude: 'La API falló con 402, genera los prompts'")
    print(f"  2. Claude lee {out_dir}/srt_pendientes.json")
    print(f"  3. Claude escribe {out_dir}/prompts_claude.json con los prompts")
    print(f"  4. Tú corres: python3 completar_timeline_claude.py {out_dir.parent}/")
    print("  ─────────────────────────────────────────────────────────")


def main():
    parser = argparse.ArgumentParser(description="Modo B — Timeline completo Familias de Riquezas")
    parser.add_argument('carpeta', help='familias/garza-sada/')
    parser.add_argument('--logos', default='',
                        help='Logos de las empresas de la familia, separados por coma. '
                             'Ej: "OXXO,FEMSA,Heineken,Tecate"')
    parser.add_argument('--pais', default='Mexico',
                        help='País de la familia para contextualizar los prompts. '
                             'Ej: "Venezuela", "Cuba", "Peru". Default: Mexico')
    parser.add_argument('--sin-api', action='store_true',
                        help='Simular modo sin API (igual que 402): guarda srt_pendientes.json y sale.')
    args = parser.parse_args()

    carpeta  = pathlib.Path(args.carpeta)
    nombre   = carpeta.name
    srt_file = carpeta / f"{nombre}.srt"
    out_dir  = carpeta / "05-montaje"
    out_file = out_dir / "timeline.json"
    logos    = args.logos or "las empresas de la familia"
    pais     = args.pais or "Mexico"

    out_dir.mkdir(parents=True, exist_ok=True)

    if not srt_file.exists():
        print(f"ERROR: No existe {srt_file}")
        sys.exit(1)

    api_key = ""
    if not args.sin_api:
        if KEY_FILE.exists():
            api_key = KEY_FILE.read_text().strip()
        elif os.environ.get('OPENROUTER_API_KEY'):
            api_key = os.environ['OPENROUTER_API_KEY']
        else:
            print(f"ERROR: Sin API key en {KEY_FILE}"); sys.exit(1)

    video_name = nombre.replace('-', ' ').replace('_', ' ').title()

    print(f"\n{'═'*62}")
    print(f"  TIMELINE FULL (MODO B) — {video_name.upper()}")
    print(f"  Canal: Familias de Riquezas")
    print(f"  Logos: {logos}")
    print(f"{'═'*62}")

    entries = parse_srt(srt_file)
    if not entries:
        print("ERROR: SRT vacío"); sys.exit(1)

    # Solo primeros 10 minutos
    entries = [e for e in entries if e['start'] < 600]
    total_duration = entries[-1]['end'] if entries else 0

    print(f"  SRT:      {len(entries)} entradas (primeros 10 min)")
    print(f"  Duración: {total_duration:.1f}s  ({total_duration/60:.1f} min)")
    print(f"  Modo A:   ≤120s animate→VEO | 120-600s zoompan | 600s+ clips YT")

    batches       = make_batches(entries, BATCH_SECONDS)
    total_batches = len(batches)
    print(f"  Lotes:    {total_batches} × ~{BATCH_SECONDS}s (cobertura total)")
    print()

    all_segments    = []
    segment_counter = 1

    for i, batch in enumerate(batches, 1):
        b_start = batch[0]['start']
        b_end   = batch[-1]['end']
        print(f"  [{i:02d}/{total_batches}] {b_start:.1f}s→{b_end:.1f}s ({len(batch)} entradas)...", end='', flush=True)

        if args.sin_api:
            # Simular 402: guardar estado y salir
            _guardar_pendientes(out_dir, all_segments, batches[i-1:], segment_counter, logos, video_name)
            print(f"\n\n  ✗ --sin-api activado (simulando 402).")
            _mostrar_instrucciones_claude(out_dir)
            sys.exit(2)

        try:
            t0       = time.time()
            segments = call_openrouter(api_key, video_name, logos, batch, i, total_batches, pais=pais)
            elapsed  = time.time() - t0
        except _NoCreditError:
            print(f"\n\n  ✗ ERROR 402 — OpenRouter sin saldo.")
            _guardar_pendientes(out_dir, all_segments, batches[i-1:], segment_counter, logos, video_name)
            _mostrar_instrucciones_claude(out_dir)
            sys.exit(2)

        segments = sanitize_and_fill(segments, b_start, b_end)

        for s in segments:
            s['segment_id'] = segment_counter
            # Asegurar campos obligatorios
            if 'ia_prompt_en' not in s:
                s['ia_prompt_en'] = s.get('ia_prompt', '')
            if 'source' not in s:
                s['source'] = 'flow'
            segment_counter += 1

        all_segments.extend(segments)
        print(f" {len(segments)} segmentos ({elapsed:.1f}s)")

        if i < total_batches:
            time.sleep(1)

    if not all_segments:
        print("ERROR: No se generaron segmentos"); sys.exit(1)

    # Cerrar gaps entre lotes (silencios del SRT entre batches)
    all_segments = sorted(all_segments, key=lambda s: s['start_seconds'])
    inter_gaps_fixed = 0
    for i in range(1, len(all_segments)):
        prev = all_segments[i-1]
        cur  = all_segments[i]
        gap  = round(cur['start_seconds'] - prev['end_seconds'], 3)
        if 0 < gap <= 2.0:
            prev['end_seconds'] = cur['start_seconds']
            prev['duration']    = round(prev['end_seconds'] - prev['start_seconds'], 3)
            inter_gaps_fixed   += 1
    if inter_gaps_fixed:
        print(f"  ↳ {inter_gaps_fixed} gap(s) entre lotes cerrados (silencios SRT ≤2s)")

    # Marcar animate/zoompan
    all_segments = mark_mode_flags(all_segments)

    # Estadísticas
    animate_count  = sum(1 for s in all_segments if s.get('animate'))
    zoompan_count  = sum(1 for s in all_segments if s.get('zoompan'))
    yt_count       = len(all_segments) - animate_count - zoompan_count
    brands         = [s['brand'] for s in all_segments if s.get('brand')]

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
        # NUNCA duración 0: si el redondeo colapsó el segmento, forzar mínimo 1s
        if _s["duration"] <= 0:
            _s["duration"] = 1
        _s["end_seconds"]   = _s["start_seconds"] + _s["duration"]
    all_segments = _segs_sorted

    out_file.write_text(
        json.dumps({"visual_timeline": all_segments}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\n{'─'*62}")
    print(f"  ✓ timeline.json → {out_file}")
    print(f"  Total segmentos: {len(all_segments)}")
    print(f"\n  Por modo:")
    print(f"    🎬 VEO (animate, 0-120s):     {animate_count:3d} segmentos")
    print(f"    🔍 Zoompan (120-600s):         {zoompan_count:3d} segmentos")
    print(f"    📹 Clips YT (600s+):           {yt_count:3d} segmentos")
    if brands:
        from collections import Counter
        brand_counts = Counter(brands)
        print(f"\n  Logos incluidos:")
        for brand, cnt in brand_counts.most_common():
            print(f"    🏷  {brand:<30} {cnt:3d} veces")
    print(f"\n  Siguiente paso:")
    print(f"  python3 harvester_timeline.py {args.carpeta} --canal familias")
    print(f"{'═'*62}\n")


if __name__ == "__main__":
    main()
