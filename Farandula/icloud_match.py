#!/usr/bin/env python3
"""
icloud_match.py — Matching seguro de nombre artista → carpeta iCloud.

Reglas de confianza (en orden):
  EXACTO    — norm(carpeta) == norm(nombre)                          → retorna sin aviso
  COMPLETO  — todas las palabras >3 chars del nombre están en carpeta → retorna sin aviso
  PARCIAL   — apellido principal + al menos 1 nombre coinciden       → retorna CON aviso
  AMBIGUO   — solo apellido coincide                                 → retorna None + error

El nivel AMBIGUO (solo apellido) ya NO se usa — era la fuente de confusiones.
"""

import pathlib, unicodedata, re

HOME   = pathlib.Path.home()
ICLOUD = HOME / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"

VERDE   = "\033[92m"; AMARILLO = "\033[93m"; ROJO = "\033[91m"; RESET = "\033[0m"


# Apodos → nombre real (ambos en minúsculas sin acentos)
APODOS: dict[str, str] = {
    "lalo":    "eduardo",
    "pepe":    "jose",
    "nacho":   "ignacio",
    "pancho":  "francisco",
    "paco":    "francisco",
    "memo":    "guillermo",
    "chava":   "salvador",
    "chuy":    "jesus",
    "beto":    "alberto",
    "tito":    "ernesto",
    "toño":    "antonio",
    "tony":    "antonio",
    "manolo":  "manuel",
    "neto":    "ernesto",
    "checho":  "sergio",
    "kiko":    "carlos",
    "coco":    "jorge",
    "fito":    "adolfo",
    "goyo":    "gregorio",
    "poncho":  "alfonso",
    "tere":    "teresa",
    "chabela": "isabel",
    "lupita":  "guadalupe",
    "concha":  "concepcion",
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z0-9 ]", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))


def expandir_apodos(nombre_norm: str) -> list[str]:
    """
    Dado 'lalo espana' retorna ['lalo espana', 'eduardo espana'].
    Sustituye cada palabra que sea apodo conocido por su nombre real.
    """
    variantes = [nombre_norm]
    palabras = nombre_norm.split()
    for i, p in enumerate(palabras):
        if p in APODOS:
            nueva = palabras[:]
            nueva[i] = APODOS[p]
            variantes.append(" ".join(nueva))
    return variantes


def palabras_sig(nombre_norm: str, min_len: int = 3) -> list[str]:
    """Palabras significativas (excluye artículos/preposiciones cortas)."""
    STOP = {"de", "la", "el", "los", "las", "del", "y", "e", "o"}
    return [p for p in nombre_norm.split() if len(p) >= min_len and p not in STOP]


def score_match(nombre: str, carpeta_nombre: str) -> tuple[str, int]:
    """
    Retorna (nivel, score):
      nivel  = "exacto" | "completo" | "parcial" | "apodo" | "ninguno"
      score  = 0-100 (cuántas palabras coinciden en %)
    """
    n  = norm(nombre)
    cn = norm(carpeta_nombre)
    pn = palabras_sig(n)

    if not pn:
        return "ninguno", 0

    if n == cn:
        return "exacto", 100

    # Intentar todas las variantes con apodos expandidos
    variantes = expandir_apodos(n)
    for variante in variantes[1:]:  # [0] es el original, ya comparado
        pv = palabras_sig(variante)
        coinciden_v = [p for p in pv if p in cn]
        if len(coinciden_v) == len(pv):
            return "apodo", 95  # match completo vía apodo
        apellido_v = pv[-1]
        nombres_v  = pv[:-1]
        if apellido_v in cn and (any(p in cn for p in nombres_v) or len(pv) == 1):
            return "apodo", 80

    # Sin apodos: cuántas palabras del nombre original están en la carpeta
    coinciden = [p for p in pn if p in cn]
    pct = int(len(coinciden) / len(pn) * 100)

    if pct == 100:
        return "completo", 100

    # Parcial: apellido + al menos 1 nombre coinciden
    apellido = pn[-1]
    nombres_propios = pn[:-1]
    apellido_ok = apellido in cn
    nombre_ok   = any(p in cn for p in nombres_propios) if nombres_propios else False

    if apellido_ok and (nombre_ok or len(pn) == 1):
        return "parcial", pct

    return "ninguno", pct


def buscar_carpeta_icloud(nombre: str, verbose: bool = True) -> pathlib.Path | None:
    """
    Busca la carpeta iCloud del artista con matching seguro.

    - Nivel EXACTO / COMPLETO → retorna silenciosamente.
    - Nivel PARCIAL            → retorna con aviso (nombre difiere pero es reconocible).
    - Nivel NINGUNO / AMBIGUO  → retorna None (evita confundir artistas con apellido similar).

    Args:
        nombre:  Nombre del artista tal como aparece en el guion.
        verbose: Si True, imprime avisos de match parcial.
    """
    if not ICLOUD.exists():
        return None

    candidatos = []
    for d in ICLOUD.iterdir():
        if not d.is_dir():
            continue
        nivel, sc = score_match(nombre, d.name)
        if nivel != "ninguno":
            candidatos.append((nivel, sc, d))

    if not candidatos:
        if verbose:
            print(f"  {ROJO}✗ No se encontró carpeta iCloud para '{nombre}'{RESET}")
        return None

    # Ordenar: exacto > completo > parcial, luego por score desc
    orden = {"exacto": 0, "completo": 1, "apodo": 2, "parcial": 3}
    candidatos.sort(key=lambda x: (orden[x[0]], -x[1]))

    nivel, sc, mejor = candidatos[0]

    # Si hay dos candidatos en nivel parcial con scores similares → ambiguo, no asumir
    if nivel == "parcial" and len(candidatos) > 1:
        nivel2, sc2, otro = candidatos[1]
        if nivel2 in ("parcial", "completo") and sc2 >= sc - 10:
            if verbose:
                print(f"  {ROJO}⛔ Match ambiguo para '{nombre}':{RESET}")
                print(f"       Candidato 1: {mejor.name} (score {sc})")
                print(f"       Candidato 2: {otro.name} (score {sc2})")
                print(f"     Retornando None — verifica manualmente cuál es el correcto.")
            return None

    if nivel in ("parcial", "apodo") and verbose:
        etiq = "apodo" if nivel == "apodo" else "parcial"
        print(f"  {AMARILLO}⚠ Match por {etiq}: '{nombre}' → '{mejor.name}'{RESET}")

    return mejor


def verificar_todos(nombres: list[str]) -> dict[str, pathlib.Path | None]:
    """
    Verifica una lista de nombres y retorna dict nombre→carpeta.
    Imprime tabla resumen con warnings.
    """
    print(f"\n  {'Artista':<28} {'Carpeta iCloud':<30} {'Nivel':<10} {'Clips MP4':>9}")
    print(f"  {'─'*80}")
    resultado = {}
    for nombre in nombres:
        carpeta = buscar_carpeta_icloud(nombre, verbose=False)
        if carpeta:
            nivel, sc = score_match(nombre, carpeta.name)
            clips = len(list(carpeta.glob("*.mp4")))
            color = VERDE if nivel in ("exacto", "completo") else AMARILLO
            aviso = " ⚠" if nivel == "parcial" else ""
            print(f"  {nombre:<28} {color}{carpeta.name:<30}{RESET} {nivel:<10} {clips:>9}{aviso}")
        else:
            print(f"  {nombre:<28} {ROJO}{'— NO ENCONTRADA':<30}{RESET} {'—':<10} {'0':>9}")
        resultado[nombre] = carpeta
    print()
    return resultado


if __name__ == "__main__":
    import sys
    nombres = sys.argv[1:] if len(sys.argv) > 1 else []
    if nombres:
        verificar_todos(nombres)
    else:
        print("Uso: python3 icloud_match.py 'Artista 1' 'Artista 2' ...")
