#!/usr/bin/env python3
"""
Validador de guion — Canal Familias de Riquezas
Uso: python3 validador_guion_familias.py /ruta/carpeta/video/

Criterios:
1. Longitud: 22,000–28,000 caracteres (22–28 min)
2. Hook con objeto cotidiano ("Hay una botella", "Ábrela", "Detrás de la barra")
3. Pregunta gancho al inicio ("¿qué es lo que no te pueden quitar?")
4. Bienvenida canónica del canal
5. Origen: inmigrante con año y lugar de llegada
6. El golpe: fecha concreta de confiscación/crisis
7. Cierre con las 3 cosas que no se pueden confiscar
8. CTA al final
9. Sin dígitos sueltos (el TTS los lee en inglés)
10. Sin etiquetas ni comentarios entre corchetes (excepto [música])
"""

import sys, pathlib, re, json

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"

CFG_PATH = pathlib.Path(__file__).parent / "_config" / "familias.json"
cfg      = json.loads(CFG_PATH.read_text(encoding="utf-8"))
MIN_CHARS = cfg["guion"]["min_chars"]
MAX_CHARS = cfg["guion"]["max_chars"]

def ok(msg):    print(f"  {VERDE}✓{RESET} {msg}")
def error(msg): print(f"  {ROJO}✗{RESET} {msg}")
def warn(msg):  print(f"  {AMARILLO}⚠{RESET} {msg}")

HOOK_OBJETOS = [
    "hay una botella", "ábrela", "abre la", "detrás de la barra",
    "en la etiqueta", "en la mesa de", "en cualquier casa",
    "en la cocina", "en el bolsillo", "en cualquier bar",
    "cada vez que", "la próxima vez que",
]

PREGUNTA_GANCHO = [
    "no te puede quitar", "no te pueden quitar",
    "qué es exactamente lo que", "qué fue lo que se llevaron",
    "qué hicieron distinto", "cómo hace una familia para",
]

BIENVENIDA = [
    "bienvenido al único lugar", "te abrimos las puertas",
    "puertas que normalmente están cerradas",
]

ORIGEN_KEYWORDS = [
    "llegó de", "venía de", "nació en", "se bajó de un barco",
    "inmigrante", "cruzó el océano", "años", "sin dinero", "sin contactos",
]

GOLPE_KEYWORDS = [
    "confiscó", "expropió", "nacionalizó", "decreto", "se quedaron con",
    "les quitó", "quitó todo", "quitaron todo",
]

CIERRE_KEYWORDS = [
    "la primera es", "la segunda es", "la tercera es",
    "tres cosas", "son tres", "tres respuestas",
    "lo que no se puede confiscar", "lo que ningún gobierno",
    "no se puede quitar", "no te pueden quitar",
]

CTA_KEYWORDS = [
    "suscríbete", "like", "comenta", "déjamelo en los comentarios",
    "nos vemos", "síguenos",
]

def validar(carpeta_path):
    carpeta = pathlib.Path(carpeta_path)
    nombre  = carpeta.name
    txt     = carpeta / f"{nombre}.txt"

    if not txt.exists():
        txt_candidates = list(carpeta.glob("*.txt"))
        if txt_candidates:
            txt = txt_candidates[0]
        else:
            print(f"{ROJO}No se encontró archivo .txt en {carpeta}{RESET}")
            sys.exit(1)

    guion = txt.read_text(encoding="utf-8")
    guion_lower = guion.lower()
    primera_parte = guion_lower[:2000]

    print(f"\n{'='*60}")
    print(f"  VALIDADOR — Familias de Riquezas")
    print(f"  Archivo: {txt.name}")
    print(f"{'='*60}\n")

    errores = 0

    # 1. Longitud
    n = len(guion)
    if MIN_CHARS <= n <= MAX_CHARS:
        ok(f"Longitud: {n:,} chars ({n/6/150:.0f} min aprox)")
    elif n < MIN_CHARS:
        error(f"Muy corto: {n:,} chars — mínimo {MIN_CHARS:,}")
        errores += 1
    else:
        error(f"Muy largo: {n:,} chars — máximo {MAX_CHARS:,}")
        errores += 1

    # 2. Hook con objeto cotidiano
    if any(p in primera_parte for p in HOOK_OBJETOS):
        ok("Hook con objeto cotidiano detectado")
    else:
        warn("No se detectó apertura con objeto cotidiano (botella, producto, etc.)")

    # 3. Pregunta gancho
    if any(p in primera_parte for p in PREGUNTA_GANCHO):
        ok("Pregunta gancho al inicio detectada")
    else:
        warn("No se detectó pregunta gancho en el hook")

    # 4. Bienvenida canónica
    if any(p in primera_parte for p in BIENVENIDA):
        ok("Bienvenida canónica del canal presente")
    else:
        warn("Falta bienvenida: 'Bienvenido al único lugar donde te abrimos las puertas...'")

    # 5. Origen inmigrante
    if any(p in guion_lower for p in ORIGEN_KEYWORDS):
        ok("Sección de origen detectada")
    else:
        warn("No se detectó sección de origen del fundador")

    # 6. El golpe con fecha concreta
    if any(p in guion_lower for p in GOLPE_KEYWORDS):
        ok("El golpe / confiscación detectado")
    else:
        error("No se detectó el golpe (confiscación, expropiación, crisis). Es obligatorio.")
        errores += 1

    # 7. Cierre con las 3 cosas
    cierre = guion_lower[-3000:]
    if any(p in cierre for p in CIERRE_KEYWORDS):
        ok("Cierre con las 3 cosas que no se pueden confiscar detectado")
    else:
        warn("No se detectó el cierre canónico con las 3 cosas que no se pueden confiscar")

    # 8. CTA
    if any(p in cierre for p in CTA_KEYWORDS):
        ok("CTA al final presente")
    else:
        error("Falta CTA al final (suscríbete, like, comentarios)")
        errores += 1

    # 9. Sin dígitos sueltos
    digitos = re.findall(r'\b\d{4,}\b|\b\d{1,3}(?:,\d{3})+\b|\b\d+\b', guion)
    digitos_filtrados = [d for d in digitos if not re.search(r'\[|\]', d)]
    if not digitos_filtrados:
        ok("Sin dígitos sueltos")
    else:
        muestra = digitos_filtrados[:8]
        error(f"Dígitos encontrados (el TTS los lee en inglés): {muestra}")
        errores += 1

    # 10. Sin etiquetas extrañas
    etiquetas = re.findall(r'\[(?!música)([^\]]+)\]', guion, re.IGNORECASE)
    if not etiquetas:
        ok("Sin etiquetas ni comentarios entre corchetes")
    else:
        warn(f"Etiquetas encontradas (revisar): {etiquetas[:5]}")

    # 11. Validar prompts del timeline si existe
    timeline_path = carpeta / "05-montaje" / "timeline.json"
    if timeline_path.exists():
        try:
            tl = json.loads(timeline_path.read_text(encoding="utf-8"))
            segs = tl.get("visual_timeline", [])
            if segs:
                prompts = [s.get("ia_prompt", "") for s in segs]
                duplicados = len(prompts) - len(set(prompts))
                max_consecutivos = 1
                cuenta = 1
                for i in range(1, len(prompts)):
                    if prompts[i] == prompts[i-1]:
                        cuenta += 1
                        max_consecutivos = max(max_consecutivos, cuenta)
                    else:
                        cuenta = 1
                if duplicados == 0:
                    ok(f"Timeline prompts: todos únicos ({len(segs)} segmentos)")
                elif max_consecutivos > 2:
                    error(f"Timeline prompts: {duplicados} duplicados, {max_consecutivos} consecutivos iguales — regenerar antes de subir a Baserow")
                    errores += 1
                else:
                    warn(f"Timeline prompts: {duplicados} duplicados (máx {max_consecutivos} consecutivos)")
        except Exception as e:
            warn(f"No se pudo validar timeline.json: {e}")

    print(f"\n{'='*60}")
    if errores == 0:
        print(f"  {VERDE}✅ GUION VÁLIDO — listo para TTS{RESET}")
    else:
        print(f"  {ROJO}❌ {errores} error(s) — corregir antes del TTS{RESET}")
    print(f"{'='*60}\n")

    return errores == 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 validador_guion_familias.py familias/[slug]/")
        sys.exit(1)
    ok_result = validar(sys.argv[1])
    sys.exit(0 if ok_result else 1)
