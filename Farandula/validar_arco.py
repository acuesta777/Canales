#!/usr/bin/env python3
"""
Validar arco narrativo — OBLIGATORIO antes del TTS.

Mide qué porcentaje del guion ocupa cada acto y lo compara contra el arco
de farandula.md. Sale con código 1 si algún acto está fuera de tolerancia,
para que el pipeline se detenga ANTES de gastar TTS + SRT + imágenes Flow.

Existe porque el error natural es escribir siguiendo el material del video
de referencia (denso en origen/ascenso, vacío en la parte oscura) en vez de
seguir la estructura. El arco del .md manda sobre el material.

Uso:
  python3 validar_arco.py "Farandula/NOMBRE/"            # Formato 2 (guion.txt)
  python3 validar_arco.py "Farandula/NOMBRE/" --tol 5    # tolerancia en puntos
"""
import sys, json, pathlib, argparse, unicodedata, re

# Arco FORMATO A — INDIVIDUAL de farandula.md, normalizado a % sobre 23 min
ARCO_INDIVIDUAL = [
    ("1 RECONOCIMIENTO",    0,  1, "Hook nostalgia → el personaje en la memoria del espectador"),
    ("2 ORIGEN",            1,  4, "Infancia humilde, orígenes, primeras batallas"),
    ("3 ASCENSO",           4,  8, "Cómo llegó a la fama, momentos icónicos, la cima"),
    ("4 GRIETA",            8, 13, "El primer crack silencioso — CASCADA de golpes, nunca uno solo"),
    ("5 CAIDA",            13, 17, "El momento en que todo se rompe — nombres, fechas, consecuencias"),
    ("6 PRESENTE",         17, 21, "Dónde y cómo vive hoy — sin romantizar"),
    ("7 REFLEXION/CIERRE", 21, 23, "Lección moral devastadora + paradoja personaje/persona"),
]
BASE_MIN = 23.0

def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--tol", type=float, default=4.0, help="Tolerancia en puntos porcentuales")
    a = ap.parse_args()

    folder = pathlib.Path(a.folder)
    guion  = folder / "guion.txt"
    arco_f = folder / "arco.json"

    if not guion.exists():
        print(f"⛔ No existe {guion} — este validador es para Formato 2 (Mono)")
        sys.exit(1)
    if not arco_f.exists():
        print(f"⛔ Falta {arco_f}")
        print('   Créalo con las primeras palabras de la frase que abre cada acto:')
        print('   {"1 RECONOCIMIENTO": "Piensa un momento", "2 ORIGEN": "Todo empieza en", ...}')
        print('   Los 7 actos deben estar, con las claves exactas del arco de farandula.md.')
        sys.exit(1)

    texto = guion.read_text(encoding="utf-8")
    tn    = norm(texto)
    marcas = json.loads(arco_f.read_text(encoding="utf-8"))

    # Localizar el offset de cada acto
    offs, faltan = [], []
    for nombre, _, _, _ in ARCO_INDIVIDUAL:
        frag = marcas.get(nombre)
        if not frag:
            faltan.append(f"{nombre} (sin entrada en arco.json)"); continue
        i = tn.find(norm(frag))
        if i < 0:
            faltan.append(f'{nombre} (no encontré "{frag}" en guion.txt)'); continue
        offs.append((nombre, i))
    if faltan:
        print("⛔ No pude ubicar estos actos:")
        for f in faltan: print(f"   - {f}")
        sys.exit(1)

    if [n for n, _ in offs] != [n for n, _, _, _ in ARCO_INDIVIDUAL]:
        print("⛔ Los actos no están en orden en arco.json"); sys.exit(1)
    if any(offs[i][1] >= offs[i+1][1] for i in range(len(offs)-1)):
        print("⛔ Los actos no aparecen en orden dentro de guion.txt:")
        for n, i in offs: print(f"   {n:<20} offset {i}")
        sys.exit(1)

    total = len(tn)
    print(f"\n  Guion: {len(texto):,} chars  ≈ {len(texto)/910:.1f} min de audio\n")
    print(f"  {'ACTO':<20}{'objetivo':>10}{'real':>8}{'delta':>8}   {'':>4}")
    print("  " + "-" * 62)

    fallas = []
    for k, (nombre, ini, fin, desc) in enumerate(ARCO_INDIVIDUAL):
        obj  = (fin - ini) / BASE_MIN * 100
        ini_c = offs[k][1]
        fin_c = offs[k+1][1] if k + 1 < len(offs) else total
        real  = (fin_c - ini_c) / total * 100
        d     = real - obj
        ok    = abs(d) <= a.tol
        if not ok:
            fallas.append((nombre, obj, real, d, desc))
        print(f"  {nombre:<20}{obj:9.1f}%{real:7.1f}%{d:+8.1f}   {'✅' if ok else '❌'}")

    print("  " + "-" * 62)
    if not fallas:
        print(f"\n  ✅ Arco OK — todos los actos dentro de ±{a.tol} puntos\n")
        sys.exit(0)

    print(f"\n  ❌ {len(fallas)} acto(s) fuera de tolerancia (±{a.tol} puntos):\n")
    for nombre, obj, real, d, desc in fallas:
        verbo = "RECORTAR" if d > 0 else "EXPANDIR"
        print(f"   {verbo} {nombre}: {real:.1f}% → {obj:.1f}%")
        print(f"      {desc}")
    print("\n  El arco de farandula.md manda sobre el material del video de referencia.")
    print("  Si un acto no tiene con qué llenarse, BUSCA MÁS FUENTES — no lo dejes corto")
    print("  ni lo rellenes repitiendo el mismo golpe con otras palabras.\n")
    sys.exit(1)

if __name__ == "__main__":
    main()
