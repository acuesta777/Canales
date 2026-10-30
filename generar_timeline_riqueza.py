#!/usr/bin/env python3
"""
generar_timeline_riqueza.py — Planificador visual para canal Caxando Famosos (riqueza).

Lee el SRT del video → Gemini analiza cada segmento → asigna fuente de imagen
→ genera 05-montaje/timeline.json anclado al audio.

Triggers válidos (13):
  RIQUEZA:  money · property · place · possessions
  HISTORIA: poverty · romance · funeral · illness · hospital · press · cinema · document · interior

Fuentes posibles:
  - "pexels"       : clip de video de Pexels (lujo, mansion, autos, viajes)
  - "pixabay"      : clip de video de Pixabay (ambiente de respaldo)
  - "ia_luxury"    : imagen generada con muapi.ai (escenas de lujo cinematic)
  - "brave_search" : imagen real (propiedades específicas, personas, yates, etc.)

Uso:
    python3 generar_timeline_riqueza.py riqueza/victoria_ruffo/
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

SYSTEM_PROMPT = """You are a Visual Timeline Planner for a Spanish-language YouTube channel about celebrity wealth called "Caxando Famosos". The channel's brand is LUXURY — mansions, cars, money, glamour, and the dramatic human stories behind the wealth.

CONTEXT: The video has real celebrity footage in the background. Your job is to find 7–15 moments in the first 10 minutes of narration where an IMAGE INSERT would reinforce the story. You now have 14 trigger types — use all of them.

TRIGGER TYPES — insert ONLY when one of these is clearly present:

WEALTH TRIGGERS (NO ownership required — insert whenever mentioned in narration):
- MONEY: any mention of money, salary, fortune, millions, contract, payment, earnings, wealth
- PROPERTY: any mention of a house, mansion, estate, ranch, penthouse, real estate — rancho, hacienda, mansión, propiedad, casa, finca — regardless of who owns it
- PLACE: any real location mentioned — state, city, town, neighborhood, country, road, highway, street, building. Fire at the EXACT timestamp where the location name appears, including second 0 if it's the first word.
- POSSESSIONS: any mention of jewels, cars, jets, yachts, watches, luxury clothing

STORY TRIGGERS (any clear mention in narration):
- POVERTY: humble origins, poor neighborhood, struggling family, no money growing up — barrio humilde, pobreza, orígenes humildes
  → Visual: modest unpainted house, barefoot child at a window, humble street in Latin America, simple clothesline
- ROMANCE: a romantic partner, lover, spouse, affair, "the love of their life", much younger partner — pareja, amante, esposa, amor de su vida
  → Visual: silhouette of the PARTNER (not celebrity) from behind, no face, romantic lighting. Adapt: male celebrity → female silhouette; female celebrity → male silhouette; age gap → youthful slender figure
- FUNERAL: death, dying, burial, coffin, wake, cemetery, mourners crying — murió, falleció, ataúd, velorio, cementerio, lloraban
  → Visual: single closed coffin in a dim chapel, cemetery at dusk, mourners in black around a grave (no faces), white flowers on dark wood
- ILLNESS: specific disease destroying the body — cirrhosis, cancer, addiction, alcoholism, overdose, deteriorating health — cirrosis, cáncer, adicción, sobredosis
  → Visual: medical illustration of affected organ, X-ray on lightbox, prescription bottles on a nightstand — no faces, no text
- HOSPITAL: hospital visit, surgery, medical emergency, OR medical staff — doctors, nurses, surgeon, tired medical team — médicos, enfermeras, cirujano, internado
  → Visual: empty hospital corridor, ambulance entrance at night, tired doctors in scrubs — no faces
- PRESS: newspaper headlines, magazine coverage, tabloid scandal, journalists writing about someone — prensa, periódico, titulares, revista, escándalo en papeles
  → Visual: stack of vintage Spanish newspapers, close-up of front page (no readable text), printing press rollers
- CINEMA: film role, movie premiere, cinema, filming a scene — película, cine, premiere, rodaje
  → Visual: vintage movie theater marquee at night, empty cinema seats with screen glowing, film reel on a projector, premiere red carpet (no faces)
- RADIO: radio show, broadcasting, recording debut, radio interview — radio, emisora, programa radial, micrófono, debut radial
  → Visual: vintage radio microphone in a small broadcast booth, old radio equipment with glowing dials, radio tower at dusk
- CONCERT: concert, sold-out show, theater performance, arena, stadium, performing live — concierto, estadio, escenario, show, teatro musical
  → Visual: empty concert stage with spotlights, arena viewed from the back with stage in distance, theater stage curtain, stadium seats empty — no faces
- ACCIDENT: car accident, crash, physical incident, injury from an accident — accidente, choque, incidente físico, herida por accidente
  → Visual: empty road at night with headlights, damaged car on roadside, police tape on a road, ambulance lights reflected on wet asphalt — no people visible
- DOCUMENT: official papers, notary, contract signed, divorce papers, will/testament, stamp being placed — documento, notaría, contrato firmado, acta de divorcio, testamento, sello
  → Visual: close-up of official document with rubber stamp, stack of papers on a desk, aged document with seal — no readable text
- INTERIOR: a specific room described cinematically — hotel room, office, backstage, apartment, corridor, recording studio — cuarto de hotel, oficina, backstage, corredor, estudio de grabación
  → Visual: dimly lit hotel corridor, empty office with single desk lamp, backstage hallway with bare bulbs — atmospheric, no people

⛔ DO NOT insert on: general career narration, personality descriptions, emotions, awards ceremonies, show titles, co-stars with no trigger.

⚠️ CONTEXT RULE: ALL triggers (both WEALTH and STORY) apply whenever the narration clearly mentions them — no ownership required for any trigger type.

🔴 MANDATORY OPENING PLACE RULE: If the VERY FIRST ENTRY of the FIRST BATCH contains a city or location name (e.g. "Ciudad de México", "Guadalajara", "Los Ángeles", "Monterrey", any state or country) — you MUST generate a PLACE insert at start_seconds=0 showing that exact city. NEVER skip the opening city. This applies even if the city appears in a date line like "Ciudad de México, 14 de enero de...". The city is ALWAYS the first trigger when it appears at t=0.

🔴 MANDATORY HOOK RULE: The FIRST BATCH almost always opens with a fortune question like "¿Cuánto valía realmente X?" or "se estima que su patrimonio superaba los Y millones". This IS a MONEY trigger — always insert a visual here (stacks of bills, property deeds, luxury items). A hook that mentions millions, patrimonio, fortuna, millón, dólares, propiedades, bienes MUST generate at least one MONEY insert in the first 30 seconds. NEVER skip the hook.


🔴 MANDATORY HOOK LOOP RULE: The hook also lists loop questions like "¿Qué propiedades tenía?", "¿Qué autos manejó?", "¿Qué joyas tenía?". These ARE real triggers even when phrased as questions — the audience sees them on screen. Each one maps to a trigger: "propiedades/mansión/rancho/casa" → PROPERTY, "autos/coche/auto" → POSSESSIONS, "joyas/relojes/ropa de lujo" → POSSESSIONS. Insert at least one PROPERTY or POSSESSIONS visual in the first 60 seconds if ANY of these words appear in the hook, question form or not.


REJECT wealth triggers only:
  - "el dinero era escaso en esa época" → general history, not celebrity's money
  - "los estudios ganaban millones" → studios, not the celebrity
  - "su familia era de clase media" → celebrity not wealthy at this point
  - "el barrio tenía casas modestas" → neighborhood, not celebrity's home

VISUAL RULES:
- Source: always "flow"
- scene_description_es: ALWAYS a Spanish translation/summary of what ia_prompt describes visually. NEVER a description of the audio/narration. Example: ia_prompt "Venezuelan bolivar banknote dissolving into dust" → scene_description_es "Billete de bolívar venezolano disolviéndose en polvo, efecto vintage"
- ia_prompt: detailed cinematic English prompt starting with "Cinematic hyperrealistic photo of"
  Era: before 1960 → "black and white, film grain, silver gelatin photography, period-accurate, 16:9" | 1960–1989 → "vintage warm color, faded film look, period-accurate, 16:9" | 1990–2009 → "modern color, slightly warm, 16:9" | 2010+ → "full color vivid, crisp, hyperrealistic, 16:9"
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
      "scene_description_es": "Descripción en español de LO QUE MUESTRA la imagen generada por ia_prompt — NO el audio. Debe ser la traducción/resumen de ia_prompt, no del SRT.",
      "ia_prompt": "Cinematic hyperrealistic photo of ..., vintage warm color, faded film look, period-accurate, 16:9, cinematic lighting, no text, no letters, no faces visible",
      "covers_text": "texto exacto del SRT",
      "trigger_type": "money|property|place|possessions|poverty|romance|funeral|illness|hospital|press|cinema|radio|concert|accident|document|interior"
    }
  ]
}"""

USER_TEMPLATE = """BATCH {batch_number} of {total_batches}
TIME WINDOW: {batch_start}s → {batch_end}s
CELEBRITY/VIDEO: {video_name}

SRT ENTRIES (Spanish narration, each with exact timestamps):
{sentences_json}

RULES:
1. Use EXACT timestamps — never invent seconds
2. Group 2–4 consecutive SRT entries into ONE insert
3. start_seconds = timestamp "t" of the SPECIFIC entry that contains the trigger word (NOT always the first entry). end_seconds = start_seconds + duration (max 8s). If the trigger word appears in the 3rd entry of a group, start_seconds must be that entry's "t".
4. Generate ONLY inserts where a valid trigger is present. If a batch has no trigger, output 0 inserts — do NOT invent one.
5. Match the visual to the trigger TYPE — but ONLY as a fallback when covers_text is generic:
   ⚠️ OVERRIDE RULE (read this first): If covers_text mentions a SPECIFIC object, place, or scene — a theater stage, a shop, a document, a building, a street, a market — illustrate THAT SPECIFIC THING regardless of the trigger type. The trigger type just determines the category; covers_text determines the exact image.
   Examples of the override in action:
   - covers_text: "siete décadas de trabajo sobre los escenarios" → NOT cash stacks (even if trigger=MONEY) → MUST show empty theater stage with spotlights
   - covers_text: "su patrimonio rondaba los seis millones de dólares" → NOT a mansion → MUST show a close-up of a handwritten estate document or net worth ledger
   - covers_text: "vendía dulces en una tienda del barrio" → NOT an apartment → MUST show a small old-fashioned candy shop
   - covers_text: "llegó sin dinero a la capital" → NOT a mansion → MUST show a person's back walking toward a big city skyline, humble clothes
   Fallback templates (use ONLY when covers_text is generic with no specific visual):
   - MONEY → cash stacks or denomination bills (generic wealth mention only)
   - PROPERTY → period-accurate luxury home/mansion (generic property mention only)
   - PLACE → upscale aerial view or elegant street of that specific city/era
   - POSSESSIONS → actual jewels, car, yacht, watch described (period-accurate)
   - POVERTY → modest unpainted house, humble street, barefoot child — NOT luxury
   - ROMANCE → silhouette of PARTNER from behind (not celebrity), no face, romantic light; adapt gender/age to narration
   - FUNERAL → closed coffin, cemetery at dusk, mourners in black (no faces)
   - ILLNESS → medical illustration of organ, X-ray, prescription bottles — no faces
   - HOSPITAL → empty hospital corridor, ambulance entrance, tired doctors in scrubs — no faces
   - PRESS → vintage Spanish newspaper stack, front page close-up (no readable text)
   - CINEMA → vintage movie theater marquee or empty cinema seats
   - RADIO → vintage radio microphone in broadcast booth or radio tower at dusk
   - CONCERT → empty concert stage with spotlights, stadium seats, theater curtain — no faces
   - ACCIDENT → empty road at night, damaged car on roadside, police tape — no people
   - DOCUMENT → official document with rubber stamp, notary desk — no readable text
   - INTERIOR → dimly lit hotel corridor, empty office with lamp, backstage hallway
   - When narration lists MULTIPLE objects: pick the MOST VISUAL one
6. NEVER invent a visual for narration that has no trigger. If no trigger → skip the batch.
7. CRITICAL — EXACT ANCHOR: Before writing ia_prompt, ask yourself: "What specific noun, object, or place does covers_text literally name?" Write that answer mentally, then build the prompt around THAT. The ia_prompt must illustrate EXACTLY what that specific sentence says — NOT the general topic of the paragraph, NOT the channel's wealth theme, NOT what came before or after. The trigger type is a CATEGORY label, not a visual prescription.
   ✅ CORRECT: covers_text "siete décadas de trabajo sobre los escenarios" → ia_prompt shows an empty Broadway theater stage with worn wooden boards bathed in golden spotlight
   ❌ WRONG: covers_text "siete décadas de trabajo sobre los escenarios" → ia_prompt shows six stacks of hundred-dollar bills (this is the general channel theme, not what the sentence says)
   ✅ CORRECT: covers_text "vendía dulces en una tienda del vecindario" → ia_prompt shows a small old-fashioned candy and sweets shop in a 1900s Brooklyn neighborhood
   ❌ WRONG: covers_text "vendía dulces en una tienda del vecindario" → ia_prompt shows cramped tenement apartments (this is what you imagine the era looks like, not what the sentence says)
   Read covers_text carefully before writing ia_prompt — if they don't match, rewrite the prompt.

JSON only."""

def ts_to_sec(ts):
    ts = ts.strip().replace(',', '.')
    p = ts.split(':')
    return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])

def parse_srt(srt_path, max_entry_secs=8.0):
    """Parsea SRT y rompe entradas largas en chunks de max_entry_secs.
    Así la IA recibe entradas cortas y genera un segmento visual por cada una."""
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
            # Romper en chunks proporcionales de max_entry_secs
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

def _srt_text_for_segment(srt_entries, start_sec, end_sec):
    """Devuelve el texto SRT que cae dentro del rango [start_sec, end_sec].
    srt_entries: lista de dicts con keys 'start', 'end', 'text' (formato de parse_srt)."""
    return " ".join(
        e["text"] for e in srt_entries if e["end"] > start_sec and e["start"] < end_sec
    ).strip()


def auto_fix_prompts(segments, api_key, srt_entries=None):
    """Segundo pase LLM: verifica que cada ia_prompt ilustre exactamente el covers_text.
    Procesa en lotes de 6 para evitar que el LLM haga rubber-stamp con demasiados items.
    Corrige automáticamente los que no coinciden. Retorna los segmentos corregidos.
    Si srt_entries se pasa, rellena covers_text vacíos desde el SRT antes de validar."""
    if not segments:
        return segments

    # Rellenar covers_text vacíos desde el SRT para que el validador no quede ciego
    if srt_entries:
        filled = 0
        for s in segments:
            if not s.get("covers_text") and s.get("source") == "flow":
                audio = _srt_text_for_segment(
                    srt_entries, s.get("start_seconds", 0), s.get("end_seconds", 0)
                )
                if audio:
                    s["covers_text"] = audio
                    filled += 1
        if filled:
            print(f"    ↳ covers_text rellenado desde SRT en {filled} segmento(s) sin texto")

    system_msg = (
        "You are a strict prompt quality validator for a cinematic video production pipeline. "
        "For each segment, you receive: covers_text (the EXACT audio line), trigger_type, and current_prompt.\n\n"
        "YOUR JOB: verify that current_prompt illustrates the SPECIFIC object/place/action in covers_text — "
        "not the channel's general wealth theme, not the trigger type's default visual, not what comes before or after.\n\n"
        "CRITICAL EXAMPLES OF MISMATCHES (mark these as fixed=true and rewrite):\n"
        "- covers_text mentions 'décadas de trabajo sobre los escenarios' but prompt shows 'stacks of dollar bills' → MISMATCH → rewrite to show empty theater stage\n"
        "- covers_text mentions 'patrimonio/net worth/millones' but prompt shows 'mansion' or 'luxury home' → MISMATCH → rewrite to show estate document or ledger with numbers\n"
        "- covers_text mentions 'vendía dulces en una tienda' but prompt shows 'cramped apartments' → MISMATCH → rewrite to show a candy shop\n"
        "- covers_text mentions a specific city/neighborhood but prompt shows generic luxury → MISMATCH → rewrite to show that specific place\n\n"
        "RULE: Ask yourself 'What specific noun does covers_text literally name?' — the prompt MUST show that noun.\n"
        "If the prompt matches covers_text literally → fixed=false, return unchanged.\n"
        "If the prompt drifts to the general theme or trigger template → fixed=true, rewrite to match covers_text.\n\n"
        "Always start rewritten prompts with 'Cinematic hyperrealistic photo of'. "
        "For all trigger types: end with 'cinematic lighting, no text, no letters, no faces visible, 16:9'. "
        "Return ONLY valid JSON array: [{\"seg_id\": N, \"ia_prompt\": \"...\", \"fixed\": true/false}]"
    )

    BATCH_SIZE = 6
    seg_map = {s["segment_id"]: s for s in segments}
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
    """Garantiza: sin overlaps, sin clips > 8s. Se ejecuta SIEMPRE antes de guardar."""
    if not segments:
        return segments

    # 1. Ordenar por start_seconds
    segments = sorted(segments, key=lambda s: s['start_seconds'])

    # 1b. Si el primer segmento empieza en < 20s, moverlo a segundo 0
    # (hooks con escena de apertura pueden arrancar después del segundo 5)
    if segments and segments[0]['start_seconds'] < 20:
        dur = segments[0]['end_seconds'] - segments[0]['start_seconds']
        segments[0]['start_seconds'] = 0
        segments[0]['end_seconds'] = round(dur, 3)
        segments[0]['duration'] = round(dur, 3)

    fixes = []

    # 2. Capear duración a MAX_CLIP_SECS
    for s in segments:
        duration = s['end_seconds'] - s['start_seconds']
        if duration > MAX_CLIP_SECS:
            old_end = s['end_seconds']
            s['end_seconds'] = round(s['start_seconds'] + MAX_CLIP_SECS, 3)
            s['duration'] = MAX_CLIP_SECS
            fixes.append(f"  ⚠ SEG {s['segment_id']}: duración {duration:.1f}s → {MAX_CLIP_SECS}s (end {old_end:.3f} → {s['end_seconds']:.3f})")
        else:
            s['duration'] = round(duration, 3)

    # 3. Eliminar overlaps
    for i in range(len(segments) - 1):
        cur  = segments[i]
        nxt  = segments[i + 1]
        # Overlap: recortar el segmento actual hasta justo antes del siguiente
        if cur['end_seconds'] > nxt['start_seconds']:
            old_end = cur['end_seconds']
            cur['end_seconds'] = round(nxt['start_seconds'] - 0.001, 3)
            cur['duration']    = round(cur['end_seconds'] - cur['start_seconds'], 3)
            if cur['duration'] < 1.0:
                cur['_delete'] = True
                fixes.append(f"  ⚠ OVERLAP SEG {cur['segment_id']} eliminado (duración resultante {cur['duration']:.2f}s < 1s)")
            else:
                fixes.append(f"  ⚠ OVERLAP SEG {cur['segment_id']}→{nxt['segment_id']}: end {old_end:.3f} → {cur['end_seconds']:.3f}")

    # Eliminar segmentos marcados para borrar (duración negativa tras overlap fix)
    segments = [s for s in segments if not s.get('_delete')]

    # 4. Extender segmentos con duración < MIN_DUR_SECS (zoompan mínimo viable = 3s)
    MIN_DUR_SECS = 3.0
    for i, s in enumerate(segments):
        duration = s['end_seconds'] - s['start_seconds']
        if duration < MIN_DUR_SECS:
            # Buscar cuánto podemos extender sin chocar con el siguiente segmento
            max_end = segments[i + 1]['start_seconds'] - 0.001 if i + 1 < len(segments) else s['start_seconds'] + MIN_DUR_SECS
            new_end = min(round(s['start_seconds'] + MIN_DUR_SECS, 3), max_end)
            if new_end - s['start_seconds'] >= 1.0:
                fixes.append(f"  ⚠ SEG {s['segment_id']}: duración {duration:.1f}s → {new_end - s['start_seconds']:.1f}s (extendido al mínimo 3s)")
                s['end_seconds'] = new_end
                s['duration']    = round(new_end - s['start_seconds'], 3)
            else:
                s['_delete'] = True
                fixes.append(f"  ⚠ SEG {s['segment_id']} eliminado (duración {duration:.1f}s < 3s y sin espacio para extender)")

    # Eliminar los que quedaron demasiado cortos incluso tras intento de extensión
    segments = [s for s in segments if not s.get('_delete')]

    if fixes:
        print(f"\n{'─'*62}")
        print(f"  sanitize_timeline: {len(fixes)} corrección(es) automática(s)")
        for f in fixes:
            print(f)
        print(f"{'─'*62}\n")
    else:
        print(f"\n  ✓ sanitize_timeline: sin overlaps, todas las duraciones ≤ {MAX_CLIP_SECS}s, gaps ≥ 5s")

    return segments


def fill_gaps(segments: list) -> list:
    """Cierra huecos entre segmentos:
    - Hueco ≤ 4s → extiende el segmento anterior
    - Hueco > 4s → inserta copia del segmento anterior con el hueco como duración (máx 8s)
    """
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
                new_seg['segment_id']   = 9000 + len(extra_segs)
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
    print(f"  TIMELINE PLANNER — {video_name.upper()}")
    print(f"  Canal: Caxando Famosos (riqueza)")
    print(f"{'═'*62}")

    entries = parse_srt(srt_file)
    if not entries:
        print("ERROR: SRT vacío"); sys.exit(1)

    # Solo los primeros 10 minutos del SRT
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

    # Normalizar keys que el LLM a veces devuelve distintas
    for s in all_segments:
        if 'start' in s and 'start_seconds' not in s:
            s['start_seconds'] = s.pop('start')
        if 'end' in s and 'end_seconds' not in s:
            s['end_seconds'] = s.pop('end')
        if 'end_seconds' not in s and 'duration' in s and 'start_seconds' in s:
            s['end_seconds'] = round(s['start_seconds'] + s['duration'], 3)

    all_segments = sanitize_timeline(all_segments)
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

    # Segundo pase post-redondeo: garantizar gap mínimo 5s entre segmentos
    MIN_GAP = 5
    for _i in range(1, len(_segs_sorted)):
        _prev = _segs_sorted[_i - 1]
        _cur  = _segs_sorted[_i]
        _gap  = _cur["start_seconds"] - _prev["end_seconds"]
        if _gap < MIN_GAP:
            _cur["start_seconds"] = _prev["end_seconds"] + MIN_GAP
            _cur["end_seconds"]   = _cur["start_seconds"] + _cur["duration"]
        # Eliminar si la corrección dejó el segmento fuera del audio (>600s)
    _segs_sorted = [_s for _s in _segs_sorted if _s["start_seconds"] < 600 and _s["duration"] >= 3]
    all_segments = _segs_sorted


    # ─── DEDUP DETERMINISTA: variante N para la N-ésima aparición del trigger ─
    # IMPORTANTE: debe correr ANTES de auto_fix_prompts para que el validador
    # pueda corregir cualquier variante hardcodeada que no coincida con el audio
    RIQUEZA_VARIANTS = {
        "money": [
            ("Billetes de peso esparcidos sobre escritorio de madera",        "Cinematic hyperrealistic photo of peso bills scattered on a worn wooden desk, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Cartera de cuero gastada y vacía sobre mesa",                   "Cinematic hyperrealistic photo of empty worn leather wallet on a table, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Pila de facturas vencidas con sellos rojos",                    "Cinematic hyperrealistic photo of stack of overdue bills with red stamps on a desk, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Sumadora antigua junto a libro de contabilidad abierto",        "Cinematic hyperrealistic photo of old adding machine next to an open ledger book, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Monedas y billetes arrugados sobre superficie gastada",         "Cinematic hyperrealistic photo of coins and crumpled bills on a worn surface, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "property": [
            ("Fachada de mansión con jardín iluminado al atardecer",          "Cinematic hyperrealistic photo of mansion facade with illuminated garden at dusk, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Piscina de lujo vacía al amanecer con luz suave",               "Cinematic hyperrealistic photo of luxury pool at dawn with soft light, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Entrada de hacienda colonial con portón de hierro",             "Cinematic hyperrealistic photo of colonial hacienda entrance with iron gate, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Penthouse con vista panorámica nocturna de ciudad",             "Cinematic hyperrealistic photo of penthouse with panoramic night city view, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Rancho con caballos pastando en potrero al amanecer",           "Cinematic hyperrealistic photo of ranch with horses grazing at dawn, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        # "place" eliminado — Gemini debe generar el lugar EXACTO según el audio
        # (antes era siempre CDMX hardcodeado, incorrecto para personajes que viven fuera de México)
        "poverty": [
            ("Cocina humilde con mesa de madera y luz tenue",                 "Cinematic hyperrealistic photo of humble kitchen with bare wooden table and single light, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Zapatos gastados junto a cama simple en cuarto pequeño",        "Cinematic hyperrealistic photo of worn shoes beside a simple bed in a small room, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Callejón angosto en barrio pobre mexicano al anochecer",        "Cinematic hyperrealistic photo of narrow alley in a poor Mexican neighborhood at dusk, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Plato de hojalata vacío sobre mesa de madera",                  "Cinematic hyperrealistic photo of empty tin plate on a wooden table, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Cortina vieja rota ondeando en ventana de casa humilde",        "Cinematic hyperrealistic photo of old torn curtain blowing in a window of a humble home, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "romance": [
            ("Silueta de mujer de espaldas en habitación tenue",              "Cinematic hyperrealistic photo of silhouette of a woman from behind in a dimly lit room, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Dos copas de vino en mesa con vela, sin personas",              "Cinematic hyperrealistic photo of two wine glasses on a candlelit table, no people, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Anillos de boda sobre superficie de madera",                    "Cinematic hyperrealistic photo of wedding rings on a wooden surface, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Carta de amor escrita a mano con pluma al lado",                "Cinematic hyperrealistic photo of love letter handwritten on paper with pen beside it, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Ramo de flores marchitas sobre alféizar de ventana",            "Cinematic hyperrealistic photo of bouquet of wilted flowers on a windowsill, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "document": [
            ("Carpeta de expediente judicial con sello de goma",              "Cinematic hyperrealistic photo of worn legal file folder on a desk with rubber stamp, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Mazo de juez sobre mesa de sala de audiencias",                 "Cinematic hyperrealistic photo of judge's wooden gavel on a courtroom table, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Orden de arresto con sello oficial sobre escritorio",           "Cinematic hyperrealistic photo of arrest warrant with official wax seal on a desk, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Esposas sobre escritorio de madera junto a papeles",            "Cinematic hyperrealistic photo of handcuffs resting on a wooden desk next to papers, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Máquina de escribir antigua con papel legal a medias",          "Cinematic hyperrealistic photo of old typewriter with legal paper half-typed in dim office, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "press": [
            ("Portada de periódico vintage en prensa de imprimir",            "Cinematic hyperrealistic photo of vintage newspaper front page on a printing press, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Paparazzi con cámaras en entrada de evento",                    "Cinematic hyperrealistic photo of paparazzi photographers with cameras at an event entrance, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Pila de revistas antiguas en español sobre mesa",               "Cinematic hyperrealistic photo of stack of old Spanish-language magazines on a table, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Redacción con máquinas de escribir y papeles sueltos",          "Cinematic hyperrealistic photo of newsroom with old typewriters and scattered papers, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Puesto de periódicos con portadas visibles al exterior",        "Cinematic hyperrealistic photo of newspaper stand with headlines visible from outside, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "interior": [
            ("Habitación de hotel tenuemente iluminada con lámpara",          "Cinematic hyperrealistic photo of dimly lit hotel room with single lamp on nightstand, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Oficina vacía con escritorio bajo luz fluorescente",            "Cinematic hyperrealistic photo of empty office with desk and papers under fluorescent light, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Pasillo de backstage con vestuario colgando",                   "Cinematic hyperrealistic photo of backstage corridor with hanging costumes, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Sala de apartamento escaso con una sola silla",                 "Cinematic hyperrealistic photo of sparse apartment living room with one chair, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Pasillo oscuro con puertas cerradas a cada lado",               "Cinematic hyperrealistic photo of dark hallway with closed doors on each side, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
        "funeral": [
            ("Ataúd cerrado en capilla oscura con flores blancas",            "Cinematic hyperrealistic photo of closed coffin in a dim chapel with white flowers, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Cementerio al atardecer con lápidas en penumbra",               "Cinematic hyperrealistic photo of cemetery at dusk with tombstones in dim light, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Dolientes de negro alrededor de tumba abierta",                 "Cinematic hyperrealistic photo of mourners in black around an open grave, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Flores marchitas sobre lápida de piedra gris",                  "Cinematic hyperrealistic photo of wilted flowers on a gray stone gravestone, cinematic lighting, no text, no letters, no faces visible, 16:9"),
            ("Velas encendidas frente a altar de duelo en casa",              "Cinematic hyperrealistic photo of lit candles in front of a home mourning altar, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ],
    }

    trigger_count: dict = {}
    dedup_fixed = 0
    for seg in all_segments:
        ttype = seg.get("trigger_type", "").lower()
        variants = RIQUEZA_VARIANTS.get(ttype)
        if not variants:
            continue
        n = trigger_count.get(ttype, 0)
        trigger_count[ttype] = n + 1
        if n == 0:
            continue  # primera aparición: conservar prompt de Gemini
        v_es, v_en = variants[(n - 1) % len(variants)]
        seg["ia_prompt"] = v_en
        seg["scene_description_es"] = v_es
        dedup_fixed += 1

    if dedup_fixed:
        print(f"  🔁 Dedup: {dedup_fixed} prompts variados (trigger repetido)")
    else:
        print(f"  ✓ Dedup: sin prompts duplicados")
    # ─────────────────────────────────────────────────────────────────────────

    # ─── SEGUNDO PASE: auto-corrección de prompts desalineados ───────────────
    # Corre DESPUÉS del dedup para poder corregir variantes hardcodeadas que
    # no coincidan con el audio real del segmento
    print("\n  Verificando coherencia prompt ↔ audio (segundo pase LLM)...")
    all_segments = auto_fix_prompts(all_segments, api_key, srt_entries=entries)
    # ─────────────────────────────────────────────────────────────────────────

    # ─── FILTRO VALID_TRIGGERS ────────────────────────────────────────────────
    VALID_TRIGGERS = {
        "money", "property", "place", "possessions",
        "poverty", "romance", "funeral", "illness",
        "hospital", "press", "cinema", "radio", "concert", "accident",
        "document", "interior"
    }
    before = len(all_segments)
    all_segments = [s for s in all_segments if s.get("trigger_type", "").lower() in VALID_TRIGGERS]
    dropped = before - len(all_segments)
    if dropped:
        print(f"  ⚠ {dropped} segmento(s) eliminados por trigger inválido")


    # ── GARANTÍA: primer segmento siempre arranca en 0 ──────────────────────
    # sanitize_timeline() ya aplica esta regla, pero el filtro VALID_TRIGGERS
    # puede eliminar ese segmento inicial dejando el siguiente > 0s.
    if all_segments:
        all_segments_sorted = sorted(all_segments, key=lambda s: s["start_seconds"])
        if all_segments_sorted[0]["start_seconds"] > 0:
            first = all_segments_sorted[0]
            old_start = first["start_seconds"]
            first["start_seconds"] = 0
            first["duration"] = min(first["end_seconds"] - 0, MAX_CLIP_SECS)
            first["end_seconds"] = first["duration"]
            print(f"  ℹ Primer segmento movido de {old_start}s → 0s (gap inicial corregido)")
        all_segments = all_segments_sorted
    # ─────────────────────────────────────────────────────────────────────────

    # ─── VERIFICACIÓN DE COHERENCIA AUDIO ↔ PROMPT ───────────────────────────
    # Regla: el prompt NO debe mostrar lujo cuando el audio habla de humildad,
    # pobreza, familia sin recursos, o la celebridad como sujeto pasivo.
    # Se detectan con palabras clave en covers_text / scene_description_es.
    HUMILDAD_KW = [
        "no tenía", "sin recursos", "pobreza", "humilde", "pobre", "miseria",
        "escaso", "austero", "economía austera", "camión", "autobús",
        "fiestas del pueblo", "verbenas", "fiesta patronal", "rancho ajeno",
        "trabajo duro", "campo", "labranza", "ordeñar", "milpa", "cortaba",
        "jornalero", "peón", "sin dinero", "sin lujo",
    ]
    LUJO_KW = [
        "mansion", "hacienda", "luxury", "champagne", "glamorous", "gilded",
        "lavish", "opulent", "crystal", "velvet", "gold", "penthouse",
        "ferrari", "rolls", "lamborghini", "yacht", "jet", "limo",
    ]
    alertas = []
    for s in all_segments:
        texto = (s.get("covers_text", "") + " " + s.get("scene_description_es", "")).lower()
        prompt = s.get("ia_prompt", "").lower()
        if any(kw in texto for kw in HUMILDAD_KW) and any(kw in prompt for kw in LUJO_KW):
            alertas.append(
                f"  ⚠ SEG {s['segment_id']:02d} [{int(s['start_seconds']//60)}:{int(s['start_seconds']%60):02d}]"
                f" — audio habla de HUMILDAD pero prompt muestra LUJO\n"
                f"    Audio   : {s.get('covers_text','')[:100]}\n"
                f"    Prompt  : {s.get('ia_prompt','')[:100]}"
            )
    if alertas:
        print("\n  ┌─ ALERTA COHERENCIA AUDIO ↔ PROMPT (" + str(len(alertas)) + " segmento(s)) ─────────────────")
        for a in alertas:
            print(a)
        print("  └─ Corregir ia_prompt y scene_description_es antes de lanzar el harvester\n")
    # ─────────────────────────────────────────────────────────────────────────

    # ⛔ VALIDACIÓN DURA: ningún segmento puede tener ia_prompt vacío
    empty_segs = [s['segment_id'] for s in all_segments if not str(s.get('ia_prompt', '')).strip()]
    if empty_segs:
        print(f"\n  ⛔ ERROR FATAL: {len(empty_segs)} segmento(s) sin ia_prompt: {empty_segs}")
        print(f"  timeline.json NO fue escrito — corregir prompts antes de continuar")
        print(f"  Tip: revisar el log de auto_fix_prompts y agregar prompt manualmente en el JSON")
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
        icon = {"pexels": "🎬", "pixabay": "🎬", "ia_luxury": "🤖", "brave_search": "🔍"}.get(src, "❓")
        print(f"    {icon} {src:<20} {count:3d} segmentos ({count/len(all_segments)*100:.0f}%)")

    print(f"\n  ⚠ Revisar prompts vs audio antes de abrir la UI de aprobación.")
    print(f"  Puerto asignado: {_approval_port}")
    print(f"  Cuando estén limpios, lanzar:")
    print(f"  python3 harvester_timeline.py {sys.argv[1]} --canal riqueza --port {_approval_port}")

if __name__ == "__main__":
    main()
