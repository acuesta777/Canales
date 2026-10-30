#!/usr/bin/env python3
"""Validador de guion para el canal Secretos Mexicanos.
Verifica el arco de 8 beats, tono y requisitos del canal.
Longitud según _config/secretos-mexicanos.json → guion.monetizado:
  - monetizado: false → 25,000–30,000 chars (~25–30 min de audio)
  - monetizado: true  → 40,000–44,000 chars (~40–44 min de audio)
Uso: python3 validador_guion_secretos-mexicanos.py secretos-mexicanos/<slug>/
"""

import sys
import re
import json
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
        print("Uso: python3 validador_guion_secretos-mexicanos.py secretos-mexicanos/<slug>/")
        sys.exit(1)

    slug_dir = Path(sys.argv[1])
    slug = slug_dir.name
    guion_path = slug_dir / f"{slug}.txt"

    if not guion_path.exists():
        print(f"{FAIL} No se encontró {guion_path}")
        sys.exit(1)

    texto = guion_path.read_text(encoding="utf-8")
    chars = len(texto)

    # Secciones del guion
    hook        = texto[:2500]        # primeros ~2.5 min
    primeros_10 = texto[:10000]       # primeros ~10 min
    kicker      = texto[-2000:]       # cierre filosófico

    print("=" * 60)
    print(f"  VALIDACIÓN DE GUION SECRETOS MEXICANOS — {slug.upper()}")
    print("=" * 60)

    # 1. LONGITUD — rango según estado de monetización en el config
    print("\n1. LONGITUD:")
    _cfg_path = Path(__file__).parent / "_config" / "secretos-mexicanos.json"
    _cfg_guion = {}
    if _cfg_path.exists():
        _cfg_guion = json.loads(_cfg_path.read_text()).get("guion", {})
    _monetizado = _cfg_guion.get("monetizado", False)
    if _monetizado:
        MIN_CH = _cfg_guion.get("min_chars_monetizado", 40000)
        MAX_CH = _cfg_guion.get("max_chars_monetizado", 44000)
    else:
        MIN_CH = _cfg_guion.get("min_chars", 25000)
        MAX_CH = _cfg_guion.get("max_chars", 30000)
    estado = "monetizado" if _monetizado else "pre-monetización"
    check(
        MIN_CH <= chars <= MAX_CH,
        f"{chars:,} caracteres — dentro del rango {estado} ({MIN_CH:,}–{MAX_CH:,})",
        f"{chars:,} caracteres — FUERA del rango {estado} ({MIN_CH:,}–{MAX_CH:,}). Ajustar.",
    )

    # 2. APERTURA CINEMATOGRÁFICA — debe empezar con lugar + fecha, SIN nombrar al artista
    print("\n2. APERTURA CINEMATOGRÁFICA (lugar + fecha, sin nombre del artista primero):")
    primeras_200 = texto[:200]
    tiene_fecha_al_inicio = bool(re.search(
        r"\b(\d{1,2}\s+de\s+\w+|\d{4}|enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre"
        r"|dos mil|mil novecientos|mil ochocientos|siglo\s+\w+|años\s+(cincuenta|sesenta|setenta|ochenta|noventa|cuarenta|treinta|veinte))",
        primeras_200, re.IGNORECASE
    ))
    check(
        tiene_fecha_al_inicio,
        "Apertura con fecha o año en los primeros 200 chars",
        "El guion debe empezar con fecha/lugar, NO con el nombre del artista",
    )

    # 3. TEASE DE REVELACIONES — numeradas en el hook
    print("\n3. TEASE DE REVELACIONES (≥3 revelaciones numeradas):")
    revelaciones = re.findall(
        r"\b(primera|segunda|tercera|cuarta|primera revelación|segunda revelación|"
        r"revelación\s+\d|1\.|2\.|3\.|4\.)",
        primeros_10, re.IGNORECASE
    )
    check(
        len(revelaciones) >= 3,
        f"{len(revelaciones)} revelaciones enumeradas detectadas",
        "Faltan revelaciones numeradas — el tease debe prometer ≥3 revelaciones concretas",
    )

    # 4. FECHAS EXACTAS (credibilidad periodística)
    print("\n4. FECHAS EXACTAS (obligatorio ≥2 en el guion completo):")
    fechas_completas = re.findall(
        r"\b(?:\d{1,2}|[a-záéíóúüñ]+)\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|"
        r"julio|agosto|septiembre|octubre|noviembre|diciembre)(?:\s+de\s+(?:\d{4}|mil\s+\w+))?",
        texto, re.IGNORECASE
    )
    years = re.findall(r"\b(1[89]\d{2}|20[012]\d)\b", texto)
    check(
        len(fechas_completas) >= 2 or len(years) >= 4,
        f"{len(fechas_completas)} fechas completas + {len(years)} años detectados",
        "Faltan fechas exactas — agregar al menos 2 fechas con día, mes y año",
    )

    # 5. LUGARES ESPECÍFICOS DE MÉXICO
    print("\n5. LUGARES ESPECÍFICOS DE MÉXICO (obligatorio ≥3):")
    lugares_mx = re.findall(
        r"\b(Ciudad de México|CDMX|Guadalajara|Monterrey|Televisa|Televisa[a-z]*|"
        r"Los Pinos|Palacio Nacional|Acapulco|Sinaloa|Jalisco|Chihuahua|Sonora|"
        r"Veracruz|Oaxaca|Puebla|Tijuana|Mérida|"
        r"[A-Z][a-záéíóúñ]+(?:,\s+México)?)\b",
        texto
    )
    check(
        len(lugares_mx) >= 3,
        f"{len(lugares_mx)} referencias geográficas detectadas",
        "Faltan lugares específicos de México — agregar ciudades, estados o recintos concretos",
    )

    # 6. PALABRAS CLAVE DEL NICHO
    print("\n6. PALABRAS CLAVE DEL NICHO (traición/secreto/silencio/verdad/precio):")
    palabras_nicho = [
        "secreto", "traición", "silencio", "verdad", "precio", "oculto", "oculta",
        "destruyó", "destruir", "infierno", "revelación", "nunca contado",
        "nadie supo", "expediente", "testimonio", "documento", "grabación"
    ]
    hits_nicho = sum(1 for p in palabras_nicho if p.lower() in texto.lower())
    check(
        hits_nicho >= 6,
        f"{hits_nicho}/{len(palabras_nicho)} palabras clave del nicho presentes",
        f"Solo {hits_nicho} palabras clave — el guion necesita más vocabulario del nicho (secreto, traición, silencio, precio...)",
        fatal=False,
    )

    # 7. ARCO DE 8 BEATS
    print("\n7. ARCO DE 8 BEATS:")
    beats_checks = [
        ("Beat 1 — Apertura cinematográfica", primeras_200,
         ["de", "en", "un", "una"], False),  # ya validado arriba
        ("Beat 2 — Tease revelaciones", primeros_10,
         ["revelación", "primera", "segunda", "cuarta", "si te vas"], True),
        ("Beat 3 — Contexto del personaje", texto[:20000],
         ["dominio", "poder", "escenario", "television", "televisión", "billones", "semanas", "récord", "record", "número uno"], True),
        ("Beat 4 — Origen humilde", texto[:25000],
         ["nació", "infancia", "pobreza", "familia", "padre", "madre", "pueblo", "rancho", "humilde"], True),
        ("Beat 5 — Ascenso al poder", texto[10000:35000],
         ["fama", "éxito", "carrera", "contrato", "gira", "disco", "programa", "estrella"], True),
        ("Beat 6 — El secreto central", texto[20000:],
         ["secreto", "traición", "oculto", "escondido", "nunca", "jamás", "silencio", "expediente"], True),
        ("Beat 7 — La caída / el precio", texto[int(len(texto)*0.75):],
         ["precio", "cayó", "destruyó", "enfermedad", "exilio", "silencio", "perdió", "olvidó", "caída", "consecuencias", "deterioró", "desapareció"], True),
        ("Beat 8 — Cierre filosófico", kicker,
         ["hoy", "sigue", "permanece", "quedó", "esa decisión", "solo queda", "pregunta"], True),
    ]
    for beat_name, seccion, keywords, fatal in beats_checks:
        found = any(k.lower() in seccion.lower() for k in keywords)
        check(found, beat_name, f"{beat_name} — no detectado", fatal=fatal)

    # 8. NUNCA NOMBRAR AL ARTISTA EN LOS PRIMEROS 30 SEGUNDOS
    print("\n8. ARTISTA NO NOMBRADO EN LOS PRIMEROS 30 SEGUNDOS:")
    # Heurística: los primeros 500 chars no deben tener sustantivos propios solos
    # (difícil de validar automáticamente sin saber el nombre del artista)
    # Verificar que no empiece con nombre propio seguido de verbo
    empieza_con_nombre = bool(re.match(r'^[A-ZÁÉÍÓÚ][a-záéíóúñ]+\s+[A-ZÁÉÍÓÚ][a-záéíóúñ]+\s+(era|fue|nació|vivió|tenía)', texto.strip()))
    check(
        not empieza_con_nombre,
        "El guion NO empieza directamente con el nombre del artista",
        "El guion empieza con el nombre del artista — debe empezar con escena cinematográfica",
    )

    # 9. HEADERS EN MAYÚSCULAS — FATAL: no pueden quedar líneas de estructura interna
    print("\n9. SIN HEADERS EN MAYÚSCULAS (títulos de sección que el TTS leería):")
    headers_encontrados = []
    for linea in texto.splitlines():
        stripped = linea.strip()
        # Línea en mayúsculas puras (sin minúsculas), mínimo 4 chars, sin puntuación final
        if (len(stripped) >= 4
                and stripped == stripped.upper()
                and any(c.isalpha() for c in stripped)
                and not stripped.endswith((".", "?", "!", ":", "…"))):
            headers_encontrados.append(stripped[:60])
    check(
        len(headers_encontrados) == 0,
        "Sin headers de sección en mayúsculas",
        f"HEADERS ENCONTRADOS — el TTS los leerá en voz alta: {headers_encontrados[:5]}",
        fatal=True,
    )

    # 10. FRASES PROHIBIDAS (chisme / moralización)
    print("\n10. TONO — sin chisme ni moralización:")
    frases_prohibidas = [
        "dizque", "se dice que", "al parecer", "supuestamente",
        "esto nos enseña", "qué lección", "ejemplo de vida",
        "debemos aprender", "lección de vida", "el amor todo lo puede",
        "al final del día", "la vida nos da"
    ]
    encontradas = [f for f in frases_prohibidas if f.lower() in texto.lower()]
    check(
        len(encontradas) == 0,
        "Sin frases de chisme ni moralización",
        f"Frases prohibidas: {encontradas} — reemplazar por lenguaje periodístico",
    )

    # 11. NÚMEROS EN LETRAS (para TTS)
    print("\n10. NÚMEROS EN LETRAS (TTS lee dígitos en inglés):")
    numeros_raw = re.findall(r"\b\d{1,3}(?:[,\.]\d{3})*(?:\.\d+)?\b", texto)
    # Excluir años (4 dígitos entre 1900-2099) y horas simples
    numeros_problematicos = [n for n in numeros_raw
                             if not re.match(r'^(19|20)\d{2}$', n)
                             and not re.match(r'^\d{1,2}$', n)]
    check(
        len(numeros_problematicos) <= 5,
        f"Números controlados ({len(numeros_problematicos)} encontrados fuera de años)",
        f"{len(numeros_problematicos)} números que el TTS podría leer en inglés — convertir a letras",
        fatal=False,
    )

    # 12. TEXTO LIMPIO para TTS
    print("\n11. LIMPIEZA para TTS:")
    etiquetas = re.findall(r"<[^>]+>|\[.*?\]|\*\*.*?\*\*|#{1,6}\s", texto)
    check(
        len(etiquetas) == 0,
        "Sin etiquetas HTML, markdown ni comentarios",
        f"Encontradas {len(etiquetas)} etiquetas/marcas — limpiar antes del TTS",
    )

    print("\n12. REPETICIONES DE IDEAS (máx 2 párrafos por idea clave):")
    parrafos = [p.strip() for p in texto.split('\n\n') if len(p.strip()) > 80]
    ideas_repeticion = {
        "cigarro/tabaco": ["cigarro", "fumaba", "tabaco", "fumar"],
        "velorio/ausencia": ["no fue al velorio", "no estuvo en el velorio", "no fue a despedirse", "no asistió al velorio"],
        "arrepentimiento": ["se arrepentía", "se arrepentía", "arrepentido", "arrepentimiento", "lamentó no haber"],
        "vestuario/ropa propia": ["vestuario", "ropa de todos los días", "ropa propia"],
        "pobreza/alquiler": ["pagar el alquiler", "vendía comida", "dinero no alcanzaba", "pedía prestado"],
        "presta atención": ["presta atención", "lo que viene"],
    }
    rep_errors = []
    for idea, terminos in ideas_repeticion.items():
        ocurrencias = [i+1 for i, p in enumerate(parrafos) if any(t.lower() in p.lower() for t in terminos)]
        if len(ocurrencias) > 2:
            rep_errors.append(f"'{idea}' repetida en {len(ocurrencias)} párrafos ({ocurrencias[:5]})")
    check(
        len(rep_errors) == 0,
        f"Sin ideas repetidas en exceso",
        "IDEAS REPETIDAS — corregir antes del TTS:\n    " + "\n    ".join(rep_errors),
        fatal=True,
    )

    # RESULTADO FINAL
    print("\n" + "=" * 60)
    if errors == 0 and warnings == 0:
        print(f"  \033[92m✓ APROBADO — listo para TTS\033[0m")
    elif errors == 0:
        print(f"  \033[93m⚠ APROBADO CON ADVERTENCIAS — {warnings} advertencia(s)\033[0m")
    else:
        print(f"  \033[91m✗ RECHAZADO — {errors} error(es), {warnings} advertencia(s)\033[0m")
        print("  Corregir antes de TTS para no gastar créditos ElevenLabs")
    print("=" * 60)

    sys.exit(0 if errors == 0 else 1)

if __name__ == "__main__":
    main()
