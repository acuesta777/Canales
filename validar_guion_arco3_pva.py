#!/usr/bin/env python3
"""
Validador de guion para Arco 3 PVA ("Porque Vive Así")
Verifica: labels/anotaciones, números sin convertir, contraste PVA presente.
Uso: python3 validar_guion_arco3_pva.py <nicho>/<personaje>/
"""
import re
import sys
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 validar_guion_arco3_pva.py <nicho>/<personaje>/")
        sys.exit(1)

    carpeta = Path(sys.argv[1])
    txts = sorted([f for f in carpeta.glob("*.txt")
                   if "_test" not in f.name and "_src" not in f.name])
    if not txts:
        print(f"❌ No se encontró ningún .txt en {carpeta}")
        sys.exit(1)

    txt_path = txts[0]
    txt = txt_path.read_text(encoding="utf-8")
    errores = []
    advertencias = []

    print(f"Validando: {txt_path}")
    print("-" * 50)

    # 1. Labels / anotaciones prohibidas
    label_patterns = [
        r'\[SUBTIPO PVA',
        r'\[BLOQUE\s*\d',
        r'\[música\]',
        r'\[VERIFICAR\]',
        r'\[BEAT',
        r'\[HOOK',
        r'\[CTA',
        r'\[NOTA',
        r'\[INSERT',
        r'\[PAUSA',
        r'\[FIN',
        r'^\[.{1,40}\]\s*$',
    ]
    for pat in label_patterns:
        matches = re.findall(pat, txt, re.IGNORECASE | re.MULTILINE)
        if matches:
            errores.append(f"LABEL ENCONTRADO: {matches[:3]}")

    if not any(e.startswith("LABEL") for e in errores):
        print("✅ Labels: ningún label o anotación en el guion")

    # 2. Números sin convertir (dígitos que el TTS leería como cifras)
    num_matches = re.findall(r'\b(\d+)\b', txt)
    sospechosos = [n for n in num_matches if not (1900 <= int(n) <= 2099)]
    if sospechosos:
        errores.append(f"NÚMEROS SIN CONVERTIR A LETRAS: {sospechosos[:10]}")
    else:
        print("✅ Números: todos los dígitos son años (1900–2099), sin cifras sueltas")

    # 3. Contraste PVA — elementos obligatorios del arco
    contraste_checks = [
        (r'(?:vive|vivió|eligió|elección|cómo vive|por qué vive)', "contraste de vida presente"),
        (r'(?:depresión|depresion|salud mental|psicólogo|psiquiatra|adicción|crisis)', "vulnerabilidad/salud mental presente"),
        (r'(?:despedida|despidieron|corrió|sin contrato|perdió su|quiebre|fracaso|divorcio)', "quiebre/pérdida presente"),
        (r'(?:crió sola|criar solo|hijos solo|sola los hijos|levantó sola)', "crianza o reconstrucción en solitario"),
        (r'(?:fortuna|patrimonio|millones|ingresos|dinero)', "datos económicos presentes"),
    ]
    for pat, nombre in contraste_checks:
        if re.search(pat, txt, re.IGNORECASE):
            print(f"✅ PVA — {nombre}")
        else:
            advertencias.append(f"PVA — {nombre}: NO encontrado — verificar si aplica al personaje")

    # 4. Hook: no debe empezar con el nombre del personaje
    personaje = carpeta.name.replace("_", " ").title()
    primeras_palabras = txt.strip()[:150]
    if re.match(rf'^{re.escape(personaje)}', primeras_palabras, re.IGNORECASE):
        errores.append(f"HOOK: comienza directamente con el nombre del personaje '{personaje}'")
    else:
        print("✅ Hook: no empieza con el nombre del personaje")

    # 5. Longitud
    chars = len(txt)
    if 24500 <= chars <= 25500:
        print(f"✅ Longitud: {chars} chars (rango 24,500–25,500)")
    else:
        errores.append(f"LONGITUD FUERA DE RANGO: {chars} chars — ajustar antes del TTS")

    # --- Resultado ---
    print("\n" + "=" * 50)
    if errores:
        print("❌ ERRORES — corregir antes del TTS:")
        for e in errores:
            print(f"  • {e}")
    else:
        print("✅ APROBADO — sin errores críticos")

    if advertencias:
        print("\n⚠️  ADVERTENCIAS (revisar, no bloquean):")
        for a in advertencias:
            print(f"  • {a}")

    sys.exit(0 if not errores else 1)

if __name__ == "__main__":
    main()
