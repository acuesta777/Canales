#!/usr/bin/env python3
"""
validar_guion_canal.py — Validador genérico de guion por canal.

Lee _config/<canal>.json → usa las reglas del canal para validar el guion.
Verifica longitud, beats obligatorios, disclaimers, frases prohibidas y limpieza.

Uso:
    python3 validar_guion_canal.py <carpeta_video> --canal botica
    python3 validar_guion_canal.py riqueza/victoria_ruffo/ --canal riqueza
"""

import sys, pathlib, re, json, argparse

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"

CANALES_DIR = pathlib.Path(__file__).parent
CONFIG_DIR  = CANALES_DIR / "_config"

def ok(msg):    print(f"  {VERDE}✓{RESET} {msg}")
def error(msg): print(f"  {ROJO}✗{RESET} {msg}")
def warn(msg):  print(f"  {AMARILLO}⚠{RESET} {msg}")

def cargar_config(canal: str) -> dict:
    cfg_path = CONFIG_DIR / f"{canal}.json"
    if not cfg_path.exists():
        print(f"{ROJO}ERROR: No existe {cfg_path}{RESET}")
        print(f"  Canales disponibles: {[f.stem for f in CONFIG_DIR.glob('*.json')]}")
        sys.exit(1)
    return json.loads(cfg_path.read_text(encoding="utf-8"))

def inferir_canal(carpeta: pathlib.Path) -> str:
    padre = carpeta.parent.name
    if (CONFIG_DIR / f"{padre}.json").exists():
        return padre
    print(f"{ROJO}ERROR: No se pudo inferir canal desde '{padre}'. Usa --canal <nombre>{RESET}")
    sys.exit(1)

def validar(carpeta_path: str, canal: str):
    carpeta = pathlib.Path(carpeta_path)
    nombre  = carpeta.name
    cfg     = cargar_config(canal)
    gcfg    = cfg.get("guion", {})

    # Buscar el archivo de guion (.txt o .docx → leer el .txt)
    txt = carpeta / f"{nombre}.txt"
    if not txt.exists():
        # Buscar cualquier .txt en la carpeta
        txts = list(carpeta.glob("*.txt"))
        txts = [t for t in txts if "_test" not in t.name and "_src" not in t.name]
        if txts:
            txt = txts[0]
        else:
            print(f"{ROJO}ERROR: No encontré guion .txt en {carpeta}{RESET}")
            sys.exit(1)

    texto       = txt.read_text(encoding="utf-8")
    chars       = len(texto)
    texto_lower = texto.lower()
    errores     = 0
    advertencias= 0

    nombre_display = cfg.get("nombre_display", canal.upper())
    print(f"\n{'='*62}")
    print(f"  VALIDACIÓN DE GUION — {nombre.upper()}")
    print(f"  Canal: {nombre_display}")
    print(f"{'='*62}\n")

    # ── 1. LONGITUD ──────────────────────────────────────────────────────────
    chars_min = gcfg.get("chars_min", 0)
    chars_max = gcfg.get("chars_max", 999999)
    dur_min   = gcfg.get("duracion_min_min", 0)
    dur_max   = gcfg.get("duracion_max_min", 0)

    print("1. LONGITUD:")
    if chars_min <= chars <= chars_max:
        ok(f"{chars:,} caracteres — dentro del rango ({chars_min:,}–{chars_max:,})")
    elif chars < chars_min:
        error(f"{chars:,} caracteres — CORTO, faltan {chars_min-chars:,} chars (~{dur_min}–{dur_max} min objetivo)")
        errores += 1
    else:
        warn(f"{chars:,} caracteres — LARGO por {chars-chars_max:,} chars")
        advertencias += 1

    # ── 2. BEATS OBLIGATORIOS ─────────────────────────────────────────────────
    beats = gcfg.get("beats", [])
    if beats:
        print("\n2. BEATS OBLIGATORIOS:")
        for beat in beats:
            nombre_beat = beat.get("nombre", "?")
            tiempo      = beat.get("tiempo", "")
            keywords    = beat.get("keywords", [])
            encontrado  = any(kw in texto_lower for kw in keywords)
            if encontrado:
                ok(f"Beat '{nombre_beat}' ({tiempo})")
            else:
                error(f"Beat '{nombre_beat}' ({tiempo}) — ninguna keyword encontrada: {keywords[:3]}")
                errores += 1

    # ── 3. DISCLAIMER MÉDICO ─────────────────────────────────────────────────
    disclaimer_keys = gcfg.get("disclaimer_obligatorio", [])
    if disclaimer_keys:
        print("\n3. DISCLAIMER:")
        encontrados_disc = [k for k in disclaimer_keys if k in texto_lower]
        if encontrados_disc:
            ok(f"Disclaimer presente: '{encontrados_disc[0]}'")
        else:
            error(f"Falta disclaimer obligatorio. Incluir alguno de: {disclaimer_keys[:3]}")
            errores += 1

    # ── 4. FRASES PROHIBIDAS ─────────────────────────────────────────────────
    prohibidas = gcfg.get("prohibido", [])
    if prohibidas:
        print("\n4. FRASES PROHIBIDAS:")
        encontradas_proh = [f for f in prohibidas if f in texto_lower]
        if not encontradas_proh:
            ok("Sin frases prohibidas")
        else:
            for f in encontradas_proh:
                error(f"Frase prohibida encontrada: '{f}'")
                errores += 1

    # ── 5. LIMPIEZA (sin etiquetas ni comentarios) ────────────────────────────
    print("\n5. LIMPIEZA (sin etiquetas ni comentarios):")
    etiquetas = ["[música]", "[bloque", "[verificar]", "## ", "**", "---", "| #", "[beat"]
    encontradas_etiq = [e for e in etiquetas if e.lower() in texto_lower]
    if not encontradas_etiq:
        ok("Texto limpio para TTS")
    else:
        error(f"Etiquetas encontradas: {encontradas_etiq}")
        errores += 1

    # ── 6. HOOK — primeras 3 líneas ──────────────────────────────────────────
    print("\n6. APERTURA:")
    primera = texto.strip().split("\n")[0].strip()
    if len(primera) > 10:
        ok(f"Primera frase presente ({len(primera)} chars)")
        print(f"       → {primera[:100]}{'...' if len(primera)>100 else ''}")
    else:
        warn("Primera frase muy corta — revisar apertura del guion")
        advertencias += 1

    # ── VEREDICTO FINAL ──────────────────────────────────────────────────────
    print(f"\n{'='*62}")
    if errores == 0 and advertencias == 0:
        print(f"  {VERDE}✓ GUION APROBADO — listo para TTS{RESET}")
    elif errores == 0:
        print(f"  {AMARILLO}⚠ APROBADO CON ADVERTENCIAS ({advertencias} aviso(s)){RESET}")
        print(f"  Revisar advertencias antes de TTS")
    else:
        print(f"  {ROJO}✗ RECHAZADO — {errores} error(es), {advertencias} advertencia(s){RESET}")
        print(f"  Corregir antes de TTS para no gastar créditos")
    print(f"{'='*62}\n")

    return errores

def main():
    parser = argparse.ArgumentParser(description="Validador genérico de guion por canal")
    parser.add_argument("carpeta", help="Carpeta del video")
    parser.add_argument("--canal", help="Nombre del canal (ej: botica, riqueza, futbol)")
    args = parser.parse_args()

    carpeta = pathlib.Path(args.carpeta)
    canal   = args.canal or inferir_canal(carpeta)
    errores = validar(args.carpeta, canal)
    sys.exit(0 if errores == 0 else 1)

if __name__ == "__main__":
    main()
