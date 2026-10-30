#!/usr/bin/env python3
"""
Validar render mono — OBLIGATORIO después de render_farandula_mono.py, antes de subir.

Seis chequeos sobre el output.mp4 real, no sobre metadata del container:

  1. Duración   — stream de video vs stream de audio vs audio.mp3 original
  2. Peso       — MB y bitrate; un archivo flaco delata un stream truncado
  3. Frames     — nb_read_frames DECODIFICADOS (no nb_frames del container) + tramos
                  muestreados para detectar congelamiento
  4. Integridad — decode completo con -f null; cualquier error = stream roto
  5. Orden      — render_used_order.json contra mono_state.json: el render tiene que
                  respetar el orden que el usuario aprobó en el dashboard
  6. Flow       — dónde cayó REALMENTE cada imagen del hook dentro del mp4, medido
                  por huella de color contra su propio _zp.mp4

Por qué existe: `format=duration` lee el container, que toma la duración del stream
más largo (el audio). Si el video termina antes, el container igual reporta bien y el
player congela el último frame. Y la regla de que las imágenes Flow caen en su segundo
exacto estaba escrita pero nada la verificaba — un desfase de 4s viajó sin que nadie
lo viera.

Uso:
  python3 validar_render_mono.py "Farandula/NOMBRE/"
  python3 validar_render_mono.py "Farandula/NOMBRE/" --rapido   # salta el chequeo 6
"""
import sys, json, math, pathlib, argparse, subprocess

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
FPS     = 30   # default; se reemplaza por el fps nominal real del stream

def probe(*a):
    return subprocess.run([FFPROBE, "-v", "error", *a], capture_output=True, text=True).stdout.strip()

def dur_de(f, stream=None):
    a = ["-select_streams", stream] if stream else []
    v = probe(*a, "-show_entries", ("stream=duration" if stream else "format=duration"),
              "-of", "csv=p=0", str(f)).split("\n")[0]
    try:    return float(v)
    except: return 0.0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--rapido", action="store_true", help="salta el chequeo perceptual de imágenes Flow")
    ap.add_argument("--tol-flow", type=float, default=1.0, help="desfase máximo tolerado por imagen (s)")
    a = ap.parse_args()

    F   = pathlib.Path(a.folder)
    out = F / "output.mp4"
    mp3 = F / "audio.mp3"
    if not out.exists(): print(f"⛔ No existe {out}"); sys.exit(1)
    if not mp3.exists(): print(f"⛔ No existe {mp3}"); sys.exit(1)

    fallas, avisos = [], []
    print(f"\n  Validando {out}\n" + "  " + "─"*66)

    # 1 ─ duración
    vd, ad, md = dur_de(out, "v:0"), dur_de(out, "a:0"), dur_de(mp3)
    d_va, d_vm = abs(vd - ad), abs(vd - md)
    print(f"  1. duración   video {vd:.2f}s | audio {ad:.2f}s | mp3 {md:.2f}s")
    print(f"     {'':13}delta video↔mp3 {d_vm:.3f}s")
    if d_vm > 1.0: fallas.append(f"video vs mp3 difiere {d_vm:.1f}s — posible stream truncado")
    if d_va > 1.0: fallas.append(f"video vs audio del mp4 difiere {d_va:.1f}s")

    # 2 ─ peso
    mb   = out.stat().st_size / 1048576
    mbps = out.stat().st_size * 8 / 1e6 / max(vd, 1)
    print(f"  2. peso       {mb:.0f} MB | {mbps:.1f} Mbps")
    if mbps < 1.5: fallas.append(f"bitrate {mbps:.1f} Mbps demasiado bajo para 1080p")

    # 3 ─ frames decodificados
    global FPS
    rfr = probe("-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                "-of", "csv=p=0", str(out))
    try:
        num, den = rfr.split("/"); FPS = float(num) / float(den)
    except Exception:
        pass
    nf = probe("-count_frames", "-select_streams", "v:0",
               "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(out))
    nf = int(nf) if nf.isdigit() else 0
    real_fps = nf / max(vd, 1)
    print(f"  3. frames     {nf:,} decodificados | {real_fps:.3f} fps real (nominal {FPS:.0f})")
    if real_fps < FPS * 0.9:
        fallas.append(f"{real_fps:.1f} fps real vs {FPS} nominal — se perdieron frames")
    huecos = []
    for t in [int(vd * k / 6) for k in range(6)]:
        n = probe("-count_frames", "-select_streams", "v:0", "-read_intervals", f"{t}%+10",
                  "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(out))
        n = int(n) if n.isdigit() else 0
        if n < FPS * 10 * 0.85: huecos.append(f"t={t}s→{n}")
    print(f"     {'':13}tramos de 10s muestreados: {'todos OK' if not huecos else 'CONGELAMIENTO ' + ', '.join(huecos)}")
    if huecos: fallas.append(f"posible congelamiento en {len(huecos)} tramo(s)")

    # 4 ─ integridad
    err = subprocess.run([FFMPEG, "-v", "error", "-i", str(out), "-f", "null", "-"],
                         capture_output=True, text=True).stderr.strip()
    print(f"  4. integridad {'decode completo sin errores' if not err else 'ERRORES DE DECODE'}")
    if err:
        fallas.append("errores de decodificación")
        for l in err.split("\n")[:3]: print(f"     {'':13}{l[:80]}")

    # 5 ─ orden aprobado en el dashboard
    used_f, state_f = F / "render_used_order.json", F / "mono_state.json"
    if not used_f.exists():
        avisos.append("sin render_used_order.json — render viejo; re-renderiza para poder validar el orden")
        print("  5. orden      ⚠ sin render_used_order.json (no se puede verificar)")
    elif not state_f.exists():
        avisos.append("sin mono_state.json")
        print("  5. orden      ⚠ sin mono_state.json")
    else:
        used  = [e["filename"] for e in json.loads(used_f.read_text()) if e["tipo"] == "clip"]
        state = [i["filename"] for i in json.loads(state_f.read_text())
                 if i["tipo"] == "clip" and i.get("estado") != "rechazado" and i.get("filename")]
        n = min(len(used), len(state))
        difs = [k for k in range(n) if used[k] != state[k]]
        recic = len(used) - len(state)
        print(f"  5. orden      {len(used)} clips usados | {len(state)} aprobados | "
              f"{'coincide' if not difs else str(len(difs)) + ' POSICIONES DISTINTAS'}"
              + (f" | +{recic} reciclados" if recic > 0 else ""))
        if difs:
            fallas.append(f"el render no respetó el orden del dashboard ({len(difs)} posiciones)")
            for k in difs[:5]: print(f"     {'':13}pos {k}: usó {used[k]} | esperaba {state[k]}")

    # 6 ─ posición real de las imágenes Flow
    tl_f = F / "hook_timeline.json"
    if a.rapido or not tl_f.exists():
        print("  6. flow       (saltado)")
    else:
        try:
            import numpy as np
        except ImportError:
            avisos.append("numpy no disponible — chequeo 6 saltado")
            print("  6. flow       ⚠ numpy no disponible")
            np = None
        if np is not None:
            segs = json.loads(tl_f.read_text())["visual_timeline"]
            W, H = 96, 54; N = W * H * 3
            hasta = max(s["end_seconds"] for s in segs) + 30
            def raw(cmd): return subprocess.run(cmd, capture_output=True).stdout
            b = raw([FFMPEG, "-v", "error", "-i", str(out), "-t", str(hasta),
                     "-vf", f"fps=2,scale={W}:{H}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
            fr = np.frombuffer(b, dtype=np.uint8).astype(float).reshape(-1, N)
            fr = (fr - fr.mean(1, keepdims=True)) / (fr.std(1, keepdims=True) + 1e-6)
            peor, nd = 0.0, 0
            det = []
            for s in segs:
                zp = F / "hook_images" / f"hook_{s['segment_id']:04d}_zp.mp4"
                if not zp.exists(): nd += 1; det.append((s, None)); continue
                refs = []
                for t in (0.5, s["duration"] / 2, s["duration"] - 0.6):
                    rb = raw([FFMPEG, "-v", "error", "-ss", str(t), "-i", str(zp), "-frames:v", "1",
                              "-vf", f"scale={W}:{H}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"])
                    if len(rb) >= N:
                        v = np.frombuffer(rb[:N], dtype=np.uint8).astype(float)
                        refs.append((v - v.mean()) / (v.std() + 1e-6))
                if not refs: nd += 1; det.append((s, None)); continue
                sim = np.max(np.stack([fr @ v / N for v in refs]), axis=0)
                m = sim > 0.60; best = None; i = 0
                while i < len(m):
                    if m[i]:
                        j = i
                        while j < len(m) and m[j]: j += 1
                        if j - i >= 10 and (best is None or j - i > best[1] - best[0]): best = (i, j)
                        i = j
                    else: i += 1
                if best is None: nd += 1; det.append((s, None)); continue
                d = best[0] / 2.0 - s["start_seconds"]
                peor = max(peor, abs(d)); det.append((s, d))
            malas = [(s, d) for s, d in det if d is not None and abs(d) > a.tol_flow]
            print(f"  6. flow       {len(segs) - nd}/{len(segs)} detectadas | desfase máx {peor:+.1f}s "
                  f"| {'todas en su segundo' if not malas else str(len(malas)) + ' FUERA DE SITIO'}")
            for s, d in malas:
                print(f"     {'':13}seg {s['segment_id']}: previsto {s['start_seconds']:.1f}s, real {s['start_seconds']+d:.1f}s ({d:+.1f}s)")
            if malas: fallas.append(f"{len(malas)} imagen(es) Flow fuera de su segundo")
            if nd:    avisos.append(f"{nd} imagen(es) Flow no detectadas en el video")

    print("  " + "─"*66)
    for w in avisos: print(f"  ⚠  {w}")
    if fallas:
        print(f"\n  ❌ RENDER NO VALIDADO — {len(fallas)} problema(s):")
        for f in fallas: print(f"     · {f}")
        print("\n  NO subir este archivo.\n")
        sys.exit(1)
    print(f"\n  ✅ RENDER VALIDADO — listo para el pack de subida\n")
    sys.exit(0)

if __name__ == "__main__":
    main()
