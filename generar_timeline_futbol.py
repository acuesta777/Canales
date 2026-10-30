#!/usr/bin/env python3
"""
generar_timeline_futbol.py — Planificador visual para canal de fútbol.

Solo genera inserts en momentos concretos: goles, equipos, trofeos,
estadios, lesiones documentadas, estadísticas, selección nacional.
El resto lo llenan los clips limpios del personaje.

Uso:
    python3 generar_timeline_futbol.py futbol/lamine_yamal/
"""

import sys, re, json, pathlib, time, os
import urllib.request, urllib.error
from timeline_prompt_fixer import auto_fix_prompts

BATCH_SECONDS = 90
HOME      = pathlib.Path.home()
KEY_FILE  = HOME / ".openrouter_key"
OR_MODEL  = "google/gemini-2.5-flash-lite"
OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a Visual Insert Selector for a Spanish-language YouTube channel about football (soccer) player stories. The channel focuses on the lives, careers, and current situations of footballers.

CONTEXT: The video already has real footage of the player (matches, interviews, press conferences). You are NOT planning the whole video — you are selecting SPECIFIC MOMENTS where inserting a real photo or stock clip would add concrete visual value because the narration mentions something specific and verifiable.

YOUR TASK:
Read the SRT narration and identify ONLY the moments where an insert makes sense. Most entries will get NO insert — that is correct and expected. Only generate an insert when the narration explicitly mentions one of these TRIGGER TYPES:

🔴 MANDATORY OPENING PLACE RULE: If the VERY FIRST ENTRY of the FIRST BATCH contains a city or location name (e.g. "Ciudad de México", "Guadalajara", "Buenos Aires", "Rosario", any city, state or country) — you MUST generate a BIRTHPLACE/CITY insert at start_seconds=0 showing that exact city. NEVER skip the opening city. The city is ALWAYS the first trigger when it appears at t=0.

TRIGGERS (only generate insert if one of these appears):
1. GOAL/MATCH: a specific goal, match, or result ("marcó el gol de la final", "el partido ante el Real Madrid", "anotó en el Mundial")
2. TROPHY/TITLE: a specific trophy, championship, or award ("ganó la Champions League", "el Balón de Oro", "campeón del mundo")
3. TEAM: a specific club the player joined, left, or played for ("fichó por el Barcelona", "su debut con el Manchester United")
4. STADIUM: a specific stadium ("en el Camp Nou", "en el Estadio Azteca", "en Wembley")
5. PROPERTY: a house, mansion, estate, finca, ranch, apartment ("tiene una mansión en Miami", "su finca en Antioquia", "su casa en Barcelona")
6. CAR/LUXURY: specific cars, yachts, jewelry, luxury lifestyle ("tenía un Ferrari", "sus carros de lujo", "su colección de relojes")
7. MONEY/WEALTH: specific wealth, salary, net worth ("ganaba 10 millones", "su fortuna de 50 millones", "fichó por 80 millones")
8. BIRTHPLACE/CITY: where the player was born or grew up ("nació en Rosario", "creció en el barrio popular", "su ciudad natal"), OR any real location, city, road, stadium, or country mentioned anywhere. Fire at the EXACT timestamp where the location name appears, including second 0 if it's the first word.
9. NATIONAL TEAM: national team appearances ("debutó con la selección", "llevó a Colombia al mundial")

VISUAL SOURCES:
- "flow": For ALL triggers — generate a photorealistic AI image. ia_prompt must start with the player's name.
- Example: "René Higuita el arquero colombiano celebrando la Copa Libertadores 1989 con Atlético Nacional, fotografía documental, sin texto"

⚠️ OVERRIDE RULE — EXACT ANCHOR (read before writing ia_prompt):
Before writing ia_prompt, ask: "What specific noun, object, place, or event does the narration literally name at this timestamp?"
If the narration names something SPECIFIC — a trophy, a specific stadium, a specific car model, a specific city neighborhood, a specific match — illustrate THAT SPECIFIC THING.
The trigger type only classifies the category. The ia_prompt MUST match what the narration literally says.

✅ CORRECT: narration "marcó en el Camp Nou ante el Real Madrid en el minuto 94" → show Camp Nou stadium at night, scoreboard, dramatic lighting (NOT a generic goal celebration)
❌ WRONG: narration "marcó en el Camp Nou ante el Real Madrid en el minuto 94" → show a generic stadium crowd (ignores the specific stadium and match)
✅ CORRECT: narration "ganaba 10 millones de euros por temporada en el PSG" → show a signed contract on a desk with PSG letterhead style, no readable text (NOT generic stacks of bills)
❌ WRONG: narration "ganaba 10 millones de euros por temporada en el PSG" → show a generic mansion (that's PROPERTY default, not what the sentence says)
✅ CORRECT: narration "nació en una pequeña habitación en Rosario, Argentina" → show a modest apartment building in Rosario, Argentina, 1980s (NOT a generic humble street)
❌ WRONG: narration "nació en una pequeña habitación en Rosario, Argentina" → show a generic poor neighborhood (ignores the specific city)

The trigger type's default visual is FALLBACK only for generic mentions. When narration is specific → match the specific noun.

STRICT RULES:
- If no trigger appears → DO NOT generate an insert (gaps are filled by the player's real footage)
- Maximum 1 insert per trigger moment
- Insert duration: 4–8 seconds
- Source is ALWAYS "flow"
- ia_prompt MUST start with: "[Player full name] el futbolista, ..."
- veo_prompt: "Slow cinematic zoom in, [player name], [scene description]"
- No text, no logos, no watermarks in ia_prompt
- Never insert generic crowd scenes or abstract stats

OUTPUT: Valid JSON only. Include ONLY segments that have an insert.

{
  "visual_timeline": [
    {
      "segment_id": 1,
      "source": "flow",
      "start_seconds": 32.5,
      "end_seconds": 38.0,
      "duration": 5.5,
      "scene_description_es": "Lamine Yamal marcando el gol ante Francia en la Eurocopa 2024",
      "ia_prompt": "Lamine Yamal el futbolista, marcando el gol ante Francia en la semifinal de la Eurocopa 2024, fotografía documental realista, sin texto, sin logos",
      "veo_prompt": "Slow cinematic zoom in, Lamine Yamal, gol ante Francia Eurocopa 2024",
      "covers_text": "el gol que paralizó a toda Europa ante Francia",
      "trigger_type": "goal|trophy|team|stadium|property|car|money|birthplace|national_team",
      "priority": "high|medium"
    }
  ]
}"""

USER_TEMPLATE = """BATCH {batch_number} of {total_batches}
TIME WINDOW: {batch_start}s → {batch_end}s ({batch_duration:.1f}s)
PLAYER/VIDEO: {video_name}

SRT ENTRIES:
{sentences_json}

Identify ONLY the moments with a concrete trigger (goal, trophy, team, stadium, property/mansion, car/luxury, money/wealth, birthplace, national_team).
Most entries should get NO insert. Only output segments where an insert genuinely adds value.
All segments must use source="flow" and ia_prompt starting with the player's name.
JSON only."""

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
            n_chunks  = int(duration / max_entry_secs) + 1
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

def call_openrouter(api_key, video_name, batch, batch_num, total_batches, retries=3):
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
                    "HTTP-Referer":  "https://futbolcanal.canal",
                }
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read())
            text     = resp["choices"][0]["message"]["content"]
            data     = extract_json(text)
            segments = data.get('visual_timeline', [])
            return segments
        except json.JSONDecodeError as e:
            print(f"    ⚠ JSON inválido intento {attempt+1}: {e}")
            if attempt < retries - 1:
                time.sleep(3)
        except Exception as e:
            print(f"    ⚠ Error intento {attempt+1}: {e}")
            if attempt < retries - 1:
                time.sleep(5)
    return []

MAX_CLIP_SECS = 8.0

def sanitize_timeline(segments: list) -> list:
    """Garantiza: sin overlaps, sin clips > 8s. Se ejecuta SIEMPRE antes de guardar."""
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
        if duration > MAX_CLIP_SECS:
            old_end = s['end_seconds']
            s['end_seconds'] = round(s['start_seconds'] + MAX_CLIP_SECS, 3)
            s['duration'] = MAX_CLIP_SECS
            fixes.append(f"  ⚠ SEG {s['segment_id']}: duración {duration:.1f}s → {MAX_CLIP_SECS}s (end {old_end:.3f} → {s['end_seconds']:.3f})")
        else:
            s['duration'] = round(duration, 3)

    for i in range(len(segments) - 1):
        cur  = segments[i]
        nxt  = segments[i + 1]
        if cur['end_seconds'] > nxt['start_seconds']:
            old_end = cur['end_seconds']
            cur['end_seconds'] = round(nxt['start_seconds'], 3)
            cur['duration']    = round(cur['end_seconds'] - cur['start_seconds'], 3)
            fixes.append(f"  ⚠ OVERLAP SEG {cur['segment_id']}→{nxt['segment_id']}: end {old_end:.3f} → {cur['end_seconds']:.3f}")

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
        print(f"  sanitize_timeline: {len(fixes)} corrección(es) automática(s)")
        for f in fixes:
            print(f)
        print(f"{'─'*62}\n")
    else:
        print(f"\n  ✓ sanitize_timeline: sin overlaps, todas las duraciones ≤ {MAX_CLIP_SECS}s")

    return segments


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 generar_timeline_futbol.py futbol/<jugador>/")
        sys.exit(1)

    carpeta  = pathlib.Path(sys.argv[1])
    nombre   = carpeta.name
    srt_file = carpeta / f"{nombre}.srt"
    out_dir  = carpeta / "05-montaje"
    out_file = out_dir / "timeline.json"

    out_dir.mkdir(parents=True, exist_ok=True)

    if not srt_file.exists():
        print(f"ERROR: No existe {srt_file}"); sys.exit(1)

    api_key = ""
    if KEY_FILE.exists():
        api_key = KEY_FILE.read_text().strip()
    elif os.environ.get('OPENROUTER_API_KEY'):
        api_key = os.environ['OPENROUTER_API_KEY']
    else:
        print(f"ERROR: Sin API key en {KEY_FILE}"); sys.exit(1)

    video_name = nombre.replace('_', ' ').title()

    print(f"\n{'═'*62}")
    print(f"  TIMELINE FÚTBOL — {video_name.upper()}")
    print(f"{'═'*62}")

    entries = parse_srt(srt_file)
    if not entries:
        print("ERROR: SRT vacío"); sys.exit(1)

    total_duration = entries[-1]['end']
    print(f"  SRT:      {len(entries)} entradas")
    print(f"  Duración: {total_duration:.1f}s  ({total_duration/60:.1f} min)")

    batches       = make_batches(entries, BATCH_SECONDS)
    total_batches = len(batches)
    print(f"  Lotes:    {total_batches} × ~{BATCH_SECONDS}s")
    print()

    all_segments    = []
    segment_counter = 1

    for i, batch in enumerate(batches, 1):
        b_start = batch[0]['start']
        b_end   = batch[-1]['end']
        print(f"  [{i:02d}/{total_batches}] {b_start:.1f}s → {b_end:.1f}s...", end='', flush=True)

        t0       = time.time()
        segments = call_openrouter(api_key, video_name, batch, i, total_batches)
        elapsed  = time.time() - t0

        for s in segments:
            s['segment_id'] = segment_counter
            segment_counter += 1
        all_segments.extend(segments)
        print(f" {len(segments)} inserts ({elapsed:.1f}s)")

        if i < total_batches:
            time.sleep(1)

    all_segments = sanitize_timeline(all_segments)

    # Segundo pase LLM: verificar que ia_prompt coincida con el audio exacto
    print("\n  Verificando coherencia prompt ↔ audio (segundo pase LLM)...")
    all_segments = auto_fix_prompts(all_segments, api_key)

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
    all_segments = _segs_sorted


    out_file.write_text(
        json.dumps({"visual_timeline": all_segments}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\n  ✓ timeline.json → {out_file}")
    print(f"  Total inserts: {len(all_segments)} en {total_duration/60:.1f} min de video")

    sources = {}
    for s in all_segments:
        src = s.get('source', '?')
        sources[src] = sources.get(src, 0) + 1
    if sources:
        print(f"\n  Distribución:")
        for src, count in sorted(sources.items(), key=lambda x: -x[1]):
            icon = {"brave_search": "🔍", "pexels": "🎬", "pixabay": "🎬", "ia_sports": "🤖"}.get(src, "❓")
            print(f"    {icon} {src:<20} {count:3d} inserts")

    print(f"\n  Siguiente paso:")
    print(f"  1. python3 filtrar_clips.py {sys.argv[1]}")
    print(f"  2. python3 harvester_timeline.py {sys.argv[1]} --canal futbol")
    print(f"  3. Aprobar en http://localhost:5001")
    print(f"  4. python3 render.py {sys.argv[1]}")

if __name__ == "__main__":
    main()
