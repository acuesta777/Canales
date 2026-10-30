#!/usr/bin/env python3
"""
generar_timeline_secretos_mexicanos.py — Planificador visual para Secretos Mexicanos.

ENFOQUE:
  - Gemini lee CADA FRASE del SRT con contexto completo y decide si hay trigger o no
  - Las duraciones vienen 100% del SRT (Gemini no inventa segundos)
  - Frases sin trigger → YT_CLIP automáticamente
  - Segmentos YT agrupados en bloques de 5s para que los clips no se corten
  - CERO GAPS: cobertura total del audio
"""

import sys, re, json, pathlib, time, os, math
import urllib.request, urllib.error

MAX_CLIP_SECS = 8.0
YT_CLIP_DUR   = 5

HOME        = pathlib.Path.home()
KEY_FILE    = HOME / ".openrouter_key"
OR_MODEL    = "google/gemini-2.5-flash-lite"
OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

VALID_TRIGGERS = {"CIUDAD","PRENSA","DINERO","POBREZA","HOSPITAL","CINE","RADIO",
                  "CONCIERTO","ACCIDENTE","DOCUMENTO","INTERIOR","FUNERAL","ENFERMEDAD","ROMANCE"}

# ── Prompt principal ─────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a Visual Timeline Planner for a Spanish-language YouTube documentary channel called "Secretos Mexicanos".

YOUR JOB: Read each sentence from the narration and decide if it strongly and clearly evokes one of the 14 trigger types. If yes, assign the trigger and write an image prompt. If not, mark it as YT_CLIP.

🔴 MANDATORY OPENING PLACE RULE: If the VERY FIRST ENTRY of the FIRST BATCH contains a city or location name — you MUST generate a CIUDAD insert at start_seconds=0 showing that exact city. NEVER skip the opening city even if it appears in a date line. The city is ALWAYS the first trigger when it appears at t=0.

THE 14 TRIGGERS — only assign when the sentence CLEARLY and SPECIFICALLY mentions:

1. CIUDAD — a specific city, street, neighborhood, landmark, airport, prison, border crossing, or geographic place
   → image: cinematic shot of that exact place
   → IMPORTANT: "la capital" or a prison name = CIUDAD. "capital" meaning money = NOT this trigger.

2. PRENSA — ONLY when the sentence explicitly and directly mentions: journalists, a specific newspaper or magazine, press coverage of an event, headlines, tabloids, paparazzi, being photographed by press photographers, a story published in the media.
   → image: vintage Spanish newspaper newsstand, printing press, journalist with camera
   → IMPORTANT: metaphors, attitudes, personality traits, or artistic descriptions are NOT prensa even if they use words like "escenario", "mundo", "fama". The sentence must literally be about the media/press. "se le nota" → NOT prensa. "vivía como una estrella" → NOT prensa. "los productores lo buscaban" → NOT prensa (no press, just industry people).

3. DINERO — money amounts, debts, financial problems, contracts, payments, wealth, bills
   → image: peso bills, empty wallet, overdue bills on a desk
   → IMPORTANT: "capital" as in capital city is NOT this trigger.

4. POBREZA — poverty, humble origins, not having enough, poor neighborhood, struggling family
   → image: modest neighborhood, humble house, simple life setting

5. HOSPITAL — a hospital, clinic, medical emergency, surgery, doctors, nurses, medical staff
   → image: hospital corridor, medical setting, tired doctors

6. CINE — a movie, film role, premiere, cinema, filming a scene, a specific movie title
   → image: vintage movie theater, cinema seats, film reel
   → IMPORTANT: "película" in everyday speech (e.g. "it was a movie-worthy moment") does NOT trigger unless about an actual film.

7. RADIO — a radio program, radio station, being on the radio, radio debut
   → image: vintage radio studio, microphone, broadcast booth

8. CONCIERTO — a concert, live show, stadium performance, theater performance, tour
   → image: empty concert stage with spotlights, arena from the back

9. ACCIDENTE — a car accident, crash, physical incident, collision
   → image: empty road at night, damaged car, police tape

10. DOCUMENTO — official documents, court papers, notary, contracts being signed, legal proceedings, arrest warrants, lawsuits, sentences, amparos, AND also: being arrested, going to prison, jail cell, being detained, serving time, "fue arrestado", "estuvo preso", "lo metieron al bote", "la cárcel", "el reclusorio", "la celda", "detenido", "expediente judicial"
    → image: when about arrest/prison: iron bars of a jail cell, dim corridor of a reclusorio, or a worn legal file folder on a desk with a rubber stamp. When about documents: official papers with stamp, notary desk, manila folder.

11. INTERIOR — a specific interior described cinematically: hotel room, office, backstage, apartment, corridor
    → image: dimly lit hotel corridor, empty office with desk lamp

12. FUNERAL — death, dying, funeral, wake, coffin, cemetery, mourning, burial
    → image: closed coffin in chapel, cemetery at dusk, mourners in black

13. ENFERMEDAD — a specific disease or physical condition: cirrhosis, cancer, tumor, addiction, alcoholism, overdose, COPD, emphysema, deteriorating body
    → image: medical diagram, X-ray on lightbox, prescription bottles

14. ROMANCE — a romantic relationship: girlfriend, boyfriend, wife, husband, lover, affair, falling in love, getting married
    → CRITICAL: "esposa" by itself could mean he had a wife (trigger) OR be mentioned in passing. Only trigger if the sentence is clearly about the romantic relationship itself.
    → image: silhouette of the partner from behind, no face, romantic lighting

STRICT RULES:
- Analyze the FULL MEANING of each sentence, not just individual words
- A word that matches a trigger category but is used in a different context → NOT a trigger
  Examples: "se le nota" → not PRENSA. "la capital" → CIUDAD not DINERO. "actuó bien" → not CINE.
- A sentence that ANNOUNCES or MENTIONS a trigger concept — even if it doesn't describe the scene cinematically — still qualifies. Examples: "fue arrestado 7 veces" → DOCUMENTO. "fotografías de revistas" → PRENSA. "el rancho donde vivió" → INTERIOR.
- If a sentence has ZERO visual anchor from any of the 14 categories → YT_CLIP
- No more than 1 trigger per sentence
- ia_prompt: always in English, cinematic, specific to what the sentence says, no faces, no readable text
- escena_es: Spanish description of the image (max 80 chars), for human review

ERA RULES for ia_prompt:
- Before 1970: prefix "black and white archival documentary photograph, film grain, high contrast"
- 1970-1989: prefix "vintage color documentary photograph, faded Kodachrome"
- 1990+: prefix "realistic documentary photograph, warm tones"
- Always end with: "cinematic lighting, no text, no letters, no words, no faces visible"

OUTPUT FORMAT — JSON only:
{
  "segments": [
    {
      "sentence_index": 1,
      "trigger_type": "CIUDAD",
      "ia_prompt": "...",
      "escena_es": "Calle colonial de Ciudad de México al amanecer"
    },
    {
      "sentence_index": 2,
      "trigger_type": "YT_CLIP"
    }
  ]
}

Every sentence_index in the input MUST appear in the output as either a trigger or YT_CLIP."""

USER_TEMPLATE = """VIDEO: {video_name}
BATCH {batch_num} of {total_batches} — sentences {first_idx} to {last_idx}

Analyze each sentence. Assign trigger or YT_CLIP:

{sentences_json}

Return JSON with "segments" array. Every sentence_index must appear."""


def parse_srt(srt_path):
    content = srt_path.read_text(encoding='utf-8')
    blocks  = re.split(r'\n\s*\n', content.strip())
    entries = []
    for block in blocks:
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        ts_line = next((l for l in lines if '-->' in l), None)
        if not ts_line:
            continue
        def t2s(ts):
            ts = ts.replace(',', '.')
            h, m, s = ts.split(':')
            return int(h)*3600 + int(m)*60 + float(s)
        try:
            start_str, end_str = [x.strip() for x in ts_line.split('-->')]
            start = t2s(start_str)
            end   = t2s(end_str)
        except Exception:
            continue
        text_lines = [l for l in lines if '-->' not in l and not l.isdigit()]
        text = ' '.join(text_lines).strip()
        if text and start < end:
            entries.append({'start': start, 'end': end, 'text': text})
    return entries


_ERA_PREFIXES = {
    'bw':      'black and white archival documentary photograph, film grain, high contrast, ',
    'vintage': 'vintage color documentary photograph, faded Kodachrome, ',
    'color':   'realistic documentary photograph, warm tones, ',
}

def _detect_era(text: str) -> str:
    """Detecta la era correcta a partir del texto de la narración."""
    import re as _re
    years = list(map(int, _re.findall(r'\b(1[89]\d{2}|20[0-2]\d)\b', text)))
    t = text.lower()
    if _re.search(r'años (40|50|cuarenta|cincuenta)|siglo xx.*primera mitad|primera mitad.*siglo|radio.*televisión.*teatro|vecindades.*años', t):
        years.append(1945)
    if _re.search(r'años (60|setenta|70|sesenta)|reinado|discos.*millones|películas.*cines|contrato discográfico', t):
        years.append(1965)
    if _re.search(r'años (80|ochenta)', t):
        years.append(1982)
    if _re.search(r'años (90|noventa)|reclusorio|arrestado|expediente|abogado|rancho.*perdió|lomas|bienes', t):
        years.append(1993)
    if not years:
        return 'vintage'  # default: época dorada del artista
    yr = min(years)
    if yr < 1940:
        return 'bw'
    elif yr < 1990:
        return 'vintage'
    else:
        return 'color'

def _fix_era_prefix(prompt: str, narration: str) -> str:
    """Reemplaza el prefijo de era del prompt con el correcto según la narración."""
    era = _detect_era(narration)
    new_pfx = _ERA_PREFIXES[era]
    for pfx in _ERA_PREFIXES.values():
        if prompt.startswith(pfx):
            return new_pfx + prompt[len(pfx):]
    return new_pfx + prompt  # no tenía prefijo


def build_sentences(entries):
    """Agrupa entradas SRT en frases completas (hasta puntuación o 8s acumulados)."""
    sentences, current = [], []
    for e in entries:
        current.append(e)
        accumulated = current[-1]['end'] - current[0]['start']
        ends = bool(re.search(r'[.!?…]\s*$', e['text'].rstrip()))
        if ends or accumulated >= MAX_CLIP_SECS:
            sentences.append({
                'start': current[0]['start'],
                'end':   current[-1]['end'],
                'text':  ' '.join(x['text'] for x in current),
            })
            current = []
    if current:
        sentences.append({'start': current[0]['start'], 'end': current[-1]['end'],
                          'text': ' '.join(x['text'] for x in current)})
    return sentences


def call_gemini_batch(api_key, video_name, sentences, batch_num, total_batches, retries=3):
    """Envía un lote de frases a Gemini para clasificar triggers con contexto."""
    indexed = [{'sentence_index': i+1, 'start': s['start'], 'end': s['end'], 'text': s['text']}
               for i, s in enumerate(sentences)]
    sentences_json = json.dumps(indexed, ensure_ascii=False, indent=2)
    user_msg = USER_TEMPLATE.format(
        video_name=video_name,
        batch_num=batch_num,
        total_batches=total_batches,
        first_idx=1,
        last_idx=len(sentences),
        sentences_json=sentences_json,
    )
    payload = json.dumps({
        "model": OR_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }).encode()

    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                OR_ENDPOINT, data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/secretos-mexicanos",
                    "X-Title": "Secretos Mexicanos Timeline",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read())
            raw = data['choices'][0]['message']['content']
            parsed = json.loads(raw)
            return parsed.get('segments', [])
        except Exception as e:
            print(f"    Intento {attempt}/{retries} fallido: {e}")
            if attempt < retries:
                time.sleep(3 * attempt)
    return []


JUDGE_SYSTEM = """You are a strict quality judge for a visual documentary timeline. You receive a list of flow segments — each has a narration sentence and an image prompt (ia_prompt) generated for it.

YOUR JOB: Review each segment and decide if it passes or fails. Return corrections where needed.

FAIL conditions (mark as rejected):
1. INCOHERENT — the ia_prompt describes something unrelated to what is being narrated. Example: narration talks about a woman waiting 55 years to meet her father, but prompt shows "pile of peso bills" → FAIL.
2. DUPLICATE — the ia_prompt or escena_es is nearly identical to another segment in this batch (same subject, same visual) → FAIL the second one.
3. WRONG ERA — the narration gives clear era clues but the prompt uses the wrong style prefix (e.g. 1965 event described as "warm tones" instead of "black and white archival") → FIX the prefix.
4. MISSING STYLE — the prompt does not end with "cinematic lighting, no text, no letters, no words, no faces visible" → ADD it.
5. FACES OR TEXT — the prompt explicitly requests faces, readable signs, or logos → REMOVE those references.

PASS conditions:
- The prompt clearly illustrates what is narrated
- Correct era prefix
- Ends with style footer
- Not a duplicate of a previous segment

OUTPUT FORMAT — JSON only:
{
  "results": [
    {
      "segment_id": 1,
      "verdict": "pass",
      "ia_prompt": "...(keep or corrected)...",
      "escena_es": "...(keep or corrected)..."
    },
    {
      "segment_id": 3,
      "verdict": "reject",
      "reason": "prompt describes money but narration is about a woman"
    }
  ]
}

Every segment_id in the input MUST appear in the output."""

def call_gemini_judge(api_key, flow_segments, retries=3):
    """Segundo pase: juez LLM que valida coherencia, duplicados y estilo de los prompts."""
    if not flow_segments:
        return []

    items = []
    for s in flow_segments:
        items.append({
            "segment_id":  s["segment_id"],
            "trigger":     s["trigger_type"],
            "narration":   s.get("scene_description", "")[:200],
            "ia_prompt":   s.get("ia_prompt", ""),
            "escena_es":   s.get("escena_es", ""),
        })

    payload = json.dumps({
        "model": OR_MODEL,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user",   "content": f"Review these {len(items)} flow segments:\n\n{json.dumps(items, ensure_ascii=False, indent=2)}\n\nReturn JSON with results array."},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }).encode()

    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                OR_ENDPOINT, data=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/secretos-mexicanos",
                    "X-Title": "Secretos Mexicanos Judge",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read())
            raw = data['choices'][0]['message']['content']
            parsed = json.loads(raw)
            return parsed.get('results', [])
        except Exception as e:
            print(f"    [Juez] Intento {attempt}/{retries} fallido: {e}")
            if attempt < retries:
                time.sleep(3 * attempt)
    return []


TRIGGER_COLORS = {
    "CIUDAD": "#3b82f6", "PRENSA": "#8b5cf6", "DINERO": "#10b981",
    "POBREZA": "#f59e0b", "HOSPITAL": "#ef4444", "CINE": "#ec4899",
    "RADIO": "#06b6d4", "CONCIERTO": "#a855f7", "ACCIDENTE": "#dc2626",
    "DOCUMENTO": "#78716c", "INTERIOR": "#475569", "FUNERAL": "#1e293b",
    "ENFERMEDAD": "#7f1d1d", "ROMANCE": "#be185d", "YT_CLIP": "#374151",
}

sys.path.insert(0, str(pathlib.Path(__file__).parent))

def _find_free_port(start=5099):
    import socket
    for p in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', p)) != 0:
                return p
    return start


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("carpeta")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    carpeta  = pathlib.Path(args.carpeta)
    port     = args.port or _find_free_port()
    nombre   = carpeta.name
    srt_file = carpeta / f"{nombre}.srt"
    out_dir  = carpeta / "05-montaje"
    out_file = out_dir / "timeline.json"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not srt_file.exists():
        print(f"ERROR: No existe {srt_file}"); sys.exit(1)

    api_key = KEY_FILE.read_text().strip() if KEY_FILE.exists() else os.environ.get('OPENROUTER_API_KEY','')
    if not api_key:
        print(f"ERROR: Sin API key en {KEY_FILE}"); sys.exit(1)

    video_name = nombre.replace('-', ' ').replace('_', ' ').title()

    print(f"\n{'═'*62}")
    print(f"  TIMELINE SECRETOS MEXICANOS — {video_name.upper()}")
    print(f"{'═'*62}")

    entries = parse_srt(srt_file)
    if not entries:
        print("ERROR: SRT vacío"); sys.exit(1)

    entries = [e for e in entries if e['start'] < 600]
    total_end = entries[-1]['end'] if entries else 0
    print(f"  SRT:      {len(entries)} entradas (primeros 10 min)")
    print(f"  Duración: {total_end:.1f}s  ({total_end/60:.1f} min)")

    sentences = build_sentences(entries)
    print(f"  Frases:   {len(sentences)} frases agrupadas")

    # ── Enviar a Gemini en lotes de 15 frases ───────────────────────────────
    BATCH_SIZE = 15
    batches = [sentences[i:i+BATCH_SIZE] for i in range(0, len(sentences), BATCH_SIZE)]
    total_batches = len(batches)
    print(f"  Lotes:    {total_batches} × {BATCH_SIZE} frases\n")

    # Mapa global: sentence global index → clasificación Gemini
    classifications = {}  # {global_idx: {trigger_type, ia_prompt, escena_es}}
    global_offset = 0

    for b_num, batch in enumerate(batches, 1):
        print(f"  Lote {b_num}/{total_batches} ({len(batch)} frases)...", end=" ", flush=True)
        results = call_gemini_batch(api_key, video_name, batch, b_num, total_batches)
        triggers_found = 0
        for r in results:
            local_idx = r.get('sentence_index', 0) - 1  # 0-based dentro del lote
            global_idx = global_offset + local_idx
            ttype = r.get('trigger_type', 'YT_CLIP')
            if ttype not in VALID_TRIGGERS:
                ttype = 'YT_CLIP'
            classifications[global_idx] = {
                'trigger_type': ttype,
                'ia_prompt':    r.get('ia_prompt', ''),
                'escena_es':    r.get('escena_es', ''),
            }
            if ttype != 'YT_CLIP':
                triggers_found += 1
        print(f"✓ {triggers_found} triggers / {len(batch) - triggers_found} YT_CLIP")
        global_offset += len(batch)
        time.sleep(1)

    # ── Construir timeline con duraciones del SRT ────────────────────────────
    print(f"\n  Construyendo timeline con duraciones del SRT...")

    def add_yt_blocks(result, start, end):
        """Divide un hueco de tiempo en bloques de YT_CLIP_DUR segundos."""
        total = end - start
        if total <= 0:
            return
        n = max(1, round(total / YT_CLIP_DUR))
        chunk = total / n
        for i in range(n):
            s = round(start + i * chunk, 3)
            e = round(start + (i+1) * chunk, 3)
            result.append({
                'trigger_type':  'YT_CLIP',
                'source':        'yt_clip',
                'start_seconds': s,
                'end_seconds':   e,
                'duration':      round(e - s, 3),
                'ia_prompt':     '',
                'escena_es':     '',
                'scene_description': 'Clip YT',
            })

    all_segments = []
    cursor = sentences[0]['start'] if sentences else 0

    for idx, sent in enumerate(sentences):
        # hueco antes de esta frase
        if sent['start'] > cursor + 0.1:
            add_yt_blocks(all_segments, cursor, sent['start'])
        cursor = sent['start']

        clf = classifications.get(idx, {'trigger_type': 'YT_CLIP', 'ia_prompt': '', 'escena_es': ''})
        ttype = clf['trigger_type']
        dur   = sent['end'] - sent['start']

        if ttype != 'YT_CLIP' and clf.get('ia_prompt'):
            # Primera parte → flow (imagen IA), resto → YT_CLIP
            n_parts = max(1, math.ceil(dur / MAX_CLIP_SECS))
            chunk = dur / n_parts
            for i in range(n_parts):
                s = round(sent['start'] + i * chunk, 3)
                e = round(sent['start'] + (i+1) * chunk, 3)
                if i == 0:
                    fixed_prompt = _fix_era_prefix(clf['ia_prompt'], sent['text'])
                    all_segments.append({
                        'trigger_type':    ttype,
                        'source':          'flow',
                        'start_seconds':   s,
                        'end_seconds':     e,
                        'duration':        round(e - s, 3),
                        'ia_prompt':       fixed_prompt,
                        'escena_es':       clf.get('escena_es', ''),
                        'scene_description': sent['text'][:120],
                    })
                else:
                    # Continuación de la misma frase → clip YT sin duplicar imagen
                    add_yt_blocks(all_segments, s, e)
        else:
            # Sin trigger válido → YT_CLIP
            add_yt_blocks(all_segments, sent['start'], sent['end'])

        cursor = sent['end']

    # hueco final
    if total_end > cursor + 0.1:
        add_yt_blocks(all_segments, cursor, total_end)

    # ── Redondear timestamps a enteros ──────────────────────────────────────
    for s in all_segments:
        s['start_seconds'] = int(round(s['start_seconds']))
        s['end_seconds']   = int(round(s['end_seconds']))
        s['duration']      = s['end_seconds'] - s['start_seconds']

    # ── Eliminar YT_CLIP stubs < 3s → extender segmento anterior (max 8s) ───
    cleaned = []
    for seg in all_segments:
        if seg['source'] == 'yt_clip' and seg['duration'] < 3 and cleaned:
            new_dur = seg['end_seconds'] - cleaned[-1]['start_seconds']
            if new_dur <= 8:
                cleaned[-1]['end_seconds'] = seg['end_seconds']
                cleaned[-1]['duration']    = new_dur
            # si extender superaría 8s → descartar el stub silenciosamente
        else:
            cleaned.append(seg)
    all_segments = cleaned

    # ── Renumerar IDs ───────────────────────────────────────────────────────
    for idx, s in enumerate(all_segments, 1):
        s['segment_id'] = idx

    flow_count = sum(1 for s in all_segments if s['source'] == 'flow')
    yt_count   = sum(1 for s in all_segments if s['source'] == 'yt_clip')
    print(f"  Flow IA:  {flow_count} segmentos")
    print(f"  Clips YT: {yt_count} segmentos")
    print(f"  Total:    {len(all_segments)} segmentos")

    # ── Guardar ─────────────────────────────────────────────────────────────
    timeline = {
        "canal":           "secretos-mexicanos",
        "video":           nombre,
        "generated":       time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_segments":  len(all_segments),
        "flow_segments":   flow_count,
        "yt_segments":     yt_count,
        "visual_timeline": all_segments,
    }
    out_file.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  ✅ Timeline guardado: {out_file}")
    print(f"  Flow IA:  {flow_count} · Clips YT: {yt_count} · Total: {len(all_segments)}")

    vp_lines = [s["ia_prompt"].strip() for s in all_segments if s.get("ia_prompt","").strip()]
    if vp_lines:
        vp_file = out_dir / "video_prompts.txt"
        vp_file.write_text("\n\n".join(vp_lines), encoding="utf-8")

    print(f"\n  Puerto: {port}")
    print(f"{'═'*62}\n")


if __name__ == "__main__":
    main()
