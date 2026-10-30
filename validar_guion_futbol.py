#!/usr/bin/env python3
"""
Validador pre-TTS para guiones de fútbol.
Verifica cumplimiento de la estructura de 5 actos según futbol.md antes de lanzar TTS.
"""

import sys
import re

VERDE = "\033[92m"
ROJO = "\033[91m"
AMARILLO = "\033[93m"
RESET = "\033[0m"
NEGRITA = "\033[1m"

def ok(msg): print(f"  {VERDE}✓{RESET} {msg}")
def falla(msg): print(f"  {ROJO}✗ FALLA: {msg}{RESET}")
def advertencia(msg): print(f"  {AMARILLO}⚠ {msg}{RESET}")

def validar(path):
    with open(path, encoding="utf-8") as f:
        texto = f.read()

    chars = len(texto)
    palabras = texto.split()
    parrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]

    # Estimación de duración: ~900 chars/min según riqueza.md
    duracion_min = chars / 900

    print(f"\n{NEGRITA}{'='*60}{RESET}")
    print(f"{NEGRITA}  VALIDADOR PRE-TTS — CANAL DE FÚTBOL{RESET}")
    print(f"{'='*60}")
    print(f"  Archivo : {path}")
    print(f"  Chars   : {chars:,}")
    print(f"  Palabras: {len(palabras):,}")
    print(f"  Duración: ~{duracion_min:.1f} min")
    print(f"{'='*60}\n")

    errores = 0
    advertencias = 0

    # ── 1. LONGITUD ──────────────────────────────────────────────
    print(f"{NEGRITA}[1] LONGITUD DEL GUION{RESET}")
    if 16000 <= chars <= 16800:
        ok(f"{chars:,} chars — dentro del rango 16,000–16,800")
    elif chars < 16000:
        falla(f"{chars:,} chars — DEMASIADO CORTO (faltan {16000-chars:,} chars)")
        errores += 1
    else:
        falla(f"{chars:,} chars — DEMASIADO LARGO (sobran {chars-16800:,} chars)")
        errores += 1

    # ── 2. PARADOJA / HOOK (primeros 45 segundos ≈ primeros 675 chars) ──
    print(f"\n{NEGRITA}[2] PARADOJA EN EL HOOK (primeros ~675 chars){RESET}")
    hook = texto[:675]
    # Palabras que indican paradoja/contraste
    palabras_paradoja = [
        "pero", "sin embargo", "aunque", "a pesar", "mientras", "no obstante",
        "y sin embargo", "y aun así", "a sus", "después de", "pese a",
        "que", "millones", "humild", "silencio", "sencill", "campo", "rancho"
    ]
    encontradas = [p for p in palabras_paradoja if p.lower() in hook.lower()]
    if len(encontradas) >= 3:
        ok(f"Paradoja detectada en el hook ({len(encontradas)} marcadores: {', '.join(encontradas[:5])})")
    else:
        advertencia(f"Hook débil — pocos marcadores de contraste/paradoja ({len(encontradas)}: {', '.join(encontradas)})")
        advertencias += 1

    # Verificar que NO empiece con "Hoy vamos a hablar de"
    inicio = texto[:100].lower()
    if "hoy vamos a hablar" in inicio or "hoy les voy a contar" in inicio:
        falla("El guion empieza con fórmula prohibida (Hoy vamos a hablar de...)")
        errores += 1
    else:
        ok("No usa fórmula de apertura prohibida")

    # ── 3. BLOQUE 2: CASA/LUGAR (2:00–8:00 ≈ chars 1800–7200) ──────────
    print(f"\n{NEGRITA}[3] BLOQUE 2 — CASA / LUGAR (2:00–8:00){RESET}")
    bloque2 = texto[1800:7200]
    palabras_lugar = [
        "casa", "vive", "apartamento", "departamento", "mansión", "propiedad",
        "miami", "marbella", "habitación", "cuarto", "piso", "residencia",
        "barrio", "ciudad", "piscina", "garage", "jardín", "rancho"
    ]
    encontradas2 = [p for p in palabras_lugar if p.lower() in bloque2.lower()]
    if len(encontradas2) >= 3:
        ok(f"Descripción de lugar detectada en zona 2:00–8:00 ({len(encontradas2)} marcadores)")
    else:
        falla(f"Faltan descripciones de casa/lugar en la zona 2:00–8:00 (solo {len(encontradas2)} marcadores)")
        errores += 1

    # ── 4. BLOQUE 4: MOMENTO EMOCIONAL (13:00–15:00 ≈ chars 11700–13500) ──
    print(f"\n{NEGRITA}[4] BLOQUE 4 — MOMENTO EMOCIONAL (13:00–15:00){RESET}")
    bloque4 = texto[11700:13500]
    palabras_emocion = [
        "lloró", "llanto", "emoción", "lágrimas", "abrazo", "corazón",
        "amor", "te amo", "hijo", "nieta", "venezia", "cumpleaños",
        "íntima", "silencio", "reconstruyó", "reconcil"
    ]
    encontradas4 = [p for p in palabras_emocion if p.lower() in bloque4.lower()]
    if len(encontradas4) >= 2:
        ok(f"Momento emocional detectado en zona 13:00–15:00 ({len(encontradas4)} marcadores: {', '.join(encontradas4[:5])})")
    else:
        advertencia(f"Momento emocional débil en zona 13:00–15:00 (solo {len(encontradas4)} marcadores)")
        advertencias += 1

    # ── 5. CIERRE FILOSÓFICO (últimos 1500 chars) ──────────────
    print(f"\n{NEGRITA}[5] CIERRE FILOSÓFICO (últimos ~1500 chars){RESET}")
    cierre = texto[-1500:]
    palabras_filosofia = [
        "siempre", "jamás", "nunca", "vida", "victoria", "lección",
        "fama", "queda", "verdadera", "al final", "desde el principio",
        "certeza", "recuerdan", "regresa", "cima", "apagar"
    ]
    encontradas5 = [p for p in palabras_filosofia if p.lower() in cierre.lower()]
    if len(encontradas5) >= 3:
        ok(f"Cierre filosófico detectado ({len(encontradas5)} marcadores: {', '.join(encontradas5[:5])})")
    else:
        falla(f"Cierre filosófico débil — faltan palabras de reflexión universal (solo {len(encontradas5)})")
        errores += 1

    # Verificar que el cierre NO sea un resumen sino una lección
    frases_resumen = ["en resumen", "como vimos", "hemos visto", "tal como te conté"]
    if any(f in cierre.lower() for f in frases_resumen):
        advertencia("El cierre parece un resumen del video en lugar de lección filosófica")
        advertencias += 1
    else:
        ok("El cierre no usa fórmulas de resumen")

    # ── 6. PRESENCIA DE ELEMENTOS CLAVE ────────────────────────
    print(f"\n{NEGRITA}[6] ELEMENTOS NARRATIVOS CLAVE{RESET}")
    elementos = {
        "Origen/infancia": ["henderson", "nació", "creció", "infancia", "pueblo", "origen"],
        "Historia deportiva": ["gol", "mundial", "partido", "selección", "club"],
        "Paradoja central": ["fama", "silencio", "humild", "millones", "sencill"],
        "Momento de crisis/caída": ["suspensión", "doping", "escándalo", "expulsado", "denunci"],
        "Vida actual": ["hoy", "miami", "actualmente", "cincuenta y nueve", "2026", "veintiséis"],
    }
    for nombre, kw in elementos.items():
        encontrado = any(k.lower() in texto.lower() for k in kw)
        if encontrado:
            ok(nombre)
        else:
            falla(f"Falta elemento: {nombre}")
            errores += 1

    # ── RESULTADO FINAL ──────────────────────────────────────────
    print(f"\n{NEGRITA}{'='*60}{RESET}")
    if errores == 0 and advertencias == 0:
        print(f"{VERDE}{NEGRITA}  ✅ GUION APROBADO — listo para TTS{RESET}")
    elif errores == 0:
        print(f"{AMARILLO}{NEGRITA}  ⚠ GUION APROBADO CON ADVERTENCIAS ({advertencias}) — revisar antes de TTS{RESET}")
    else:
        print(f"{ROJO}{NEGRITA}  ❌ GUION RECHAZADO — {errores} error(es), {advertencias} advertencia(s){RESET}")
        print(f"{ROJO}  Corregir antes de lanzar TTS{RESET}")
    print(f"{'='*60}\n")

    return errores == 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 validar_guion_futbol.py <archivo.txt>")
        sys.exit(1)
    ok_result = validar(sys.argv[1])
    sys.exit(0 if ok_result else 1)
