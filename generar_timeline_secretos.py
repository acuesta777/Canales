#!/usr/bin/env python3
"""
generar_timeline_secretos.py — Planificador visual para canal Secretos del Poder.

Lee el SRT → Gemini detecta los 5 triggers del canal → asigna fuente brave/flow
→ genera 05-montaje/timeline.json anclado al segundo exacto del audio.

Los 5 triggers (equivalente a mansiones/autos en riqueza):
  1. DOCUMENTO  — manifiesto, acta, expediente, NDA, herencia, firma legal
  2. BODA_LUGAR — iglesia, ceremonia, recepción, boda, altar, casamiento
  3. LUGAR_CLAVE — barco, hospital, juzgado, edificio específico, casa familiar, despacho
  4. TENSION_DOMESTICA — mujer sola, silencio, pareja distante, niño solo, abandono cotidiano
  5. ARCHIVO_CONTROL — archivos sellados, cajas de documentos, alguien firmando, encubrir

Fuentes:
  - "brave"  → foto de archivo real (persona, documento, propiedad)
  - "flow"   → imagen IA en estilo documental B&W de época

Uso:
    python3 generar_timeline_secretos.py secretos/ethel-kennedy/
"""

import sys, re, json, pathlib, time, os
import urllib.request, urllib.error
from timeline_prompt_fixer import auto_fix_prompts

BATCH_SECONDS   = 90
MAX_SEG_SECS    = 8.0
MIN_SEG_SECS    = 2.0

HOME        = pathlib.Path.home()
KEY_FILE    = HOME / ".openrouter_key"
OR_MODEL    = "google/gemini-2.5-flash-lite"
OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a Visual Timeline Planner for a Spanish-language YouTube channel called "Secretos del Poder". The channel covers the dark secrets and hidden truths behind the marriages of powerful American political families (Kennedy, Trump, Roosevelt, Lincoln, Reagan, etc.).

CHANNEL VISUAL IDENTITY (verified from the #1 most-viewed video):
- 85% real archival material (press photos, government documents, old footage)
- 10% AI-generated vintage B&W documentary imagery
- 5% generated text cards and infographics
- The visual promise is: "I will show you EVIDENCE, not decoration"

YOUR JOB: Scan the narration and find moments where one of the 5 TRIGGER TYPES appears. At that exact second, schedule a visual insert that PROVES what the narrator is saying.

THE 5 TRIGGER TYPES (only insert on these):

1. DOCUMENTO — narrator mentions: a document, record, manifest, NDA, legal paper, will, inheritance, signature, filing, sealed record, court document, IRS record, contract, letter, testimony
   → Visuals: government document closeup, stacks of legal papers with dates labeled, sealed envelope with official stamp, filing cabinet being accessed

2. BODA_LUGAR — narrator mentions: wedding, church, ceremony, reception, altar, marriage vows, the wedding day itself, the guests, the dress
   → Visuals: interior of formal church of the era (cold, not romantic), empty reception hall with tables, wedding cake alone on table, formal ballroom in period style

🔴 MANDATORY OPENING PLACE RULE: If the VERY FIRST ENTRY of the FIRST BATCH contains a city or location name — you MUST generate a LUGAR_CLAVE insert at start_seconds=0 showing that exact city/place. NEVER skip the opening location even if it appears in a date line. The location is ALWAYS the first trigger when it appears at t=0.

3. LUGAR_CLAVE — narrator mentions a specific NAMED place: a ship, hospital, courthouse, specific building, specific house, specific city neighborhood, a specific hotel, a specific harbor
   → Visuals: exterior of that type of building in the era, ship deck of the period, hospital corridor B&W, courthouse exterior, harbor with period ships

4. TENSION_DOMESTICA — narrator mentions: a woman alone, a couple in silence, a husband absent, a child receiving bad news alone, domestic work, a mother who didn't come, abandonment in daily life, silence between people who live together
   → Visuals: woman alone in 1940s kitchen, couple sitting in formal room not looking at each other, child walking to school alone B&W, woman hanging laundry alone, man with back turned at window

5. ARCHIVO_CONTROL — narrator mentions: hiding information, controlling the narrative, NDA, sealed records, lawsuit, family who controls the story, archive that can't be touched, settlement signed, keeping secrets, silencing someone
   → Visuals: person accessing tall filing cabinets, boxes of documents stacked with official seals, someone signing papers at a desk (formal, not romantic), shelves of legal folders

SOURCE RULES:
- If the trigger involves a NAMED REAL PERSON who can be photographed → source: "brave", brave_query: "[full name] [year] photo"
- If the trigger involves a NAMED REAL DOCUMENT that exists online → source: "brave", brave_query: "[document name] [year] original"
- If the trigger involves a GENERIC SCENE of the era (no specific identifiable person) → source: "flow", ia_prompt in English
- NEVER generate AI images of specific real people's faces
- NEVER generate documents with readable specific text (looks fake)

IA PROMPT RULES (flow only):
- Always in English
- Format: "[era adjective] [scene], black and white archival photograph, film grain, high contrast, [decade]s documentary style, no text, no letters, no words"
- Era: pre-1940 → "1930s", 1940-1969 → "1940s/1950s/1960s", 1970-1989 → "1970s color faded"
- Be specific to the scene described in narration — reference the actual situation being narrated
- NEVER: luxury cars, mansions as aspirational symbols, money as aspiration. Those belong to a different channel.

OUTPUT FORMAT — valid JSON only:
{
  "visual_timeline": [
    {
      "segment_id": 1,
      "source": "flow",
      "start_seconds": 45.2,
      "end_seconds": 52.0,
      "duration": 6.8,
      "scene_description_es": "Descripción en español de lo que se ve",
      "ia_prompt": "1930s woman alone in kitchen, black and white archival photograph, film grain, high contrast, domestic scene, no text no letters",
      "brave_query": null,
      "covers_text": "texto exacto del SRT que dispara este visual",
      "trigger_type": "tension_domestica"
    }
  ]
}

For brave source, use ia_prompt: null and fill brave_query instead."""

USER_TEMPLATE = """BATCH {batch_number} of {total_batches}
TIME WINDOW: {batch_start}s → {batch_end}s
VIDEO SUBJECT: {video_name}

SRT ENTRIES (Spanish narration with exact timestamps):
{sentences_json}

INSTRUCTIONS:
1. Scan every SRT entry for one of the 5 trigger types: DOCUMENTO, BODA_LUGAR, LUGAR_CLAVE, TENSION_DOMESTICA, ARCHIVO_CONTROL
2. When you find a trigger, create ONE insert anchored to that exact timestamp
3. start_seconds = the exact "t" value of the SRT entry that contains the trigger word
4. end_seconds = start_seconds + 4 to 7 seconds (never more than 8s, never less than 3s)
5. No overlapping inserts
6. Generate 2–4 inserts per batch — only on genuine triggers, not on every sentence
7. If a batch has no triggers, return an empty visual_timeline array
8. The visual must PROVE what the narrator is saying at that moment — not decorate it

JSON only. No explanations."""


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
                    "HTTP-Referer":  "https://secretosdelpoder.canal",
                }
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read())

            text     = resp["choices"][0]["message"]["content"]
            data     = extract_json(text)
            segments = data.get('visual_timeline', [])
            return segments  # puede ser lista vacía si no hay triggers en el batch
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


def sanitize_timeline(segments):
    if not segments:
        return segments

    segments = sorted(segments, key=lambda s: s['start_seconds'])
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
        print(f"  sanitize_timeline: {len(fixes)} corrección(es)")
        for f in fixes:
            print(f)
        print(f"{'─'*62}\n")
    else:
        print(f"\n  ✓ sanitize_timeline: sin overlaps, duraciones 3–8s, gaps ≥ 5s")

    return segments


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 generar_timeline_secretos.py secretos/<slug>/")
        sys.exit(1)

    carpeta  = pathlib.Path(sys.argv[1])
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

    # Verificar saldo OpenRouter
    try:
        kreq = urllib.request.Request(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(kreq, timeout=10) as kr:
            kdata = json.loads(kr.read()).get('data', {})
        usage = kdata.get('usage', 0)
        limit = kdata.get('limit')
        if limit:
            restante = limit - usage
            print(f"  💰 OpenRouter: ${usage:.4f} usado / ${limit:.2f} límite — restante ${restante:.4f}")
            if restante < 0.10:
                print(f"  ⚠️  SALDO BAJO — recargar antes de continuar")
        else:
            print(f"  💰 OpenRouter: ${usage:.4f} usado (sin límite)")
    except Exception as e:
        print(f"  ℹ  No se pudo verificar saldo: {e}")

    video_name = nombre.replace('-', ' ').replace('_', ' ').title()

    print(f"\n{'═'*62}")
    print(f"  TIMELINE SECRETOS — {video_name.upper()}")
    print(f"  Canal: Secretos del Poder")
    print(f"  Triggers: DOCUMENTO · BODA_LUGAR · LUGAR_CLAVE · TENSION_DOMESTICA · ARCHIVO_CONTROL")
    print(f"{'═'*62}")

    entries = parse_srt(srt_file)
    if not entries:
        print("ERROR: SRT vacío"); sys.exit(1)

    # Solo primeros 10 minutos del SRT (igual que riqueza)
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

    # ── HOOK COVERAGE (primeros 120s) ──────────────────────────────────
    # Cortes en finales de frase del SRT — duración variable 3-8s, no grilla fija
    HOOK_DURATION   = 120.0
    MIN_SEG = 3.0
    MAX_SEG = 8.0
    # Detectar cortes naturales en el SRT: final de frase (., ?, !)
    hook_entries = [e for e in entries if e['start'] < HOOK_DURATION]
    cut_points = [0.0]
    for e in hook_entries:
        txt = e.get('text', '').strip()
        if txt and txt[-1] in '.!?—…':
            t_cut = min(e['end'], HOOK_DURATION)
            # solo si el corte agrega al menos MIN_SEG al último
            if t_cut - cut_points[-1] >= MIN_SEG:
                cut_points.append(round(t_cut, 3))
    # Fragmentar segmentos que superen MAX_SEG
    final_cuts = [0.0]
    for i in range(1, len(cut_points)):
        prev = final_cuts[-1]
        nxt  = cut_points[i]
        while nxt - prev > MAX_SEG:
            prev = round(prev + MAX_SEG, 3)
            final_cuts.append(prev)
        final_cuts.append(nxt)
    if final_cuts[-1] < HOOK_DURATION:
        prev = final_cuts[-1]
        while HOOK_DURATION - prev > MAX_SEG:
            prev = round(prev + MAX_SEG, 3)
            final_cuts.append(prev)
        final_cuts.append(HOOK_DURATION)

    # Construir lista de segmentos con su texto SRT
    raw_hook_segs = []
    for i in range(len(final_cuts) - 1):
        t_start = final_cuts[i]
        t_end   = final_cuts[i + 1]
        dur     = round(t_end - t_start, 3)
        if dur < 1.0:
            continue
        seg_text = " ".join(
            e.get('text', '') for e in hook_entries
            if e['start'] >= t_start - 0.5 and e['end'] <= t_end + 0.5
        ).strip() or f"Narración sobre {video_name}"
        raw_hook_segs.append({"t_start": t_start, "t_end": t_end, "dur": dur, "text": seg_text})

    # Una sola llamada a Gemini con todos los segmentos del hook
    segs_json = json.dumps([{"id": i+1, "t": f"{s['t_start']:.1f}s–{s['t_end']:.1f}s", "text": s['text']} for i, s in enumerate(raw_hook_segs)], ensure_ascii=False)
    hook_prompt = f"""You are creating Brave image search queries for archival photos for a YouTube video about {video_name} and their marriage.

For each narration segment below, generate a specific Brave search query to find a REAL archival photo.

RULES:
- ALWAYS include "{video_name}" by full name in the query unless the text is clearly about their spouse/family
- If text mentions spouse "Rosario Gálvez" or "Rosario" → include her name
- If text mentions the book "Cuentas de un rosario" → search for the book cover
- Be specific: use years, roles, context from the narration
- Queries in Spanish
- Return ONLY a JSON array, one object per segment

SEGMENTS:
{segs_json}

Return ONLY:
[
  {{"id": 1, "desc_es": "descripción breve", "brave_query": "query específica"}},
  ...
]"""

    hook_queries = {}
    payload = json.dumps({
        "model": OR_MODEL,
        "messages": [{"role": "user", "content": hook_prompt}],
        "max_tokens": 1000,
        "temperature": 0.3,
    }).encode()
    req = urllib.request.Request(
        OR_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}",
                 "HTTP-Referer": "https://localhost", "X-Title": "secretos-pipeline"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
        content = resp['choices'][0]['message']['content'].strip()
        import re as _re_hook
        m = _re_hook.search(r'\[.*\]', content, _re_hook.DOTALL)
        if m:
            results = json.loads(m.group())
            for item in results:
                hook_queries[item['id']] = (item.get('desc_es', ''), item.get('brave_query', f"{video_name} foto archivo"))
    except Exception as e:
        print(f"  ⚠ Hook Gemini call failed: {e}")

    hook_segs = []
    for i, s in enumerate(raw_hook_segs):
        desc_es, brave_query = hook_queries.get(i+1, (s['text'][:60], f"{video_name} foto archivo"))
        hook_segs.append({
            "segment_id": segment_counter,
            "start_seconds": s['t_start'],
            "end_seconds": s['t_end'],
            "duration": s['dur'],
            "source": "brave",
            "brave_query": brave_query,
            "ia_prompt": None,
            "scene_description_es": desc_es,
            "trigger_type": "HOOK_COVERAGE",
        })
        segment_counter += 1
        print(f"    hook [{i+1}] {s['t_start']:.1f}s–{s['t_end']:.1f}s → {brave_query[:65]}")
    all_segments.extend(hook_segs)
    print(f"  Hook coverage: {len(hook_segs)} segmentos brave (0–{HOOK_DURATION:.0f}s)")
    # ── FIN HOOK COVERAGE ──────────────────────────────────────────────

    for i, batch in enumerate(batches, 1):
        b_start = batch[0]['start']
        b_end   = batch[-1]['end']
        print(f"  [{i:02d}/{total_batches}] {b_start:.1f}s → {b_end:.1f}s  ({len(batch)} entradas)...", end='', flush=True)

        t0       = time.time()
        segments = call_openrouter(api_key, video_name, batch, i, total_batches)
        elapsed  = time.time() - t0

        if segments:
            # Ignorar triggers que solapen con el hook coverage (primeros 120s)
            segments = [s for s in segments if s.get('start_seconds', 0) >= HOOK_DURATION]
            for s in segments:
                s['segment_id'] = segment_counter
                segment_counter += 1
            all_segments.extend(segments)
            print(f" {len(segments)} inserts ({elapsed:.1f}s)")
        else:
            print(f" sin triggers ({elapsed:.1f}s)")

        if i < total_batches:
            time.sleep(1)

    if not all_segments:
        print("ERROR: No se encontraron triggers en el SRT")
        print("Verificar que el SRT tiene texto y que el guion menciona documentos, bodas, lugares, tensión o archivos.")
        sys.exit(1)

    # Normalizar keys
    for s in all_segments:
        if 'start' in s and 'start_seconds' not in s:
            s['start_seconds'] = s.pop('start')
        if 'end' in s and 'end_seconds' not in s:
            s['end_seconds'] = s.pop('end')
        if 'end_seconds' not in s and 'duration' in s and 'start_seconds' in s:
            s['end_seconds'] = round(s['start_seconds'] + s['duration'], 3)
        # Asegurar campo ia_prompt y brave_query presentes
        s.setdefault('ia_prompt', None)
        s.setdefault('brave_query', None)

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
    all_segments = _segs_sorted


    out_file.write_text(
        json.dumps({"visual_timeline": all_segments}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\n  ✓ timeline.json → {out_file}")
    print(f"  Total inserts: {len(all_segments)}")

    # Resumen de triggers y fuentes
    triggers = {}
    sources  = {}
    for s in all_segments:
        t = s.get('trigger_type', '?')
        triggers[t] = triggers.get(t, 0) + 1
        src = s.get('source', '?')
        sources[src] = sources.get(src, 0) + 1

    print(f"\n  Triggers detectados:")
    trigger_icons = {
        'documento': '📄', 'boda_lugar': '⛪', 'lugar_clave': '🏛',
        'tension_domestica': '🚪', 'archivo_control': '🗄'
    }
    for t, count in sorted(triggers.items(), key=lambda x: -x[1]):
        icon = trigger_icons.get(t.lower(), '❓')
        print(f"    {icon} {t:<22} {count:3d} inserts")

    print(f"\n  Fuentes asignadas:")
    for src, count in sorted(sources.items(), key=lambda x: -x[1]):
        icon = '🔍' if src == 'brave' else '🤖'
        print(f"    {icon} {src:<10} {count:3d} inserts ({count/len(all_segments)*100:.0f}%)")

    print(f"\n  Siguiente paso:")
    print(f"  python3 harvester_timeline.py {sys.argv[1]} --canal secretos")


if __name__ == "__main__":
    main()
