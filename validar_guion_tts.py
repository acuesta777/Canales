#!/usr/bin/env python3
"""
validar_guion_tts.py — Detecta etiquetas estructurales y título antes de lanzar TTS.
Uso: python3 validar_guion_tts.py <archivo.txt>
Sale con código 1 si hay problemas, 0 si está limpio.
"""

import sys, re, pathlib

NUMEROS_ES = {
    0: "cero", 1: "uno", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco",
    6: "seis", 7: "siete", 8: "ocho", 9: "nueve", 10: "diez",
    11: "once", 12: "doce", 13: "trece", 14: "catorce", 15: "quince",
    16: "dieciséis", 17: "diecisiete", 18: "dieciocho", 19: "diecinueve",
    20: "veinte", 21: "veintiuno", 22: "veintidós", 23: "veintitrés",
    24: "veinticuatro", 25: "veinticinco", 26: "veintiséis", 27: "veintisiete",
    28: "veintiocho", 29: "veintinueve", 30: "treinta", 40: "cuarenta",
    50: "cincuenta", 60: "sesenta", 70: "setenta", 80: "ochenta", 90: "noventa",
}

def _num_a_letras(n):
    if n in NUMEROS_ES:
        return NUMEROS_ES[n]
    if n < 100:
        dec = (n // 10) * 10
        uni = n % 10
        return NUMEROS_ES[dec] + " y " + NUMEROS_ES[uni]
    if n < 1000:
        c = n // 100
        r = n % 100
        prefijos = {1:"cien", 2:"doscientos", 3:"trescientos", 4:"cuatrocientos",
                    5:"quinientos", 6:"seiscientos", 7:"setecientos", 8:"ochocientos", 9:"novecientos"}
        base = "ciento" if (c == 1 and r > 0) else prefijos[c]
        return base if r == 0 else base + " " + _num_a_letras(r)
    if n < 10000:
        miles = n // 1000
        r = n % 1000
        prefijo = "mil" if miles == 1 else _num_a_letras(miles) + " mil"
        return prefijo if r == 0 else prefijo + " " + _num_a_letras(r)
    return str(n)

def convertir_numeros(path):
    p = pathlib.Path(path)
    texto = p.read_text(encoding="utf-8")
    nums = sorted(set(int(m) for m in re.findall(r'\b\d+\b', texto)), reverse=True)
    if not nums:
        return
    for n in nums:
        texto = re.sub(r'\b' + str(n) + r'\b', _num_a_letras(n), texto)
    p.write_text(texto, encoding="utf-8")
    print(f"🔢 {len(nums)} número(s) convertido(s) a letras automáticamente.")

# Palabras/patrones que NO deben aparecer en el texto a narrar
ETIQUETAS = [
    r"^HOOK\s*$",
    r"^Hook\s*$",
    r"^BEAT\s+\d+",
    r"^Beat\s+\d+",
    r"^Introducción\s*$",
    r"^Conclusión\s*$",
    r"^Sección\s+\d+",
    r"^Segmento\s+\d+",
    r"^---+\s*$",          # separadores de markdown
    r"^#{1,6}\s+",         # títulos markdown
    r"^\*\*[^*]+\*\*\s*$", # líneas solo con negrita
    r"^Título:",
    r"^TÍTULO:",
    r"^Narración:",
    r"^NARRACIÓN:",
    r"^\[.+\]\s*$",        # [Pausa], [Música], etc.
]

AUTO_LIMPIAR = [
    r"^\[SUBTIPO PVA:.*\]\s*$",   # [SUBTIPO PVA: A/B/C...]
    r"^\[ARCO\s+\d+.*\]\s*$",     # [ARCO 3 ...]
    r"^\[ARCO:.*\]\s*$",
]

def limpiar(path):
    """Borra automáticamente labels conocidos de la línea 1 (y línea 2 vacía que queda)."""
    p = pathlib.Path(path)
    lineas = p.read_text(encoding="utf-8").splitlines()
    if not lineas:
        return
    primera = lineas[0].strip()
    for patron in AUTO_LIMPIAR:
        if re.match(patron, primera, re.IGNORECASE):
            # Quitar línea 1 y la línea vacía que queda debajo si existe
            lineas = lineas[1:]
            if lineas and lineas[0].strip() == "":
                lineas = lineas[1:]
            p.write_text("\n".join(lineas) + "\n", encoding="utf-8")
            print(f"🧹 Label eliminado automáticamente: '{primera}'")
            break

def validar(path):
    texto = pathlib.Path(path).read_text(encoding="utf-8")
    lineas = texto.splitlines()
    errores = []

    # Regla 1: la línea 1 NO debe ser el título (el TTS lo leería)
    if lineas and lineas[0].strip() and not lineas[0].startswith("#"):
        # Si la primera línea no está vacía y parece un título (mayúsculas, puntos suspensivos, corto)
        primera = lineas[0].strip()
        if len(primera) < 120 and ("…" in primera or primera.isupper() or primera.endswith("?")):
            errores.append(f"L1: posible TÍTULO en línea 1 — el TTS lo leerá: '{primera[:80]}'")

    # Regla 2: detectar etiquetas estructurales
    for i, linea in enumerate(lineas, 1):
        stripped = linea.strip()
        for patron in ETIQUETAS:
            if re.match(patron, stripped, re.IGNORECASE):
                errores.append(f"L{i}: etiqueta estructural detectada → '{stripped}'")
                break

    return errores

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 validar_guion_tts.py <archivo.txt|carpeta>")
        sys.exit(1)

    path = sys.argv[1]
    # Si es carpeta, buscar el .txt principal dentro
    p = pathlib.Path(path)
    if p.is_dir():
        txts = sorted(p.glob("*.txt"))
        if not txts:
            print(f"❌ No se encontró ningún .txt en {path}")
            sys.exit(1)
        path = str(txts[0])

    limpiar(path)
    convertir_numeros(path)
    errores = validar(path)

    if errores:
        print(f"\n⛔ GUION INVÁLIDO — {len(errores)} problema(s) encontrado(s):\n")
        for e in errores:
            print(f"  {e}")
        print("\n❌ Corrige el guion antes de lanzar el TTS.\n")
        sys.exit(1)
    else:
        print("✅ Guion limpio — sin etiquetas estructurales. Listo para TTS.")
        sys.exit(0)
