#!/usr/bin/env python3
"""
generar_timeline_arco3.py — Planificador visual para guiones Arco 3 "Detrás de Cámaras".

Lee el SRT del video → Gemini analiza cada segmento → asigna fuente de imagen
→ genera 05-montaje/timeline.json anclado al audio.

Triggers válidos (11):
  ESCENA_ICONICA · CASTING · CONFLICTO · ACCIDENTE_SET · RODAJE
  SECRETO_OSCURO · DECISION_PRODUCCION · SET_LOCACION · VIDA_DESPUES
  FINAL_ALTERNATIVO · VESTUARIO_OBJETO

Regla de estilo visual: el prompt se adapta al AÑO de la producción cubierta.
  1950–1969 → vintage 35mm Technicolor
  1970–1989 → 1970s/80s film grain, warm analog
  1990–2005 → late 90s/2000s photorealistic warm TV lighting
  2006+     → modern cinematic photorealistic

Uso:
    python3 generar_timeline_arco3.py riqueza/embrujadas/
    python3 generar_timeline_arco3.py riqueza/batman_1966/
"""

import sys, re, json, pathlib, time, os
import urllib.request, urllib.error

BATCH_SECONDS   = 90
MAX_SEG_SECS    = 8.0
MIN_SEG_SECS    = 2.0

HOME        = pathlib.Path.home()
KEY_FILE    = HOME / ".openrouter_key"
OR_MODEL    = "google/gemini-2.5-flash-lite"
OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a Visual Timeline Planner for a Spanish-language YouTube channel that reveals behind-the-scenes secrets of iconic movies and TV shows.

CORE VISUAL PHILOSOPHY — READ THIS FIRST:
The video mixes real YouTube footage of the actual movie/show with AI-generated image inserts. The AI images MUST blend seamlessly with that footage. This means:
- Every prompt must look like it BELONGS IN THE WORLD of that specific production
- Generate images that feel like frames from the movie/show itself, or atmosphere shots that match its visual world
- NEVER generate generic "production industry" images (empty dressing rooms, torn contracts, casting tables) — these look completely out of place next to real footage of Embrujadas, Batman, or Grease
- Ask yourself: "If someone sees this image next to a real clip of [SHOW], will it feel like it belongs?" If NO → redesign the prompt

⛔ NARRATION-FIRST RULE — ABSOLUTE:
The ia_prompt scene content MUST come EXCLUSIVELY from what the narration text LITERALLY says at that timestamp. NEVER use your background knowledge about the show's settings, props, or visual world to decide what to show.
- If the narration says "la CBS encendió los televisores" → show a TV broadcast scene, NOT San Francisco
- If the narration says "Shannen Doherty dejó la serie" → show a press/media environment, NOT the Book of Shadows
- The show title is ONLY used for: (1) the "Scene from..." prefix, and (2) the era/style modifier
- NEVER let show knowledge determine WHAT scene to show — only the narration text does that

ERA RULE — CRITICAL: Every prompt must match the visual era of the PRODUCTION being discussed (NOT the current year):
- 1950–1969 → "vintage 35mm photograph, warm Technicolor colors, period-accurate, slightly faded, 16:9"
- 1970–1989 → "1970s/1980s analog film grain, warm amber tones, period-accurate fashion and locations, 16:9"
- 1990–2005 → "late 1990s/early 2000s photorealistic, warm practical TV lighting, period-accurate wardrobe and sets, 16:9"
- 2006+     → "modern cinematic, photorealistic, sharp digital photography, 16:9"

TRIGGER TYPES — insert ONLY when one of these is clearly present:

🔴 MANDATORY OPENING PLACE RULE: If the VERY FIRST ENTRY of the FIRST BATCH LITERALLY MENTIONS a city or geographic location name IN THE TEXT — you MUST generate a PLACE insert at start_seconds=0. ONLY fire if the city/location is explicitly written in the SRT text. NEVER infer a location from general knowledge about the show. If the first entry talks about a date, a TV network, or anything other than a named place → DO NOT generate an opening insert.

- MONEY: Dinero, salarios, contratos, negocios, presupuesto de producción
  → Visual: objetos de dinero/contrato DENTRO del mundo visual de la producción — un contrato sobre la mesa victoriana de Embrujadas, una maleta de dinero en el estilo de época del show, la mansión del actor con la paleta del show. NUNCA una mesa de oficina genérica moderna.

- PROPERTY: Propiedades, casas, mansiones, fincas de actores o relacionadas con la producción
  → Visual: arquitectura o espacios que se PAREZCAN al mundo del show — una mansión de época que evoca el estilo visual de la producción, una casa filmada con la paleta del show.

- PLACE: Ciudad, país, locación geográfica real mencionada
  → Visual: ese lugar tal como se vería EN la producción — Los Ángeles de los años 90 con la paleta del show, no foto de stock moderna.

- POSSESSIONS: Objetos personales icónicos, propiedades físicas de un actor o personaje
  → Visual: el objeto en el mundo del show — un vestido colgado en un camerino de la época, un auto de la era del show, un objeto personal en el set.

- POVERTY: Pobreza, inicios humildes, época antes del estrellato
  → Visual: ambiente modesto pero con la paleta de color de la era del show — una habitación sencilla de los años en que se filmó, ropa simple en un ambiente de época.

- FUNERAL: Muerte de un miembro del elenco o equipo, funeral, pérdida
  → Visual: el mundo del show en atmósfera de pérdida — la sala victoriana vacía, una silla sin ocupar, velas apagadas. El mundo de la serie pero silencioso y solo.

- ILLNESS: Enfermedad, diagnóstico, condición médica de un actor
  → Visual: atmósfera silenciosa y vulnerable en el mundo del show — un rincón vacío del set, un objeto del personaje dejado solo, luz tenue en el ambiente de la producción.

- HOSPITAL: Hospitalización, urgencias, rehabilitación
  → Visual: nunca un hospital genérico — anclar al mundo del show: la habitación del personaje en el set pero con luz de emergencia, una camilla en el estilo de época de la producción.

- PRESS: ONLY when the narration EXPLICITLY mentions a press appearance, interview, magazine cover, red carpet, award ceremony, or media coverage — words like "entrevista", "portada de revista", "alfombra roja", "premios", "declaró en medios", "cobertura", "paparazzi". DO NOT fire for general drama, conflicts, behind-the-scenes tensions, or character descriptions.
  → Visual: el ambiente de prensa de la ERA del show — una alfombra roja de los años 90 si el show es de los 90, un set de televisión vintage, una sala de prensa de época.

- CINEMA: Estreno, premiere, proyección, premios relacionados con la producción
  → Visual: teatro o sala de cine de la época del show con la paleta visual correspondiente.

- RADIO: Entrevista radial, actuación en radio, mención en radio
  → Visual: estudio de radio de la era del show, micrófono vintage si corresponde.

- CONCERT: Actuación musical en vivo, concierto relacionado con un actor o la banda sonora
  → Visual: escenario o venue del estilo de la época del show.

- ACCIDENT: Accidente de tráfico, lesión fuera del set, emergencia no relacionada con el rodaje
  → Visual: ambiente de la época del show que evoque el accidente — una calle de los años correspondientes con la paleta del show, un objeto dejado en el set.

⛔ DO NOT insert on: general plot descriptions, ratings numbers, general character descriptions, episode recaps, transition phrases, behind-the-scenes drama without specific trigger words, general narration about actors without a concrete event.

⚠️ DENSITY RULE: Maximum 1 insert per 20 seconds of audio. If a batch is 90 seconds, generate at most 4–5 inserts. Be selective — only the STRONGEST triggers. It is better to generate too few than too many.

⚠️ ABSOLUTE RULES:
- NEVER generate: celebrity faces, identifiable people, generic modern images unrelated to the show's visual world, comic/cartoon/illustration/animated/CGI style
- ALWAYS: photorealistic, production's visual world, era-accurate
- Every image must look like it BELONGS next to a real clip of the show — if it doesn't, redesign the prompt

VISUAL OUTPUT RULES:
- Source: always "flow"
- ia_prompt: English, MUST start with "Scene from the [movie/TV show] [EXACT TITLE] ([YEAR]), " — then describe ONLY what the narration literally mentions
  The scene description comes FROM the narration text. The show title sets the style. These are two separate things.
  Example (narration says "la CBS encendió los televisores"): "Scene from the TV show Charmed (1998), a vintage television set showing a broadcast network logo, warm late 1990s practical lighting, late 1990s photorealistic, cinematic lighting, no text, no letters, no faces visible, 16:9"
  Example (narration says "fue despedida del set"): "Scene from the movie Grease (1978), an empty film set with studio lights and equipment, 1970s analog film grain, warm amber tones, cinematic lighting, no text, no letters, no faces visible, 16:9"
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
      "scene_description_es": "Descripción en español de lo que se ve",
      "ia_prompt": "Scene from the [movie/TV show] [TITLE] ([YEAR]), ..., [era modifier], cinematic lighting, no text, no letters, no faces visible, 16:9",
      "covers_text": "texto exacto del SRT que disparó este insert",
      "trigger_type": "money|property|place|possessions|poverty|funeral|illness|hospital|press|cinema|radio|concert|accident"
    }
  ]
}"""

USER_TEMPLATE = """BATCH {batch_number} of {total_batches}
TIME WINDOW: {batch_start}s → {batch_end}s
PRODUCTION/VIDEO: {video_name}
PROMPT PREFIX REQUIRED: Every ia_prompt MUST start exactly with: "Scene from the {prod_type} {video_name} ({year_hint}), "

SRT ENTRIES (Spanish narration, each with exact timestamps):
{sentences_json}

RULES:
1. Use EXACT timestamps — never invent seconds
2. Group 2–4 consecutive SRT entries into ONE insert
3. start_seconds = timestamp "t" of the SPECIFIC entry that contains the trigger word. end_seconds = start_seconds + duration (max 8s).
4. Generate ONLY inserts where a valid trigger is present. If a batch has no trigger → 0 inserts.
5. CRITICAL — PRODUCTION TITLE ANCHOR: Every ia_prompt MUST start with "Scene from the [movie/TV show] [EXACT TITLE] ([YEAR]), " then describe ONLY what the narration text literally says.
   ✅ CORRECT (narration says "CBS encendió los televisores"): "Scene from the TV show Charmed (1998), a vintage television set broadcasting a network premiere, late 1990s photorealistic, warm practical TV lighting, cinematic lighting, no text, no letters, no faces visible, 16:9"
   ❌ WRONG (narration says CBS but prompt invents "Book of Shadows"): "Scene from the TV show Charmed (1998), the Halliwell manor Victorian living room with the Book of Shadows open on the table..." (narration never mentioned this)
   ❌ WRONG: any prompt without "Scene from [TITLE] ([YEAR])" at the start
   ⛔ NEVER USE show background knowledge to decide the scene. The NARRATION TEXT is the ONLY source of scene content.
6. ALWAYS apply ERA modifier matching the production year described in narration.
7. NEVER add faces, people, celebrities, or recognizable individuals to any prompt.
8. NEVER use words: comic, cartoon, illustration, animated, CGI, graphic novel, painted.

JSON only."""


# ── helpers ────────────────────────────────────────────────────────────────────

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


def call_openrouter(api_key, video_name, batch, batch_num, total_batches, retries=3, prod_type="TV show", year_hint="1998"):
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
        prod_type=prod_type,
        year_hint=year_hint,
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


def auto_fix_prompts(segments, api_key):
    """Segundo pase LLM: verifica que cada ia_prompt ilustre exactamente el covers_text
    y que no tenga estilo de cómic/ilustración. Procesa en lotes de 6."""
    if not segments:
        return segments

    system_msg = (
        "You are a strict prompt quality validator for a cinematic YouTube behind-the-scenes channel. "
        "For each segment you receive: covers_text (exact audio line), trigger_type, and current_prompt.\n\n"
        "YOUR JOB: verify TWO things:\n"
        "1. current_prompt illustrates the SPECIFIC object/place/atmosphere in covers_text — not the general topic\n"
        "2. current_prompt does NOT use comic, illustration, cartoon, animated, CGI, graphic novel style\n\n"
        "MISMATCH EXAMPLES (mark fixed=true and rewrite):\n"
        "- covers_text mentions 'pantalones de cuero' but prompt shows a high school hallway → MISMATCH\n"
        "- prompt contains 'comic book style' or 'illustrated' or 'cartoon' → ALWAYS fix\n"
        "- covers_text mentions 'piloto no emitido' but prompt shows a luxury set → MISMATCH\n"
        "- covers_text mentions a specific filming location but prompt is generic → MISMATCH\n\n"
        "RULE: The prompt must be photorealistic. MUST start with 'Scene from the [movie/TV show] [EXACT TITLE] ([YEAR]), '. "
        "Always end with 'cinematic lighting, no text, no letters, no faces visible, 16:9'. "
        "Apply correct era modifier from production year context. "
        "If the prompt starts with 'Cinematic hyperrealistic photo of' instead of 'Scene from...' → mark fixed=true and rewrite with the correct prefix. "
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

        user_msg = "Validate and fix these segments:\n" + json.dumps(items, ensure_ascii=False)

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
            OR_ENDPOINT,
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
        print(f"  ✓ auto_fix_prompts: todos los prompts correctos")
    return segments


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
        if duration > MAX_SEG_SECS:
            old_end = s['end_seconds']
            s['end_seconds'] = round(s['start_seconds'] + MAX_SEG_SECS, 3)
            s['duration'] = MAX_SEG_SECS
            fixes.append(f"  ⚠ SEG {s['segment_id']}: duración {duration:.1f}s → {MAX_SEG_SECS}s")
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
                fixes.append(f"  ⚠ SEG {s['segment_id']}: extendido a {MIN_DUR_SECS}s mínimo")
                s['end_seconds'] = new_end
                s['duration']    = round(new_end - s['start_seconds'], 3)
            else:
                s['_delete'] = True
                fixes.append(f"  ⚠ SEG {s['segment_id']} eliminado (muy corto)")

    segments = [s for s in segments if not s.get('_delete')]

    if fixes:
        print(f"\n{'─'*62}")
        print(f"  sanitize_timeline: {len(fixes)} corrección(es)")
        for f in fixes:
            print(f)
        print(f"{'─'*62}\n")
    else:
        print(f"\n  ✓ sanitize_timeline: sin overlaps, duraciones ≤ {MAX_SEG_SECS}s")

    return segments


# ── Variantes dedup por trigger ─────────────────────────────────────────────────
# Para cuando el mismo trigger aparece varias veces: rotar variantes visuales.

ARCO3_VARIANTS = {
    "casting": [
        ("Silla vacía bajo foco de audición en sala oscura",
         "Cinematic hyperrealistic photo of empty wooden chair under a single spotlight in a dark audition room, late 1990s/2000s photorealistic, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Mesa de casting con papeles y vasos de agua vacíos",
         "Cinematic hyperrealistic photo of casting table with script sides and empty water glasses, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Tablón de anuncios con convocatoria de casting pegada",
         "Cinematic hyperrealistic photo of studio bulletin board with a casting call notice pinned to it, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Silla de director vacía en set apagado",
         "Cinematic hyperrealistic photo of empty director's chair on a dark studio sound stage, cinematic lighting, no text, no letters, no faces visible, 16:9"),
    ],
    "conflicto": [
        ("Camarín vacío con espejo roto y maquillaje tirado",
         "Cinematic hyperrealistic photo of empty dressing room with cracked mirror and scattered makeup, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Dos sillas de espaldas en pasillo de estudio vacío",
         "Cinematic hyperrealistic photo of two chairs facing opposite directions in an empty studio hallway, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Contrato rasgado sobre escritorio de producción",
         "Cinematic hyperrealistic photo of torn contract on a production office desk, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Puerta de camarín cerrada con nombre tachado",
         "Cinematic hyperrealistic photo of closed dressing room door with name tag removed, cinematic lighting, no text, no letters, no faces visible, 16:9"),
    ],
    "accidente_set": [
        ("Botiquín de primeros auxilios abierto en backstage",
         "Cinematic hyperrealistic photo of open first aid kit in a backstage area, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Entrada de urgencias de hospital de noche",
         "Cinematic hyperrealistic photo of hospital emergency entrance at night with lights glowing, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Camilla vacía en pasillo de set bajo luz fluorescente",
         "Cinematic hyperrealistic photo of empty medical stretcher in a studio hallway under fluorescent light, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Frasco de pastillas sobre mesa de camerino",
         "Cinematic hyperrealistic photo of prescription pill bottle on a dressing room vanity, cinematic lighting, no text, no letters, no faces visible, 16:9"),
    ],
    "rodaje": [
        ("Set iluminado vacío con cámara en trípode",
         "Cinematic hyperrealistic photo of empty lit film set with camera on a tripod, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Claqueta de filmación sobre silla de director",
         "Cinematic hyperrealistic photo of film clapperboard resting on a director's chair on set, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Estudio de sonido vacío con reflectores apagados",
         "Cinematic hyperrealistic photo of empty sound stage with lights rigged above and cables on the floor, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Monitor de producción con imagen congelada en set",
         "Cinematic hyperrealistic photo of production monitor showing a frozen frame on a film set, cinematic lighting, no text, no letters, no faces visible, 16:9"),
    ],
    "secreto_oscuro": [
        ("Espejo de camerino con luz de vanity tenue",
         "Cinematic hyperrealistic photo of dressing room vanity mirror with warm bulb lights, late 1990s warm tone, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Pasillo oscuro de estudio con luz al fondo",
         "Cinematic hyperrealistic photo of dark studio corridor with a single light at the far end, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Manos sosteniendo carta doblada sobre mesa",
         "Cinematic hyperrealistic photo of hands holding a folded letter on a table, close-up, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Ventana de tráiler de producción al anochecer",
         "Cinematic hyperrealistic photo of production trailer window at dusk with warm interior light, cinematic lighting, no text, no letters, no faces visible, 16:9"),
    ],
    "decision_produccion": [
        ("Mesa de sala de guionistas con páginas esparcidas",
         "Cinematic hyperrealistic photo of writers' room table with scattered script pages and coffee cups, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Guión con líneas tachadas a mano en rojo",
         "Cinematic hyperrealistic photo of a script with lines crossed out in red pen, close-up, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Pizarrón de sala de producción con post-its",
         "Cinematic hyperrealistic photo of production whiteboard covered in sticky notes in a darkened room, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Teléfono de baquelita en escritorio de ejecutivo",
         "Cinematic hyperrealistic photo of bakelite telephone on an executive's cluttered desk, period-accurate, cinematic lighting, no text, no letters, no faces visible, 16:9"),
    ],
    "set_locacion": [
        ("Exterior de casa victoriana al atardecer vacía",
         "Cinematic hyperrealistic photo of empty Victorian house exterior at dusk with warm window lights, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Calle de backlot de estudio vacía al anochecer",
         "Cinematic hyperrealistic photo of empty studio backlot street at dusk with period storefronts, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Gimnasio de secundaria vacío con sillas plegables",
         "Cinematic hyperrealistic photo of empty high school gymnasium with folding chairs stacked along the walls, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Platillo de filmación abandonado entre temporadas",
         "Cinematic hyperrealistic photo of empty TV sound stage between seasons, equipment covered with tarps, cinematic lighting, no text, no letters, no faces visible, 16:9"),
    ],
    "final_alternativo": [
        ("Sala de edición con rollos de película y moviola",
         "Cinematic hyperrealistic photo of editing room with film reels and a moviola editing machine, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Sala de proyección vacía con asiento único bajo luz",
         "Cinematic hyperrealistic photo of empty screening room with a single seat lit from above, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Papelera llena de páginas de guión arrugadas",
         "Cinematic hyperrealistic photo of wastebasket overflowing with crumpled script pages, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Caja de archivo con etiqueta 'no emitido'",
         "Cinematic hyperrealistic photo of archival film canister box on a shelf in a storage room, cinematic lighting, no text, no letters, no faces visible, 16:9"),
    ],
    "vestuario_objeto": [
        ("Percha con traje de época bajo luz de camerino",
         "Cinematic hyperrealistic photo of period costume on a hanger under warm dressing room lighting, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Rack de vestuario con ropa de época en backstage",
         "Cinematic hyperrealistic photo of costume rack with period-accurate wardrobe in a backstage area, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Prop icónico sobre mesa de propiedades del set",
         "Cinematic hyperrealistic photo of iconic prop resting on a prop department table under a work lamp, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Caja de maquillaje de época sobre tocador de set",
         "Cinematic hyperrealistic photo of vintage makeup kit open on a set dressing table, period-accurate, cinematic lighting, no text, no letters, no faces visible, 16:9"),
    ],
    "vida_despues": [
        ("Teatro vacío al final de la función con luces bajas",
         "Cinematic hyperrealistic photo of empty theater at the end of a show with house lights dimming, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Flores marchitas sobre silla de camarín vacío",
         "Cinematic hyperrealistic photo of wilted flowers left on an empty dressing room chair, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Cartel de película desvaneciéndose en pared",
         "Cinematic hyperrealistic photo of a faded movie poster peeling from a wall in an empty corridor, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Memorial con velas y flores en calle tranquila",
         "Cinematic hyperrealistic photo of street memorial with candles and flowers on a quiet sidewalk, cinematic lighting, no text, no letters, no faces visible, 16:9"),
    ],
    "escena_iconica": [
        ("Set vacío preparado para escena dramática con focos",
         "Cinematic hyperrealistic photo of empty film set dressed for a dramatic scene with theatrical lighting, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Escenario de TV vacío con decorado de época iluminado",
         "Cinematic hyperrealistic photo of empty TV sound stage with period-accurate set dressing lit for filming, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Exterior de locación nocturna con equipo de cámara",
         "Cinematic hyperrealistic photo of location shoot exterior at night with camera equipment visible and empty set, cinematic lighting, no text, no letters, no faces visible, 16:9"),
        ("Primer plano de claqueta antes de toma importante",
         "Cinematic hyperrealistic photo of clapperboard close-up just before an important take on a dimly lit set, cinematic lighting, no text, no letters, no faces visible, 16:9"),
    ],
}

def detect_actors_hyperframes(entries: list, api_key: str, seg_counter: int) -> list:
    """
    Detecta nombres de actores/personas reales en el SRT.
    Por cada actor encontrado, inserta un segmento source=hyperframe en su primera mención.
    Retorna lista de segmentos HyperFrame nuevos.
    """
    full_text = " ".join(e["text"] for e in entries)

    prompt = f"""Lee este texto en español y extrae TODOS los nombres de actores, actrices o personas reales mencionados.

TEXTO:
{full_text}

Responde SOLO con un JSON array de objetos, cada uno con:
- "name": nombre completo de la persona
- "first_mention": texto EXACTO (máximo 8 palabras) de la frase donde aparece por PRIMERA vez su nombre

Ejemplo: [{{"name": "Shannen Doherty", "first_mention": "Shannen Doherty interpretaba a Prue Halliwell"}}]

Si no hay personas reales mencionadas, responde: []
Responde SOLO con el JSON, sin explicaciones."""

    try:
        import urllib.request as _req, urllib.error as _uerr
        payload = json.dumps({
            "model": OR_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 1000,
        }).encode()
        req = _req.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST"
        )
        with _req.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read())
        raw = resp["choices"][0]["message"]["content"].strip()
        # Limpiar markdown si viene
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
        actors = json.loads(raw)
    except Exception as e:
        print(f"  ⚠ detect_actors error: {e}")
        return []

    if not actors:
        return []

    hyperframe_segs = []
    seen_names = set()

    for actor in actors:
        name = actor.get("name", "").strip()
        mention = actor.get("first_mention", "").strip()
        if not name or not mention or name in seen_names:
            continue
        seen_names.add(name)

        # Buscar primera entrada del SRT que contenga parte del nombre o la frase
        name_parts = name.split()
        target_entry = None
        for entry in entries:
            text_lower = entry["text"].lower()
            if any(p.lower() in text_lower for p in name_parts if len(p) > 3):
                target_entry = entry
                break

        if not target_entry:
            continue

        t_start = int(round(target_entry["start"]))
        t_end   = t_start + 5  # 5 segundos para el HyperFrame

        hyperframe_segs.append({
            "segment_id":          seg_counter,
            "source":              "hyperframe",
            "start_seconds":       t_start,
            "end_seconds":         t_end,
            "duration":            5,
            "actor_name":          name,
            "actor_search_query":  f"{name} actress actor photo",
            "scene_description_es": f"Presentación: {name}",
            "ia_prompt":           f"[HYPERFRAME] {name}",
            "covers_text":         target_entry["text"],
            "trigger_type":        "actor",
        })
        seg_counter += 1
        print(f"    → HyperFrame: {name} @ {t_start}s")

    return hyperframe_segs


VALID_TRIGGERS = {
    "money", "property", "place", "possessions", "poverty",
    "funeral", "illness", "hospital", "press", "cinema", "radio",
    "concert", "accident"
}


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

    # Detectar año de producción del nombre o carpeta (ej. batman_1966 → 1966)
    year_match = re.search(r'(19\d{2}|20\d{2})', str(carpeta))
    year_hint  = year_match.group(1) if year_match else "1998"
    # Detectar si es película o serie (heurística: si el nombre tiene "pelicula"/"movie" es movie, sino TV show)
    is_movie   = any(k in str(carpeta).lower() for k in ["pelicula","movie","film","grease","batman"])
    prod_type  = "movie" if is_movie else "TV show"

    print(f"\n{'═'*62}")
    print(f"  TIMELINE PLANNER ARCO 3 — {video_name.upper()}")
    print(f"  Canal: Detrás de Cámaras")
    print(f"  Triggers: {', '.join(sorted(VALID_TRIGGERS))}")
    print(f"{'═'*62}")

    entries = parse_srt(srt_file)
    if not entries:
        print("ERROR: SRT vacío"); sys.exit(1)

    # Solo primeros 10 minutos
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
        segments = call_openrouter(api_key, video_name, batch, i, total_batches, prod_type=prod_type, year_hint=year_hint)
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

    # Normalizar keys
    for s in all_segments:
        if 'start' in s and 'start_seconds' not in s:
            s['start_seconds'] = s.pop('start')
        if 'end' in s and 'end_seconds' not in s:
            s['end_seconds'] = s.pop('end')
        if 'end_seconds' not in s and 'duration' in s and 'start_seconds' in s:
            s['end_seconds'] = round(s['start_seconds'] + s['duration'], 3)

    all_segments = sanitize_timeline(all_segments)

    # Redondear a enteros + cap 8s
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

    # ── Segundo pase: auto-corrección de prompts ──────────────────────────────
    print("\n  Verificando coherencia prompt ↔ audio (segundo pase LLM)...")
    all_segments = auto_fix_prompts(all_segments, api_key)

    # ── Filtro de triggers válidos (HyperFrame actor siempre pasa) ──────────
    before = len(all_segments)
    all_segments = [s for s in all_segments if (s.get("trigger_type") or "").lower() in VALID_TRIGGERS
                    or s.get("source") == "hyperframe"]
    dropped = before - len(all_segments)
    if dropped:
        print(f"  ⚠ {dropped} segmento(s) eliminados por trigger inválido")

    # ── Detección de actores → segmentos HyperFrame ──────────────────────────
    print("\n  Detectando nombres de actores para HyperFrames...")
    actor_segs = detect_actors_hyperframes(entries, api_key, segment_counter)
    if actor_segs:
        all_segments.extend(actor_segs)
        segment_counter += len(actor_segs)
        # Re-ordenar por tiempo
        all_segments = sorted(all_segments, key=lambda s: s["start_seconds"])
        # Empujar segmentos flow que se solapan con un HyperFrame:
        # el HyperFrame tiene prioridad — el flow se recorta para empezar DESPUÉS
        hf_windows = [(s["start_seconds"], s["end_seconds"])
                      for s in all_segments if s.get("source") == "hyperframe"]
        for seg in all_segments:
            if seg.get("source") == "hyperframe":
                continue
            for hf_start, hf_end in hf_windows:
                if seg["start_seconds"] < hf_end and seg["end_seconds"] > hf_start:
                    seg["start_seconds"] = hf_end
                    seg["duration"] = max(1, seg["end_seconds"] - seg["start_seconds"])
                    break
        # Re-ordenar tras ajuste
        all_segments = sorted(all_segments, key=lambda s: s["start_seconds"])
        # Re-numerar
        for idx, s in enumerate(all_segments, 1):
            s["segment_id"] = idx
        print(f"  ✓ {len(actor_segs)} segmento(s) HyperFrame de actores añadidos")
    else:
        print(f"  — Sin actores detectados")

    # ── Regla: mínimo 4s de gap entre segmentos flow consecutivos ─────────────
    # Si dos flow seguidos no tienen gap, recortamos el final del primero.
    MIN_GAP = 4
    gaps_fixed = 0
    sorted_segs = sorted(all_segments, key=lambda s: s["start_seconds"])
    for i in range(len(sorted_segs) - 1):
        a = sorted_segs[i]
        b = sorted_segs[i + 1]
        if b.get("source") == "hyperframe":
            continue  # HyperFrames tienen su propio gap
        gap = b["start_seconds"] - a["end_seconds"]
        if gap < MIN_GAP and a.get("source") != "hyperframe":
            new_end = b["start_seconds"] - MIN_GAP
            if new_end > a["start_seconds"] + 1:  # mantener mínimo 1s
                a["end_seconds"] = new_end
                a["duration"] = new_end - a["start_seconds"]
                gaps_fixed += 1
    if gaps_fixed:
        print(f"  ✓ Gap-fix: {gaps_fixed} segmento(s) recortados para forzar gap ≥{MIN_GAP}s")
    all_segments = sorted(all_segments, key=lambda s: s["start_seconds"])

    # ── Dedup: rotar variantes para triggers repetidos ────────────────────────
    trigger_count: dict = {}
    dedup_fixed = 0
    for seg in all_segments:
        if seg.get("source") == "hyperframe":
            continue  # HyperFrames no participan en dedup
        ttype = seg.get("trigger_type", "").lower()
        variants = ARCO3_VARIANTS.get(ttype)
        if not variants:
            continue
        n = trigger_count.get(ttype, 0)
        trigger_count[ttype] = n + 1
        if n == 0:
            continue  # primera aparición: conservar prompt de Gemini
        v_es, v_en = variants[(n - 1) % len(variants)]
        # inyectar título de producción al inicio del prompt de dedup
        prefix = f"Scene from the {prod_type} {video_name} ({year_hint}), "
        clean_en = v_en.replace("Cinematic hyperrealistic photo of ", "").replace("Cinematic hyperrealistic photo of", "")
        seg["ia_prompt"] = prefix + clean_en
        seg["scene_description_es"] = v_es
        dedup_fixed += 1

    if dedup_fixed:
        print(f"  🔁 Dedup: {dedup_fixed} prompts variados (trigger repetido)")
    else:
        print(f"  ✓ Dedup: sin prompts duplicados")

    # ── Validación: comic/illustration en prompts ─────────────────────────────
    BANNED_STYLE_KW = ["comic", "cartoon", "illustration", "illustrated", "animated",
                       "cgi", "graphic novel", "painted", "drawing", "sketch"]
    style_alerts = []
    for s in all_segments:
        prompt_lower = s.get("ia_prompt", "").lower()
        if any(kw in prompt_lower for kw in BANNED_STYLE_KW):
            style_alerts.append(
                f"  ⚠ SEG {s['segment_id']:02d} — prompt contiene estilo prohibido\n"
                f"    Prompt: {s.get('ia_prompt','')[:100]}"
            )
    if style_alerts:
        print("\n  ┌─ ALERTA ESTILO PROHIBIDO (" + str(len(style_alerts)) + " segmento(s)) ─────────────────")
        for a in style_alerts:
            print(a)
        print("  └─ Corregir ia_prompt antes del harvester — eliminar toda referencia a cómic/ilustración\n")

    # ── Validación: ia_prompt vacío ────────────────────────────────────────────
    empty_segs = [s['segment_id'] for s in all_segments
                  if not str(s.get('ia_prompt', '')).strip() and s.get("source") != "hyperframe"]
    if empty_segs:
        print(f"\n  ⛔ ERROR FATAL: {len(empty_segs)} segmento(s) sin ia_prompt: {empty_segs}")
        print(f"  timeline.json NO fue escrito")
        sys.exit(1)

    out_file.write_text(
        json.dumps({"visual_timeline": all_segments}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\n  ✓ timeline.json → {out_file}")
    print(f"  Total segmentos: {len(all_segments)}")

    triggers_used: dict = {}
    for s in all_segments:
        t = s.get('trigger_type', '?')
        triggers_used[t] = triggers_used.get(t, 0) + 1
    print(f"\n  Distribución de triggers:")
    for t, count in sorted(triggers_used.items(), key=lambda x: -x[1]):
        print(f"    • {t:<25} {count:3d} segmento(s)")

    print(f"\n  ⚠ Revisar prompts vs audio antes de abrir la UI de aprobación.")
    print(f"  Puerto asignado: {_approval_port}")
    print(f"  Cuando estén limpios, lanzar:")
    print(f"  python3 harvester_timeline.py {sys.argv[1]} --canal riqueza --port {_approval_port}")


if __name__ == "__main__":
    main()
