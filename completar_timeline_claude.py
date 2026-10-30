#!/usr/bin/env python3
"""
completar_timeline_claude.py — Completa un timeline cuando OpenRouter falló con 402.

Flujo:
  1. generar_timeline_familias_full.py hit 402 → guardó 05-montaje/srt_pendientes.json
  2. Claude leyó el archivo y generó 05-montaje/prompts_claude.json
  3. Este script fusiona ambos y escribe el timeline.json definitivo

Uso:
    python3 completar_timeline_claude.py familias/bailleres/
"""

import sys, json, pathlib, re

MAX_SEG_SECS = 8.0

def ts_to_sec(ts):
    ts = ts.strip().replace(',', '.')
    p = ts.split(':')
    return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])

def mark_mode_flags(segments):
    for s in segments:
        t = s.get('start_seconds', 0)
        if t < 120:
            s['animate'] = True
            s.pop('zoompan', None)
        elif t < 600:
            s['zoompan'] = True
            s.pop('animate', None)
        else:
            s.pop('animate', None)
            s.pop('zoompan', None)
    return segments

def srt_batch_to_segments(batch, prompts, start_seg_id):
    """Convierte entradas SRT + lista de prompts en segmentos del timeline."""
    segments = []
    seg_id = start_seg_id

    entries = batch  # lista de {start, end, text}
    n = len(entries)

    # Repartir prompts: si hay más entradas que prompts, agrupar entradas
    if len(prompts) == 0:
        raise ValueError("Sin prompts para este lote")

    # Calcular cuántas entradas por prompt (aproximado)
    entries_per_prompt = max(1, n // len(prompts))

    prompt_idx = 0
    i = 0
    while i < n:
        chunk = entries[i: i + entries_per_prompt]
        if not chunk:
            break

        t_start = chunk[0]['start']
        t_end   = chunk[-1]['end']
        dur     = t_end - t_start

        # Si la duración supera el máximo, partir
        if dur > MAX_SEG_SECS:
            sub_dur = MAX_SEG_SECS
            t = t_start
            while t < t_end:
                seg_end = min(t + sub_dur, t_end)
                prompt  = prompts[min(prompt_idx, len(prompts) - 1)]
                segments.append({
                    "segment_id": seg_id,
                    "start_seconds": round(t, 3),
                    "end_seconds": round(seg_end, 3),
                    "duration": round(seg_end - t, 3),
                    "ia_prompt": prompt,
                    "ia_prompt_en": prompt,
                    "scene_description_es": chunk[0].get('text', ''),
                    "source": "flow",
                })
                seg_id += 1
                t = seg_end
        else:
            prompt = prompts[min(prompt_idx, len(prompts) - 1)]
            segments.append({
                "segment_id": seg_id,
                "start_seconds": round(t_start, 3),
                "end_seconds": round(t_end, 3),
                "duration": round(dur, 3),
                "ia_prompt": prompt,
                "ia_prompt_en": prompt,
                "scene_description_es": ' '.join(e['text'] for e in chunk),
                "source": "flow",
            })
            seg_id += 1

        prompt_idx = min(prompt_idx + 1, len(prompts) - 1)
        i += entries_per_prompt

    return segments, seg_id

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 completar_timeline_claude.py familias/bailleres/")
        sys.exit(1)

    carpeta   = pathlib.Path(sys.argv[1])
    out_dir   = carpeta / "05-montaje"
    pendientes_file = out_dir / "srt_pendientes.json"
    prompts_file    = out_dir / "prompts_claude.json"
    timeline_file   = out_dir / "timeline.json"

    if not pendientes_file.exists():
        print(f"ERROR: No existe {pendientes_file}")
        print("Corre primero generar_timeline_familias_full.py --sin-api para generar el archivo.")
        sys.exit(1)

    if not prompts_file.exists():
        print(f"ERROR: No existe {prompts_file}")
        print("Claude debe escribir ese archivo con los prompts generados.")
        print()
        print("Dile a Claude: 'La API falló con 402, genera los prompts para completar el timeline'")
        sys.exit(1)

    estado  = json.loads(pendientes_file.read_text())
    prompts_data = json.loads(prompts_file.read_text())

    completados     = estado['completados']
    batches_pend    = estado['pendientes']
    next_seg_id     = estado['next_segment_id']
    video_name      = estado['video_name']
    logos           = estado['logos']

    print(f"\n{'═'*62}")
    print(f"  COMPLETAR TIMELINE — {video_name.upper()}")
    print(f"  Segmentos ya completados: {len(completados)}")
    print(f"  Lotes pendientes: {len(batches_pend)}")
    print(f"{'═'*62}\n")

    # prompts_data puede ser:
    #   {"lotes": [[prompt, prompt, ...], [prompt, ...], ...]}
    #   o una lista plana de prompts
    if isinstance(prompts_data, dict) and 'lotes' in prompts_data:
        lotes_prompts = prompts_data['lotes']
    elif isinstance(prompts_data, list):
        # Lista plana — repartir equitativamente entre lotes
        total_segs_pend = sum(len(b) for b in batches_pend)
        if total_segs_pend == 0:
            total_segs_pend = 1
        per_batch = max(1, len(prompts_data) // len(batches_pend)) if batches_pend else 1
        lotes_prompts = []
        idx = 0
        for batch in batches_pend:
            lotes_prompts.append(prompts_data[idx:idx+per_batch] or prompts_data[-1:])
            idx += per_batch
    else:
        print("ERROR: formato de prompts_claude.json inválido.")
        print('Debe ser {"lotes": [[prompts lote 1], [prompts lote 2], ...]} o una lista plana.')
        sys.exit(1)

    nuevos_segmentos = []
    seg_id = next_seg_id

    for b_idx, batch in enumerate(batches_pend):
        prompts_lote = lotes_prompts[b_idx] if b_idx < len(lotes_prompts) else lotes_prompts[-1]
        b_start = batch[0]['start']
        b_end   = batch[-1]['end']
        print(f"  Lote {b_idx+1}/{len(batches_pend)}: {b_start:.1f}s→{b_end:.1f}s | {len(prompts_lote)} prompts")

        segs, seg_id = srt_batch_to_segments(batch, prompts_lote, seg_id)
        nuevos_segmentos.extend(segs)

    all_segments = sorted(completados + nuevos_segmentos, key=lambda s: s['start_seconds'])

    # Reasignar segment_id consecutivos
    for idx, s in enumerate(all_segments, 1):
        s['segment_id'] = idx

    all_segments = mark_mode_flags(all_segments)

    timeline = {
        "canal": "familias",
        "video": video_name,
        "logos": logos,
        "total_segments": len(all_segments),
        "visual_timeline": all_segments,
    }

    timeline_file.write_text(json.dumps(timeline, ensure_ascii=False, indent=2))
    print(f"\n  ✓ timeline.json escrito: {len(all_segments)} segmentos")
    print(f"  → Archivo: {timeline_file}")
    print(f"\n  Próximo paso: python3 harvester_timeline.py {carpeta}/ --canal familias")

if __name__ == "__main__":
    main()
