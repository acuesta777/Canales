#!/usr/bin/env python3
"""
Validador de guion — Canal Historia Animada
Uso: python3 validador_guion_historia.py /ruta/carpeta/video/

Criterios:
1. Longitud: 14,000–18,000 caracteres
2. Hook sensorial (año exacto + escena concreta en primeros 500 chars)
3. Paradoja/pregunta central presente
4. Atribución correcta de afirmaciones históricas
5. Sin overclaiming — usa "algunos historiadores sugieren", "según..."
6. CTA al final
7. Texto limpio para TTS (sin etiquetas, sin dígitos)
8. Enfoque en el nicho: historia, mitología, civilizaciones antiguas
"""

import sys, pathlib, re, json

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"

CANALES_DIR = pathlib.Path(__file__).parent
HOOKS_FILE  = CANALES_DIR / "historia" / "datos" / "hooks_usados.json"

def ok(msg):    print(f"  {VERDE}✓{RESET} {msg}")
def error(msg): print(f"  {ROJO}✗{RESET} {msg}")
def warn(msg):  print(f"  {AMARILLO}⚠{RESET} {msg}")

def cargar_hooks():
    if HOOKS_FILE.exists():
        return json.loads(HOOKS_FILE.read_text(encoding="utf-8"))
    return {}

def guardar_hook(slug, primera_frase):
    hooks = cargar_hooks()
    hooks[slug] = {"primera_frase": primera_frase[:120]}
    HOOKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOOKS_FILE.write_text(json.dumps(hooks, ensure_ascii=False, indent=2), encoding="utf-8")

def validar(carpeta_path):
    carpeta = pathlib.Path(carpeta_path)
    slug    = carpeta.name
    txt     = carpeta / f"{slug}.txt"

    if not txt.exists():
        print(f"{ROJO}ERROR: No encontré {txt}{RESET}")
        sys.exit(1)

    texto       = txt.read_text(encoding="utf-8")
    chars       = len(texto)
    texto_lower = texto.lower()
    errores     = 0
    advertencias = 0

    print(f"\n{'='*60}")
    print(f"  VALIDACIÓN HISTORIA — {slug.upper()}")
    print(f"{'='*60}\n")

    # ── 1. LONGITUD ──────────────────────────────────────────────────────────
    print("1. LONGITUD:")
    if 14000 <= chars <= 18000:
        ok(f"{chars:,} caracteres — dentro del rango (14,000–18,000)")
    elif chars < 14000:
        error(f"{chars:,} caracteres — CORTO, faltan {14000-chars:,} chars")
        errores += 1
    else:
        warn(f"{chars:,} caracteres — LARGO por {chars-18000:,} chars (máx 18,000)")
        advertencias += 1

    # ── 2. HOOK SENSORIAL (año exacto + escena concreta) ─────────────────────
    print("\n2. HOOK SENSORIAL (primeros 500 chars):")
    hook = texto[:500]
    # Año con letras o con dígitos
    tiene_anno = bool(re.search(
        r'\b(año\s+\w+|siglo\s+\w+|\d{3,4}\s+(antes|después|a\.C|d\.C|a\.d\.C|BCE|CE))',
        hook, re.IGNORECASE))
    if tiene_anno:
        ok("Año/período exacto presente en el hook")
    else:
        error("Falta año o período concreto en los primeros 500 chars ('Es el año...')")
        errores += 1

    # Verifica que NO empieza con pregunta abstracta ni "En este video"
    primera = texto.strip().split("\n")[0].strip()
    if primera.startswith("¿") or "en este video" in primera.lower():
        error(f"Hook empieza con pregunta abstracta o 'en este video' — debe ser escena sensorial:\n    → {primera[:100]}")
        errores += 1
    else:
        ok("Hook no empieza con pregunta abstracta")

    # ── 3. PARADOJA / PREGUNTA CENTRAL ───────────────────────────────────────
    print("\n3. PARADOJA / PREGUNTA CENTRAL:")
    paradojas = ["la pregunta es", "pero la verdadera pregunta", "la verdadera pregunta",
                 "cómo fue posible", "cómo pudo", "¿cómo una", "¿cómo un", "eso no es",
                 "no es una coincidencia", "es una decisión"]
    tiene_paradoja = any(p in texto_lower[:3000] for p in paradojas)
    if tiene_paradoja:
        ok("Paradoja o pregunta central presente")
    else:
        warn("No se detectó paradoja/pregunta central en los primeros 3,000 chars")
        advertencias += 1

    # ── 4. ATRIBUCIÓN HISTÓRICA ───────────────────────────────────────────────
    print("\n4. ATRIBUCIÓN HISTÓRICA:")
    atribuciones = ["según", "se estima", "algunos historiadores", "los relatos",
                    "la evidencia", "se cree", "se dice", "los registros", "las fuentes",
                    "investigadores", "arqueólogos", "historiadores", "aproximadamente",
                    "se calcula", "los expertos"]
    n_attr = sum(texto_lower.count(a) for a in atribuciones)
    if n_attr >= 8:
        ok(f"{n_attr} frases de atribución encontradas")
    elif n_attr >= 4:
        warn(f"Solo {n_attr} frases de atribución — agregar más para no overclaimar")
        advertencias += 1
    else:
        error(f"Solo {n_attr} frases de atribución — riesgo de overclaiming")
        errores += 1

    # ── 5. SIN OVERCLAIMING ───────────────────────────────────────────────────
    print("\n5. SIN OVERCLAIMING:")
    overclaims = ["definitivamente", "está comprobado que", "es un hecho que",
                  "la historia demuestra que", "es indudable"]
    encontrados = [o for o in overclaims if o in texto_lower]
    if not encontrados:
        ok("Sin frases de overclaiming detectadas")
    else:
        warn(f"Posible overclaiming: {encontrados} — revisar y suavizar")
        advertencias += 1

    # ── 6. CTA AL FINAL ───────────────────────────────────────────────────────
    print("\n6. CTA AL FINAL (últimos 500 chars):")
    cierre = texto[-500:].lower()
    ctas = ["suscríbete", "suscribete", "comenta", "comentarios", "comparte",
            "like", "siguiente video", "próximo video", "trazamos estas conexiones"]
    tiene_cta = any(c in cierre for c in ctas)
    if tiene_cta:
        ok("CTA presente al final")
    else:
        error("Falta CTA al final del guion")
        errores += 1

    # ── 7. TEXTO LIMPIO PARA TTS ──────────────────────────────────────────────
    print("\n7. LIMPIEZA PARA TTS:")
    etiquetas = ["[música]", "[bloque", "[verificar]", "## ", "**", "---", "| #"]
    encontradas = [e for e in etiquetas if e.lower() in texto_lower]
    if not encontradas:
        ok("Sin etiquetas de formato")
    else:
        error(f"Etiquetas encontradas (rompen TTS): {encontradas}")
        errores += 1

    # Dígitos sueltos (TTS los lee en inglés)
    digitos = re.findall(r'\b\d+\b', texto)
    if not digitos:
        ok("Sin dígitos — TTS leerá todo en español")
    else:
        ejemplos = digitos[:5]
        error(f"Dígitos encontrados (TTS los lee en inglés): {ejemplos} — convertir a letras")
        errores += 1

    # ── 8. ENFOQUE EN NICHO HISTORIA ─────────────────────────────────────────
    print("\n8. ENFOQUE EN HISTORIA/MITOLOGÍA:")
    palabras_nicho = ["griegos", "grecia", "romano", "roma", "antiguo", "antigua", "mitología",
                      "mito", "historia", "histórico", "civilización", "dios", "diosa", "deidad",
                      "templo", "imperio", "siglo", "antes de cristo", "después de cristo",
                      "arqueología", "manuscrito", "papiro", "inscripción"]
    n_nicho = sum(texto_lower.count(p) for p in palabras_nicho)
    if n_nicho >= 15:
        ok(f"{n_nicho} referencias a historia/mitología")
    elif n_nicho >= 8:
        warn(f"Solo {n_nicho} referencias al nicho — verificar enfoque temático")
        advertencias += 1
    else:
        error(f"Solo {n_nicho} referencias al nicho — guion no cumple el tema")
        errores += 1

    # ── VEREDICTO ─────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    if errores == 0 and advertencias == 0:
        print(f"  {VERDE}✓ GUION APROBADO — listo para TTS{RESET}")
    elif errores == 0:
        print(f"  {AMARILLO}⚠ APROBADO CON ADVERTENCIAS ({advertencias} avisos){RESET}")
    else:
        print(f"  {ROJO}✗ RECHAZADO — {errores} error(es), {advertencias} advertencia(s){RESET}")
        print(f"  Corregir antes de TTS para no gastar créditos")
    print(f"{'='*60}\n")

    guardar_hook(slug, primera)
    return errores

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 validador_guion_historia.py /ruta/carpeta/video/")
        sys.exit(1)
    errores = validar(sys.argv[1])
    sys.exit(0 if errores == 0 else 1)
