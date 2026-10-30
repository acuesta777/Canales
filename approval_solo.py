#!/usr/bin/env python3
"""
Lanza solo la pantalla de aprobación desde un timeline.json existente.
Uso:
    python3 approval_solo.py secretos-mexicanos/jose-alfredo-jimenez
"""
import sys, json, pathlib, time, os, math
import urllib.request

from timeline_approval import (
    run_approval, upload_to_baserow, generate_ai33pro,
    generate_muapi, generate_flow_mcp, BASEROW_DEFAULTS,
)

TRIGGER_COLORS = {
    "CIUDAD":      "#3b82f6",
    "DOCUMENTO":   "#8b5cf6",
    "INTERIOR":    "#06b6d4",
    "DINERO":      "#10b981",
    "POBREZA":     "#f59e0b",
    "HOSPITAL":    "#ef4444",
    "CINE":        "#ec4899",
    "RADIO":       "#06b6d4",
    "CONCIERTO":   "#a855f7",
    "ACCIDENTE":   "#dc2626",
    "TRAICION":    "#ef4444",
    "SECRETO":     "#8b5cf6",
    "PODER":       "#f59e0b",
    "CRIMEN":      "#dc2626",
    "FUNERAL":     "#64748b",
    "ENFERMEDAD":  "#ef4444",
    "ROMANCE":     "#ec4899",
    # EpocaDeOro triggers
    "MUERTE":      "#ef4444",
    "HOSPITAL":    "#dc2626",
    "DEUDA":       "#6366f1",
    "POBREZA":     "#f59e0b",
    "RIQUEZA":     "#eab308",
    "LUGAR":       "#22c55e",
    "CONTRATO":    "#a855f7",
}

HOME        = pathlib.Path.home()
KEY_FILE    = HOME / ".openrouter_key"
OR_MODEL    = "google/gemini-2.5-flash-lite"
OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

JUDGE_SYSTEM = """You are a STRICT quality judge for a visual documentary timeline. You receive flow segments — each has a narration sentence and an image prompt (ia_prompt).

FAIL CONDITIONS — reject immediately if ANY of these are true:

1. INCOHERENT — the ia_prompt illustrates something not present in the narration sentence.
   - Ask yourself: "If I only read the narration, would I expect this image?" If NO → FAIL.
   - Examples of FAIL: narration describes someone's attitude/personality but prompt shows a newspaper. Narration is about a wedding but prompt shows court documents. Narration is metaphorical but prompt is literal.
   - Be strict: a weak or indirect connection is NOT enough. The connection must be direct and obvious.

2. DUPLICATE — the ia_prompt or escena_es is nearly identical (same subject, same visual) to another segment already reviewed OR already rewritten in this batch → REWRITE it to a DIFFERENT but thematically related visual. IMPORTANT: after you rewrite a prompt, treat your rewritten version as "already used" — the next duplicate must differ from BOTH the original AND your rewrite. Keep building a mental list of all visuals used so far (original + rewritten) and ensure every segment has a unique visual. Example chain for DOCUMENTO: seg A → jail bars, seg B (duplicate of A) → rewrite to legal folder with stamp, seg C (duplicate of B) → rewrite to judge's gavel on wooden block, seg D → rewrite to arrest warrant being stamped. Each one different. Mark verdict "pass" with the rewritten prompts.

3. MISSING STYLE FOOTER — prompt does not end with "cinematic lighting, no text, no letters, no words, no faces visible" → ADD it.

4. FACES OR TEXT — prompt requests visible faces, readable signs, logos, or names → REMOVE those references.

PASS: image directly and obviously illustrates what is narrated, correct era, correct footer, not a duplicate of a prior segment.

OUTPUT FORMAT — JSON only:
{
  "results": [
    {"segment_id": 1, "verdict": "pass", "ia_prompt": "...", "escena_es": "..."},
    {"segment_id": 3, "verdict": "reject", "reason": "prompt shows newspaper but narration describes personality/attitude — no press mentioned"}
  ]
}
Every segment_id in input MUST appear in output."""

def call_gemini_judge(api_key, flow_segments, retries=3):
    if not flow_segments:
        return []
    items = [{"segment_id": s["segment_id"], "trigger": s.get("trigger_type", "flow"),
               "narration": s.get("scene_description","")[:200],
               "ia_prompt": s.get("ia_prompt",""), "escena_es": s.get("escena_es","")}
             for s in flow_segments]
    payload = json.dumps({
        "model": OR_MODEL,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": f"Review these {len(items)} segments:\n\n{json.dumps(items, ensure_ascii=False, indent=2)}\n\nReturn JSON with results array."},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }).encode()
    for attempt in range(1, retries+1):
        try:
            req = urllib.request.Request(OR_ENDPOINT, data=payload, headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/secretos-mexicanos",
                "X-Title": "Secretos Mexicanos Judge",
            }, method="POST")
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read())
            return json.loads(data['choices'][0]['message']['content']).get('results', [])
        except Exception as e:
            print(f"    [Juez] Intento {attempt}/{retries} fallido: {e}")
            if attempt < retries:
                time.sleep(3 * attempt)
    return []

def run_judge(segments, api_key):
    """Corre el juez LLM sobre los segmentos flow y devuelve la lista corregida."""
    YT_CLIP_DUR = 5
    flow_segs = [s for s in segments if s.get('source') == 'flow']
    if not flow_segs:
        return segments

    print(f"\n  🔍 Juez LLM revisando {len(flow_segs)} segmentos flow...", flush=True)
    results = call_gemini_judge(api_key, flow_segs)
    rejected_ids = set()
    corrections  = {}
    for r in results:
        sid = r.get('segment_id')
        if r.get('verdict') == 'reject':
            rejected_ids.add(sid)
            print(f"    ✗ Seg {sid} rechazado: {r.get('reason','')[:80]}")
        elif r.get('verdict') == 'pass':
            corrections[sid] = {'ia_prompt': r.get('ia_prompt',''), 'escena_es': r.get('escena_es','')}

    new_segments = []
    for seg in segments:
        sid = seg['segment_id']
        if sid in rejected_ids and seg.get('source') == 'flow':
            dur = seg['end_seconds'] - seg['start_seconds']
            n = max(1, round(dur / YT_CLIP_DUR))
            chunk = dur / n
            for j in range(n):
                s2 = seg['start_seconds'] + j * chunk
                e2 = seg['start_seconds'] + (j+1) * chunk
                new_segments.append({
                    'trigger_type': 'YT_CLIP', 'source': 'yt_clip',
                    'start_seconds': int(round(s2)), 'end_seconds': int(round(e2)),
                    'duration': int(round(e2-s2)), 'ia_prompt': '', 'escena_es': '',
                    'scene_description': 'Clip YT',
                })
        else:
            if sid in corrections and seg.get('source') == 'flow':
                if corrections[sid].get('ia_prompt'):
                    seg['ia_prompt'] = corrections[sid]['ia_prompt']
                if corrections[sid].get('escena_es'):
                    seg['escena_es'] = corrections[sid]['escena_es']
            new_segments.append(seg)

    for idx, s in enumerate(new_segments, 1):
        s['segment_id'] = idx

    flow_final = sum(1 for s in new_segments if s.get('source') == 'flow')
    print(f"  ✅ Juez: {len(rejected_ids)} rechazados → YT_CLIP | Flow final: {flow_final}")

    # ── Pase determinista: deduplicar escena_es idénticas ───────────────────
    # Variantes en español (escena_es visible) — ia_prompt se construye en inglés internamente
    TRIGGER_VARIANTS = {
        "DOCUMENTO": [
            ("Carpeta de expediente judicial con sello de goma",        "worn legal file folder on a desk with rubber stamp"),
            ("Mazo de juez sobre mesa de sala de audiencias",           "judge's wooden gavel on a courtroom table"),
            ("Orden de arresto con sello oficial sobre escritorio",     "arrest warrant document with official wax seal on a desk"),
            ("Esposas sobre escritorio de madera junto a papeles",      "handcuffs resting on a wooden desk next to papers"),
            ("Pila de documentos judiciales atados con cinta roja",     "stack of court documents tied with red ribbon on a shelf"),
            ("Máquina de escribir antigua con papel legal a medias",    "old typewriter with legal paper half-typed in dim office light"),
        ],
        "CIUDAD": [
            ("Vista aérea panorámica de Ciudad de México al amanecer",  "wide aerial shot of Mexico City at dawn"),
            ("Esquina concurrida del Centro Histórico de CDMX",         "busy street corner in the historic center of Mexico City"),
            ("Plaza vacía de noche con arquitectura colonial",          "empty plaza at night with colonial architecture"),
            ("Mercado callejero lleno en ciudad mexicana",              "crowded market street in a Mexican city"),
            ("Entrada de autopista a ciudad mexicana al atardecer",     "highway entrance to a major Mexican city at dusk"),
            ("Azoteas de barrio urbano denso en México",                "rooftops of a dense urban Mexican neighborhood"),
        ],
        "DINERO": [
            ("Billetes de peso esparcidos sobre escritorio de madera",  "peso bills scattered on a wooden desk"),
            ("Cartera de cuero gastada y vacía sobre mesa",             "empty worn leather wallet on a table"),
            ("Pila de facturas vencidas con sellos rojos",              "stack of overdue bills with red stamps"),
            ("Sumadora antigua junto a libro de contabilidad",          "old adding machine next to a ledger book"),
            ("Monedas y billetes arrugados sobre superficie gastada",   "coins and crumpled bills on a worn surface"),
            ("Alcancía rota sobre piso de azulejos",                    "piggy bank broken on a tile floor"),
        ],
        "INTERIOR": [
            ("Habitación de hotel tenuemente iluminada con lámpara",    "dimly lit hotel room with single lamp on nightstand"),
            ("Oficina vacía con escritorio bajo luz fluorescente",      "empty office with desk and papers under fluorescent light"),
            ("Interior rústico de rancho con vigas y luz solar",        "rustic ranch interior with wooden beams and sunlight"),
            ("Pasillo de backstage con vestuario colgando",             "backstage corridor with hanging costumes"),
            ("Sala de apartamento escaso con una sola silla",           "sparse apartment living room with one chair"),
            ("Pasillo oscuro con puertas cerradas a cada lado",         "dark hallway with closed doors on each side"),
        ],
        "PRENSA": [
            ("Portada de periódico vintage en prensa de imprimir",      "vintage newspaper front page on a printing press"),
            ("Paparazzi con cámaras en entrada de evento",              "paparazzi photographers with cameras at an event entrance"),
            ("Pila de revistas antiguas en español sobre mesa",         "stack of old Spanish-language magazines on a table"),
            ("Libreta y pluma de periodista sobre mesa de prensa",      "journalist's notebook and pen on a press table"),
            ("Redacción con máquinas de escribir y papeles sueltos",    "newsroom with old typewriters and scattered papers"),
            ("Puesto de periódicos con portadas visibles",              "newspaper stand with headlines visible from outside"),
        ],
        "RADIO": [
            ("Estudio de radio vintage con micrófono grande y consola", "vintage radio studio with large microphone and soundboard"),
            ("Radio transistor antiguo encendido en mesa oscura",       "old transistor radio on a wooden table glowing in the dark"),
            ("Cabina de transmisión con grabadora de carrete",          "radio broadcast booth with reel-to-reel tape machine"),
            ("Primer plano de dial de radio con luz ámbar cálida",      "close-up of radio dial with warm amber glow"),
            ("Micrófono vintage en pie en sala de grabación tenue",     "vintage microphone on a stand in a dim recording room"),
            ("Pasillo de estudio de radio vacío con luz apagada",       "empty radio studio hallway with light off"),
        ],
        "CONCIERTO": [
            ("Escenario de concierto vacío con focos y humo",           "empty concert stage with spotlights and smoke"),
            ("Butacas de estadio vistas desde el escenario, vacías",    "stadium seats viewed from the stage, all empty"),
            ("Telón de backstage con luces de escena al fondo",         "backstage curtain with stage lights visible through gap"),
            ("Batería sola en escenario oscuro bajo un foco",           "drum kit alone on a dark stage under a single spotlight"),
            ("Entradas de concierto usadas esparcidas en el suelo",     "concert ticket stubs scattered on a wooden floor"),
            ("Amplificadores y stands de guitarra en escenario vacío",  "amplifiers and guitar stands on an empty stage"),
        ],
        "ROMANCE": [
            ("Silueta de mujer de espaldas en habitación tenue",        "silhouette of a woman from behind in a dimly lit room"),
            ("Dos copas de vino en mesa con vela, sin personas",        "two wine glasses on a candlelit table, no people"),
            ("Anillos de boda sobre superficie de madera",              "wedding rings on a wooden surface"),
            ("Banca de parque vacía al atardecer con hojas caídas",     "empty park bench at dusk with autumn leaves"),
            ("Carta de amor escrita a mano con pluma al lado",          "love letter handwritten on paper with pen beside it"),
            ("Ramo de flores marchitas sobre alféizar de ventana",      "bouquet of wilted flowers on a windowsill"),
        ],
        "CINE": [
            ("Marquesina de cine vintage iluminada de noche",           "vintage movie theater marquee with lights on at night"),
            ("Butacas vacías de cine con haz de proyección",            "empty cinema seats with projection light beam"),
            ("Carrete de película antiguo sobre mesa de madera",        "old film reel on a wooden table"),
            ("Claqueta de filmación en piso de set de cine",            "movie clapperboard on a film set floor"),
            ("Fila de afiches de películas vintage en pared",           "row of vintage film posters on a wall"),
            ("Ventana de cabina de proyección hacia teatro oscuro",     "projection booth window looking into dark theater"),
        ],
        "POBREZA": [
            ("Cocina humilde con mesa de madera y luz tenue",           "humble kitchen with bare wooden table and single light"),
            ("Zapatos gastados junto a cama simple en cuarto pequeño",  "worn shoes beside a simple bed in a small room"),
            ("Callejón angosto en barrio pobre mexicano al anochecer",  "narrow alley in a poor Mexican neighborhood at dusk"),
            ("Plato de hojalata vacío sobre mesa de madera",            "empty tin plate on a wooden table"),
            ("Cortina vieja rota ondeando en ventana de casa humilde",  "old torn curtain blowing in a window of a humble home"),
            ("Zapatos de niño fuera de puerta modesta",                 "children's shoes outside a modest doorway"),
        ],
    }

    # Dedup determinista: cada aparición N de un trigger → variante N de la lista
    trigger_count: dict = {}  # trigger_type → cuántas veces ha aparecido
    fixed_count = 0
    suffix = 'cinematic lighting, no text, no letters, no words, no faces visible'

    for seg in new_segments:
        if seg.get('source') != 'flow':
            continue
        ttype = seg.get('trigger_type', '')
        variants = TRIGGER_VARIANTS.get(ttype)
        if not variants:
            continue
        n = trigger_count.get(ttype, 0)
        trigger_count[ttype] = n + 1
        if n == 0:
            continue  # primera aparición: conservar prompt original de Gemini
        # Segunda aparición en adelante → asignar variante N-1
        v_es, v_en = variants[(n - 1) % len(variants)]
        prompt = seg.get('ia_prompt', '')
        era_prefix = 'black and white archival documentary photograph, film grain, high contrast, '
        for pfx in ['black and white archival documentary photograph, film grain, high contrast, ',
                    'vintage color documentary photograph, faded Kodachrome, ',
                    'realistic documentary photograph, warm tones, ']:
            if prompt.startswith(pfx):
                era_prefix = pfx
                break
        seg['ia_prompt'] = f"{era_prefix}{v_en}, {suffix}"
        seg['escena_es'] = v_es[:80]
        fixed_count += 1

    if fixed_count:
        print(f"  🔁 Dedup Python: {fixed_count} prompts variados por escena idéntica")

    return new_segments


def _kill_port(port):
    """Mata el proceso que ocupa `port` para que el nuevo arranque siempre ahí."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["lsof", "-ti", f"tcp:{port}"], text=True
        ).strip()
        if out:
            for pid in out.splitlines():
                subprocess.call(["kill", "-9", pid])
            time.sleep(1.5)
            print(f"  ⚡ Puerto {port} liberado (PID {out.strip()})")
    except subprocess.CalledProcessError:
        pass  # ya estaba libre


def _find_free_port(start=5099, end=5120):
    import socket
    for p in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start  # fallback

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 approval_solo.py <ruta-proyecto>")
        print("Ej:  python3 approval_solo.py secretos-mexicanos/jose-alfredo-jimenez")
        sys.exit(1)

    carpeta = pathlib.Path(sys.argv[1])
    if not carpeta.is_absolute():
        carpeta = pathlib.Path(__file__).parent / carpeta

    timeline_file = carpeta / "05-montaje" / "timeline.json"
    if not timeline_file.exists():
        print(f"❌ No existe: {timeline_file}")
        sys.exit(1)

    data = json.loads(timeline_file.read_text(encoding="utf-8"))
    segments = data.get("visual_timeline", data.get("segments", []))
    video_name = data.get("video", carpeta.name)

    # ── JUEZ LLM ────────────────────────────────────────────────────────────
    api_key = KEY_FILE.read_text().strip() if KEY_FILE.exists() else os.environ.get('OPENROUTER_API_KEY','')
    if api_key:
        segments = run_judge(segments, api_key)
        # Persistir el timeline corregido
        data["visual_timeline"] = segments
        data["total_segments"]  = len(segments)
        data["flow_segments"]   = sum(1 for s in segments if s.get('source') == 'flow')
        data["yt_segments"]     = sum(1 for s in segments if s.get('source') == 'yt_clip')
        timeline_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print("  ⚠ Sin API key — juez omitido")

    # ── VALIDADOR PREVIO ────────────────────────────────────────────────────
    flow_segs_all = [s for s in segments if s.get("source") == "flow"]
    sin_prompt = [s["segment_id"] for s in flow_segs_all if not s.get("ia_prompt","").strip()]
    prompts_ok = [s for s in flow_segs_all if s.get("ia_prompt","").strip()]

    print(f"\n  {'='*56}")
    print(f"  VALIDADOR — {video_name}")
    print(f"  {'='*56}")
    print(f"  Total segmentos : {len(segments)}")
    print(f"  IDs             : {[s['segment_id'] for s in segments]}")
    print(f"  Flow con prompt : {len(prompts_ok)}/{len(flow_segs_all)}")
    if sin_prompt:
        print(f"\n  ⛔ ERROR FATAL: {len(sin_prompt)} segmento(s) flow sin ia_prompt: {sin_prompt}")
        print(f"  approval_solo NO arranca — corregir el timeline.json y relanzar.")
        sys.exit(1)
    # Regenerar video_prompts.txt con TODOS los prompts (por posición)
    vp_file = carpeta / "05-montaje" / "video_prompts.txt"
    lines = [s["ia_prompt"].strip() for s in segments if s.get("ia_prompt","").strip()]
    vp_file.write_text("\n\n".join(lines), encoding="utf-8")
    print(f"  video_prompts   : {len(lines)} prompts → {vp_file.name}")
    print(f"  NOTA: generacion01=seg#{segments[0]['segment_id']}, gen{len(segments):02d}=seg#{segments[-1]['segment_id']}")
    print(f"  {'='*56}\n")
    # ── FIN VALIDADOR ───────────────────────────────────────────────────────

    # Puerto: arg CLI > timeline.json > 5099 (liberando el que lo ocupe)
    if len(sys.argv) >= 3 and sys.argv[2].isdigit():
        port = int(sys.argv[2])
    else:
        port = data.get("approval_port") or 5099
    _kill_port(port)

    # Solo mostrar segmentos flow que NO tienen clip descargado aún
    img_dir = carpeta / "03-imagenes"
    flow_only = [
        s for s in segments
        if s.get("source") == "flow"
    ]
    print(f"  📋 {len(flow_only)} segmentos flow (de {len(segments)} totales) en {video_name}")
    print(f"  🌐 http://localhost:{port}")

    approved, fuente, yt_segs = run_approval(
        segments=flow_only,
        video_name=video_name,
        carpeta=carpeta,
        trigger_colors=TRIGGER_COLORS,
        port=port,
    )

    if not approved and not yt_segs:
        print("  ❌ Sin segmentos aprobados.")
        sys.exit(0)

    print(f"\n  Fuente elegida: {fuente.upper()}")
    if fuente == "ai33pro":
        generate_ai33pro(approved, str(carpeta))
    elif fuente == "muapi":
        generate_muapi(approved, str(carpeta))
    elif fuente == "flow_mcp":
        generate_flow_mcp(approved, str(carpeta))
    elif fuente == "flow":
        print(f"  ✓ timeline.json guardado — corre harvester_timeline.py para subir a Flow.")
    else:
        print(f"  ⚠ Fuente '{fuente}' no reconocida")

if __name__ == "__main__":
    main()
