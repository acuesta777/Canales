#!/usr/bin/env python3
"""
relanzar_segs_familias.py — Regenera prompts y imágenes para un rango de segmentos animate.

Uso:
    python3 relanzar_segs_familias.py familias/bailleres/ 9 16 --logos "El Palacio de Hierro,Peñoles,GNP Seguros"
"""
import sys, re, json, pathlib, time, urllib.request, urllib.error, argparse, subprocess

HOME        = pathlib.Path.home()
KEY_FILE    = HOME / ".openrouter_key"
OR_MODEL    = "google/gemini-2.5-flash-lite"
OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a Visual Timeline Planner for a Spanish-language YouTube channel called "Familias de Riquezas" about wealthy Mexican dynasties.

YOUR MISSION: Create a COMPLETE visual coverage of the narration — every second must have an image. There are NO gaps.

COVERAGE RULES (strict):
1. Every SRT entry in the batch MUST produce at least one visual segment.
2. Segment duration: minimum 1.5s, maximum 8s. Split long entries into multiple segments.
3. Segments are CONTIGUOUS — each starts exactly where the previous ended.
4. The first segment starts at batch_start. The last segment ends at batch_end.
5. DO NOT skip any SRT entry. DO NOT leave any time gap.

PROMPT RULES — HYPERREALISTIC WITH BRAND LOGOS:
- All prompts in English.
- Always start with: "Cinematic hyperrealistic photo of"
- CRITICAL: When the narration mentions a specific company or product, include that brand's visual identity:
    • El Palacio de Hierro → "El Palacio de Hierro luxury department store with the iconic Palacio de Hierro logo"
    • Peñoles → "Industrias Peñoles mining facility with Peñoles corporate signage"
    • GNP Seguros → "GNP Seguros insurance office building with GNP Seguros logo"
    • Fresnillo → "Fresnillo PLC silver mining operation with industrial equipment"
- Never generic streets. Always specific subject: building, product, person (unnamed), or event.
- End every prompt with the era style + ", 16:9 aspect ratio"
- 50-80 words per prompt.

Era styles:
- 1800-1939 → "sepia-toned, period-accurate, colonial Mexico architecture"
- 1940-1969 → "vintage warm color, faded film look, 1950s Mexico"
- 1970-1999 → "color photography, slightly warm, 1970s-1990s Mexico"
- 2000+     → "full color vivid, crisp, hyperrealistic, modern Mexico"

OUTPUT FORMAT — JSON ONLY:
{
  "visual_timeline": [
    {
      "start_seconds": 0.0,
      "end_seconds": 4.5,
      "ia_prompt": "Cinematic hyperrealistic photo of ..., 16:9 aspect ratio",
      "scene_description_es": "Descripción breve en español"
    }
  ]
}"""

def ts_to_sec(ts):
    ts = ts.strip().replace(',', '.')
    p  = ts.split(':')
    return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])

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
            entries.append({'start': round(start, 3), 'end': round(end, 3), 'text': text})
    return entries

def extract_json(text):
    text = text.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```\s*$',       '', text, flags=re.MULTILINE)
    return json.loads(text)

def call_api(api_key, video_name, logos, batch, batch_start, batch_end, retries=3):
    sentences = json.dumps(
        [{'t': e['start'], 'end': e['end'], 'text': e['text']} for e in batch],
        ensure_ascii=False, indent=2
    )
    user_msg = f"""Batch 1/1 | Video: {video_name} | Logos: {logos}
Batch: {batch_start:.1f}s → {batch_end:.1f}s

SRT entries:
{sentences}

JSON únicamente."""

    payload = json.dumps({
        "model": OR_MODEL,
        "max_tokens": 8000,
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
                "HTTP-Referer":  "https://familiasderiquezas.canal",
            })
            with urllib.request.urlopen(req, timeout=90) as r:
                resp = json.loads(r.read())
            text     = resp["choices"][0]["message"]["content"]
            data     = extract_json(text)
            segments = data.get('visual_timeline', [])
            if segments:
                return segments
            print(f"  ⚠ Respuesta vacía — reintento {attempt+1}")
        except urllib.error.HTTPError as e:
            if e.code == 402:
                print("  ✗ ERROR 402 — recarga OpenRouter")
                sys.exit(1)
            print(f"  ⚠ HTTP {e.code} intento {attempt+1}")
        except Exception as e:
            print(f"  ⚠ Error intento {attempt+1}: {e}")
        if attempt < retries - 1:
            time.sleep(4)
    return []

def generar_imagen(carpeta, seg_id, prompt, img_dir):
    """Genera imagen con muapi, fallback a ai33pro."""
    out_jpg = img_dir / f"flow_{seg_id:04d}.jpg"

    # Intentar muapi
    import urllib.parse
    muapi_url = "https://muapi.ai/api/v1/image/generation"
    muapi_payload = json.dumps({
        "model": "flux-schnell",
        "prompt": prompt,
        "width": 1280,
        "height": 720,
        "num_inference_steps": 4
    }).encode()
    muapi_key_file = HOME / ".muapi_key"
    muapi_key = muapi_key_file.read_text().strip() if muapi_key_file.exists() else ""

    if muapi_key:
        try:
            req = urllib.request.Request(muapi_url, data=muapi_payload, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {muapi_key}",
            })
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read())
            request_id = resp.get("request_id") or resp.get("id")
            if request_id:
                # Polling
                for _ in range(30):
                    time.sleep(3)
                    poll = urllib.request.Request(
                        f"https://muapi.ai/api/v1/image/generation/{request_id}",
                        headers={"Authorization": f"Bearer {muapi_key}"}
                    )
                    with urllib.request.urlopen(poll, timeout=30) as r2:
                        pr = json.loads(r2.read())
                    status = pr.get("status", "")
                    if status == "completed":
                        img_url = (pr.get("output") or [None])[0]
                        if img_url:
                            urllib.request.urlretrieve(img_url, out_jpg)
                            print(f"    ✓ [muapi] flow_{seg_id:04d}.jpg")
                            return True
                        break
                    elif status == "failed":
                        break
        except Exception as e:
            print(f"    ⚠ muapi falló: {e} — usando ai33pro")

    # Fallback ai33pro
    print(f"    → ai33pro para seg {seg_id}...")
    result = subprocess.run(
        ["python3", "imagen_ai33pro.py", str(carpeta), "--seg", str(seg_id)],
        timeout=300, capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"    ✓ [ai33pro] flow_{seg_id:04d}.jpg")
        return True
    print(f"    ✗ ai33pro falló: {result.stderr[-200:]}")
    return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('carpeta')
    parser.add_argument('seg_desde', type=int)
    parser.add_argument('seg_hasta', type=int)
    parser.add_argument('--logos', default='las empresas de la familia')
    args = parser.parse_args()

    carpeta    = pathlib.Path(args.carpeta)
    nombre     = carpeta.name
    srt_file   = carpeta / f"{nombre}.srt"
    tl_file    = carpeta / "05-montaje" / "timeline.json"
    img_dir    = carpeta / "03-imagenes"
    api_key    = KEY_FILE.read_text().strip()
    video_name = nombre.replace('-', ' ').replace('_', ' ').title()

    print(f"\n{'═'*62}")
    print(f"  RELANZAR SEGS {args.seg_desde}–{args.seg_hasta} — {video_name.upper()}")
    print(f"{'═'*62}\n")

    # Leer timeline existente
    tl   = json.loads(tl_file.read_text())
    segs = tl['visual_timeline']

    # Localizar los segmentos a reemplazar
    target = [s for s in segs if args.seg_desde <= s['segment_id'] <= args.seg_hasta]
    if not target:
        print(f"  ✗ No encontré segs {args.seg_desde}–{args.seg_hasta} en timeline.json")
        sys.exit(1)

    batch_start = target[0]['start_seconds']
    batch_end   = target[-1]['end_seconds']
    print(f"  Rango temporal: {batch_start:.1f}s → {batch_end:.1f}s")
    print(f"  Segmentos a reemplazar: {len(target)}\n")

    # Leer SRT en ese rango
    all_entries = parse_srt(srt_file)
    batch = [e for e in all_entries if e['end'] > batch_start - 0.5 and e['start'] < batch_end + 0.5]
    print(f"  Entradas SRT en rango: {len(batch)}")

    # Llamar API
    print(f"  Generando prompts con {OR_MODEL}...")
    t0       = time.time()
    new_segs = call_api(api_key, video_name, args.logos, batch, batch_start, batch_end)
    elapsed  = time.time() - t0

    if not new_segs:
        print("  ✗ No se generaron segmentos"); sys.exit(1)

    # Corregir timing
    new_segs[0]['start_seconds'] = round(batch_start, 3)
    for i in range(1, len(new_segs)):
        new_segs[i]['start_seconds'] = round(new_segs[i-1]['end_seconds'], 3)
    new_segs[-1]['end_seconds'] = round(batch_end, 3)
    for s in new_segs:
        s['duration']      = round(s['end_seconds'] - s['start_seconds'], 3)
        s['animate']       = True
        s['source']        = 'flow'
        if 'ia_prompt_en' not in s:
            s['ia_prompt_en'] = s.get('ia_prompt', '')

    # Reasignar segment_ids de los nuevos (mismos IDs que los viejos)
    old_ids = [s['segment_id'] for s in target]
    for i, s in enumerate(new_segs):
        s['segment_id'] = old_ids[i] if i < len(old_ids) else old_ids[-1] + i - len(old_ids) + 1

    print(f"  ✓ {len(new_segs)} segmentos generados ({elapsed:.1f}s)\n")
    for s in new_segs:
        print(f"    [{s['segment_id']:03d}] {s['start_seconds']:.1f}→{s['end_seconds']:.1f}s")
        print(f"         {s.get('ia_prompt','')[:90]}...")
    print()

    # Reemplazar en timeline
    remaining = [s for s in segs if not (args.seg_desde <= s['segment_id'] <= args.seg_hasta)]
    combined  = sorted(remaining + new_segs, key=lambda s: s['start_seconds'])
    tl['visual_timeline']   = combined
    tl['total_segments']    = len(combined)
    tl_file.write_text(json.dumps(tl, ensure_ascii=False, indent=2))
    print(f"  ✓ timeline.json actualizado ({len(combined)} segs totales)\n")

    # Generar imágenes para los nuevos segmentos
    print(f"  Generando imágenes para segs {args.seg_desde}–{args.seg_hasta}...")
    img_dir.mkdir(parents=True, exist_ok=True)
    ok = 0
    for s in new_segs:
        sid    = s['segment_id']
        prompt = s.get('ia_prompt', '')
        print(f"  Seg {sid}: {prompt[:70]}...")
        if generar_imagen(carpeta, sid, prompt, img_dir):
            ok += 1

    print(f"\n  {'✓' if ok==len(new_segs) else '⚠'} {ok}/{len(new_segs)} imágenes generadas")
    print(f"\n  Próximo paso: revisar en el dashboard http://localhost:5004/aprobar/familias/{carpeta.name}/")

if __name__ == '__main__':
    main()
