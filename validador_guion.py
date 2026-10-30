#!/usr/bin/env python3
"""
Validador de guion — verifica que el guion cumple con el manual riqueza.md
Uso: python3 validador_guion.py /ruta/carpeta/personaje/

Criterios evaluados:
1. Longitud: 24,500–25,500 caracteres
2. Hook variado — detecta fórmula usada y avisa si ya se usó en otro personaje
3. Loops apilados en el hook (4-5 preguntas)
4. Arco narrativo maestro (11 bloques del manual)
5. Atribución correcta de cifras
6. Re-anzuelos presentes
7. CTA al final
8. Sin etiquetas ni comentarios
9. Enfoque en riqueza/lujo
"""

import sys, pathlib, re, json

VERDE   = "\033[92m"
ROJO    = "\033[91m"
AMARILLO = "\033[93m"
RESET   = "\033[0m"

CANALES_DIR = pathlib.Path(__file__).parent
HOOKS_FILE  = CANALES_DIR / "hooks_usados.json"

def ok(msg):    print(f"  {VERDE}✓{RESET} {msg}")
def error(msg): print(f"  {ROJO}✗{RESET} {msg}")
def warn(msg):  print(f"  {AMARILLO}⚠{RESET} {msg}")

# ── Fórmulas de hook del manual ───────────────────────────────────────────────
HOOK_FORMULAS = {
    # Nuevo formato: lugar + fecha + escena sensorial (sin nombre ni fortuna en primera frase)
    # La fortuna y el nombre aparecen en la Parte 2 del hook (~párrafo 2-3)
    "cinematografica":   [
        ", una noche de", ", una mañana de", ", un día de",
        ", primavera de", ", verano de", ", otoño de", ", invierno de",
        ", enero de", ", febrero de", ", marzo de", ", abril de",
        ", mayo de", ", junio de", ", julio de", ", agosto de",
        ", septiembre de", ", octubre de", ", noviembre de", ", diciembre de",
        "hay un rancho que", "hay una casa que", "hay una propiedad que",
        "hay un lugar que guarda",
    ],
    "fortuna_directa":   ["¿cuánta fortuna llegó a amasar", "¿cuánta fortuna llegó a acumular", "¿cuánto dinero llegó a acumular"],
    "contraste":         ["pocos saben que detrás de", "nadie sabía que detrás de", "todo el mundo lo vio", "todo el mundo la vio"],
    "imagen_de_lujo":    ["imagina despertar", "imagina entrar a una propiedad", "imagina vivir en"],
    "pregunta_de_vida":  ["¿cómo vive realmente", "¿cómo vivía realmente", "¿cómo es la vida real de"],
    "dato_impactante":   ["en sus mejores años", "lo que ganó en", "ganaba más en un mes"],
    "misterio":          ["hay una historia que", "hay un secreto que", "hay algo que nunca contó"],
    "nostalgia_lujo":    ["una generación entera lo vio", "una generación entera la vio", "una generación entera creció"],
    "sabias_que":        ["¿sabías que el hombre que", "¿sabías que la mujer que", "¿sabías que quien", "¿sabías que este hombre", "¿sabías que esta mujer"],
    "hoy_vas_a_descubrir": ["hoy vas a descubrir cómo vivió", "hoy vas a descubrir cómo vive", "hoy vas a conocer cómo vivió", "hoy vas a conocer cómo vive"],
}

def detectar_formula_hook(primera_frase):
    f = primera_frase.lower()
    for nombre, patrones in HOOK_FORMULAS.items():
        if any(p in f for p in patrones):
            return nombre
    return "otra"

def cargar_hooks():
    if HOOKS_FILE.exists():
        return json.loads(HOOKS_FILE.read_text(encoding="utf-8"))
    return {}

def guardar_hook(personaje, formula, primera_frase):
    hooks = cargar_hooks()
    hooks[personaje] = {"formula": formula, "primera_frase": primera_frase[:120]}
    HOOKS_FILE.write_text(json.dumps(hooks, ensure_ascii=False, indent=2), encoding="utf-8")

# ── Bloques del arco narrativo maestro (riqueza.md §5) ───────────────────────
BLOQUES_NARRATIVOS = {
    "Hook / fortuna inicial":     ["se estima que", "según reportes", "su fortuna", "millones de dólares", "patrimonio"],
    "Orígenes / trayectoria":     ["nació", "infancia", "creció", "origen", "humilde", "pueblo", "ciudad natal", "sus inicios"],
    "Propiedad principal":        ["mansión", "mansion", "rancho", "hacienda", "residencia", "propiedad", "villa", "penthouse", "suite"],
    "Colección de autos":         ["auto", "carro", "colección", "ferrari", "lamborghini", "mercedes", "rolls", "garaje"],
    "Patrimonio / ingresos":      ["ingresos", "derechos de autor", "gira", "contrato", "negocios", "inversión", "salario", "sueldo"],
    "Vida personal / amores":     ["esposa", "esposo", "pareja", "matrimonio", "amor", "divorci", "hijo", "hija"],
    "Conflicto / revelación":     ["escándalo", "conflicto", "enfermedad", "muerte", "pérdida", "accidente", "problema", "drama"],
    "Vida cotidiana / hoy":       ["hoy", "actualmente", "en la actualidad", "retiro", "jubil", "últimos años"],
    "Cierre emotivo / CTA":       ["comenta", "cuéntanos", "comentarios", "suscríbete", "comparte", "like", "¿qué piensas"],
}

def validar(carpeta_path):
    carpeta = pathlib.Path(carpeta_path)
    nombre  = carpeta.name
    txt     = carpeta / f"{nombre}.txt"

    if not txt.exists():
        print(f"{ROJO}ERROR: No encontré {txt}{RESET}")
        sys.exit(1)

    texto = txt.read_text(encoding="utf-8")
    chars = len(texto)
    texto_lower = texto.lower()
    errores = 0
    advertencias = 0

    print(f"\n{'='*58}")
    print(f"  VALIDACIÓN DE GUION — {nombre.upper()}")
    print(f"{'='*58}\n")

    # ── 1. LONGITUD ──────────────────────────────────────────────────────────
    print("1. LONGITUD:")
    if 24500 <= chars <= 25500:
        ok(f"{chars:,} caracteres — dentro del rango (24,500–25,500)")
    elif chars < 24500:
        error(f"{chars:,} caracteres — CORTO, faltan {24500-chars:,} chars")
        errores += 1
    else:
        warn(f"{chars:,} caracteres — LARGO por {chars-25500:,} chars")
        advertencias += 1

    # ── 2. HOOK — FÓRMULA Y VARIEDAD ─────────────────────────────────────────
    print("\n2. HOOK — FÓRMULA Y VARIEDAD:")
    primera = texto.strip().split("\n")[0].strip()
    formula = detectar_formula_hook(primera)
    hooks_anteriores = cargar_hooks()

    # Buscar si esta fórmula se usó recientemente (últimos 3 personajes)
    ultimos = list(hooks_anteriores.items())[-3:]
    formulas_recientes = [h["formula"] for _, h in ultimos if _ != nombre]
    personajes_con_misma = [p for p, h in ultimos if h["formula"] == formula and p != nombre]

    if formula == "otra":
        warn(f"Fórmula de hook no reconocida — verificar manualmente:\n    → {primera[:100]}")
        advertencias += 1
    elif personajes_con_misma:
        warn(f"Fórmula '{formula}' ya usada en: {', '.join(personajes_con_misma)} — variar para no repetir")
        advertencias += 1
    else:
        ok(f"Hook con fórmula '{formula}' — no repetida en últimos 3 personajes")

    # Verificar que establece nicho de lujo en la primera frase
    # Excepción: hook cinematográfico — la fortuna aparece en la Parte 2, no en la primera línea
    palabras_nicho = ["fortuna", "millones", "mansión", "mansion", "lujo", "riqueza", "patrimonio",
                      "dólares", "propiedad", "villa", "rancho", "colección", "jet"]
    tiene_nicho = any(p in primera.lower() for p in palabras_nicho)
    if formula == "cinematografica":
        # Verificar que la fortuna aparece en los primeros 3,000 chars (Parte 2 del hook)
        apertura = texto[:3000].lower()
        tiene_fortuna_parte2 = any(p in apertura for p in palabras_nicho + ["se estima", "patrimonio", "tres millones", "dos millones", "un millón"])
        if tiene_fortuna_parte2:
            ok("Hook cinematográfico — fortuna establecida en Parte 2 ✓")
        else:
            warn("Hook cinematográfico pero la fortuna no aparece en los primeros 3,000 chars")
            advertencias += 1
    elif tiene_nicho:
        ok("Primera frase establece el nicho de lujo")
    else:
        warn(f"Primera frase no menciona lujo/fortuna directamente:\n    → {primera[:100]}")
        advertencias += 1

    # ── 3. LOOPS APILADOS EN EL HOOK ─────────────────────────────────────────
    print("\n3. LOOPS EN EL HOOK (primeros 3,500 chars):")
    # Hook cinematográfico es más largo (3 partes) — ampliar ventana de búsqueda
    ventana = 3500 if formula == "cinematografica" else 2500
    hook = texto[:ventana]
    n_preguntas = hook.count("¿")

    if formula == "cinematografica":
        # Verificar también revelaciones numeradas ("Primero", "Segundo", "Tercero")
        tiene_revelaciones = all(p in hook.lower() for p in ["primero", "segundo", "tercero"])
        tiene_cuarta = any(p in hook.lower() for p in ["la cuarta", "y la cuarta", "cuarto"])
        if tiene_revelaciones and tiene_cuarta:
            ok("4 revelaciones numeradas presentes (Primero / Segundo / Tercero / cuarta)")
        elif tiene_revelaciones:
            warn("Faltan las 4 revelaciones — solo se detectaron Primero/Segundo/Tercero")
            advertencias += 1
        else:
            warn("Hook cinematográfico sin revelaciones numeradas — agregar 'Primero… Segundo… Tercero… Y la cuarta'")
            advertencias += 1

    if n_preguntas >= 4:
        ok(f"{n_preguntas} preguntas-loop en el hook")
    elif n_preguntas >= 2:
        warn(f"Solo {n_preguntas} preguntas en el hook (manual pide 4–5)")
        advertencias += 1
    else:
        error(f"Solo {n_preguntas} preguntas en el hook — insuficiente retención")
        errores += 1

    # Promesa de payoff diferido
    payoffs = ["hasta el final", "apenas estamos comenzando", "como verás más adelante", "en un momento"]
    tiene_payoff = any(p in hook.lower() for p in payoffs)
    if tiene_payoff:
        ok("Promesa de payoff diferido presente en el hook")
    else:
        warn("Falta promesa de payoff al cierre del hook ('quédate hasta el final...')")
        advertencias += 1

    # ── 4. ARCO NARRATIVO MAESTRO (11 bloques) ───────────────────────────────
    print("\n4. ARCO NARRATIVO (bloques del manual §5):")
    for bloque, palabras in BLOQUES_NARRATIVOS.items():
        encontrado = any(p in texto_lower for p in palabras)
        if encontrado:
            ok(bloque)
        else:
            error(f"Bloque ausente: {bloque}")
            errores += 1

    # ── 5. ATRIBUCIÓN DE CIFRAS ──────────────────────────────────────────────
    print("\n5. ATRIBUCIÓN DE CIFRAS:")
    atribuciones = ["se estima", "según reportes", "según fuentes", "aproximadamente",
                    "se calcula", "se dice que", "según publicaciones", "según medios"]
    n_attr = sum(texto_lower.count(a) for a in atribuciones)
    if n_attr >= 5:
        ok(f"{n_attr} frases de atribución encontradas")
    elif n_attr >= 2:
        warn(f"Solo {n_attr} frases de atribución — revisar cifras sin fuente")
        advertencias += 1
    else:
        error(f"Solo {n_attr} frases de atribución — riesgo legal por cifras sin fuente")
        errores += 1

    # ── 6. RE-ANZUELOS ───────────────────────────────────────────────────────
    print("\n6. RE-ANZUELOS (retención a media parte):")
    anzuelos = ["lo que descubrió después", "presta atención", "aquí viene lo que más",
                "da un giro", "aún más impactante", "lo que casi nadie sabe",
                "pero hay algo", "pero lo verdaderamente", "pero antes de",
                "como veremos más adelante", "ya llegaremos", "en un momento te",
                "pero lo que nadie esperaba", "aquí es donde"]
    encontrados = [a for a in anzuelos if a in texto_lower]
    if len(encontrados) >= 4:
        ok(f"{len(encontrados)} re-anzuelos detectados")
    elif len(encontrados) >= 2:
        warn(f"Solo {len(encontrados)} re-anzuelos — agregar más cada 2-3 min")
        advertencias += 1
    else:
        error(f"Solo {len(encontrados)} re-anzuelos — retención a media parte en riesgo")
        errores += 1

    # ── 7. LIMPIEZA ──────────────────────────────────────────────────────────
    print("\n7. LIMPIEZA (sin etiquetas ni comentarios):")
    etiquetas = ["[música]", "[bloque", "[verificar]", "## ", "**", "---", "| #"]
    encontradas = [e for e in etiquetas if e.lower() in texto_lower]
    if not encontradas:
        ok("Texto limpio para TTS")
    else:
        error(f"Etiquetas encontradas: {encontradas}")
        errores += 1

    # ── 8. ENFOQUE EN RIQUEZA ────────────────────────────────────────────────
    print("\n8. ENFOQUE EN RIQUEZA/LUJO (nicho del canal):")
    palabras_riqueza = ["mansión", "mansion", "propiedad", "millones", "fortuna", "lujo", "lujoso",
                        "lujosa", "colección", "auto", "carro", "avión", "yate", "rancho", "resort"]
    n_riqueza = sum(texto_lower.count(p) for p in palabras_riqueza)
    if n_riqueza >= 20:
        ok(f"{n_riqueza} menciones de riqueza/lujo en el texto")
    elif n_riqueza >= 10:
        warn(f"Solo {n_riqueza} menciones de riqueza/lujo — verificar enfoque")
        advertencias += 1
    else:
        error(f"Solo {n_riqueza} menciones de riqueza/lujo — guion no cumple el nicho")
        errores += 1

    # ── VEREDICTO FINAL ──────────────────────────────────────────────────────
    print(f"\n{'='*58}")
    if errores == 0 and advertencias == 0:
        print(f"  {VERDE}✓ GUION APROBADO — listo para TTS{RESET}")
    elif errores == 0:
        print(f"  {AMARILLO}⚠ APROBADO CON ADVERTENCIAS ({advertencias} avisos){RESET}")
        print(f"  Revisar advertencias antes de TTS")
    else:
        print(f"  {ROJO}✗ RECHAZADO — {errores} error(es), {advertencias} advertencia(s){RESET}")
        print(f"  Corregir antes de TTS para no gastar créditos")
    print(f"{'='*58}\n")

    # Registrar el hook usado (aunque tenga errores — para llevar historial)
    guardar_hook(nombre, formula, primera)
    print(f"  Hook registrado en hooks_usados.json → '{formula}'")
    if hooks_anteriores:
        print(f"  Hooks anteriores registrados: {len(hooks_anteriores)} personaje(s)")
    print()

    return errores

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 validador_guion.py /ruta/carpeta/personaje/")
        sys.exit(1)
    errores = validar(sys.argv[1])
    sys.exit(0 if errores == 0 else 1)
