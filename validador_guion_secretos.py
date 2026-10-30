#!/usr/bin/env python3
"""Validador de guion para el canal Secretos del Poder.
Verifica el arco de 8 beats, longitud, tono y requisitos del canal.
Uso: python3 validador_guion_secretos.py secretos/<slug>/
"""

import sys
import re
from pathlib import Path

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m⚠\033[0m"

errors = 0
warnings = 0

def check(ok, msg_ok, msg_fail, fatal=True):
    global errors, warnings
    if ok:
        print(f"  {PASS} {msg_ok}")
    else:
        if fatal:
            errors += 1
            print(f"  {FAIL} {msg_fail}")
        else:
            warnings += 1
            print(f"  {WARN} {msg_fail}")

def main():
    global errors, warnings
    if len(sys.argv) < 2:
        print("Uso: python3 validador_guion_secretos.py secretos/<slug>/")
        sys.exit(1)

    slug_dir = Path(sys.argv[1])
    slug = slug_dir.name
    guion_path = slug_dir / f"{slug}.txt"

    if not guion_path.exists():
        print(f"{FAIL} No se encontró {guion_path}")
        sys.exit(1)

    texto = guion_path.read_text(encoding="utf-8")
    chars = len(texto)
    palabras = texto.split()
    lineas = texto.splitlines()

    # primeros 2500 chars = hook
    hook = texto[:2500]
    # primeros 9000 chars = primeros ~10 min
    primeros_10 = texto[:9000]
    # últimos 1500 = kicker
    kicker = texto[-1500:]

    print("=" * 60)
    print(f"  VALIDACIÓN DE GUION SECRETOS DEL PODER — {slug.upper()}")
    print("=" * 60)

    # 1. LONGITUD
    print("\n1. LONGITUD:")
    MIN_CH, MAX_CH = 24500, 25500
    check(
        MIN_CH <= chars <= MAX_CH,
        f"{chars:,} caracteres — dentro del rango ({MIN_CH:,}–{MAX_CH:,})",
        f"{chars:,} caracteres — FUERA del rango ({MIN_CH:,}–{MAX_CH:,}). Ajustar.",
    )

    # 2. FECHAS EXACTAS (día mes año)
    print("\n2. FECHAS EXACTAS (obligatorio ≥1 en primeros 10 min):")
    fecha_pattern = re.compile(
        r"\b(\d{1,2}\s+de\s+\w+\s+de\s+\d{4}|"
        r"\d{1,2}\s+de\s+\w+,?\s+\d{4}|"
        r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
        r"septiembre|octubre|noviembre|diciembre\s+de\s+\d{4}|"
        r"\d{4}\b)",
        re.IGNORECASE
    )
    # también detectar años escritos en palabras (para TTS): "mil novecientos X"
    years_in_hook = re.findall(r"\b(1[89]\d{2}|20\d{2})\b", primeros_10)
    years_in_hook += re.findall(r"\bmil\s+(?:novecientos|ochocientos)\b", primeros_10, re.IGNORECASE)
    fechas_completas = re.findall(
        r"\b(?:\d{1,2}|[a-záéíóúüñ]+)\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+(?:\d{4}|mil\s+\w+)",
        texto, re.IGNORECASE
    )
    check(
        len(fechas_completas) >= 1 or len(years_in_hook) >= 2,
        f"{len(fechas_completas)} fechas completas + {len(years_in_hook)} años en primeros 10 min",
        "Sin fechas exactas en primeros 10 min — agregar al menos una fecha con día, mes y año",
    )

    # 3. LUGAR ESPECÍFICO
    print("\n3. LUGAR ESPECÍFICO (obligatorio ≥1):")
    lugares = re.findall(
        r"\b(Hermosillo|Sonora|Mazatlán|Sinaloa|México|CDMX|Ciudad de México|"
        r"Hollywood|Washington|Nueva York|Texas|California|"
        r"[A-Z][a-záéíóúñ]+(?:\s+[A-Z][a-záéíóúñ]+)*(?:\s+(?:Hotel|Church|Club|Palace|Hall|Theatre|Theater|Stadium|Arena|Building|Church|Cathedral|Street|Avenue|Boulevard|Plaza|Park)))",
        texto
    )
    check(
        len(lugares) >= 2,
        f"{len(lugares)} lugares específicos detectados",
        "Faltan lugares concretos — agregar nombres propios de lugares",
    )

    # 4. HOOK — contraste público vs privado
    print("\n4. HOOK — contraste imagen pública vs realidad:")
    palabras_quiebre = ["secreto", "libro", "verdad", "documento", "acta", "manifiesto",
                        "publicó", "escribió", "cuenta", "cuentas", "relato", "sin permiso",
                        "hechos", "reveló", "pero"]
    quiebre_hits = sum(1 for p in palabras_quiebre if p.lower() in hook.lower())
    check(
        quiebre_hits >= 2,
        f"Contraste detectado ({quiebre_hits} señales de quiebre en el hook)",
        "El hook no introduce evidencia concreta de contraste — agregar documento o dato contradictorio",
    )

    # 5. TONO — sin sentimentalismo
    print("\n5. TONO — sin sentimentalismo ni moralización:")
    frases_prohibidas = [
        "esto nos enseña", "qué lección", "ejemplo de vida", "qué inspiración",
        "debemos aprender", "hay que reconocer", "lección de vida", "admirable",
        "la vida nos da", "a pesar de todo", "al final del día",
        "el amor todo lo puede", "el amor verdadero"
    ]
    prohibidas_encontradas = [f for f in frases_prohibidas if f.lower() in texto.lower()]
    check(
        len(prohibidas_encontradas) == 0,
        "Sin frases moralizantes ni sentimentalistas",
        f"Frases prohibidas encontradas: {prohibidas_encontradas}",
    )

    adjetivos_emocionales = ["trágico", "devastador", "hermoso", "maravilloso",
                              "increíble vida", "gran amor", "noble", "generoso corazón"]
    adj_encontrados = [a for a in adjetivos_emocionales if a.lower() in texto.lower()]
    check(
        len(adj_encontrados) <= 1,
        "Tono neutro — sin adjetivos emocionales excesivos",
        f"Adjetivos emocionales detectados: {adj_encontrados} — quitar o reducir",
        fatal=False,
    )

    # 6. ARCO 8 BEATS
    print("\n6. ARCO DE 8 BEATS:")
    beats = {
        "Beat 1 — imagen oficial": ["fotografía", "foto", "imagen", "icónico", "ícono", "conocido", "famoso"],
        "Beat 2 — quiebre con evidencia": ["libro", "documento", "acta", "manifiesto", "sin permiso", "publicó", "escribió"],
        "Beat 3 — origen real": ["nació", "hermosillo", "sonora", "origen", "familia", "padre", "infancia", "creció"],
        "Beat 5 — matrimonio en oscuridad": ["alcohol", "alcoholismo", "ausencia", "ausencias", "silencio", "guardó"],
        "Beat 6 — catástrofe": ["murió", "muerto", "disparo", "arma", "muerte", "accidental", "tragedia"],
        "Beat 7 — control del relato": ["relato", "versión", "imagen", "industria", "permiso", "archivos", "narrativa"],
        "Beat 8 — kicker final": ["fotografía", "foto", "imagen", "charro"],
    }
    for beat_name, keywords in beats.items():
        # search in appropriate section
        if "Beat 8" in beat_name:
            seccion = kicker
        elif "Beat 1" in beat_name or "Beat 2" in beat_name:
            seccion = hook
        else:
            seccion = texto
        found = any(k.lower() in seccion.lower() for k in keywords)
        check(found, f"{beat_name}", f"{beat_name} — no detectado", fatal=("Beat 1" in beat_name or "Beat 6" in beat_name or "Beat 8" in beat_name))

    # 7. KICKER
    print("\n7. KICKER FINAL (últimas 1,500 chars):")
    kicker_frases_cortas = [s.strip() for s in kicker.split(".") if len(s.strip()) < 80 and len(s.strip()) > 10]
    check(
        len(kicker_frases_cortas) >= 2,
        f"Kicker con {len(kicker_frases_cortas)} frases cortas contundentes",
        "Kicker débil — debe terminar con 2-3 frases cortas que redefinen todo",
        fatal=False,
    )

    # 8. TEXTO LIMPIO para TTS
    print("\n8. LIMPIEZA para TTS:")
    etiquetas = re.findall(r"<[^>]+>|\[.*?\]|\*\*.*?\*\*|#{1,6}\s", texto)
    check(
        len(etiquetas) == 0,
        "Sin etiquetas HTML, markdown ni comentarios",
        f"Encontradas {len(etiquetas)} etiquetas/marcas — limpiar antes del TTS",
    )

    # RESULTADO FINAL
    print("\n" + "=" * 60)
    if errors == 0 and warnings == 0:
        print(f"  \033[92m✓ APROBADO — listo para TTS\033[0m")
    elif errors == 0:
        print(f"  \033[93m⚠ APROBADO CON ADVERTENCIAS — {warnings} advertencia(s)\033[0m")
    else:
        print(f"  \033[91m✗ RECHAZADO — {errors} error(es), {warnings} advertencia(s)\033[0m")
        print("  Corregir antes de TTS para no gastar créditos")
    print("=" * 60)

    sys.exit(0 if errors == 0 else 1)

if __name__ == "__main__":
    main()
