#!/usr/bin/env python3
"""
validar_prompts_timeline.py — Valida y corrige los ia_prompt del timeline
contra el guion real del personaje.

Usa el guion (.txt) + el SRT (.srt) para que el modelo LLM corrija cada
prompt asegurando que:
  - La época visual sea la correcta (año real de los eventos)
  - Los objetos/lugares sean los que menciona el guion
  - No haya prompts genéricos que no correspondan al personaje

Uso:
    python3 validar_prompts_timeline.py riqueza/alberto_del_rio/
"""

import sys, json, pathlib, urllib.request, urllib.error, re

HOME        = pathlib.Path.home()
KEY_FILE    = HOME / ".openrouter_key"
OR_MODEL    = "google/gemini-2.5-flash-lite"
OR_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """Eres un validador de prompts de imagen para un canal de YouTube en español sobre famosos.

Tu tarea: revisar los ia_prompt del timeline visual y corregirlos para que:
1. Sean ESPECÍFICOS al personaje y su historia real (no prompts genéricos)
2. La época visual sea correcta (si el evento fue en 2009, la imagen debe verse de 2009, no vintage)
3. Los objetos coincidan exactamente con lo que dice el guion (color, modelo, año, estilo)
4. El estilo cinematográfico sea adecuado a la época de la escena

REGLAS DE ÉPOCA VISUAL:
- Antes de 1940: "black and white film grain, high contrast"
- 1940-1960: "warm sepia, soft film grain, period accurate"
- 1960-1989: "vintage warm color, faded film look, period-accurate to the [decade]"
- 1990-2009: "modern color, slightly warm, contemporary"
- 2010+: "full color vivid, crisp, hyperrealistic, modern"

FORMATO DE RESPUESTA — devuelve ÚNICAMENTE JSON válido, sin markdown:
{
  "correcciones": [
    {
      "segment_id": 1,
      "problema": "descripción del problema con el prompt original",
      "ia_prompt_corregido": "Cinematic hyperrealistic photo of..."
    }
  ]
}

Si un prompt ya es correcto y específico, NO lo incluyas en correcciones.
Siempre termina el ia_prompt con ", 16:9".
"""

def load_key():
    if not KEY_FILE.exists():
        raise FileNotFoundError(f"No se encontró {KEY_FILE}")
    return KEY_FILE.read_text().strip()

def call_llm(key: str, messages: list) -> str:
    body = json.dumps({
        "model": OR_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 8000,
    }).encode()
    req = urllib.request.Request(OR_ENDPOINT, data=body, method="POST", headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://canales.local",
    })
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]

def extract_json(text: str) -> dict:
    text = text.strip()
    # Quitar markdown code fences si las hay
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    return json.loads(text)

def load_srt_context(srt_path: pathlib.Path) -> str:
    """Extrae los primeros 10 min del SRT como texto plano con timestamps."""
    if not srt_path.exists():
        return ""
    raw = srt_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\n+", raw.strip())
    lines_out = []
    for b in blocks:
        lines = b.strip().split("\n")
        if len(lines) < 3:
            continue
        m = re.match(r"(\d{2}:\d{2}:\d{2}),\d+ --> (\d{2}:\d{2}:\d{2})", lines[1])
        if m:
            ts = m.group(1)[:5]  # MM:SS
            text = " ".join(lines[2:])
            lines_out.append(f"[{ts}] {text}")
    return "\n".join(lines_out)

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 validar_prompts_timeline.py <nicho>/<personaje>/")
        sys.exit(1)

    base        = pathlib.Path("/Users/anyelocuesta/Downloads/Canales")
    char_dir    = base / sys.argv[1].rstrip("/")
    timeline_f  = char_dir / "05-montaje" / "timeline.json"
    personaje   = char_dir.name

    # Buscar guion
    guion_f = next(char_dir.glob("*.txt"), None)
    if not guion_f:
        print("❌ No se encontró el guion .txt")
        sys.exit(1)

    # Buscar SRT
    srt_f = next(char_dir.glob("*.srt"), None)

    if not timeline_f.exists():
        print("❌ No existe timeline.json")
        sys.exit(1)

    timeline = json.loads(timeline_f.read_text(encoding="utf-8"))
    segments = timeline.get("visual_timeline", [])

    # Guion (primeros 8000 chars para no saturar el contexto)
    guion_text = guion_f.read_text(encoding="utf-8")[:8000]

    # SRT con timestamps
    srt_context = load_srt_context(srt_f) if srt_f else ""

    # Construir tabla de prompts actuales
    prompts_str = json.dumps([{
        "segment_id": s["segment_id"],
        "start_seconds": s["start_seconds"],
        "end_seconds": s["end_seconds"],
        "covers_text": s.get("covers_text", ""),
        "scene_description_es": s.get("scene_description_es", ""),
        "ia_prompt": s.get("ia_prompt", ""),
        "trigger_type": s.get("trigger_type", ""),
    } for s in segments], ensure_ascii=False, indent=2)

    user_msg = f"""PERSONAJE: {personaje.replace('_', ' ').title()}

=== GUION (primeros 8000 caracteres) ===
{guion_text}

=== SRT CON TIMESTAMPS (primeros 10 min) ===
{srt_context}

=== PROMPTS ACTUALES DEL TIMELINE ===
{prompts_str}

Revisa cada ia_prompt. Corrígelos para que sean ESPECÍFICOS a este personaje y a lo que el guion dice en ese momento exacto.
Ejemplos de errores comunes a corregir:
- "classic silver Rolls-Royce" cuando el guion dice que llegaba en un Rolls-Royce Phantom negro moderno (2009-2014)
- Prompt genérico de "city landscape" cuando el guion describe una ciudad específica
- Época incorrecta (imagen vintage cuando el evento fue en 2010)
- Objetos que no coinciden con el modelo/año/color descrito en el guion
"""

    print(f"Personaje   : {personaje}")
    print(f"Segmentos   : {len(segments)}")
    print(f"Guion       : {len(guion_text)} chars")
    print(f"SRT         : {len(srt_context.splitlines())} líneas")
    print("Validando prompts contra el guion...\n")

    key = load_key()
    response = call_llm(key, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])

    try:
        result = extract_json(response)
    except json.JSONDecodeError:
        print("❌ El modelo no devolvió JSON válido:")
        print(response[:500])
        sys.exit(1)

    correcciones = result.get("correcciones", [])
    if not correcciones:
        print("✓ Todos los prompts ya son correctos y específicos al personaje.")
        return

    # Aplicar correcciones al timeline
    corr_map = {c["segment_id"]: c for c in correcciones}
    print(f"{'='*60}")
    print(f"  {len(correcciones)} prompts corregidos")
    print(f"{'='*60}\n")

    for seg in segments:
        sid = seg["segment_id"]
        if sid in corr_map:
            c = corr_map[sid]
            print(f"[{sid:02d}] PROBLEMA  : {c['problema']}")
            print(f"      ANTES    : {seg['ia_prompt'][:80]}...")
            print(f"      DESPUÉS  : {c['ia_prompt_corregido'][:80]}...")
            print()
            seg["ia_prompt"] = c["ia_prompt_corregido"]

    # Guardar timeline corregido
    timeline_f.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ timeline.json actualizado con {len(correcciones)} prompts corregidos.")
    print(f"\nPróximo paso: actualizar Baserow con los nuevos prompts y regenerar imágenes en Flow.")

if __name__ == "__main__":
    main()
