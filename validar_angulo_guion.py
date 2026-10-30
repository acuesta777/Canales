#!/usr/bin/env python3
"""
REGLA DURA: Validar que hook, arco narrativo y trama giren en torno al ángulo seleccionado.
Uso: python3 validar_angulo_guion.py <carpeta_video> --angulo "doble vida"
"""
import sys
import re
from pathlib import Path

ANGULOS = {
    "doble vida": {
        "keywords": ["doble vida", "novia oficial", "andrea", "en secreto", "ocultó", "ocultaba", "al mismo tiempo", "mientras", "paralela", "sabía", "no sabía", "engaño", "infidelidad", "dos mujeres", "dos relaciones"],
        "hook_required": ["doble vida", "novia", "secreto", "al mismo tiempo", "mientras"],
        "prohibido_ausente": [],  # keywords que DEBEN aparecer en el guion
        "descripcion": "Doble vida / infidelidad — novia oficial + hijo secreto simultáneos",
    },
    "aborto forzado": {
        "keywords": ["aborto", "clínica", "embarazo", "presionó", "obligó", "los ángeles", "pagó", "dinero", "desapareció", "6 meses"],
        "hook_required": ["aborto", "presionó", "clínica"],
        "prohibido_ausente": [],
        "descripcion": "Aborto forzado — presión para abortar y desaparición posterior",
    },
    "hijo robado": {
        "keywords": ["robó", "quitó", "madrina", "custodia", "secuestró", "se llevó", "dos años", "separada", "plan", "sin su hijo"],
        "hook_required": ["robó", "quitó", "custodia", "hijo"],
        "prohibido_ausente": [],
        "descripcion": "Hijo robado — conspiración para quitarle el hijo a Lourdes",
    },
    "heredero destruido": {
        "keywords": ["shila devil", "millones", "herencia", "drogas", "alcohol", "sin dientes", "destruido", "40 años", "7 millones", "camilín", "camilo blanes"],
        "hook_required": ["millones", "heredero", "destruido", "shila"],
        "prohibido_ausente": [],
        "descripcion": "Heredero destruido — Camilín y el legado malgastado",
    },
}

def validar(carpeta: Path, angulo: str):
    angulo = angulo.lower()
    if angulo not in ANGULOS:
        print(f"❌ Ángulo '{angulo}' no reconocido. Válidos: {list(ANGULOS.keys())}")
        sys.exit(1)

    config = ANGULOS[angulo]
    print(f"\n🎯 Validando ángulo: {config['descripcion']}")
    print("="*60)

    # Buscar guion
    guion_paths = list(carpeta.glob("01-guion/*.txt")) + list(carpeta.glob("01-guion/*.md"))
    if not guion_paths:
        print("❌ No se encontró guion en 01-guion/")
        sys.exit(1)

    guion_path = guion_paths[0]
    texto = guion_path.read_text(encoding="utf-8").lower()
    lineas = texto.split("\n")

    errores = []
    advertencias = []

    # 1. HOOK — primeras 400 palabras deben contener keywords del ángulo
    palabras = texto.split()
    hook_texto = " ".join(palabras[:400])
    hook_hits = [k for k in config["hook_required"] if k in hook_texto]
    if not hook_hits:
        errores.append(f"HOOK (primeras 400 palabras) no menciona ninguna keyword del ángulo: {config['hook_required']}")
    else:
        print(f"✅ HOOK contiene: {hook_hits}")

    # 2. ARCO NARRATIVO — el ángulo debe aparecer en CADA TERCIO del guion
    tercio = len(palabras) // 3
    tercios = [
        " ".join(palabras[:tercio]),
        " ".join(palabras[tercio:tercio*2]),
        " ".join(palabras[tercio*2:]),
    ]
    nombres = ["Tercio 1 (apertura-contexto)", "Tercio 2 (ascenso-secreto)", "Tercio 3 (caída-cierre)"]
    for i, (t, nombre) in enumerate(zip(tercios, nombres)):
        hits = [k for k in config["keywords"] if k in t]
        if not hits:
            errores.append(f"ARCO — {nombre} no contiene keywords del ángulo '{angulo}'")
        else:
            print(f"✅ {nombre}: {hits[:3]}")

    # 3. TRAMA — densidad mínima: al menos 1 keyword cada 800 palabras
    ventana = 800
    for i in range(0, len(palabras), ventana):
        segmento = " ".join(palabras[i:i+ventana])
        hits = [k for k in config["keywords"] if k in segmento]
        if not hits:
            pos_aprox = i // 150  # aprox minuto
            advertencias.append(f"Segmento ~min {pos_aprox}-{pos_aprox+5} sin mención del ángulo — riesgo de desvío narrativo")

    # 4. PROPORCIÓN — keywords del ángulo deben representar presencia significativa
    total_hits = sum(texto.count(k) for k in config["keywords"])
    total_palabras = len(palabras)
    densidad = total_hits / (total_palabras / 1000)
    if densidad < 2.0:
        errores.append(f"Densidad del ángulo muy baja: {densidad:.1f} menciones/1000 palabras (mínimo 2.0)")
    else:
        print(f"✅ Densidad del ángulo: {densidad:.1f} menciones/1000 palabras")

    # Reporte final
    print()
    if advertencias:
        print(f"⚠️  {len(advertencias)} advertencia(s):")
        for a in advertencias:
            print(f"   - {a}")

    if errores:
        print(f"\n❌ {len(errores)} ERROR(ES) CRÍTICO(S) — el guion no cumple el ángulo seleccionado:")
        for e in errores:
            print(f"   ❌ {e}")
        print("\n🛑 BLOQUEADO: corregir el guion antes de continuar al TTS.")
        sys.exit(1)
    else:
        print(f"\n✅ ÁNGULO VALIDADO — el guion gira en torno a: {config['descripcion']}")
        sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python3 validar_angulo_guion.py <carpeta_video> --angulo <angulo>")
        print(f"Ángulos válidos: {list(ANGULOS.keys())}")
        sys.exit(1)

    carpeta = Path(sys.argv[1])
    angulo_idx = sys.argv.index("--angulo") + 1 if "--angulo" in sys.argv else None
    if not angulo_idx:
        print("❌ Falta --angulo")
        sys.exit(1)

    angulo = sys.argv[angulo_idx]
    validar(carpeta, angulo)
