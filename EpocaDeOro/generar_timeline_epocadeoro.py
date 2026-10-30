#!/usr/bin/env python3
"""
generar_timeline_epocadeoro.py — Genera timeline visual anclado al SRT.

Uso:
  python3 generar_timeline_epocadeoro.py "Video-001 Murieron en la Miseria/"

Salida:
  VIDEO_FOLDER/05-montaje/timeline.json   (formato approval_solo.py)

Luego lanza approval_solo.py en http://localhost:5099
"""

import sys, re, json, pathlib, subprocess, urllib.request, urllib.error, time
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from timeline_prompt_fixer import auto_fix_prompts

BASE      = pathlib.Path("/Users/anyelocuesta/Downloads/Canales/EpocaDeOro")
CANALES   = pathlib.Path("/Users/anyelocuesta/Downloads/Canales")
APPROVAL  = CANALES / "approval_solo.py"

KEY_FILE    = pathlib.Path.home() / ".openrouter_key"
OR_MODEL    = "google/gemini-2.5-flash-lite"
OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """Eres un director de fotografía de archivo especializado en la Época de Oro del Cine Mexicano (1930-1970).
Tu tarea: dado un fragmento de narración en español y el tipo de trigger visual, genera UN prompt en inglés para generación de imagen IA.

REGLAS OBLIGATORIAS:
- El prompt DEBE ilustrar EXACTAMENTE lo que dice el fragmento — si dice "Valencia, España" → foto de Valencia España; si dice "Hollywood" → Hollywood; si dice "Cuernavaca" → Cuernavaca
- ANTES de escribir el prompt, identifica el SUSTANTIVO ESPECÍFICO que menciona el fragmento (una ciudad concreta, un edificio concreto, un objeto concreto, una acción concreta). El prompt DEBE mostrar ESE sustantivo.
- Si el fragmento menciona "el Teatro Lírico de Ciudad de México" → mostrar ese teatro específico, NO un set genérico de cine
- Si el fragmento menciona "falleció en Cuernavaca" → mostrar Cuernavaca, NO un velorio genérico
- Si el fragmento menciona "firmó con la XEW" → mostrar estudio de radio de la XEW, NO un set de filmación
- Los prompts genéricos (fallback) se usan SOLO cuando el fragmento no nombra nada específico
- Estilo SIEMPRE: vintage black and white hyperrealistic photograph, heavy film grain, cinematic shadows
- Época: 1930s-1970s según el contexto
- NUNCA mostrar caras reconocibles de personas reales
- NUNCA texto visible en la imagen
- Máximo 120 palabras
- Responde SOLO con el prompt en inglés, sin explicaciones"""

# ─── Triggers ──────────────────────────────────────────────────────────────────
TRIGGERS = {
    "MUERTE": {
        "keywords": [
            r"\bmurió\b", r"\bmurieron\b", r"\bfalleció\b", r"\bfallecieron\b",
            r"\bmuerte\b", r"\bfallecimiento\b", r"\bpartió\b", r"\bperdió la vida\b",
            r"\bfue encontrado muerto\b", r"\bsu último\b", r"\bsu final\b",
            r"\bsu muerte\b", r"\bel día que murió\b",
        ],
        "prompt_es": "Fotografía vintage en blanco y negro hiperrealista, escena dramática de funeral mexicano años 1940-1960, féretro con flores, dolientes vestidos de negro, iluminación de vela, grano de película, atmósfera densa y melancólica",
        "prompt_en": "Vintage black and white hyperrealistic photograph, dramatic Mexican funeral scene 1940s-1960s, coffin with flowers, mourners in black, candlelight, heavy film grain, melancholic atmosphere, cinematic shadows",
    },
    "POBREZA": {
        "keywords": [
            r"\bpobreza\b", r"\bpobre\b", r"\bpobres\b", r"\bmiseria\b",
            r"\bsin dinero\b", r"\bsin un centavo\b", r"\bhambre\b", r"\bescasez\b",
            r"\bhumilde\b", r"\bhumildes\b", r"\bsin recursos\b", r"\bprecario\b",
            r"\bnada que comer\b", r"\bno tenía nada\b",
        ],
        "prompt_es": "Fotografía vintage en blanco y negro hiperrealista, familia mexicana en pobreza extrema años 1940s, cuarto humilde, ropa raída, luz tenue que entra por ventana pequeña, grano de película pronunciado, realismo documental",
        "prompt_en": "Vintage black and white hyperrealistic photograph, Mexican family in extreme poverty 1940s, humble one-room home, worn clothing, dim window light, heavy film grain, documentary realism, harsh shadows",
    },
    "DEUDA": {
        "keywords": [
            r"\bdeuda\b", r"\bdeudas\b", r"\bdebía\b", r"\badeudaba\b",
            r"\bpréstamo\b", r"\bprestó\b", r"\bcobrar\b", r"\bembargado\b",
            r"\bacreedor\b", r"\bacreedores\b", r"\bno pudo pagar\b",
            r"\bsin pagar\b", r"\blo que debía\b",
        ],
        "prompt_es": "Fotografía vintage en blanco y negro hiperrealista, hombre en oficina bancaria años 1950s firmando documentos con expresión tensa, papeles sobre escritorio oscuro, iluminación dramática de lámpara de escritorio, México antiguo",
        "prompt_en": "Vintage black and white hyperrealistic photograph, man in 1950s Mexican bank office signing documents with tense expression, papers on dark desk, dramatic desk lamp lighting, film noir aesthetic, heavy grain",
    },
    "LUGAR": {
        "keywords": [
            r"\bnació en\b", r"\bnacido en\b", r"\boriginario de\b",
            r"\bllegó a México\b", r"\bllegó a\b", r"\bse mudó a\b",
            r"\bviajó a\b", r"\bMéxico\b", r"\bEspaña\b", r"\bHollywood\b",
            r"\bGuadalajara\b", r"\bVeracruz\b", r"\bCiudad de México\b",
            r"\bla capital\b", r"\bArgentina\b", r"\bCuba\b",
            r"\bEuropa\b", r"\bEstados Unidos\b",
        ],
        "prompt_es": "Fotografía vintage en blanco y negro hiperrealista, calle del centro histórico de la Ciudad de México años 1940s-1950s, tranvías, edificios art déco, peatones vestidos de época, luz de tarde, grano de película",
        "prompt_en": "Vintage black and white hyperrealistic photograph, historic downtown Mexico City street 1940s-1950s, trams, art deco buildings, period-dressed pedestrians, afternoon light, heavy film grain, cinematic composition",
    },
    "CONTRATO": {
        "keywords": [
            r"\bcontrato\b", r"\bcontrató\b", r"\bfirmó\b", r"\bfirmar\b",
            r"\bproducción\b", r"\bpelícula\b", r"\bpelicula\b",
            r"\bestudio\b", r"\bMGM\b", r"\bColumbia\b", r"\bCinema\b",
            r"\bcinematográfico\b", r"\bla cámara\b", r"\bfue elegido\b",
            r"\bse le ofreció\b", r"\bpapel\b",
        ],
        "prompt_es": "Fotografía vintage en blanco y negro hiperrealista, set de filmación cinematográfica mexicana años 1950s, cámaras de cine de época, reflectores, actores de espaldas, director con megáfono, atmósfera de la Época de Oro",
        "prompt_en": "Vintage black and white hyperrealistic photograph, Mexican Golden Age film set 1950s, vintage movie cameras, studio lights, actors from behind, director with megaphone, Epoca de Oro atmosphere, high contrast",
    },
    "RIQUEZA": {
        "keywords": [
            r"\briqueza\b", r"\bfortuna\b", r"\béxito\b", r"\bfama\b",
            r"\bganó millones\b", r"\bmillones\b", r"\bdinero\b",
            r"\bopulencia\b", r"\blujoso\b", r"\bmansión\b",
            r"\ben la cima\b", r"\bcumbre\b", r"\bel más famoso\b",
        ],
        "prompt_es": "Fotografía vintage en blanco y negro hiperrealista, mansión lujosa mexicana años 1950s, salón de baile, champán, mujeres elegantes y hombres de traje, candelabros de cristal, fotografía de alta sociedad de la Época de Oro",
        "prompt_en": "Vintage black and white hyperrealistic photograph, luxurious Mexican mansion 1950s, ballroom scene, champagne, elegant women and suited men, crystal chandeliers, high society Golden Age photography, dramatic lighting",
    },
    "HOSPITAL": {
        "keywords": [
            r"\bhospital\b", r"\bclinica\b", r"\bcama de hospital\b",
            r"\benfermó\b", r"\benfermedad\b", r"\benferma\b", r"\benfermo\b",
            r"\btuberculos\b", r"\bcancer\b", r"\bcáncer\b",
            r"\bsalud\b", r"\bmédico\b", r"\bdoctor\b",
            r"\boperación\b", r"\boperar\b", r"\bconvaleci\b",
            r"\bdiagnóst\b", r"\bagoni\b",
        ],
        "prompt_es": "Fotografía vintage en blanco y negro hiperrealista, sala de hospital mexicano años 1940s-1950s, cama de metal blanca, enfermera con cofia, ventanas con luz dura, ambiente clínico austero, grano de película pronunciado",
        "prompt_en": "Vintage black and white hyperrealistic photograph, Mexican hospital room 1940s-1950s, white metal hospital bed, nurse in cap, harsh window light, austere clinical atmosphere, heavy film grain, documentary realism",
    },
}

# Prioridad de triggers cuando coinciden varios en el mismo bloque
TRIGGER_PRIORITY = ["MUERTE", "HOSPITAL", "DEUDA", "POBREZA", "RIQUEZA", "CONTRATO", "LUGAR"]

SEG_DUR_MAX = 8   # cap duro — nunca más de 8s
SEG_DUR_MIN = 3   # mínimo viable


def load_api_key():
    try:
        return KEY_FILE.read_text().strip()
    except Exception:
        import os
        return os.environ.get("OPENROUTER_API_KEY", "")


def generate_prompt_gemini(api_key, trigger_type, srt_text, fallback_prompt):
    """Genera un prompt específico basado en el texto del SRT."""
    if not api_key:
        return fallback_prompt

    user_msg = f"Trigger: {trigger_type}\nFragmento de narración: \"{srt_text}\"\n\nGenera el prompt de imagen:"

    body = json.dumps({
        "model": OR_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        "max_tokens": 200,
        "temperature": 0.7,
    }).encode()

    req = urllib.request.Request(
        OR_ENDPOINT,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"    ⚠ Gemini falló ({e}) — usando prompt por defecto")
        return fallback_prompt


def parse_srt(srt_path):
    """Devuelve lista de {start, end, text}."""
    text = srt_path.read_text(encoding="utf-8")
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    entries = []
    for b in blocks:
        lines = b.split("\n")
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        t_parts = lines[1].split("-->")
        def to_sec(ts):
            h, m, s = ts.strip().replace(",", ".").split(":")
            return float(h) * 3600 + float(m) * 60 + float(s)
        entries.append({
            "start": to_sec(t_parts[0]),
            "end":   to_sec(t_parts[1]),
            "text":  " ".join(lines[2:]).strip(),
        })
    return entries


def detect_trigger(text):
    """Retorna el tipo de trigger con mayor prioridad que matchea, o None."""
    text_lower = text.lower()
    for trigger in TRIGGER_PRIORITY:
        for kw in TRIGGERS[trigger]["keywords"]:
            if re.search(kw, text_lower, re.IGNORECASE):
                return trigger
    return None


def srt_window_text(entries, start, end):
    """Texto concatenado de todos los bloques SRT en el rango start→end."""
    return " ".join(e["text"] for e in entries if e["start"] >= start and e["end"] <= end)


def generate_timeline(video_folder, max_seconds=600, api_key=""):
    """
    Analiza el SRT en los primeros max_seconds y genera segmentos visuales
    en el formato que espera approval_solo.py (campo ia_prompt único).
    """
    srt_path = video_folder / "audio.srt"
    ts_path  = video_folder / "timestamps.json"

    if not srt_path.exists():
        print(f"✗ No existe {srt_path}"); sys.exit(1)
    if not ts_path.exists():
        print(f"✗ No existe {ts_path}"); sys.exit(1)

    srt_entries  = parse_srt(srt_path)
    timestamps   = json.loads(ts_path.read_text())
    # Incluir hook + artistas; excluir solo cierre y mid-roll
    artists_only = [t for t in timestamps if not t.get("is_cierre")]

    segments     = []
    seg_id       = 1
    last_seg_end = 0

    for artist in artists_only:
        a_start = artist["start"]
        a_end   = a_start + artist["duration"]
        if a_start >= max_seconds:
            break

        a_label       = artist["label"]
        a_name        = artist["name"]
        effective_end = min(a_end, max_seconds)

        print(f"\n  Analizando: {a_label} ({a_start:.0f}s → {effective_end:.0f}s)")

        # Bloques SRT del artista (en orden)
        artist_entries = [e for e in srt_entries
                          if e["start"] >= a_start and e["start"] < effective_end]

        i = 0
        while i < len(artist_entries):
            entry = artist_entries[i]
            trigger = detect_trigger(entry["text"])
            if not trigger:
                i += 1
                continue

            seg_start = int(entry["start"])

            # Gap mínimo 5s desde el último segmento
            if seg_start < last_seg_end + 5:
                i += 1
                continue

            srt_text = entry["text"]

            # Avanzar mientras el SRT siga hablando del mismo tema
            # (bloques consecutivos que también matchean el mismo trigger)
            j = i + 1
            seg_end = int(entry["end"])
            while j < len(artist_entries):
                next_entry = artist_entries[j]
                next_trigger = detect_trigger(next_entry["text"])
                if next_trigger == trigger:
                    seg_end = int(next_entry["end"])
                    j += 1
                else:
                    break

            # Aplicar cap: mínimo SEG_DUR_MIN, máximo SEG_DUR_MAX
            raw_dur   = seg_end - seg_start
            actual_dur = max(SEG_DUR_MIN, min(SEG_DUR_MAX, raw_dur))
            seg_end    = seg_start + actual_dur

            if actual_dur < SEG_DUR_MIN:
                i += 1
                continue

            i = j  # saltar los bloques ya consumidos

            tdata = TRIGGERS[trigger]
            ia_prompt = generate_prompt_gemini(
                api_key, trigger, srt_text[:200], tdata["prompt_en"]
            )
            seg = {
                "segment_id":           seg_id,
                "artist_label":         a_label,
                "artist_name":          a_name,
                "trigger_type":         trigger,
                "start_seconds":        seg_start,
                "end_seconds":          seg_end,
                "duration":             actual_dur,
                "srt_text":             srt_text[:120],
                "covers_text":          srt_text[:120],
                "ia_prompt":            ia_prompt,
                "scene_description_es": tdata["prompt_es"],
                "image_path":           None,
            }
            segments.append(seg)
            last_seg_end = seg_end
            seg_id += 1
            print(f"    [{trigger:10s}] t={seg_start}s→{seg_end}s ({actual_dur}s)  \"{srt_text[:50]}\"")

    return segments


# ─── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 generar_timeline_epocadeoro.py 'Video-001 Murieron en la Miseria/'")
        sys.exit(1)

    folder_arg   = sys.argv[1].rstrip("/")
    video_folder = BASE / folder_arg
    if not video_folder.exists():
        print(f"✗ No existe: {video_folder}"); sys.exit(1)

    max_sec = int(sys.argv[2]) if len(sys.argv) > 2 else 600

    print(f"\n  La Verdad Dorada — Generador de Timeline Visual")
    print(f"  Carpeta: {video_folder.name}")
    print(f"  Analizando primeros {max_sec}s del audio…")

    api_key = load_api_key()
    if api_key:
        print(f"  🤖 Gemini activo — prompts específicos por segmento")
    else:
        print(f"  ⚠ Sin API key — usando prompts genéricos (crea ~/.openrouter_key)")

    segments = generate_timeline(video_folder, max_seconds=max_sec, api_key=api_key)

    # Segundo pase LLM: verificar que ia_prompt coincida con el audio exacto
    if segments and api_key:
        print(f"\n  Verificando coherencia prompt ↔ audio (segundo pase LLM)...")
        segments = auto_fix_prompts(segments, api_key)

    # Guardar en 05-montaje/timeline.json (formato approval_solo.py)
    montaje_dir = video_folder / "05-montaje"
    montaje_dir.mkdir(exist_ok=True)
    timeline_path = montaje_dir / "timeline.json"
    data = {
        "video":           video_folder.name,
        "visual_timeline": segments,
        "approval_port":   5099,
    }
    timeline_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    print(f"\n  ✓ {len(segments)} segmentos → {timeline_path}")
    by_trigger = {}
    for s in segments:
        by_trigger[s["trigger_type"]] = by_trigger.get(s["trigger_type"], 0) + 1
    for t, n in sorted(by_trigger.items(), key=lambda x: -x[1]):
        print(f"    {t:12s}: {n}")

    print(f"\n  Lanzando approval_solo.py…")
    subprocess.run([
        "python3", str(APPROVAL),
        str(video_folder),
    ])
