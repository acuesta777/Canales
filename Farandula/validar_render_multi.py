#!/usr/bin/env python3
"""
Validar render multi (Formato 1) — OBLIGATORIO después de render_farandula.py, antes de subir.

Complemento de validar_render_mono.py para videos de varios artistas.
Los chequeos técnicos son los mismos; cambia el chequeo estructural:

  1. Duración   — stream de video vs stream de audio vs audio.mp3 original
  2. Peso       — MB y bitrate
  3. Frames     — nb_read_frames DECODIFICADOS + tramos muestreados (congelamiento)
  4. Integridad — decode completo con -f null
  5. Segmentos  — cada artista arranca en su segundo de timestamps.json, verificado
                  detectando el overlay del nombre (banda roja + texto amarillo) en
                  el frame correspondiente. Valida a la vez el corte del segmento Y
                  que el overlay se aplicó.

En Formato 1 cada segmento se corta duro con `-t duracion`, así que no hay arrastre
acumulado como en el mono — pero nada verificaba que el overlay estuviera puesto ni
que el corte cayera donde debía.

Uso:
  python3 validar_render_multi.py "Farandula/NOMBRE/"
  python3 validar_render_multi.py "Farandula/NOMBRE/" --rapido    # salta el chequeo 5
"""
import sys, re, json, pathlib, argparse, subprocess

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

def cargar_timestamps(F):
    """timestamps.json puede ser lista [{label,start,end,duration}] o dict {label:{...}}."""
    p = F / "timestamps.json"
    if not p.exists(): return []
    d = json.loads(p.read_text())
    if isinstance(d, dict):
        out = []
        for label, v in d.items():
            if isinstance(v, dict): out.append({"label": label, **v})
        return sorted(out, key=lambda x: x.get("start", 0))
    return sorted(d, key=lambda x: x.get("start", 0))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--rapido", action="store_true")
    a = ap.parse_args()

    F   = pathlib.Path(a.folder)
    out = F / "output.mp4"
    mp3 = F / "audio.mp3"
    if not out.exists(): print(f"⛔ No existe {out}"); sys.exit(1)
    if not mp3.exists(): print(f"⛔ No existe {mp3}"); sys.exit(1)

    fallas, avisos = [], []
    print(f"\n  Validando {out}\n  " + "─"*66)

    vd, ad, md = dur_de(out, "v:0"), dur_de(out, "a:0"), dur_de(mp3)
    print(f"  1. duración   video {vd:.2f}s | audio {ad:.2f}s | mp3 {md:.2f}s")
    print(f"     {'':13}delta video↔mp3 {abs(vd-md):.3f}s")
    if abs(vd - md) > 1.0: fallas.append(f"video vs mp3 difiere {abs(vd-md):.1f}s — posible stream truncado")

    mb   = out.stat().st_size / 1048576
    mbps = out.stat().st_size * 8 / 1e6 / max(vd, 1)
    print(f"  2. peso       {mb:.0f} MB | {mbps:.1f} Mbps")
    if mbps < 1.5: fallas.append(f"bitrate {mbps:.1f} Mbps demasiado bajo para 1080p")

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
    rfps = nf / max(vd, 1)
    print(f"  3. frames     {nf:,} decodificados | {rfps:.3f} fps real (nominal {FPS:.0f})")
    if rfps < FPS * 0.9: fallas.append(f"{rfps:.1f} fps real vs {FPS} nominal — frames perdidos")
    huecos = []
    for t in [int(vd * k / 6) for k in range(6)]:
        n = probe("-count_frames", "-select_streams", "v:0", "-read_intervals", f"{t}%+10",
                  "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(out))
        n = int(n) if n.isdigit() else 0
        if n < FPS * 10 * 0.85: huecos.append(f"t={t}s→{n}")
    print(f"     {'':13}tramos de 10s: {'todos OK' if not huecos else 'CONGELAMIENTO ' + ', '.join(huecos)}")
    if huecos: fallas.append(f"posible congelamiento en {len(huecos)} tramo(s)")

    err = subprocess.run([FFMPEG, "-v", "error", "-i", str(out), "-f", "null", "-"],
                         capture_output=True, text=True).stderr.strip()
    print(f"  4. integridad {'decode completo sin errores' if not err else 'ERRORES DE DECODE'}")
    if err:
        fallas.append("errores de decodificación")
        for l in err.split("\n")[:3]: print(f"     {'':13}{l[:80]}")

    # 5 ─ segmentos de artista + overlay del nombre
    ts = cargar_timestamps(F)
    if a.rapido or not ts:
        print("  5. segmentos  (saltado)" if a.rapido else "  5. segmentos  ⚠ sin timestamps.json")
        if not ts and not a.rapido: avisos.append("sin timestamps.json — no se pudo verificar segmentos")
    else:
        try:
            import numpy as np
        except ImportError:
            print("  5. segmentos  ⚠ numpy no disponible"); avisos.append("numpy no disponible"); np = None
        if np is not None:
            W, H = 320, 180; N = W * H * 3
            def es_artista(lab):
                # los labels vienen como "00_HOOK", "01_LOLITA AYALA", "09_CIERRE"
                l = re.sub(r"^\d+[_\-\s]*", "", str(lab)).strip().upper()
                return l not in ("HOOK", "CIERRE", "INTRO", "OUTRO")
            artistas = [s for s in ts if es_artista(s.get("label", ""))]
            sin_ov = []
            for s in artistas:
                t = s.get("start", 0) + 1.5      # overlay visible de 0 a 4s del segmento
                b = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{t:.2f}", "-i", str(out),
                                    "-frames:v", "1", "-vf", f"scale={W}:{H}",
                                    "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                                   capture_output=True).stdout
                if len(b) < N: sin_ov.append((s, "sin frame")); continue
                im = np.frombuffer(b[:N], dtype=np.uint8).reshape(H, W, 3).astype(int)
                c  = im[int(H*0.35):int(H*0.65), :, :]          # banda central
                R, G, B = c[:,:,0], c[:,:,1], c[:,:,2]
                rojo     = ((R > 80) & (R < 200) & (G < 80) & (B < 80)).mean()
                amarillo = ((R > 190) & (G > 160) & (B < 160)).mean()
                if rojo < 0.02 or amarillo < 0.0008:
                    sin_ov.append((s, f"rojo {rojo*100:.1f}% amarillo {amarillo*100:.2f}%"))
            print(f"  5. segmentos  {len(artistas)} artistas | "
                  f"{'overlay detectado en todos' if not sin_ov else str(len(sin_ov)) + ' SIN OVERLAY'}")
            for s, why in sin_ov:
                print(f"     {'':13}{s.get('label','?')} @ {s.get('start',0):.1f}s — {why}")
            if sin_ov:
                fallas.append(f"{len(sin_ov)} segmento(s) sin overlay de nombre o cortados fuera de su segundo")

    print("  " + "─"*66)
    for w in avisos: print(f"  ⚠  {w}")
    if fallas:
        print(f"\n  ❌ RENDER NO VALIDADO — {len(fallas)} problema(s):")
        for f in fallas: print(f"     · {f}")
        print("\n  NO subir este archivo.\n"); sys.exit(1)
    print("\n  ✅ RENDER VALIDADO — listo para el pack de subida\n"); sys.exit(0)

if __name__ == "__main__":
    main()
