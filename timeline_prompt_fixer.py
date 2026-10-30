"""
Segundo pase LLM: verifica que cada ia_prompt ilustre exactamente el covers_text.
Importar desde cualquier generar_timeline_*.py y llamar antes de guardar timeline.json.
Procesa en lotes de 6 para evitar rubber-stamp con muchos segmentos.
"""
import json, time, urllib.request

OR_MODEL = "google/gemini-2.5-flash-lite"

SYSTEM_MSG = (
    "You are a strict prompt quality validator for a cinematic video production pipeline. "
    "For each segment you receive: covers_text (the EXACT audio line), trigger_type, and current_prompt.\n\n"
    "YOUR JOB: verify that current_prompt illustrates the SPECIFIC object/place/action in covers_text — "
    "not the channel's general theme, not the trigger type's default visual, not what comes before or after.\n\n"
    "CRITICAL EXAMPLES OF MISMATCHES (mark fixed=true and rewrite):\n"
    "  - covers_text 'cargando bultos en La Merced' → prompt shows generic humble street → MISMATCH → show La Merced market\n"
    "  - covers_text 'cortaba caña de azúcar en Veracruz' → prompt shows colonial hacienda → MISMATCH → show sugarcane field\n"
    "  - covers_text 'siete décadas de trabajo sobre los escenarios' → prompt shows stacks of dollar bills → MISMATCH → show empty theater stage\n"
    "  - covers_text 'su patrimonio rondaba los 6 millones de dólares' → prompt shows a mansion → MISMATCH → show estate document or net worth ledger\n"
    "  - covers_text 'vendía dulces en una tienda del vecindario' → prompt shows cramped apartments → MISMATCH → show candy shop\n"
    "  - covers_text 'Pedro Infante, Jorge Negrete, María Félix' → prompt shows radio booth → MISMATCH → show Golden Age film set\n"
    "  - covers_text 'recaudó millones en todo el mundo' → prompt shows luxury penthouse → MISMATCH → show box office or stacked cash\n\n"
    "RULE: Ask 'What specific noun does covers_text literally name?' — the prompt MUST show that noun.\n"
    "If the prompt already matches covers_text literally → fixed=false, return unchanged.\n"
    "If the prompt drifts to the general theme or trigger template → fixed=true, rewrite.\n\n"
    "Always start rewritten prompts with 'Cinematic hyperrealistic photo of'. "
    "Always end with 'cinematic lighting, no text, no letters, no faces visible, 16:9'. "
    "Return ONLY valid JSON array: [{\"seg_id\": N, \"ia_prompt\": \"...\", \"fixed\": true/false}]"
)

BATCH_SIZE = 6

def auto_fix_prompts(segments: list, api_key: str) -> list:
    """Valida y corrige ia_prompt vs covers_text en un segundo pase LLM.
    Procesa en lotes de 6. Retorna los segmentos (corregidos donde aplique)."""
    if not segments or not api_key:
        return segments

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

        payload = json.dumps({
            "model": OR_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_MSG},
                {"role": "user",   "content": "Validate and fix (be strict — mismatch = fixed=true):\n" + json.dumps(items, ensure_ascii=False)},
            ],
            "temperature": 0.1,
            "max_tokens": 2000,
        }).encode()

        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            raw = data["choices"][0]["message"]["content"].strip()
            raw = raw.lstrip("```json").lstrip("```").rstrip("```").strip()
            fixed_list = json.loads(raw)
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
