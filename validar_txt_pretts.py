#!/usr/bin/env python3
"""
validar_txt_pretts.py — Valida el guion TXT ANTES de enviarlo al TTS.
Detecta problemas que causan alucinaciones o audio corrupto.

Uso: python3 validar_txt_pretts.py <archivo.txt>
"""
import sys, re
from pathlib import Path

VERDE   = "\033[92m"
ROJO    = "\033[91m"
AMARILLO= "\033[93m"
RESET   = "\033[0m"
NEGRITA = "\033[1m"

def ok(msg):   print(f"  {VERDE}✓{RESET} {msg}")
def falla(msg):print(f"  {ROJO}✗ FALLA: {msg}{RESET}")
def warn(msg): print(f"  {AMARILLO}⚠ {msg}{RESET}")

# Palabras inequívocamente inglesas (no existen en español)
ENGLISH_WORDS = [
    "the", "and", "that", "with", "this", "from", "they", "were",
    "have", "will", "our", "your", "their", "very", "because",
    "which", "about", "after", "before", "through", "would", "could",
    "should", "been", "being", "said", "going", "doing", "thing",
    "distrust", "expensive", "player", "football", "striker",
    "goalkeeper", "manager", "club", "league", "score", "goal",
]

def detectar_ingles(texto):
    """Encuentra líneas/frases con 2+ palabras en inglés consecutivas."""
    problemas = []
    lineas = texto.split('\n')
    for i, linea in enumerate(lineas, 1):
        palabras = re.findall(r'\b([a-zA-Z]{3,})\b', linea)
        streak = 0
        for p in palabras:
            if p.lower() in ENGLISH_WORDS:
                streak += 1
                if streak >= 2:
                    problemas.append((i, linea.strip()[:100]))
                    break
            else:
                streak = 0
    return problemas

def detectar_caracteres_raros(texto):
    """Detecta caracteres que confunden al TTS: emojis, símbolos, HTML."""
    problemas = []
    lineas = texto.split('\n')
    for i, linea in enumerate(lineas, 1):
        # Emojis y símbolos unicode no latinos
        if re.search(r'[\U00010000-\U0010ffff]|[☀-➿]', linea):
            problemas.append((i, f"emoji/símbolo: {linea.strip()[:80]}"))
        # HTML tags
        if re.search(r'<[a-z]+>', linea, re.IGNORECASE):
            problemas.append((i, f"HTML: {linea.strip()[:80]}"))
        # URLs
        if re.search(r'https?://', linea):
            problemas.append((i, f"URL: {linea.strip()[:80]}"))
        # Markdown headers
        if re.match(r'^#{1,3}\s', linea):
            problemas.append((i, f"markdown: {linea.strip()[:80]}"))

def detectar_repeticiones(texto):
    """Detecta párrafos o frases largas que se repiten."""
    parrafos = [p.strip() for p in texto.split('\n\n') if len(p.strip()) > 80]
    vistos = {}
    repetidos = []
    for p in parrafos:
        clave = p[:60].lower()
        if clave in vistos:
            repetidos.append(p[:80])
        else:
            vistos[clave] = True
    return repetidos

def detectar_saltos_idioma(texto):
    """Detecta bloques donde de repente hay una oración en inglés."""
    oraciones = re.split(r'[.!?]\s+', texto)
    problemas = []
    for o in oraciones:
        palabras = re.findall(r'\b[a-zA-Z]{3,}\b', o)
        if len(palabras) < 4:
            continue
        en = sum(1 for p in palabras if p.lower() in ENGLISH_WORDS)
        ratio = en / len(palabras)
        if ratio > 0.4:  # más del 40% de palabras son inglesas
            problemas.append(o.strip()[:100])
    return problemas

def validar(path):
    texto = Path(path).read_text(encoding="utf-8")
    chars = len(texto)
    lineas = texto.count('\n')

    print(f"\n{NEGRITA}{'='*60}{RESET}")
    print(f"{NEGRITA}  VALIDADOR PRE-TTS — GUION TXT{RESET}")
    print(f"{'='*60}")
    print(f"  Archivo: {path}")
    print(f"  Chars  : {chars:,} | Líneas: {lineas}")
    print(f"{'='*60}\n")

    errores = 0
    advertencias = 0

    # ── 1. INGLÉS MEZCLADO ───────────────────────────────────────
    print(f"{NEGRITA}[1] INGLÉS MEZCLADO EN EL TEXTO{RESET}")
    ing = detectar_ingles(texto)
    if ing:
        for linea_n, txt in ing[:5]:
            falla(f"Línea {linea_n}: \"{txt}\"")
        errores += len(ing)
    else:
        ok("Sin inglés detectado")

    # ── 2. SALTOS DE IDIOMA (oraciones enteras en inglés) ────────
    print(f"\n{NEGRITA}[2] ORACIONES EN INGLÉS{RESET}")
    saltos = detectar_saltos_idioma(texto)
    if saltos:
        for s in saltos[:3]:
            falla(f"\"{s}\"")
        errores += len(saltos)
    else:
        ok("Sin oraciones en inglés")

    # ── 3. CARACTERES PROBLEMÁTICOS ──────────────────────────────
    print(f"\n{NEGRITA}[3] CARACTERES QUE CONFUNDEN AL TTS{RESET}")
    # Emojis
    if re.search(r'[\U00010000-\U0010ffff]|[☀-➿]', texto):
        falla("Contiene emojis o símbolos unicode")
        errores += 1
    else:
        ok("Sin emojis ni símbolos")
    # URLs
    if re.search(r'https?://', texto):
        falla("Contiene URLs")
        errores += 1
    else:
        ok("Sin URLs")
    # HTML
    if re.search(r'<[a-z]+>', texto, re.IGNORECASE):
        falla("Contiene HTML")
        errores += 1
    else:
        ok("Sin HTML")
    # Números romanos seguidos de punto (pueden confundir)
    romanos = re.findall(r'\b(I{2,}|IV|VI{0,3}|IX|XI{0,3}|XIV|XV)\b\.', texto)
    if romanos:
        warn(f"Números romanos con punto: {romanos[:3]} — pueden causar pausa rara")
        advertencias += 1
    else:
        ok("Sin números romanos problemáticos")

    # ── 4. PÁRRAFOS REPETIDOS ────────────────────────────────────
    print(f"\n{NEGRITA}[4] PÁRRAFOS O FRASES REPETIDAS{RESET}")
    reps = detectar_repeticiones(texto)
    if reps:
        for r in reps[:3]:
            falla(f"Repetido: \"{r}\"")
        errores += len(reps)
    else:
        ok("Sin repeticiones de párrafos")

    # ── 5. LONGITUD MÍNIMA ───────────────────────────────────────
    print(f"\n{NEGRITA}[5] LONGITUD{RESET}")
    # Para fútbol: mín 16,000. Para riqueza: mín 24,500
    if chars < 15000:
        falla(f"Muy corto ({chars:,} chars) — TTS puede generar audio incompleto")
        errores += 1
    else:
        ok(f"{chars:,} chars — longitud aceptable")

    # ── RESULTADO ────────────────────────────────────────────────
    print(f"\n{NEGRITA}{'='*60}{RESET}")
    if errores == 0 and advertencias == 0:
        print(f"{VERDE}{NEGRITA}  ✅ TXT APROBADO — listo para enviar a TTS{RESET}")
    elif errores == 0:
        print(f"{AMARILLO}{NEGRITA}  ⚠ TXT APROBADO CON ADVERTENCIAS — revisar antes de TTS{RESET}")
    else:
        print(f"{ROJO}{NEGRITA}  ❌ TXT RECHAZADO — corregir antes de TTS ({errores} error(es)){RESET}")
    print(f"{'='*60}\n")
    return errores == 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 validar_txt_pretts.py <archivo.txt>")
        sys.exit(1)
    ok_result = validar(sys.argv[1])
    sys.exit(0 if ok_result else 1)
