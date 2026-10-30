#!/usr/bin/env python3
"""
Validador pre/post render para riqueza.
Verifica que cada card del clips_order tenga su archivo físico.
"""
import json
import sys
from pathlib import Path
import subprocess

def dur(p):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
        capture_output=True, text=True
    )
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 validar_clips_render.py <nicho>/<personaje>/")
        sys.exit(1)

    base = Path(sys.argv[1].rstrip("/"))
    meta_path = base / "metadata.json"
    timeline_path = base / "05-montaje" / "timeline.json"
    clips_dir = base / "clips"
    img_dir = base / "03-imagenes"

    ok = True
    print("=" * 60)
    print(f"  VALIDADOR CLIPS RENDER — {base.name}")
    print("=" * 60)

    # ── 1. metadata.json ──────────────────────────────────────────
    if not meta_path.exists():
        print("❌ metadata.json no encontrado")
        sys.exit(1)
    meta = json.loads(meta_path.read_text())
    order = meta.get("clips_order", [])
    rejected = set(meta.get("rejected_yt_clips", {}).keys())
    deleted  = set(meta.get("deleted_yt_clips",  {}).keys())

    print(f"\n[YT CLIPS]  clips_order: {len(order)} | rechazados: {len(rejected)} | eliminados: {len(deleted)}")

    bad_clips = []
    for clip in order:
        if clip in rejected or clip in deleted:
            continue
        p = clips_dir / clip
        if not p.exists():
            bad_clips.append(f"  ❌ NO EXISTE : {clip}")
            ok = False
            continue
        size = p.stat().st_size
        if size < 50_000:
            bad_clips.append(f"  ❌ CORRUPTO ({size//1024}KB) : {clip}")
            ok = False
            continue
        d = dur(p)
        if d < 1.0:
            bad_clips.append(f"  ❌ DUR={d:.2f}s : {clip}")
            ok = False

    if bad_clips:
        print("  Clips con problemas:")
        for b in bad_clips:
            print(b)
    else:
        activos = len(order) - len(rejected) - len(deleted)
        print(f"  ✅ Todos los {activos} clips activos tienen archivo válido")

    # ── 2. Flow clips ─────────────────────────────────────────────
    if timeline_path.exists():
        tl = json.loads(timeline_path.read_text())
        segs = tl.get("visual_timeline", [])
        bad_flow = []
        for s in segs:
            sid = s["segment_id"]
            p = img_dir / f"flow_{sid:04d}_zp.mp4"
            if not p.exists():
                bad_flow.append(f"  ❌ flow_{sid:04d}_zp.mp4  NO EXISTE")
                ok = False
            else:
                d = dur(p)
                if d < 1.0:
                    bad_flow.append(f"  ❌ flow_{sid:04d}_zp.mp4  DUR={d:.2f}s")
                    ok = False
        print(f"\n[FLOW]      segmentos: {len(segs)}")
        if bad_flow:
            for b in bad_flow:
                print(b)
        else:
            print(f"  ✅ {len(segs)}/{len(segs)} flow clips OK")
    else:
        print("\n[FLOW]  ⚠️  timeline.json no encontrado — omitido")

    # ── 3. Render final ───────────────────────────────────────────
    final = base / f"{base.name}_final.mp4"
    print(f"\n[RENDER]    {final.name}")
    if final.exists():
        size_mb = final.stat().st_size / 1024 / 1024
        d = dur(final)
        mins = int(d // 60); secs = int(d % 60)
        print(f"  ✅ Existe  | {size_mb:.1f} MB | {mins}:{secs:02d}")
    else:
        print("  ⏳ Aún no existe (render en curso o pendiente)")

    # ── Resumen ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if ok:
        print("  ✅ TODO OK — listo para render / upload")
    else:
        print("  ❌ HAY PROBLEMAS — corregir antes del render")
    print("=" * 60)

if __name__ == "__main__":
    main()
