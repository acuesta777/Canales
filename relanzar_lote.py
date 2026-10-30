#!/usr/bin/env python3
"""
relanzar_lote.py — Relanza un lote específico del timeline y lo inserta en el JSON existente.
Uso: python3 relanzar_lote.py seduccion/7_errores/ 368.6 459.0
"""
import sys, re, json, pathlib, time, urllib.request

HOME         = pathlib.Path.home()
KEY_FILE     = HOME / ".openrouter_key"
OR_MODEL     = "google/gemini-2.5-flash-lite"
OR_ENDPOINT  = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a Visual Content Planner for a Spanish-language YouTube channel about male psychology and attraction. The channel is called "Enigma Estoica".

VISUAL STYLE: Minimalist stick figures (white lines on black background).

VISUAL SOURCES — use "ia_stickfigure" for everything in this channel.

STICK FIGURE PROMPT STYLE:
- White minimalist stick figures on pure black background
- Line art style, expressive poses, simple facial expressions
- Include speech bubbles, thought bubbles, or action lines when relevant
- Max 2-3 figures per scene
- Always end with: "white line art on black background, minimalist stick figure style, no color, high contrast"

RULES:
1. Every SRT entry gets AT LEAST one segment
2. No segment > 8.0 seconds
3. No segment < 2.0 seconds
4. ZERO GAPS between segments
5. First segment.start_seconds = batch_start (exact float)
6. Last segment.end_seconds = batch_end (exact float)

OUTPUT: Valid JSON only, no markdown.
{
  "visual_timeline": [
    {
      "segment_id": 1,
      "source": "ia_stickfigure",
      "start_seconds": 0.0,
      "end_seconds": 6.5,
      "duration": 6.5,
      "scene_description_es": "Descripción en español",
      "prompt_or_query": "English prompt... white line art on black background, minimalist stick figure style, no color, high contrast",
      "covers_text": "Exact phrase from narration",
      "emotional_beat": "contrast|hook|problem|insight|framework|resolution|cta",
      "priority": "high|medium|low"
    }
  ]
}"""

def ts_to_sec(ts):
    ts = ts.strip().replace(',', '.')
    p  = ts.split(':')
    return int(p[0])*3600 + int(p[1])*60 + float(p[2])

def parse_srt(srt_path):
    blocks  = re.split(r'\n\n+', pathlib.Path(srt_path).read_text(encoding='utf-8').strip())
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
            entries.append({'start': round(start,3), 'end': round(end,3), 'text': text})
    return entries

def extract_json(text):
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$',       '', text, flags=re.MULTILINE)
    return json.loads(text)

def call_openrouter(api_key, batch, batch_start, batch_end, retries=5):
    sentences_json = json.dumps(
        [{'t': e['start'], 'end': e['end'], 'text': e['text']} for e in batch],
        ensure_ascii=False, indent=2
    )
    user_msg = f"""TIME WINDOW: {batch_start}s → {batch_end}s ({batch_end-batch_start:.1f}s)
VIDEO: 7 Errores — Enigma Estoica

SRT ENTRIES:
{sentences_json}

Create segments covering EXACTLY {batch_start}s to {batch_end}s. Zero gaps. JSON only."""

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
            req = urllib.request.Request(OR_ENDPOINT, data=payload, headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer":  "https://enigmaestoica.canal",
            })
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read())
            text     = resp["choices"][0]["message"]["content"]
            data     = extract_json(text)
            segments = data.get('visual_timeline', [])
            if segments:
                return segments
            print(f"  ⚠ Respuesta vacía — reintento {attempt+1}")
        except json.JSONDecodeError as e:
            print(f"  ⚠ JSON inválido intento {attempt+1}: {e}")
        except Exception as e:
            print(f"  ⚠ Error intento {attempt+1}: {e}")
        if attempt < retries - 1:
            time.sleep(4)
    return []

def main():
    if len(sys.argv) < 4:
        print("Uso: python3 relanzar_lote.py <carpeta> <start_s> <end_s>")
        sys.exit(1)

    carpeta     = pathlib.Path(sys.argv[1])
    batch_start = float(sys.argv[2])
    batch_end   = float(sys.argv[3])
    nombre      = carpeta.name
    srt_file    = carpeta / f"{nombre}.srt"
    timeline_f  = carpeta / "05-montaje" / "timeline.json"
    api_key     = KEY_FILE.read_text().strip()

    print(f"\nRelanzando lote {batch_start}s → {batch_end}s ...")

    # Filtrar entradas del SRT en ese rango
    all_entries = parse_srt(srt_file)
    batch = [e for e in all_entries if e['start'] >= batch_start - 0.5 and e['end'] <= batch_end + 0.5]
    print(f"Entradas SRT en rango: {len(batch)}")

    segments = call_openrouter(api_key, batch, batch_start, batch_end)
    if not segments:
        print("ERROR: No se pudo generar el lote.")
        sys.exit(1)

    # Corregir gaps
    segments[0]['start_seconds'] = round(batch_start, 3)
    for i in range(1, len(segments)):
        segments[i]['start_seconds'] = round(segments[i-1]['end_seconds'], 3)
    segments[-1]['end_seconds'] = round(batch_end, 3)
    for s in segments:
        s['duration'] = round(s['end_seconds'] - s['start_seconds'], 3)

    print(f"✓ {len(segments)} segmentos generados")

    # Insertar en timeline.json existente
    data     = json.loads(timeline_f.read_text(encoding='utf-8'))
    existing = data['visual_timeline']

    # Reasignar IDs a los nuevos segmentos (continuando desde el mayor existente)
    max_id = max((s.get('segment_id', 0) for s in existing), default=0)
    for i, s in enumerate(segments, 1):
        s['segment_id'] = max_id + i

    # Insertar en la posición correcta (ordenado por start_seconds)
    combined = existing + segments
    combined.sort(key=lambda s: s.get('start_seconds', 0))

    data['visual_timeline']          = combined
    data['meta']['total_segments']   = len(combined)

    timeline_f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"✓ Timeline actualizado: {len(combined)} segmentos totales")
    print(f"  Guardado en: {timeline_f}")

if __name__ == '__main__':
    main()
