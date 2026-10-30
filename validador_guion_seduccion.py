#!/usr/bin/env python3
"""
validador_guion_seduccion.py — Valida que el guion cumple con seduccion.md
Uso: python3 validador_guion_seduccion.py <carpeta_video>
     python3 validador_guion_seduccion.py seduccion/no_eres_malo/

Criterios evaluados:
1. Longitud: 14,000–18,000 caracteres (15-20 min)
2. Apertura sin presentación (no empezar con "hola soy")
3. Gancho específico en el primer minuto
4. Destrucción de al menos 2 creencias falsas
5. Nombre del villano (sistema/paradigma, no el espectador)
6. Giro contraintuitivo presente
7. Framework con nombre bautizado
8. Cierre filosófico
9. Tono: segunda persona, sin vulgaridades
10. Sin etiquetas ni acotaciones
"""

import sys, pathlib, re

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"

def ok(msg):   print(f"  {VERDE}✓{RESET} {msg}")
def error(msg): print(f"  {ROJO}✗{RESET} {msg}")
def warn(msg):  print(f"  {AMARILLO}⚠{RESET} {msg}")


def validar(carpeta_path):
    carpeta = pathlib.Path(carpeta_path)
    nombre  = carpeta.name

    # Buscar el .txt del guion
    txt = carpeta / f"{nombre}.txt"
    if not txt.exists():
        txts = list((carpeta / "01-guion").glob("*.txt")) if (carpeta / "01-guion").exists() else []
        if txts:
            txt = txts[0]
        else:
            print(f"{ROJO}ERROR: No encontré guion en {carpeta}{RESET}")
            sys.exit(1)

    texto = txt.read_text(encoding="utf-8")
    chars = len(texto)
    texto_low = texto.lower()
    primera_linea = texto.strip().split("\n")[0].strip()
    primeros_2000 = texto[:2000].lower()
    primeros_5000 = texto[:5000].lower()
    ultimos_2000  = texto[-2000:].lower()
    errores = 0
    advertencias = 0

    print(f"\n{'='*58}")
    print(f"  VALIDACIÓN GUION SEDUCCIÓN — {nombre.upper()}")
    print(f"{'='*58}\n")

    # ── 1. LONGITUD ──────────────────────────────────────────────────────────
    print("1. LONGITUD (objetivo: 14,000–18,000 chars / 15-20 min):")
    if 14000 <= chars <= 18000:
        ok(f"{chars:,} caracteres — dentro del rango")
    elif chars < 14000:
        error(f"{chars:,} caracteres — CORTO, faltan {14000 - chars:,} chars")
        errores += 1
    else:
        warn(f"{chars:,} caracteres — LARGO por {chars - 18000:,} chars (igual es válido)")
        advertencias += 1

    # ── 2. APERTURA SIN PRESENTACIÓN ─────────────────────────────────────────
    print("\n2. APERTURA — sin presentación tipo 'hola soy':")
    presentaciones = ["hola, soy", "hola soy", "bienvenidos", "en este video", "hoy vamos a", "mi nombre es"]
    tiene_presentacion = any(p in primeros_2000 for p in presentaciones)
    if tiene_presentacion:
        error(f"El guion abre con presentación — debe empezar con contraste o escena de dolor")
        errores += 1
    else:
        ok("Apertura directa sin presentación")

    # ── 3. GANCHO ESPECÍFICO ─────────────────────────────────────────────────
    print("\n3. GANCHO ESPECÍFICO en el primer minuto:")
    ganchos = ["al final", "al terminar", "al final del video", "te voy a dar",
               "te voy a mostrar", "la frase exacta", "el método", "la técnica",
               "te voy a revelar", "quedate hasta"]
    tiene_gancho = any(g in primeros_2000 for g in ganchos)
    if tiene_gancho:
        ok("Gancho específico detectado en la apertura")
    else:
        warn("No se detectó gancho específico en los primeros 2,000 chars — agregar promesa que se revela al final")
        advertencias += 1

    # ── 4. DESTRUCCIÓN DE CREENCIAS ──────────────────────────────────────────
    print("\n4. DESTRUCCIÓN DE CREENCIAS falsas:")
    destructores = ["no es tu", "no se trata de", "no es cuestión de", "la mayoría piensa",
                    "eso es mentira", "eso está mal", "incorrecto", "ese es el error",
                    "contrario a lo que", "no funciona así"]
    encontrados = [d for d in destructores if d in texto_low]
    if len(encontrados) >= 3:
        ok(f"{len(encontrados)} frases de destrucción de creencias")
    elif len(encontrados) >= 1:
        warn(f"Solo {len(encontrados)} destrucción de creencias — el manual pide al menos 2-3")
        advertencias += 1
    else:
        error("No se detectaron frases que destruyan creencias falsas")
        errores += 1

    # ── 5. NOMBRE DEL VILLANO ────────────────────────────────────────────────
    print("\n5. NOMBRE DEL VILLANO (sistema o paradigma, no el espectador):")
    villanos = ["la trampa", "el error del", "el síndrome", "el problema es",
                "el modo", "el patrón", "la ilusión", "el paradigma", "la mentalidad de"]
    tiene_villano = any(v in texto_low for v in villanos)
    if tiene_villano:
        ok("Villano / paradigma erróneo identificado con nombre")
    else:
        warn("No se detectó un nombre para el error — bautizá el problema (ej. 'La Trampa del Guión Mental')")
        advertencias += 1

    # ── 6. GIRO CONTRAINTUITIVO ──────────────────────────────────────────────
    print("\n6. GIRO CONTRAINTUITIVO:")
    giros = ["contrario a lo que", "suena raro pero", "parecería que", "¿y si te dijera",
             "paradójicamente", "descubrí algo", "lo que nadie te dice",
             "la mayoría diría", "va en contra de"]
    tiene_giro = any(g in texto_low for g in giros)
    if tiene_giro:
        ok("Giro contraintuitivo presente")
    else:
        warn("No se detectó giro contraintuitivo claro — agregar el momento 'descubrí algo fascinante'")
        advertencias += 1

    # ── 7. FRAMEWORK CON NOMBRE ──────────────────────────────────────────────
    print("\n7. FRAMEWORK CON NOMBRE:")
    frameworks = ["los tres elementos", "los siete", "los cinco", "los cuatro",
                  "el primer punto", "punto número", "elemento 1", "error número",
                  "primer error", "segundo error", "tercer error",
                  "número uno", "número dos", "número tres"]
    tiene_framework = any(f in texto_low for f in frameworks)
    if tiene_framework:
        ok("Framework con elementos numerados detectado")
    else:
        error("No se detectó framework numerado — el núcleo del video debe tener lista bautizada")
        errores += 1

    # ── 8. CIERRE FILOSÓFICO ─────────────────────────────────────────────────
    print("\n8. CIERRE FILOSÓFICO:")
    cierres = ["al final del día", "en definitiva", "lo que importa", "lo que realmente",
               "el objetivo no es", "no se trata de ser", "recordá que", "llevate esto",
               "la verdad es que", "lo que de verdad"]
    tiene_cierre = any(c in ultimos_2000 for c in cierres)
    if tiene_cierre:
        ok("Cierre filosófico detectado en el final")
    else:
        warn("No se detectó cierre filosófico — agregar reflexión final de 10-15 palabras memorable")
        advertencias += 1

    # ── 9. SEGUNDA PERSONA Y TONO ────────────────────────────────────────────
    print("\n9. TONO — segunda persona y sin vulgaridades:")
    segunda_persona = texto_low.count(" vos ") + texto_low.count(" te ") + texto_low.count(" tu ")
    if segunda_persona >= 20:
        ok(f"{segunda_persona} usos de segunda persona (vos/te/tu)")
    else:
        warn(f"Solo {segunda_persona} usos de segunda persona — verificar que el tono sea directo")
        advertencias += 1

    vulgares = ["puta", "mierda", "coño", "culo", "joder", "cabrón"]
    tiene_vulgar = any(v in texto_low for v in vulgares)
    if tiene_vulgar:
        error("Vocabulario vulgar detectado — el canal mantiene tono serio y respetuoso")
        errores += 1
    else:
        ok("Vocabulario limpio")

    # ── 10. LIMPIEZA ─────────────────────────────────────────────────────────
    print("\n10. LIMPIEZA — sin etiquetas ni acotaciones:")
    etiquetas = ["[música]", "[pausa]", "[corte]", "## ", "**", "---", "[bloque", "[verificar]"]
    encontradas = [e for e in etiquetas if e.lower() in texto_low]
    if not encontradas:
        ok("Texto limpio para TTS")
    else:
        error(f"Etiquetas encontradas: {encontradas} — el .txt debe tener solo texto narrado")
        errores += 1

    # ── 11. POLÍTICAS DE YOUTUBE — CONTENIDO SENSIBLE ────────────────────────
    print("\n11. POLÍTICAS DE YOUTUBE — nicho seducción (alto riesgo):")

    # 11a. Lenguaje sexual explícito
    sexual_explicito = [
        "sexo", "sexual", "seducir en la cama", "acostar", "coger", "fornicar",
        "penetr", "orgasmo", "excitación sexual", "cuerpo desnudo", "desnud",
        "seducción sexual", "atracción sexual explícita",
    ]
    encontrado_sexual = [p for p in sexual_explicito if p in texto_low]
    if encontrado_sexual:
        error(f"Lenguaje sexual explícito detectado: {encontrado_sexual} — YouTube puede demonetizar o restringir")
        errores += 1
    else:
        ok("Sin lenguaje sexual explícito")

    # 11b. Framing de manipulación o acoso
    manipulacion = [
        "cómo manipular", "técnica de manipulación", "truco para manipular",
        "trucos para que ella", "hacer que ella te obedezca",
        "obligar a una mujer", "controlar a una mujer", "dominar a una mujer",
        "cómo perseguir", "cómo acechar",
        "cómo convencer a la fuerza", "si dice no insist", "aunque no quiera",
        "sin que se dé cuenta", "sin que ella sepa", "engañar a una mujer",
    ]
    encontrado_manip = [p for p in manipulacion if p in texto_low]
    if encontrado_manip:
        error(f"Framing de manipulación/acoso: {encontrado_manip} — viola políticas de acoso de YouTube")
        errores += 1
    else:
        ok("Sin framing de manipulación ni acoso")

    # 11c. Lenguaje misógino o degradante hacia la mujer
    misogino = [
        "las mujeres son", "todas las mujeres", "ellas solo quieren",
        "son todas iguales", "son interesadas", "son falsas", "son manipuladoras",
        "las hembras", "esa es su naturaleza", "así son ellas",
        "tratar mal para que te quieran", "hacerte el difícil para dominarla",
    ]
    encontrado_mis = [p for p in misogino if p in texto_low]
    if encontrado_mis:
        error(f"Lenguaje misógino o generalizaciones degradantes: {encontrado_mis}")
        errores += 1
    else:
        ok("Sin lenguaje misógino ni generalizaciones degradantes")

    # 11d. Tácticas red-pill / pickup tóxico
    redpill = [
        "hipergamia", "chad", "incel", "orbitar", "friendzone como trampa",
        "las mujeres no merecen", "zona de amigos es culpa de ella",
        "negging", "hacer sentir mal para atraer", "rebajar para conquistar",
        "el dominante alfa", "sumisión femenina",
    ]
    encontrado_rp = [p for p in redpill if p in texto_low]
    if encontrado_rp:
        error(f"Terminología red-pill/pickup tóxico: {encontrado_rp} — alto riesgo de restricción de audiencia")
        errores += 1
    else:
        ok("Sin terminología red-pill ni pickup tóxico")

    # 11e. Referencias a menores
    menores = [
        "menor de edad", "niña", "joven de ", "adolescente", "chica de 1", "chica de 1",
        "universitaria de primer", "recién cumplió",
    ]
    encontrado_men = [p for p in menores if p in texto_low]
    if encontrado_men:
        error(f"Posible referencia a menores de edad: {encontrado_men} — CRÍTICO")
        errores += 1
    else:
        ok("Sin referencias a menores de edad")

    # 11f. Advertencias leves (amarillo) — palabras que YouTube monitorea en este nicho
    riesgo_leve = [
        "seducir", "seducción", "conquistar", "ligarse", "atraer mujeres",
        "cómo hablar con mujeres", "técnica", "método",
    ]
    encontrado_leve = [p for p in riesgo_leve if p in texto_low]
    if encontrado_leve:
        warn(f"Palabras que YouTube monitorea en este nicho: {encontrado_leve[:4]} — normales si el contexto es educativo/respetuoso")
        advertencias += 1
    else:
        ok("Sin palabras de monitoreo leve")

    # ── VEREDICTO ────────────────────────────────────────────────────────────
    print(f"\n{'='*58}")
    if errores == 0 and advertencias == 0:
        print(f"  {VERDE}✓ GUION APROBADO — listo para TTS{RESET}")
    elif errores == 0:
        print(f"  {AMARILLO}⚠ APROBADO CON {advertencias} ADVERTENCIA(S){RESET}")
        print(f"  Revisar antes de TTS para maximizar retención")
    else:
        print(f"  {ROJO}✗ RECHAZADO — {errores} error(es), {advertencias} advertencia(s){RESET}")
        print(f"  Corregir antes de TTS para no gastar créditos")
    print(f"{'='*58}\n")

    return errores


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 validador_guion_seduccion.py <carpeta_video>")
        sys.exit(1)
    errores = validar(sys.argv[1])
    sys.exit(0 if errores == 0 else 1)
