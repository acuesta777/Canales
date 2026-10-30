#!/usr/bin/env python3
"""
Aplica overlay de nombre al output.mp4 segmento por segmento.
Por cada artista: extrae su porción, aplica overlay en los primeros 4.5s, reconcat.
"""
import sys, json, pathlib, subprocess, tempfile, shutil
from PIL import Image, ImageDraw, ImageFont

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"

VERDE="\033[92m"; ROJO="\033[91m"; RESET="\033[0m"
def ok(m):  print(f"  {VERDE}✓{RESET} {m}", flush=True)
def err(m): print(f"  {ROJO}✗{RESET} {m}", flush=True)

DUR_SHOW=4.0; FADE_IN=0.3; FADE_OUT=0.5; OV_DUR=DUR_SHOW+FADE_OUT


def get_duration(p):
    r = subprocess.run([FFPROBE,"-v","error","-show_entries","format=duration",
        "-of","default=noprint_wrappers=1:nokey=1",str(p)],
        capture_output=True, text=True, timeout=30)
    try: return float(r.stdout.strip())
    except: return 0.0


def generar_png(nombre, tmp):
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 88)
    dummy = ImageDraw.Draw(Image.new("RGBA",(1,1)))
    bb = dummy.textbbox((0,0), nombre, font=font)
    tw, th = bb[2]-bb[0], bb[3]-bb[1]
    PAD=28; BAND_H=th+PAD*2
    by=(1080-BAND_H)//2; tx=(1920-tw)//2; ty=by+PAD
    img = Image.new("RGBA",(1920,1080),(0,0,0,0))
    d = ImageDraw.Draw(img)
    d.rectangle([(0,by),(1920,by+BAND_H)], fill=(140,10,10,224))
    d.text((tx+3,ty+3), nombre, font=font, fill=(0,0,0,180))
    d.text((tx,ty), nombre, font=font, fill=(255,229,102,255))
    p = tmp/f"{nombre.replace(' ','_')}.png"
    img.save(p)
    return p


def aplicar_overlay_segmento(video, png, out, seg_dur):
    """Aplica overlay PNG con fade a los primeros OV_DUR segundos del video."""
    fc = (
        f"[1:v]fade=in:st=0:d={FADE_IN}:alpha=1,"
        f"fade=out:st={DUR_SHOW-FADE_OUT:.2f}:d={FADE_OUT}:alpha=1[ov];"
        f"[0:v][ov]overlay=0:0:eof_action=pass[v]"
    )
    r = subprocess.run([
        FFMPEG,"-hide_banner","-loglevel","error","-nostdin","-y",
        "-i", str(video),
        "-loop","1","-t",str(OV_DUR),"-i", str(png),
        "-filter_complex", fc,
        "-map","[v]","-an",
        "-c:v","libx264","-preset","ultrafast","-crf","23","-pix_fmt","yuv420p",
        str(out)
    ], capture_output=True, text=True, timeout=300)
    return out.exists() and out.stat().st_size > 10000


def main():
    folder    = pathlib.Path(sys.argv[1])
    input_mp4 = folder/"output.mp4"
    out_final = folder/"output_overlays.mp4"
    ts_file   = folder/"timestamps.json"

    timestamps = json.loads(ts_file.read_text())
    total_dur  = get_duration(input_mp4)

    # Construir lista de todos los segmentos con sus tiempos
    segs = []
    for i, s in enumerate(timestamps):
        start = float(s['start'])
        nxt   = float(timestamps[i+1]['start']) if i+1 < len(timestamps) else total_dur
        dur   = nxt - start
        segs.append({'name': s['name'], 'start': start, 'dur': dur,
                     'is_hook': s.get('is_hook',False), 'is_cierre': s.get('is_cierre',False)})

    print(f"\n  Video: {total_dur:.1f}s — {len(segs)} segmentos\n")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="ov_"))
    parts = []

    try:
        for i, seg in enumerate(segs):
            start = seg['start']; dur = seg['dur']; nombre = seg['name'].title()
            raw = tmp/f"raw_{i:02d}.mp4"

            # Extraer segmento del video original
            subprocess.run([
                FFMPEG,"-hide_banner","-loglevel","error","-nostdin","-y",
                "-ss",str(start),"-t",str(dur),"-i",str(input_mp4),
                "-c","copy", str(raw)
            ], capture_output=True, timeout=120)

            if not seg['is_hook'] and not seg['is_cierre']:
                # Aplicar overlay de nombre al segmento del artista
                png = generar_png(nombre, tmp)
                with_ov = tmp/f"ov_{i:02d}.mp4"
                if aplicar_overlay_segmento(raw, png, with_ov, dur):
                    parts.append(with_ov)
                    ok(f"{nombre}: overlay aplicado")
                else:
                    parts.append(raw)
                    err(f"{nombre}: overlay falló, usando sin overlay")
            else:
                parts.append(raw)
                ok(f"{seg['name']}: sin overlay")

        # Concat todos los segmentos
        print(f"\n  Concatenando {len(parts)} segmentos...")
        concat_txt = tmp/"concat.txt"
        concat_txt.write_text("\n".join(f"file '{p.resolve()}'" for p in parts))

        r = subprocess.run([
            FFMPEG,"-hide_banner","-loglevel","error","-nostdin","-y",
            "-f","concat","-safe","0","-i",str(concat_txt),
            "-i",str(input_mp4),
            "-map","0:v","-map","1:a",
            "-c:v","libx264","-preset","ultrafast","-crf","23",
            "-c:a","copy","-pix_fmt","yuv420p",
            str(out_final)
        ], capture_output=True, text=True, timeout=7200)

        if out_final.exists() and out_final.stat().st_size > 1_000_000:
            ok(f"output_overlays.mp4: {out_final.stat().st_size//(1024*1024)}MB")
            print(f"\n  {out_final}")
        else:
            err(f"Concat falló: {r.stderr[-400:]}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
