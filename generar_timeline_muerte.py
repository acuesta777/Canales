#!/usr/bin/env python3
"""
generar_timeline_muerte.py — Planificador visual para videos de tipo "muerte/tragedia".

Igual que generar_timeline_riqueza.py pero con triggers orientados a:
  muerte, funeral, cementerio, hospital, enfermedad, adicción, guerra,
  exilio, soledad, escenas históricas, despedida, velorio.

El script base (riqueza) NO se modifica — este es el override para arcos de muerte.

Uso:
    python3 generar_timeline_muerte.py riqueza/angelines_fernandez/
"""

import sys, re, json, pathlib, time, os
import urllib.request, urllib.error

BATCH_SECONDS   = 90
MAX_SEG_SECS    = 8.0
MIN_SEG_SECS    = 2.0
PRIORITY_WINDOW = 180

HOME        = pathlib.Path.home()
KEY_FILE    = HOME / ".openrouter_key"
OR_MODEL    = "google/gemini-2.5-flash-lite"
OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a Visual Timeline Planner for a Spanish-language YouTube channel about celebrity life and death called "Caxando Famosos". The channel's brand for this video type is HUMAN DRAMA — death, illness, farewell, grief, historical settings, exile, loneliness, and the poignant stories of people who lived extraordinary lives.

CONTEXT: The video has real celebrity footage in the background. Your job is to find 7–15 moments in the first 10 minutes of narration where an IMAGE INSERT would reinforce the story. Prioritize triggers related to death, illness, historical settings, and human drama.

TRIGGER TYPES — insert ONLY when one of these is clearly present:

DEATH / GRIEF TRIGGERS (primary triggers for this video type):
- FUNERAL: death, dying, burial, coffin, wake, cemetery, mourners, farewell — murió, falleció, ataúd, velorio, cementerio, lloraban, entierro, sepelio, despedida, última voluntad, últimos días
  → Visual: single closed coffin in a dim chapel with white lilies, cemetery at dusk with mist, mourners in black around a grave (no faces), stone gravestone with faded flowers, candlelit home altar for mourning
- ILLNESS: specific disease, addiction, deteriorating health — cirrosis, cáncer, adicción, tabaquismo, sobredosis, pulmones, tos crónica, enfermedad terminal, salud deteriorada, diagnóstico
  → Visual: X-ray on a lightbox showing lungs, prescription bottles on a nightstand in dim light, hospital wristband on a bedside table, medical illustration of affected organ — no faces, no text
- HOSPITAL: hospital visit, medical emergency, doctors, surgery — hospital, médicos, cirujano, internado, sala de emergencias, clínica, enfermeras, operación
  → Visual: empty hospital corridor at night with fluorescent lights, ambulance entrance with red lights, tired doctor in scrubs leaning against a wall — no faces
- LONELINESS: isolation, solitude, abandonment, forgotten — soledad, sola, solo, olvidado, retirado, ausente, ya no aparecía, silencio, apartamento vacío, últimos meses
  → Visual: single chair by a window with rain outside, empty apartment with one lamp, unmade bed with morning light filtering through curtains, woman's silhouette alone at a kitchen table — no face

STORY / HISTORICAL TRIGGERS:
- PLACE: any real location mentioned — city, country, neighborhood, building, street — Madrid, México, barrio, calle, Atlántico, vecindario, estudios Televisa
  → Visual: period-accurate view of that specific place. Use era: pre-1950 → black and white, film grain; 1950–1989 → vintage warm color, faded film; 1990+ → modern color
- POVERTY: humble origins, struggling family, no money — barrio humilde, pobreza, sin recursos, familia modesta, guerra, miseria, escasez
  → Visual: modest street in 1930s Madrid with cobblestones, humble Spanish Republican-era house, child at a window looking out at a war-torn street — no faces
- WAR: civil war, guerrilla, battle, combat, military — guerra civil, combatiente, guerrillero, maquis, resistencia, Franco, milicia, refugiado, exilio, persecución
  → Visual: bombed Spanish street in the 1930s, mountains with guerrilla fighters silhouettes (no faces), Republican-era political poster torn on a wall, checkpoint soldiers at dawn — black and white, film grain, period-accurate
- ROMANCE: a love partner, unrequited love, secret love, farewell to love — amor, pareja, amor no correspondido, amor silencioso, lo amaba, enamorada, corazón roto, amor imposible
  → Visual: single red rose placed on a closed coffin, two chairs facing each other at a table with one empty, silhouette of a woman looking out a window alone — no faces
- CINEMA: film role, movie scene, filming, theater — película, cine, rodaje, escena, teatro, película clásica, época dorada del cine
  → Visual: vintage 1950s–1960s Mexican movie set with camera equipment, empty golden-age cinema seats with the screen glowing, old film reel on a projector — period-accurate
- RADIO: radio, broadcast, recording — radio, XEW, emisora, micrófono, transmisión, programa radial
  → Visual: vintage 1940s radio microphone in a small broadcast booth with glowing dials, old radio tower at dusk, operator with headphones at an analog console — black and white or sepia
- PRESS: newspapers, media, coverage — prensa, periódicos, titulares, revista, nota periodística
  → Visual: stack of vintage Spanish newspapers from the 1940s–1990s, printing press in motion, news kiosk with headlines — no readable text
- INTERIOR: a specific room or setting described — apartamento, departamento, set de televisión, estudio, camerino, corredor, sala de espera
  → Visual: 1970s–1980s Mexican television studio set empty with stage lights off, hospital waiting room with worn chairs and fluorescent lighting, small apartment with single bulb and bare walls — no faces
- DOCUMENT: official papers, will, testament, last wishes — documentos, testamento, papeles, última voluntad, acta de defunción
  → Visual: aged handwritten document with official seal on a desk, fountain pen resting on notarized paper — no readable text

⛔ DO NOT insert on: general career narration without specific trigger, personality descriptions, show titles, co-stars with no trigger.

⚠️ CONTEXT RULE: ALL triggers apply whenever the narration clearly mentions them.

🔴 MANDATORY OPENING RULE: This video opens with a death/tragedy scene — a specific place, a date, or a cinematic description of the person's world. The FIRST BATCH always has at least one PLACE or WAR or POVERTY trigger. NEVER skip the opening.

VISUAL RULES:
- Source: always "flow"
- ia_prompt: detailed cinematic English prompt starting with "Cinematic hyperrealistic photo of"
  Era: before 1950 → "black and white, film grain, silver gelatin photography, period-accurate, 16:9" | 1950–1969 → "vintage warm desaturated color, faded film look, period-accurate, 16:9" | 1970–1989 → "warm 1970s color film look, slightly faded, period-accurate, 16:9" | 1990–2009 → "modern color, slightly warm, 16:9" | 2010+ → "full color vivid, crisp, hyperrealistic, 16:9"
- IMPORTANT: for scenes of death, loneliness, illness — use muted tones, dim lighting, empty spaces, no faces
- Always end with: "cinematic lighting, no text, no letters, no faces visible, 16:9"
- Insert duration: 3–8 seconds MAX. No overlaps.

OUTPUT: Valid JSON only.
{
  "visual_timeline": [
    {
      "segment_id": 1,
      "source": "flow",
      "start_seconds": 12.9,
      "end_seconds": 20.0,
      "duration": 7.1,
      "scene_description_es": "Descripción en español",
      "ia_prompt": "Cinematic hyperrealistic photo of ..., black and white, film grain, period-accurate, 16:9, cinematic lighting, no text, no letters, no faces visible",
      "covers_text": "texto exacto del SRT",
      "trigger_type": "funeral|illness|hospital|loneliness|place|poverty|war|romance|cinema|radio|press|interior|document"
    }
  ]
}"""

USER_TEMPLATE = """BATCH {batch_number} of {total_batches}
TIME WINDOW: {batch_start}s → {batch_end}s
CELEBRITY/VIDEO: {video_name}
VIDEO TYPE: MUERTE / TRAGEDIA — prioritize death, illness, war, loneliness, historical triggers

SRT ENTRIES (Spanish narration, each with exact timestamps):
{sentences_json}

RULES:
1. Use EXACT timestamps — never invent seconds
2. Group 2–4 consecutive SRT entries into ONE insert
3. start_seconds = timestamp "t" of the SPECIFIC entry that contains the trigger word. end_seconds = start_seconds + duration (max 8s).
4. Generate ONLY inserts where a valid trigger is present. If a batch has no trigger, output 0 inserts.
5. Match the visual to the EXACT content of covers_text — not the general topic of the video:
   ⚠️ OVERRIDE RULE: If covers_text names a SPECIFIC object, place, or scene — illustrate THAT SPECIFIC THING.
   Examples:
   - covers_text: "barrio de Chamberí en Madrid" → show cobblestone street in 1930s Madrid neighborhood, B&W
   - covers_text: "guerra civil española" → show bombed Spanish street or resistance fighters silhouettes, B&W
   - covers_text: "ataúd cerrado en la capilla" → show closed coffin with white lilies in dim chapel
   - covers_text: "fumaba demasiado" → show ashtray overflowing with cigarette butts on a nightstand, dim light
   - covers_text: "trastornos cardíacos" → show EKG monitor with flat line on a hospital screen, dim corridor
   - covers_text: "mausoleos del Ángel" → show elegant mausoleum corridor with stone niches at dusk
   - covers_text: "velorio" → show mourners in black silhouettes around an open coffin (no faces)
6. NEVER invent a visual for narration with no trigger.
7. ia_prompt MUST illustrate EXACTLY what covers_text says — not the general death theme.

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

def auto_fix_prompts(segments, api_key):
    if not segments:
        return segments

    system_msg = (
        "You are a strict prompt quality validator for a MUERTE/TRAGEDY video production pipeline. "
        "For each segment, you receive: covers_text (the EXACT audio line), trigger_type, and current_prompt.\n\n"
        "YOUR JOB: verify that current_prompt illustrates the SPECIFIC object/place/action in covers_text — "
        "not the general death/grief theme, not the trigger type's default visual.\n\n"
        "CRITICAL EXAMPLES OF MISMATCHES (mark as fixed=true and rewrite):\n"
        "- covers_text mentions 'fumaba cigarrillos' but prompt shows 'hospital corridor' → MISMATCH → rewrite to show overflowing ashtray\n"
        "- covers_text mentions 'Mausoleos del Ángel' but prompt shows generic cemetery → MISMATCH → rewrite to show elegant stone mausoleum niches\n"
        "- covers_text mentions 'barrio de Chamberí' but prompt shows generic poor street → MISMATCH → rewrite to show 1930s Madrid cobblestone neighborhood\n"
        "- covers_text mentions 'Bruja del 71' but prompt shows coffin → MISMATCH → show empty 1970s TV studio set\n\n"
        "RULE: Ask yourself 'What specific noun does covers_text literally name?' — the prompt MUST show that noun.\n"
        "If prompt matches covers_text literally → fixed=false.\n"
        "If prompt drifts → fixed=true, rewrite.\n\n"
        "Always start rewritten prompts with 'Cinematic hyperrealistic photo of'. "
        "Always end with 'cinematic lighting, no text, no letters, no faces visible, 16:9'. "
        "Return ONLY valid JSON array: [{\"seg_id\": N, \"ia_prompt\": \"...\", \"fixed\": true/false}]"
    )

    BATCH_SIZE = 6
    total_fixed = 0

    for batch_start in range(0, len(segments), BATCH_SIZE):
        batch = segments[batch_start: batch_start + BATCH_SIZE]
        items = [
            {
                "seg_id": s["segment_id"],
                "covers_text": s.get("covers_text", ""),
                "trigger_type": s.get("trigger_type", ""),
                "current_prompt": s.get("ia_prompt", ""),
            }
            for s in batch
        ]

        user_msg = "Validate and fix these segments (be strict — mismatch = fixed=true):\n" + json.dumps(items, ensure_ascii=False)

        payload = json.dumps({
            "model": OR_MODEL,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": user_msg},
            ],
            "temperature": 0.1,
            "max_tokens": 2000,
        }).encode()

        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            raw = data["choices"][0]["message"]["content"]
            fixed_list = json.loads(raw.strip().lstrip("```json").rstrip("```").strip())
            fix_map = {item["seg_id"]: item for item in fixed_list}
            for s in batch:
                fix = fix_map.get(s["segment_id"])
                if fix and fix.get("fixed"):
                    s["ia_prompt"] = fix["ia_prompt"]
                    total_fixed += 1
                    print(f"    🔧 SEG {s['segment_id']:02d} corregido: {s.get('covers_text','')[:60]}")
        except Exception as e:
            print(f"  ⚠ auto_fix_prompts lote {batch_start//BATCH_SIZE+1} falló ({e}) — continuando")

        if batch_start + BATCH_SIZE < len(segments):
            time.sleep(1)

    if total_fixed:
        print(f"  🔧 auto_fix_prompts: {total_fixed} prompt(s) corregido(s)")
    else:
        print(f"  ✓ auto_fix_prompts: todos los prompts coinciden con el audio")
    return segments


def extract_json(text):
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$', '', text, flags=re.MULTILINE)
    return json.loads(text)

def call_openrouter(api_key, video_name, batch, batch_num, total_batches, retries=3):
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
                    "HTTP-Referer":  "https://caxandofamosos.canal",
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

def validate_segments(segments, batch_start, batch_end):
    if not segments:
        return segments
    segments[0]['start_seconds'] = round(batch_start, 3)
    for i in range(1, len(segments)):
        segments[i]['start_seconds'] = round(segments[i-1]['end_seconds'], 3)
    segments[-1]['end_seconds'] = round(batch_end, 3)
    for s in segments:
        s['duration'] = round(s['end_seconds'] - s['start_seconds'], 3)
    return segments

MAX_CLIP_SECS = 8.0

def sanitize_timeline(segments: list) -> list:
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
            fixes.append(f"  ⚠ SEG {s['segment_id']}: duración {duration:.1f}s → {MAX_CLIP_SECS}s")
        else:
            s['duration'] = round(duration, 3)

    for i in range(len(segments) - 1):
        cur  = segments[i]
        nxt  = segments[i + 1]
        if cur['end_seconds'] > nxt['start_seconds']:
            old_end = cur['end_seconds']
            cur['end_seconds'] = round(nxt['start_seconds'] - 0.001, 3)
            cur['duration']    = round(cur['end_seconds'] - cur['start_seconds'], 3)
            if cur['duration'] < 1.0:
                cur['_delete'] = True
                fixes.append(f"  ⚠ OVERLAP SEG {cur['segment_id']} eliminado")
            else:
                fixes.append(f"  ⚠ OVERLAP SEG {cur['segment_id']}→{nxt['segment_id']}: end {old_end:.3f} → {cur['end_seconds']:.3f}")

    segments = [s for s in segments if not s.get('_delete')]

    MIN_DUR_SECS = 3.0
    for i, s in enumerate(segments):
        duration = s['end_seconds'] - s['start_seconds']
        if duration < MIN_DUR_SECS:
            max_end = segments[i + 1]['start_seconds'] - 0.001 if i + 1 < len(segments) else s['start_seconds'] + MIN_DUR_SECS
            new_end = min(round(s['start_seconds'] + MIN_DUR_SECS, 3), max_end)
            if new_end - s['start_seconds'] >= 1.0:
                fixes.append(f"  ⚠ SEG {s['segment_id']}: duración {duration:.1f}s → {new_end - s['start_seconds']:.1f}s")
                s['end_seconds'] = new_end
                s['duration']    = round(new_end - s['start_seconds'], 3)
            else:
                s['_delete'] = True

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


def fill_gaps(segments: list) -> list:
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
                chunk = min(gap, MAX_CLIP_SECS)
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
        print(f"  fill_gaps: {len(extra_segs)} segmento(s) de relleno insertado(s)")

    for i, s in enumerate(filled, 1):
        s['segment_id'] = i

    return filled


def main():
    import argparse, socket
    def _find_free_port(start=5099):
        for p in range(start, start + 50):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('127.0.0.1', p)) != 0:
                    return p
        return start

    parser = argparse.ArgumentParser()
    parser.add_argument("carpeta")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    carpeta  = pathlib.Path(args.carpeta)
    _approval_port = args.port if args.port else _find_free_port()
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

    video_name = nombre.replace('_', ' ').title()

    print(f"\n{'═'*62}")
    print(f"  TIMELINE PLANNER (MUERTE) — {video_name.upper()}")
    print(f"  Canal: Caxando Famosos | Tipo: tragedia/muerte")
    print(f"{'═'*62}")

    entries = parse_srt(srt_file)
    if not entries:
        print("ERROR: SRT vacío"); sys.exit(1)

    entries = [e for e in entries if e['start'] < 600]

    total_duration = entries[-1]['end'] if entries else 0
    print(f"  SRT:      {len(entries)} entradas (primeros 10 min)")
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
        print(f"  [{i:02d}/{total_batches}] {b_start:.1f}s → {b_end:.1f}s  ({len(batch)} entradas)...", end='', flush=True)

        t0       = time.time()
        segments = call_openrouter(api_key, video_name, batch, i, total_batches)
        elapsed  = time.time() - t0

        if segments:
            for s in segments:
                s['segment_id'] = segment_counter
                segment_counter += 1
            all_segments.extend(segments)
            print(f" {len(segments)} segmentos ({elapsed:.1f}s)")
        else:
            print(f" ⚠ Sin segmentos (saltado)")

        if i < total_batches:
            time.sleep(1)

    if not all_segments:
        print("ERROR: No se generaron segmentos"); sys.exit(1)

    for s in all_segments:
        if 'start' in s and 'start_seconds' not in s:
            s['start_seconds'] = s.pop('start')
        if 'end' in s and 'end_seconds' not in s:
            s['end_seconds'] = s.pop('end')
        if 'end_seconds' not in s and 'duration' in s and 'start_seconds' in s:
            s['end_seconds'] = round(s['start_seconds'] + s['duration'], 3)

    all_segments = sanitize_timeline(all_segments)

    _segs_sorted = sorted(all_segments, key=lambda s: s["start_seconds"])
    for _i in range(1, len(_segs_sorted)):
        _prev_end  = _segs_sorted[_i-1]["end_seconds"]
        _cur_start = _segs_sorted[_i]["start_seconds"]
        if 0 < _cur_start - _prev_end < 2.0:
            _segs_sorted[_i]["start_seconds"] = _prev_end
    for _s in _segs_sorted:
        _s["start_seconds"] = int(round(_s["start_seconds"]))
        _s["end_seconds"]   = int(round(_s["end_seconds"]))
        _s["duration"]      = min(_s["end_seconds"] - _s["start_seconds"], 8)
        _s["end_seconds"]   = _s["start_seconds"] + _s["duration"]
    all_segments = _segs_sorted

    print("\n  Verificando coherencia prompt ↔ audio (segundo pase LLM)...")
    all_segments = auto_fix_prompts(all_segments, api_key)

    # Dedup variants — orientadas a muerte/tragedia
    MUERTE_VARIANTS = {
        "funeral": [
            ("Ataúd cerrado en capilla oscura con flores blancas",             "Cinematic hyperrealistic photo of closed wooden coffin in a dim chapel lit by candles, white lilies draped over the lid, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Cementerio al atardecer con niebla entre lápidas",               "Cinematic hyperrealistic photo of old cemetery at dusk with mist drifting between weathered tombstones, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Dolientes de negro con cabezas bajas junto a tumba",             "Cinematic hyperrealistic photo of mourners dressed in black standing with bowed heads around an open grave, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Flores marchitas sobre lápida de mármol gris",                   "Cinematic hyperrealistic photo of wilted white flowers on a gray marble gravestone, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Velas encendidas frente a altar de duelo con fotos",             "Cinematic hyperrealistic photo of lit candles in front of a home mourning altar with framed photographs, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "illness": [
            ("Radiografía de pulmones en caja de luz médica",                  "Cinematic hyperrealistic photo of chest X-ray showing lungs on a medical lightbox in a dim room, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Frascos de medicamentos en mesita de noche tenue",               "Cinematic hyperrealistic photo of prescription medicine bottles on a dimly lit nightstand, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Cenicero lleno de colillas en mesa de noche",                    "Cinematic hyperrealistic photo of overflowing ashtray with cigarette butts on a bedside table, dim warm light, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Suero médico colgado en habitación de hospital vacía",           "Cinematic hyperrealistic photo of IV drip bag hanging in an empty hospital room, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Pulsera de paciente sobre cama de hospital sin hacer",           "Cinematic hyperrealistic photo of hospital wristband on an unmade hospital bed, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "hospital": [
            ("Pasillo de hospital vacío de noche con luz fluorescente",        "Cinematic hyperrealistic photo of empty hospital corridor at night with fluorescent ceiling lights, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Entrada de urgencias con ambulancia en lluvia",                  "Cinematic hyperrealistic photo of hospital emergency entrance with ambulance and red lights in the rain, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Sala de espera de hospital con sillas desgastadas",              "Cinematic hyperrealistic photo of hospital waiting room with worn plastic chairs under fluorescent light, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Camilla vacía en corredor de hospital al alba",                  "Cinematic hyperrealistic photo of empty hospital gurney in a corridor at dawn, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Monitor cardíaco apagado junto a cama vacía",                   "Cinematic hyperrealistic photo of turned-off cardiac monitor beside an empty hospital bed, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "loneliness": [
            ("Silla sola frente a ventana con lluvia",                         "Cinematic hyperrealistic photo of single empty chair facing a rain-streaked window, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Apartamento vacío con una sola lámpara encendida",               "Cinematic hyperrealistic photo of sparse apartment with single lamp on in the corner, bare walls, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Cama sin hacer con luz matutina en cuarto vacío",                "Cinematic hyperrealistic photo of unmade bed with morning light filtering through curtains in an empty room, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Taza de café vacía sobre mesa de madera sola",                   "Cinematic hyperrealistic photo of empty coffee cup on a wooden table, single window light, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Pasillo oscuro de apartamento con luz al fondo",                 "Cinematic hyperrealistic photo of dark apartment hallway with a single light visible at the far end, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "war": [
            ("Calle española bombardeada en blanco y negro años 1930",         "Cinematic hyperrealistic photo of bombed cobblestone street in 1930s Spain with rubble and smoke, black and white, film grain, period-accurate, 16:9, cinematic lighting, no text, no letters, no faces visible"),
            ("Montañas con siluetas de guerrilleros al amanecer B&N",          "Cinematic hyperrealistic photo of mountain silhouettes with guerrilla fighters at dawn, black and white, film grain, 1930s Spain, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Cartel republicano rasgado en pared de Madrid B&N",              "Cinematic hyperrealistic photo of torn Republican-era political poster on a crumbling wall in Madrid, black and white, silver gelatin, period-accurate, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Refugiados con maletas caminando en blanco y negro",             "Cinematic hyperrealistic photo of refugees carrying suitcases walking along a road, black and white, film grain, 1940s Spain, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Puesto de control militar en calle española B&N",                "Cinematic hyperrealistic photo of military checkpoint on a Spanish street at dawn, black and white, period-accurate, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "poverty": [
            ("Calle adoquinada de barrio humilde en Madrid años 1930",         "Cinematic hyperrealistic photo of cobblestone alley in a humble Madrid neighborhood in the 1930s, black and white, film grain, period-accurate, 16:9, cinematic lighting, no text, no letters, no faces visible"),
            ("Cocina austera con mesa de madera y luz de vela",                "Cinematic hyperrealistic photo of austere kitchen with bare wooden table and candlelight, black and white, period-accurate, 16:9, cinematic lighting, no text, no letters, no faces visible"),
            ("Ropa tendida en balcón de vivienda humilde",                     "Cinematic hyperrealistic photo of laundry hanging on balconies of humble apartment building in 1940s Spain, black and white, film grain, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Zapatos viejos junto a puerta de casa modesta",                  "Cinematic hyperrealistic photo of worn shoes beside the door of a modest home, dim light, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Niño mirando por ventana en barrio pobre B&N",                   "Cinematic hyperrealistic photo of small child silhouette looking out a window in a poor neighborhood, black and white, film grain, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "romance": [
            ("Rosa roja sobre ataúd cerrado",                                  "Cinematic hyperrealistic photo of a single red rose placed on a closed dark wood coffin, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Dos sillas vacías frente a frente en habitación tenue",          "Cinematic hyperrealistic photo of two empty chairs facing each other in a dimly lit room, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Carta escrita a mano con pluma en mesa de madera",               "Cinematic hyperrealistic photo of handwritten letter on worn paper with fountain pen on a wooden desk, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Flores marchitas en jarrón junto a ventana con lluvia",          "Cinematic hyperrealistic photo of wilted flowers in a vase by a rain-streaked window, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Fotografía borrosa de dos siluetas sin rostros",                 "Cinematic hyperrealistic photo of blurred old photograph showing two silhouettes without visible faces, vintage sepia tone, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "place": [
            ("Calle adoquinada de Madrid de noche en blanco y negro",          "Cinematic hyperrealistic photo of cobblestone street in Madrid at night, black and white, film grain, silver gelatin, period-accurate 1930s, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Vista aérea de Ciudad de México al atardecer años 1970",         "Cinematic hyperrealistic photo of wide aerial view of Mexico City at dusk, warm vintage 1970s color, period-accurate, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Estudios de televisión vacíos de Televisa años 1970",            "Cinematic hyperrealistic photo of empty 1970s Mexican television studio with camera equipment and stage lights off, warm vintage color, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Mausoleo de piedra con nichos al atardecer",                     "Cinematic hyperrealistic photo of elegant stone mausoleum corridor with burial niches at dusk, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Puerto de mar con barco alejándose al horizonte B&N",            "Cinematic hyperrealistic photo of harbor with a ship sailing away toward the horizon, black and white, film grain, 1940s, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "cinema": [
            ("Set de cine mexicano años 1950 con cámaras antiguas",            "Cinematic hyperrealistic photo of 1950s Mexican film set with vintage cameras and studio lights, warm sepia, period-accurate, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Sala de cine vacía con pantalla iluminada años 1960",            "Cinematic hyperrealistic photo of empty golden-age cinema seats with glowing screen, warm vintage 1960s color, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Bobina de película en proyector antiguo",                        "Cinematic hyperrealistic photo of old film reel on a vintage projector with light beam, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Claqueta de cine sobre guion en mesa de producción",             "Cinematic hyperrealistic photo of film clapperboard on a production script on a desk, vintage warm color, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Marquesina de cine antiguo iluminada de noche",                  "Cinematic hyperrealistic photo of vintage cinema marquee glowing at night with Art Deco lettering, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "interior": [
            ("Camerino de televisión vacío con luces de espejo",               "Cinematic hyperrealistic photo of empty TV dressing room with vanity mirror lights, 1970s warm color, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Habitación de apartamento pequeño con luz tenue",                "Cinematic hyperrealistic photo of small apartment room with dim warm lamp, sparse furniture, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Pasillo de televisora vacío con puertas cerradas",               "Cinematic hyperrealistic photo of empty television studio hallway with closed doors, fluorescent light, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Sala de espera pequeña con sillas de plástico",                  "Cinematic hyperrealistic photo of small waiting room with plastic chairs and single window, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Set de televisión años 1970 sin actores con luces encendidas",   "Cinematic hyperrealistic photo of 1970s television set fully lit but empty, no actors, warm vintage color, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "radio": [
            ("Micrófono vintage de radio años 1940 en estudio oscuro",         "Cinematic hyperrealistic photo of vintage 1940s radio microphone in a small dark broadcast booth with glowing dials, black and white, period-accurate, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Torre de radio al atardecer en sepia",                           "Cinematic hyperrealistic photo of radio transmission tower at dusk in warm sepia tones, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Mesa de control de radio con equipo analógico",                  "Cinematic hyperrealistic photo of analog radio control desk with glowing meters and knobs, vintage warm color, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "press": [
            ("Pila de periódicos españoles vintage",                           "Cinematic hyperrealistic photo of stack of vintage Spanish newspapers from the 1940s–1950s on a desk, black and white, film grain, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Redacción con máquinas de escribir y papeles sueltos",           "Cinematic hyperrealistic photo of newsroom with old typewriters and scattered papers, vintage warm color, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "document": [
            ("Acta de defunción con sello oficial sobre escritorio",           "Cinematic hyperrealistic photo of aged death certificate with official wax seal on a desk, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Testamento escrito a mano con pluma antigua",                    "Cinematic hyperrealistic photo of handwritten last will and testament on aged paper with fountain pen, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
    }

    trigger_count: dict = {}
    dedup_fixed = 0
    for seg in all_segments:
        ttype = seg.get("trigger_type", "").lower()
        variants = MUERTE_VARIANTS.get(ttype)
        if not variants:
            continue
        n = trigger_count.get(ttype, 0)
        trigger_count[ttype] = n + 1
        if n == 0:
            continue
        v_es, v_en = variants[(n - 1) % len(variants)]
        seg["ia_prompt"] = v_en
        seg["scene_description_es"] = v_es
        dedup_fixed += 1

    if dedup_fixed:
        print(f"  🔁 Dedup: {dedup_fixed} prompts variados (trigger repetido)")
    else:
        print(f"  ✓ Dedup: sin prompts duplicados")

    VALID_TRIGGERS = {
        "funeral", "illness", "hospital", "loneliness",
        "place", "poverty", "war", "romance",
        "cinema", "radio", "press", "interior", "document",
        # compatibilidad con triggers del script riqueza que también aplican
        "money", "property", "possessions", "accident", "concert",
    }
    before = len(all_segments)
    all_segments = [s for s in all_segments if s.get("trigger_type", "").lower() in VALID_TRIGGERS]
    dropped = before - len(all_segments)
    if dropped:
        print(f"  ⚠ {dropped} segmento(s) eliminados por trigger inválido")

    empty_segs = [s['segment_id'] for s in all_segments if not str(s.get('ia_prompt', '')).strip()]
    if empty_segs:
        print(f"\n  ⛔ ERROR FATAL: {len(empty_segs)} segmento(s) sin ia_prompt: {empty_segs}")
        print(f"  timeline.json NO fue escrito — corregir prompts antes de continuar")
        sys.exit(1)

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
    print(f"\n  Distribución de fuentes:")
    for src, count in sorted(sources.items(), key=lambda x: -x[1]):
        print(f"    🤖 {src:<20} {count:3d} segmentos ({count/len(all_segments)*100:.0f}%)")

    print(f"\n  ⚠ Revisar prompts vs audio antes de abrir la UI de aprobación.")
    print(f"  Puerto asignado: {_approval_port}")
    print(f"  Cuando estén limpios, lanzar:")
    print(f"  python3 approval_solo.py {sys.argv[1]} --port {_approval_port}")

if __name__ == "__main__":
    main()
