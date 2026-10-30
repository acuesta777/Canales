#!/usr/bin/env python3
"""
generar_timeline_farandula_mono.py — Planificador visual para Farandula Formato 2 (mono-artista).

Lee el SRT (primeros 10 min) → Gemini detecta triggers del canal →
genera hook_timeline.json con segmentos de imágenes IA anclados al segundo exacto.

El render_farandula_mono.py ya sabe intercalar esas imágenes con clips_ref/
en su timestamp exacto — igual que secretos-mexicanos y riqueza.

Triggers válidos (12):
  DRAMA:   hospital · pobreza · romance · funeral · enfermedad · caida
  FAMA:    fama · television · prensa
  LUGAR:   ciudad · interior · documento

Uso:
    python3 Farandula/generar_timeline_farandula_mono.py "Farandula/LUCHA VILLA/"
"""

import sys, re, json, pathlib, time, os
import urllib.request, urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from timeline_prompt_fixer import auto_fix_prompts

BATCH_SECONDS = 90
MAX_CLIP_SECS = 8.0
MIN_SEG_SECS  = 3.0
MAX_SRT_SECS  = 600  # primeros 10 min

HOME        = pathlib.Path.home()
KEY_FILE    = HOME / ".openrouter_key"
OR_MODEL    = "google/gemini-2.5-flash-lite"
OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a Visual Timeline Planner for a Spanish-language YouTube documentary channel called "Farandula" — a channel about the hidden lives of Latin American celebrities: their rise, their fall, their loves, illnesses, and legacies.

YOUR JOB: Read the narration and find moments where one of the TRIGGER TYPES below appears. At that exact second, schedule an AI-generated image insert that reinforces what the narrator is saying.

THE TRIGGERS — only insert when the narration clearly mentions one of these 17:

1. POBREZA — humble origins, poor neighborhood, struggling family, no money growing up, misery, childhood poverty
   → Visuals: modest unpainted house on a dusty Latin American street, barefoot child looking out a window, simple clothesline with worn clothes, small kitchen with cracked walls
   → ia_prompt must show: humble neighborhood, simple house, poverty — NOT luxury

2. HOSPITAL — hospital visit, surgery, medical emergency, health crisis, recovery, OR any medical personnel: tired doctors, nurses, surgeon
   → Visuals: empty hospital corridor with fluorescent lights, ambulance entrance at night, tired doctors in scrubs sitting in a hallway, medical staff in white coats
   → ia_prompt must show: hospital setting or medical personnel — no faces

3. ROMANCE — a romantic relationship, a lover, spouse, affair, much younger partner, "the love of their life"
   → Visuals: silhouette of the PARTNER (not the celebrity) from behind, no face. Adapt:
     - Male celebrity → feminine silhouette in a doorway or by a window
     - Female celebrity → masculine silhouette in a corridor
     - "much younger" → slender youthful figure
   → Always: "seen from behind, no face visible, cinematic romantic lighting, no text"

4. FUNERAL — death, dying, burial, coffin (ataúd), wake (velorio), cemetery, mourners crying, people in black
   → Visuals: single closed coffin in a dim chapel, cemetery path at dusk, mourners in black around a grave (no faces), white flowers on dark wood, candlelit wake room
   → ia_prompt must show: funeral setting — no faces, somber lighting

5. ENFERMEDAD — specific disease destroying the body: cirrhosis, cancer, addiction, alcoholism, overdose, hepatitis — NOT a hospital visit, but the disease itself
   → Visuals: medical illustration of affected organ, X-ray on a lightbox, prescription bottles on a nightstand, empty pill bottles — no faces, no readable text

6. CAIDA — forced retirement, exile, scandal, being forgotten by the industry, public humiliation, career collapse, blacklisting
   → Visuals: empty theater seats with a single spotlight on an empty stage, a closed venue with a rusted lock, a forgotten newspaper on a bench, a dark empty dressing room
   → ia_prompt must show: emptiness, abandonment, end of glory — no people visible

7. FAMA — sold-out concert, stadium full of people, career peak, being at the top, applause, crowd cheering
   → Visuals: packed concert venue seen from the back, stadium with thousands of people, spotlights on an empty stage at night (no performer faces), marquee sign with celebrity's name in lights
   → ia_prompt must show: crowd, stadium, stage — no faces

8. TELEVISION — TV show filming, telenovela set, cameras on set, studio lights, being on television, ratings
   → Visuals: vintage TV studio set with old cameras on pedestals, director's clapper board in front of lights, broadcast booth with old monitors, empty telenovela set with dramatic lighting
   → ia_prompt must show: TV studio or filming equipment — no faces, no readable text

9. PRENSA — newspaper headlines about the celebrity, tabloid scandal, press coverage, magazine covers, paparazzi
   → Visuals: stack of vintage Spanish-language newspapers, close-up of a front page (no readable text), printing press rollers, photographers with cameras (no faces)
   → ia_prompt must show: newspapers, press — no readable text

10. CIUDAD — a specific city or neighborhood tied to the celebrity's life: birthplace, city where they grew up, lived, or performed
    → Visuals: aerial view or street-level shot of that specific city in the correct era (vintage or modern)
    → ia_prompt must include the city name and era

11. INTERIOR — a specific room described cinematically: hotel room, dressing room, recording studio, office, corridor, backstage, apartment
    → Visuals: dimly lit hotel corridor with closed doors, empty dressing room with lights around the mirror, small recording studio with old microphone, backstage hallway with bare bulbs
    → ia_prompt must show: interior setting, atmospheric lighting — no people visible

12. DOCUMENTO — official documents, contracts, divorce papers, court orders, legal proceedings, a signature being placed
    → Visuals: close-up of official document with rubber stamp impression, stack of legal papers on a desk, notary office with ink and papers, manila envelope on a wooden desk
    → ia_prompt must show: documents, paper, stamps — no readable text, no faces

13. DINERO — money, debts, financial problems, bills, contracts, earnings, payments, celebrity's fortune or poverty of finances
    → Visuals: stack of peso bills on a table, empty wallet, overdue bills scattered on a desk, hands counting cash
    → ia_prompt must show: cash, peso bills, or debt-related scene — no faces

14. CINE — film role, movie premiere, cinema, filming a scene, a movie theater
    → Visuals: vintage movie theater marquee at night, empty cinema seats with screen glowing, film reel on a projector, premiere red carpet (no faces)
    → ia_prompt must show: cinema, movie theater, or film set — no faces

15. RADIO — radio show, broadcasting, radio interview, radio debut, being on the air
    → Visuals: vintage radio microphone in a small broadcast booth, old radio equipment with glowing dials, radio tower at dusk
    → ia_prompt must show: vintage radio studio or equipment — no faces

16. CONCIERTO — a specific concert, sold-out show, theater performance, arena or stadium show, performing live on stage
    → Visuals: empty concert stage with spotlights, arena viewed from the back with stage in distance, theater stage curtain, stadium seats empty
    → ia_prompt must show: concert stage, empty theater, or stadium — no faces
    → NOTE: use FAMA when the narration emphasizes crowd/success; use CONCIERTO when it describes the specific event/venue

17. ACCIDENTE — car accident, crash, physical incident, injury from an accident, something that went wrong physically
    → Visuals: empty road at night with headlights, damaged car on roadside, police tape on a road, ambulance lights reflected on wet asphalt
    → ia_prompt must show: accident scene, empty road, or emergency vehicles — no people visible

STRICT RULE — TRIGGER NAMES: You MUST use ONLY these exact trigger_type values:
"POBREZA", "HOSPITAL", "ROMANCE", "FUNERAL", "ENFERMEDAD", "CAIDA", "FAMA", "TELEVISION", "PRENSA", "CIUDAD", "INTERIOR", "DOCUMENTO", "DINERO", "CINE", "RADIO", "CONCIERTO", "ACCIDENTE"
Do NOT use: "PODER", "SECRETO", "CRIMEN", "CAIDA_EMOCIONAL", "CONCERT", "CINEMA", "MONEY" or any other variation. Only the 17 names exactly as listed.

RULES:
- source is ALWAYS "flow" — all images are AI-generated
- ia_prompt: always in English, very specific and cinematic
  - Before 1960: prefix with "black and white, film grain, silver gelatin photography, period-accurate"
  - 1960–1989: prefix with "vintage warm color, faded film look, period-accurate"
  - 1990+: prefix with "realistic documentary photograph, warm tones"
  - Always end with: "cinematic lighting, no text, no letters, no words, no faces visible"
- NEVER generate real people's faces
- NEVER show readable text
- Duration: 3–8 seconds MAX per segment
- No overlapping segments
- 2–4 inserts per 90-second batch

OUTPUT FORMAT — valid JSON only:
{
  "visual_timeline": [
    {
      "segment_id": 1,
      "trigger_type": "FAMA",
      "start_seconds": 45.2,
      "end_seconds": 51.8,
      "duration": 6.6,
      "source": "flow",
      "ia_prompt": "vintage color documentary photograph, faded Kodachrome, packed concert venue seen from the back, thousands of people cheering, stage with bright spotlights in the distance, 1970s Mexico, cinematic lighting, no text, no letters, no words, no faces visible",
      "scene_description": "Narrador menciona que llenaba estadios en los años 70"
    }
  ]
}

⚠️ OVERRIDE RULE — EXACT ANCHOR (read before writing ia_prompt):
Before writing ia_prompt, ask: "What specific noun, object, place, or action does the narration literally name at this timestamp?"
If the narration names something SPECIFIC — a market, a shop, a stage, a studio, a street, a specific city building, a disease, a document — illustrate THAT SPECIFIC THING, even if it deviates from the trigger type's default visual.
The trigger type only classifies the category. The ia_prompt MUST match what the narration literally says.

✅ CORRECT: narration "trabajaba en los mercados de La Merced" → show La Merced market (NOT a generic humble street)
❌ WRONG: narration "trabajaba en los mercados de La Merced" → show a modest unpainted house (that's POBREZA default but doesn't match)
✅ CORRECT: narration "firmó contrato en Televisa por 50 mil pesos" → show a signed contract on a desk (NOT a TV studio)
❌ WRONG: narration "firmó contrato en Televisa por 50 mil pesos" → show stacks of bills (that's DINERO default but doesn't match)
✅ CORRECT: narration "llenó el Palacio de los Deportes tres noches seguidas" → show an empty sports arena interior with spotlights (NOT a generic stadium exterior)
❌ WRONG: narration "llenó el Palacio de los Deportes tres noches seguidas" → show a generic crowd (ignores the specific venue)

The trigger type's default visual is the FALLBACK for generic mentions only. When narration is specific → always match the specific noun.

CONSTRAINTS:
- 2–4 inserts per 90-second batch
- Each insert: 3.0s minimum, 8.0s maximum
- No overlapping segments
- If a batch has no genuine triggers → return empty array
- ONLY insert on genuine trigger moments"""

USER_TEMPLATE = """BATCH {batch_number} of {total_batches}
TIME WINDOW: {batch_start}s → {batch_end}s
CELEBRITY/VIDEO: {video_name}

NARRATION (timestamps in seconds):
{sentences_json}

Find POBREZA / HOSPITAL / ROMANCE / FUNERAL / ENFERMEDAD / CAIDA / FAMA / TELEVISION / PRENSA / CIUDAD / INTERIOR / DOCUMENTO / DINERO / CINE / RADIO / CONCIERTO / ACCIDENTE trigger moments.
JSON only."""


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


def make_batches(entries):
    batches = []
    cur, cur_start = [], None
    for e in entries:
        if cur_start is None:
            cur_start = e['t']
        if e['t'] - cur_start >= BATCH_SECONDS and cur:
            batches.append(cur)
            cur, cur_start = [e], e['t']
        else:
            cur.append(e)
    if cur:
        batches.append(cur)
    return batches


def call_openrouter(api_key, video_name, batch, batch_num, total_batches):
    b_start = batch[0]['t']
    b_end   = batch[-1]['end']
    payload = json.dumps({
        "model": OR_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(
                batch_number=batch_num,
                total_batches=total_batches,
                batch_start=b_start,
                batch_end=b_end,
                video_name=video_name,
                sentences_json=json.dumps(batch, ensure_ascii=False)
            )}
        ],
        "temperature": 0.3,
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
                    "X-Title":       "Farandula Mono Timeline",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            raw    = data['choices'][0]['message']['content']
            parsed = json.loads(raw)
            return parsed.get('visual_timeline', [])
        except Exception as e:
            print(f"    Intento {attempt}/3 fallido: {e}")
            if attempt < 3:
                time.sleep(3 * attempt)
    return []


VALID_TRIGGERS = {
    "POBREZA","HOSPITAL","ROMANCE","FUNERAL","ENFERMEDAD",
    "CAIDA","FAMA","TELEVISION","PRENSA","CIUDAD","INTERIOR","DOCUMENTO",
    "DINERO","CINE","RADIO","CONCIERTO","ACCIDENTE"
}

TRIGGER_COLORS = {
    "POBREZA":     "#f59e0b",
    "HOSPITAL":    "#ef4444",
    "ROMANCE":     "#be185d",
    "FUNERAL":     "#1e293b",
    "ENFERMEDAD":  "#7f1d1d",
    "CAIDA":       "#64748b",
    "FAMA":        "#a855f7",
    "TELEVISION":  "#06b6d4",
    "PRENSA":      "#8b5cf6",
    "CIUDAD":      "#3b82f6",
    "INTERIOR":    "#475569",
    "DOCUMENTO":   "#78716c",
    "DINERO":      "#16a34a",
    "CINE":        "#d97706",
    "RADIO":       "#0891b2",
    "CONCIERTO":   "#9333ea",
    "ACCIDENTE":   "#dc2626",
}


def sanitize_timeline(segments):
    if not segments:
        return segments
    MIN_GAP_SECS = 5.0
    segments = sorted(segments, key=lambda s: s['start_seconds'])
    for s in segments:
        duration = s['end_seconds'] - s['start_seconds']
        if duration > MAX_CLIP_SECS:
            s['end_seconds'] = round(s['start_seconds'] + MAX_CLIP_SECS, 3)
        s['duration'] = round(s['end_seconds'] - s['start_seconds'], 3)
    for i in range(len(segments) - 1):
        cur, nxt = segments[i], segments[i + 1]
        gap = nxt['start_seconds'] - cur['end_seconds']
        # 3a. Overlap: recortar cur
        if cur['end_seconds'] > nxt['start_seconds']:
            cur['end_seconds'] = round(nxt['start_seconds'] - 0.001, 3)
            cur['duration']    = round(cur['end_seconds'] - cur['start_seconds'], 3)
            if cur['duration'] < 1.0:
                cur['_delete'] = True
        # 3b. Gap < 5s: mover nxt hacia adelante
        elif 0 <= gap < MIN_GAP_SECS:
            nxt['start_seconds'] = round(cur['end_seconds'] + MIN_GAP_SECS, 3)
            nxt['end_seconds']   = round(nxt['start_seconds'] + nxt.get('duration', MAX_CLIP_SECS), 3)
            nxt['duration']      = round(nxt['end_seconds'] - nxt['start_seconds'], 3)
    segments = [s for s in segments if not s.get('_delete')]
    segments = [s for s in segments if s['duration'] >= MIN_SEG_SECS]
    before   = len(segments)
    segments = [s for s in segments
                if s.get('trigger_type', '') in VALID_TRIGGERS
                and len(s.get('ia_prompt', '').strip()) >= 10]
    if len(segments) < before:
        print(f"    ⚠ {before - len(segments)} descartados (trigger inválido o prompt vacío)")
    seen, unique = set(), []
    for s in segments:
        key = s.get('ia_prompt', '').strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 Farandula/generar_timeline_farandula_mono.py 'Farandula/NOMBRE/'")
        sys.exit(1)

    carpeta  = pathlib.Path(sys.argv[1])
    nombre   = carpeta.name
    # SRT puede estar en la raíz de la carpeta con distintos nombres
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
    print(f"  TIMELINE FARANDULA MONO — {video_name.upper()}")
    print(f"  SRT: {srt_file.name} (primeros {MAX_SRT_SECS}s)")
    print(f"  Triggers: POBREZA · HOSPITAL · ROMANCE · FUNERAL · ENFERMEDAD")
    print(f"            CAIDA · FAMA · TELEVISION · PRENSA · CIUDAD · INTERIOR · DOCUMENTO")
    print(f"{'═'*62}\n")

    entries = parse_srt(srt_file)
    if not entries:
        print("ERROR: SRT vacío o no parseable"); sys.exit(1)

    print(f"  SRT: {len(entries)} entradas hasta {MAX_SRT_SECS}s")

    batches      = make_batches(entries)
    total_batches = len(batches)
    print(f"  Batches: {total_batches} × {BATCH_SECONDS}s\n")

    all_segments    = []
    segment_counter = 1

    for i, batch in enumerate(batches, 1):
        b_start = batch[0]['t']
        b_end   = batch[-1]['end']
        print(f"  [{i:02d}/{total_batches}] {b_start:.1f}s → {b_end:.1f}s  ({len(batch)} entradas)...", end='', flush=True)

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
        print("ERROR: Gemini no generó ningún segmento. Revisar el SRT o el prompt.")
        sys.exit(1)

    all_segments = sanitize_timeline(all_segments)

    # Renumerar secuencialmente tras sanitize
    for i, s in enumerate(all_segments, 1):
        s['segment_id'] = i

    # Segundo pase LLM: verificar que ia_prompt coincida con el audio exacto
    print("\n  Verificando coherencia prompt ↔ audio (segundo pase LLM)...")
    all_segments = auto_fix_prompts(all_segments, api_key)

    out_file.write_text(
        json.dumps({"visual_timeline": all_segments}, ensure_ascii=False, indent=2),
        encoding='utf-8'
    )

    print(f"\n{'─'*62}")
    print(f"  ✓ {len(all_segments)} segmentos → {out_file}")
    print(f"\n  PRÓXIMO PASO:")
    print(f"  → Revisar hook_timeline.json")
    print(f"  → Correr: python3 Farandula/harvester_farandula.py '{carpeta}/' --solo-hook")
    print(f"  → Esperar VEO3 → --solo-descargar-hook")
    print(f"{'─'*62}\n")


if __name__ == "__main__":
    main()
