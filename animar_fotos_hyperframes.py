#!/usr/bin/env python3
"""
animar_fotos_hyperframes.py — Anima fotos con el estilo HyperFrames/EpocaDeOro.

Genera una composición animada con:
  - Fondo negro con cuadrícula sutil animada
  - Fotos con borde blanco, adaptadas a su orientación (portrait/landscape)
  - Entrada/salida alternando izquierda/derecha con GSAP
  - Badge dorado con nombre del artista
  - Filtro B&N en todas las fotos
  - Vignette

Uso:
  python3 animar_fotos_hyperframes.py \\
    --fotos "Foto1:/ruta/foto1.jpg" "Foto2:/ruta/foto2.jpg" "Foto3:/ruta/foto3.jpg" \\
    --out /ruta/salida/ \\
    --dur-slot 5.0 \\
    [--dur-ultimo 3.6]

Salida:
  /ruta/salida/index.html   ← composición HyperFrames
  /ruta/salida/render.mp4   ← video renderizado (si se usa --render)

Ejemplos:
  # Solo generar el index.html
  python3 animar_fotos_hyperframes.py \\
    --fotos "LUPE VÉLEZ:/path/lupe.jpg" "JORGE MISTRAL:/path/jorge.webp" \\
    --out /tmp/hook-test/

  # Generar y renderizar directamente
  python3 animar_fotos_hyperframes.py \\
    --fotos "LUPE VÉLEZ:/path/lupe.jpg" "JORGE MISTRAL:/path/jorge.webp" \\
    --out /tmp/hook-test/ --render
"""

import argparse, pathlib, shutil, subprocess, sys, textwrap

# ── Colores terminal ───────────────────────────────────────────────────────────
VERDE = "\033[92m"; ROJO = "\033[91m"; RESET = "\033[0m"; BOLD = "\033[1m"

# ── Parámetros visuales fijos del estilo ──────────────────────────────────────
MAX_W   = 1382   # 72% de 1920 — ancho máximo de foto
MAX_H   = 842    # 78% de 1080 — alto máximo de foto
XFADE   = 0.45
BADGE_IN = 1.2

def build_html(fotos: list[tuple[str, str]], dur_slot: float, dur_ultimo: float) -> str:
    """
    fotos: lista de (nombre, ruta_absoluta)
    dur_slot: duración en segundos de cada slot
    dur_ultimo: duración del último slot (puede ser menor)
    Retorna el HTML completo de la composición HyperFrames.
    """
    n = len(fotos)
    total = (n - 1) * dur_slot + dur_ultimo

    # ── Imgs relativas (se copian al dir de salida antes de renderizar) ────────
    img_tags = ""
    for i, (nombre, ruta) in enumerate(fotos):
        ext = pathlib.Path(ruta).suffix
        rel = f"foto_{i:02d}{ext}"
        alt = nombre
        img_tags += f"""
  <!-- Slot {i} ({i * dur_slot:.1f}–{i * dur_slot + (dur_ultimo if i == n-1 else dur_slot):.1f}s): {nombre} -->
  <div class="photo-frame" id="frame-{i}">
    <img class="slide-img" id="img-{i}" src="{rel}" alt="{alt}">
  </div>"""

    badge_tags = ""
    for i, (nombre, _) in enumerate(fotos):
        badge_tags += f"""
  <div class="gold-line" id="gl-{i}"></div>
  <div class="badge" id="badge-{i}"><span class="badge-text">{nombre.upper()}</span></div>"""

    # ── GSAP JS por cada slot ──────────────────────────────────────────────────
    def slot_js(i, nombre, slot_dur, is_last):
        t_start = i * dur_slot
        t_end   = t_start + slot_dur
        # Alternar dirección: pares entran desde izquierda, impares desde derecha
        enter_x = -700 if i % 2 == 0 else 700
        exit_x  =  400 if i % 2 == 0 else -400
        pan_x   = -12  if i % 2 == 0 else 12
        ir      = "false" if i > 0 else "true"
        exit_tween = "" if is_last else f"""
  tl.to("#frame-{i}", {{ opacity: 0, x: {exit_x}, duration: XFADE, ease: "power2.in", immediateRender: false }}, {t_end:.3f} - XFADE);
  tl.to("#gl-{i}",    {{ opacity: 0, duration: XFADE, ease: "power2.in" }}, {t_end:.3f} - XFADE);
  tl.to("#badge-{i}", {{ opacity: 0, y: -10, duration: XFADE, ease: "power2.in" }}, {t_end:.3f} - XFADE);"""
        return f"""
  // ── Slot {i} (t={t_start:.1f}–{t_end:.1f}s): {nombre} ──────────────────────────
  tl.fromTo("#frame-{i}",
    {{ opacity: 0, xPercent: -50, yPercent: -50, x: {enter_x} }},
    {{ opacity: 1, x: 0, duration: 0.65, ease: "power3.out", immediateRender: {ir} }},
    {t_start:.3f}
  );
  tl.fromTo("#img-{i}",
    {{ scale: 1.0, x: 0, y: 0 }},
    {{ scale: 1.06, x: {pan_x}, y: -8, duration: {slot_dur:.3f}, ease: "none", immediateRender: {ir} }},
    {t_start:.3f}
  );
  tl.fromTo("#gl-{i}",
    {{ width: 0, opacity: 0 }},
    {{ width: 320, opacity: 1, duration: 0.55, ease: "power3.out", immediateRender: {ir} }},
    {t_start + BADGE_IN - 0.15:.3f}
  );
  tl.fromTo("#badge-{i}",
    {{ opacity: 0, y: 20 }},
    {{ opacity: 1, y: 0, duration: 0.6, ease: "power3.out", immediateRender: {ir} }},
    {t_start + BADGE_IN:.3f}
  );{exit_tween}"""

    gsap_slots = ""
    for i, (nombre, _) in enumerate(fotos):
        slot_dur = dur_ultimo if i == n - 1 else dur_slot
        gsap_slots += slot_js(i, nombre, slot_dur, i == n - 1)

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Hook Card</title>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #0D0D0D; width: 1920px; height: 1080px; overflow: hidden; font-family: 'Arial', sans-serif; }}
    .clip {{ position: absolute; inset: 0; width: 1920px; height: 1080px; overflow: hidden; }}
    .bg {{ position: absolute; inset: 0; background: #0D0D0D; z-index: 0; }}
    .grid-layer {{
      position: absolute; inset: -120px;
      width: calc(100% + 240px); height: calc(100% + 240px);
      background-image:
        linear-gradient(to right,  rgba(255,255,255,0.06) 1px, transparent 1px),
        linear-gradient(to bottom, rgba(255,255,255,0.06) 1px, transparent 1px);
      background-size: 60px 60px; will-change: transform; z-index: 1;
    }}
    .vignette {{
      position: absolute; inset: 0;
      background: radial-gradient(ellipse 75% 75% at 50% 50%, transparent 40%, rgba(0,0,0,0.65) 100%);
      pointer-events: none; z-index: 5;
    }}
    .photo-frame {{
      position: absolute; top: 50%; left: 50%;
      transform: translate(-50%, -50%);
      width: fit-content; height: fit-content; overflow: hidden;
      border: 10px solid rgba(255,255,255,0.85);
      box-shadow: 0 0 0 1px rgba(255,255,255,0.15), 0 24px 80px rgba(0,0,0,0.8);
      z-index: 10; opacity: 0;
    }}
    .slide-img {{
      display: block;
      max-width: {MAX_W}px;
      max-height: {MAX_H}px;
      width: auto; height: auto;
      filter: grayscale(1) contrast(1.1) brightness(0.88);
      will-change: transform;
    }}
    .badge {{
      position: absolute; bottom: 148px; left: 50%; transform: translateX(-50%);
      background: #C9A227; padding: 14px 48px;
      border: 2px solid rgba(255,255,255,0.35);
      z-index: 20; opacity: 0; will-change: transform, opacity;
    }}
    .badge-text {{
      font-family: 'Arial Black', 'Arial', sans-serif;
      font-weight: 900; font-size: 32px; letter-spacing: 0.14em;
      color: #FFFFFF; text-transform: uppercase; white-space: nowrap;
    }}
    .gold-line {{
      position: absolute; bottom: 136px; left: 50%; transform: translateX(-50%);
      height: 2px; background: #C9A227; z-index: 20; width: 0; opacity: 0;
    }}
  </style>
</head>
<body>

<!-- TOTAL: {total:.1f}s — {n} fotos × {dur_slot:.1f}s (último {dur_ultimo:.1f}s) -->
<div data-hf-id="hf-hook-fotos" class="clip" data-start="0" data-duration="{total:.1f}"
     id="hook-card" data-composition-id="hook-card" data-width="1920" data-height="1080">

  <div class="bg"></div>
  <div class="grid-layer" id="grid"></div>
  <div class="vignette"></div>
{img_tags}
{badge_tags}

</div>

<script>
(function () {{
  var TOTAL    = {total:.3f};
  var XFADE    = {XFADE};
  var BADGE_IN = {BADGE_IN};

  var tl = gsap.timeline({{ paused: true }});
  window.__timelines = window.__timelines || {{}};
  window.__timelines["hook-card"] = tl;

  // Grid drift diagonal permanente
  tl.fromTo("#grid",
    {{ x: 0, y: 0 }},
    {{ x: -40, y: -28, duration: TOTAL, ease: "none" }},
    0
  );
{gsap_slots}
  // Fade-out general
  tl.to("#hook-card",
    {{ opacity: 0, duration: 0.4, ease: "power2.in" }},
    TOTAL - 0.4
  );
}})();
</script>
</body>
</html>"""
    return html


def main():
    parser = argparse.ArgumentParser(
        description="Genera y opcionalmente renderiza una composición HyperFrames con fotos animadas."
    )
    parser.add_argument(
        "--fotos", nargs="+", required=True,
        metavar="NOMBRE:/ruta/foto.jpg",
        help='Lista de fotos en formato "NOMBRE:/ruta/archivo.ext"'
    )
    parser.add_argument("--out", required=True, help="Directorio de salida para index.html y renders")
    parser.add_argument("--dur-slot", type=float, default=5.0, help="Duración de cada slot en segundos (default: 5.0)")
    parser.add_argument("--dur-ultimo", type=float, default=None,
                        help="Duración del último slot (default: igual a --dur-slot)")
    parser.add_argument("--render", action="store_true", help="Renderizar con HyperFrames después de generar HTML")
    parser.add_argument("--render-out", default=None, help="Ruta del MP4 de salida (default: <out>/render.mp4)")
    args = parser.parse_args()

    # Parsear fotos
    fotos = []
    for item in args.fotos:
        if ":" not in item:
            print(f"{ROJO}✗ Formato inválido: '{item}'. Usa NOMBRE:/ruta/archivo{RESET}")
            sys.exit(1)
        nombre, ruta = item.split(":", 1)
        p = pathlib.Path(ruta)
        if not p.exists():
            print(f"{ROJO}✗ No existe: {ruta}{RESET}")
            sys.exit(1)
        fotos.append((nombre.strip(), p.resolve()))

    dur_slot   = args.dur_slot
    dur_ultimo = args.dur_ultimo if args.dur_ultimo is not None else dur_slot
    out_dir    = pathlib.Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"{BOLD}── Animando {len(fotos)} fotos con HyperFrames ──{RESET}")
    for i, (nombre, ruta) in enumerate(fotos):
        d = dur_ultimo if i == len(fotos) - 1 else dur_slot
        print(f"  {i+1}. {nombre} ({ruta.name}) → {d:.1f}s")

    # Copiar fotos al directorio de salida con nombres normalizados
    fotos_rel = []
    for i, (nombre, ruta) in enumerate(fotos):
        ext = ruta.suffix.lower()
        dest = out_dir / f"foto_{i:02d}{ext}"
        shutil.copy2(ruta, dest)
        fotos_rel.append((nombre, ruta))

    # Generar HTML
    html = build_html(fotos_rel, dur_slot, dur_ultimo)
    index_path = out_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print(f"{VERDE}✓ index.html generado: {index_path}{RESET}")

    if not args.render:
        print(f"\n  Para renderizar:\n  cd {out_dir} && npx hyperframes render . --skill=motion-graphics -q high -o render.mp4")
        return

    # Renderizar con HyperFrames
    render_out = pathlib.Path(args.render_out) if args.render_out else out_dir / "render.mp4"
    print(f"\n  Renderizando con HyperFrames → {render_out.name} ...")
    result = subprocess.run(
        ["npx", "hyperframes", "render", ".", "--skill=motion-graphics",
         "-q", "high", "-o", str(render_out)],
        cwd=str(out_dir),
        capture_output=False
    )
    if result.returncode != 0:
        print(f"{ROJO}✗ HyperFrames falló (código {result.returncode}){RESET}")
        sys.exit(1)
    print(f"{VERDE}✓ Video listo: {render_out}{RESET}")


if __name__ == "__main__":
    main()
