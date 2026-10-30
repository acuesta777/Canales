#!/usr/bin/env python3
"""
Tracker de tiempos del pipeline de producción.
Uso:
  python3 timing.py start  <carpeta> <paso>   # registra inicio
  python3 timing.py end    <carpeta> <paso>   # registra fin
  python3 timing.py report <carpeta>          # imprime tabla resumen
"""
import sys, time, pathlib, json

PASOS_ORDEN = [
    "descargar_audio",
    "hacer_guion",
    "tts_audio",
    "cortar_clips",
    "srt_transcripcion",
    "prompts_imagen",
    "renderizar_video",
]

PASOS_LABEL = {
    "descargar_audio":   "Descargar audio YouTube",
    "hacer_guion":       "Escribir guion",
    "tts_audio":         "TTS (generar MP3)",
    "cortar_clips":      "Cortar clips",
    "srt_transcripcion": "Transcripción SRT",
    "prompts_imagen":    "Prompts de imagen",
    "renderizar_video":  "Renderizar video final",
}

def log_file(carpeta):
    return pathlib.Path(carpeta) / "timing.json"

def load(carpeta):
    f = log_file(carpeta)
    if f.exists():
        return json.loads(f.read_text())
    return {}

def save(carpeta, data):
    log_file(carpeta).write_text(json.dumps(data, indent=2))

def fmt(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    return f"{m} min {s}s" if s else f"{m} min"

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    carpeta = sys.argv[2]

    if cmd == "report":
        data = load(carpeta)
        nombre = pathlib.Path(carpeta).name
        print(f"\n{'='*50}")
        print(f"  TIEMPOS DE PRODUCCIÓN — {nombre.upper()}")
        print(f"{'='*50}")
        total = 0
        for paso in PASOS_ORDEN:
            if paso not in data:
                continue
            entry = data[paso]
            if "end" not in entry:
                continue
            dur = entry["end"] - entry["start"]
            total += dur
            label = PASOS_LABEL.get(paso, paso)
            print(f"  {label:<28} {fmt(dur):>10}")
        print(f"{'─'*50}")
        print(f"  {'TOTAL':<28} {fmt(total):>10}")
        print(f"{'='*50}\n")
        return

    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    paso = sys.argv[3]
    data = load(carpeta)

    if paso not in data:
        data[paso] = {}

    if cmd == "start":
        data[paso]["start"] = time.time()
        print(f"[timing] Inicio: {paso}")
    elif cmd == "end":
        if "start" not in data[paso]:
            data[paso]["start"] = time.time()
        data[paso]["end"] = time.time()
        dur = data[paso]["end"] - data[paso]["start"]
        print(f"[timing] Fin: {paso} — {fmt(dur)}")

    save(carpeta, data)

if __name__ == "__main__":
    main()
