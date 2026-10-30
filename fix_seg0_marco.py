#!/usr/bin/env python3
"""
Agrega el segmento 0 (0→12s) al timeline de marco_antonio_vazquez.
Uso:
  1. Pon la imagen generada (Santa Julia) como:
     riqueza/marco_antonio_vazquez/03-imagenes/santa_julia_seg0.jpg
  2. python3 fix_seg0_marco.py
"""
import json, sys
from pathlib import Path

BASE = Path(__file__).parent
PERSONA_DIR = BASE / "riqueza/marco_antonio_vazquez"
TIMELINE_PATH = PERSONA_DIR / "05-montaje/timeline.json"
IMG_DIR = PERSONA_DIR / "03-imagenes"
INPUT_IMG = IMG_DIR / "santa_julia_seg0.jpg"
OUTPUT_CLIP = IMG_DIR / "flow_0000_zp.mp4"

SEG0 = {
    "segment_id": 0,
    "source": "flow",
    "start_seconds": 0,
    "end_seconds": 12,
    "duration": 8,
    "scene_description_es": "Barrio de Santa Julia, Ciudad de México, invierno de 1942. Calles empedradas con casas modestas.",
    "ia_prompt": "Cinematic hyperrealistic photo of Santa Julia neighborhood in Mexico City, 1942. Narrow cobblestone streets lined with modest working-class adobe homes, laundry hanging between buildings. Black and white, film grain, period-accurate, cinematic lighting, no text, no letters, no faces visible, 16:9",
    "covers_text": "Santa Julia, Ciudad de México, invierno de mil novecientos cuarenta y dos.",
    "trigger_type": "place"
}

def main():
    # 1. Verificar imagen
    if not INPUT_IMG.exists():
        print(f"❌ Imagen no encontrada: {INPUT_IMG}")
        print("   Descarga la imagen de Flow y guárdala ahí con ese nombre.")
        sys.exit(1)

    # 2. Crear zoompan clip
    sys.path.insert(0, str(BASE))
    from zoompan_clip import make_zoompan
    print(f"  → Creando zoompan {OUTPUT_CLIP.name} (8s)...")
    make_zoompan(INPUT_IMG, OUTPUT_CLIP, 8, index=0)
    print(f"  ✓ {OUTPUT_CLIP.name} creado")

    # 3. Insertar SEG 0 en timeline.json
    tl = json.loads(TIMELINE_PATH.read_text())
    segments = tl["visual_timeline"]
    if segments[0]["segment_id"] == 0:
        print("  ℹ SEG 0 ya existe en timeline.json — no se modifica")
    else:
        segments.insert(0, SEG0)
        TIMELINE_PATH.write_text(json.dumps(tl, ensure_ascii=False, indent=2))
        print(f"  ✓ SEG 0 insertado en timeline.json — total: {len(segments)} segmentos")

    # 4. Verificar N/N
    found = sum(1 for s in segments if (IMG_DIR / f"flow_{s['segment_id']:04d}_zp.mp4").exists())
    print(f"\n  Clips: {found}/{len(segments)}")
    if found == len(segments):
        print("  ✅ PASO 9 OK — todos los clips presentes. Puedes lanzar render.py")
    else:
        missing = [s["segment_id"] for s in segments if not (IMG_DIR / f"flow_{s['segment_id']:04d}_zp.mp4").exists()]
        print(f"  ⚠ Faltan clips: {missing}")

if __name__ == "__main__":
    main()
