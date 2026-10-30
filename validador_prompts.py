#!/usr/bin/env python3
"""
Valida que los prompts de imagen correspondan al contenido del guion
en el segmento de tiempo indicado. Evita prompts irrelevantes.
"""
import sys, re, pathlib

# Palabras que NUNCA deben aparecer en un prompt a menos que el guion las mencione
# Palabras que NO deben aparecer en prompt a menos que el guion las mencione
# Aplica a cualquier tipo de personaje — si el guion habla de lucha, el prompt puede incluirlo
PALABRAS_RIESGO = [
    "ring", "lucha", "wrestlers", "boxing", "luchador", "pelea",
    "wrestling", "fighter", "arena deportiva", "combat",
    "trophy", "trophies", "award statue", "grammy statue", "trofeo",
    "couple kissing", "couple embracing", "pareja besándose",
    "portrait", "person smiling", "rostro", "cara sonriente",
]

# Si el prompt menciona dinero/billetes/premios → DEBE ser mansión, no otra cosa
REGLA_DINERO_MANSION = [
    "money", "bills", "cash", "dollar bills", "billetes", "dinero en efectivo",
    "award", "grammy", "prize", "premio", "galardón",
]

def srt_a_texto_por_minuto(srt_path):
    """Convierte SRT a dict {minuto_inicio: texto_acumulado}"""
    contenido = pathlib.Path(srt_path).read_text(encoding="utf-8")
    bloques = re.split(r'\n\n+', contenido.strip())
    por_minuto = {}
    for bloque in bloques:
        lineas = bloque.strip().split('\n')
        if len(lineas) < 3:
            continue
        tiempo = lineas[1] if '-->' in lineas[1] else None
        if not tiempo:
            continue
        inicio = tiempo.split('-->')[0].strip()
        h, m, s = re.split('[:,]', inicio)[:3]
        minuto = int(h) * 60 + int(m)
        texto = ' '.join(lineas[2:])
        por_minuto.setdefault(minuto, []).append(texto)
    return {m: ' '.join(t) for m, t in por_minuto.items()}

def timestamp_a_minutos(ts):
    """'00:02:30' -> 2"""
    partes = ts.split(':')
    return int(partes[0]) * 60 + int(partes[1])

def validar_prompt(prompt, timestamp, srt_por_minuto, guion_completo, ventana=2):
    """
    Valida que el prompt sea coherente con el contenido del guion
    en ±ventana minutos del timestamp.
    Retorna (ok: bool, mensaje: str)
    """
    minuto = timestamp_a_minutos(timestamp)
    # Texto relevante: ventana de minutos alrededor del timestamp
    texto_zona = ' '.join([
        srt_por_minuto.get(m, '')
        for m in range(max(0, minuto - 1), minuto + ventana + 1)
    ]).lower()

    prompt_lower = prompt.lower()
    errores = []

    # 1c. Regla dinero/premios → debe ser mansión
    for palabra in REGLA_DINERO_MANSION:
        if re.search(r'\b' + re.escape(palabra) + r'\b', prompt_lower):
            palabras_mansion = ["mansion", "house", "villa", "estate", "property", "hacienda", "rancho"]
            if not any(m in prompt_lower for m in palabras_mansion):
                errores.append(f"⚠ '{palabra}' en prompt → imagen debe ser mansión/propiedad, no otra cosa")

    # 1. Palabras de riesgo: verificar que el guion las mencione si el prompt las usa
    # Excepción: si la palabra está negada en el prompt ("no face", "no trophy") es válido
    for palabra in PALABRAS_RIESGO:
        patron = r'\b' + re.escape(palabra) + r'\b'
        if re.search(patron, prompt_lower):
            patron_negado = r'\bno\b(?:\s+\w+){0,6}\s+' + re.escape(palabra)
            if re.search(patron_negado, prompt_lower):
                continue  # "no face" / "no trophy" → válido, ignorar
            if not re.search(patron, guion_completo.lower()):
                errores.append(f"⚠ '{palabra}' en prompt pero NO aparece en el guion")

    # 2. Verificar que el prompt no sea completamente ajeno al contexto
    # Extraer sustantivos clave del prompt (palabras > 5 chars, no artículos)
    stopwords = {'cinematic','hyperrealistic','photo','image','dramatic','lighting',
                 'background','foreground','style','colors','scene','setting',
                 'portrait','landscape','16:9','mood','atmosphere','light','dark',
                 'golden','black','white','soft','warm','cool','interior','exterior'}
    palabras_prompt = [w for w in re.findall(r'[a-záéíóúñ]{5,}', prompt_lower)
                       if w not in stopwords]

    # Buscar si al menos 1 concepto del prompt aparece en la zona del SRT
    match = any(p in texto_zona for p in palabras_prompt)
    if not match and texto_zona.strip():
        # Segundo intento: buscar en guion completo cerca del timestamp
        guion_lower = guion_completo.lower()
        match = any(p in guion_lower for p in palabras_prompt[:5])
        if not match:
            errores.append(f"⚠ Prompt parece no relacionado con el contenido en {timestamp}")

    if errores:
        return False, ' | '.join(errores)
    return True, "✓ OK"

def validar_csv(carpeta_path):
    carpeta = pathlib.Path(carpeta_path)
    nombre = carpeta.name

    csv_file = carpeta / f"{nombre}_prompts.csv"
    srt_file = carpeta / f"{nombre}.srt"
    txt_file = carpeta / f"{nombre}.txt"

    if not csv_file.exists():
        print(f"ERROR: No encontré {csv_file}"); sys.exit(1)
    if not srt_file.exists():
        print(f"ERROR: No encontré {srt_file}"); sys.exit(1)
    if not txt_file.exists():
        print(f"ERROR: No encontré {txt_file}"); sys.exit(1)

    srt_por_minuto = srt_a_texto_por_minuto(srt_file)
    guion = txt_file.read_text(encoding="utf-8")

    lineas = csv_file.read_text(encoding="utf-8").strip().split('\n')
    header = lineas[0]
    filas = lineas[1:]

    print(f"\n{'='*60}")
    print(f"  VALIDADOR DE PROMPTS — {nombre.upper()}")
    print(f"{'='*60}")

    todos_ok = True
    resultados = []
    for i, fila in enumerate(filas, 1):
        partes = fila.split(',', 1)
        if len(partes) < 2:
            continue
        ts, prompt = partes[0].strip(), partes[1].strip()
        ok, mensaje = validar_prompt(prompt, ts, srt_por_minuto, guion)
        estado = "✓" if ok else "✗"
        if not ok:
            todos_ok = False
        resultados.append((i, ts, estado, mensaje, prompt))
        print(f"\n  Imagen {i} — {ts}")
        print(f"  {estado} {mensaje}")
        print(f"  Prompt: {prompt[:80]}...")

    print(f"\n{'='*60}")
    if todos_ok:
        print("  ✓ TODOS LOS PROMPTS APROBADOS")
    else:
        print("  ✗ HAY PROMPTS CON PROBLEMAS — revisar antes de generar")
    print(f"{'='*60}\n")
    return todos_ok, resultados

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 validador_prompts.py <carpeta_personaje>")
        sys.exit(1)
    ok, _ = validar_csv(sys.argv[1])
    sys.exit(0 if ok else 1)
