#!/usr/bin/env python3
"""
Verifica disponibilidad de clips en iCloud para una lista de artistas.
Uso: python3 verificar_icloud.py "Artista 1" "Artista 2" ...
     python3 verificar_icloud.py  (sin args = lista todos los artistas con clips)
"""
import pathlib, unicodedata, re, sys

ICLOUD_ART = pathlib.Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Artistas"
ICLOUD_YT  = pathlib.Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/yt"

def norm(s):
    """Normaliza: minúsculas, sin acentos, solo letras y números."""
    s = unicodedata.normalize('NFD', s.lower())
    return re.sub(r'[^a-z0-9 ]', '', ''.join(
        c for c in s if unicodedata.category(c) != 'Mn'
    ))

def score_match(query_norm, carpeta_norm):
    """
    Devuelve score de coincidencia entre query y nombre de carpeta.
    Requiere que TODAS las palabras significativas del query estén en la carpeta.
    Palabras cortas (<= 3 chars) se ignoran.
    """
    palabras = [p for p in query_norm.split() if len(p) > 3]
    if not palabras:
        return 0
    hits = sum(1 for p in palabras if p in carpeta_norm)
    # Solo es match válido si todas las palabras significativas coinciden
    if hits == len(palabras):
        return hits
    # Match parcial solo si hay apellido único (>5 chars) que coincide exactamente
    for p in palabras:
        if len(p) > 5 and p in carpeta_norm.split():
            return 1
    return 0

def buscar_artista(nombre):
    """Busca artista en iCloud/Artistas y iCloud/yt. Devuelve dict con resultado."""
    n = norm(nombre)

    mejor_carpeta = None
    mejor_score = 0

    if ICLOUD_ART.exists():
        for d in ICLOUD_ART.iterdir():
            if not d.is_dir():
                continue
            dn = norm(d.name)
            s = score_match(n, dn)
            if s > mejor_score:
                mejor_score = s
                mejor_carpeta = d

    if mejor_carpeta and mejor_score > 0:
        clips = len([f for f in mejor_carpeta.glob("*.mp4") if "_zp" not in f.stem])
        imgs  = len([f for f in mejor_carpeta.iterdir()
                     if f.suffix.lower() in ('.jpg','.jpeg','.png','.webp')])
        # Avisar si el nombre de carpeta es diferente al query (nombre artístico vs real)
        nombre_carpeta_n = norm(mejor_carpeta.name)
        if nombre_carpeta_n != n:
            print(f"  ⚠️  '{nombre}' → carpeta diferente: '{mejor_carpeta.name}' — ¿es ese? (asumiendo sí)")
        return {
            "found": True,
            "path": str(mejor_carpeta),
            "folder": mejor_carpeta.name,
            "clips": clips,
            "imgs": imgs,
            "source": "Artistas"
        }

    # Buscar en yt/
    if ICLOUD_YT.exists():
        for f in ICLOUD_YT.glob("*.mp4"):
            fn = norm(f.stem)
            if score_match(n, fn) > 0:
                return {
                    "found": True,
                    "path": str(f),
                    "folder": f.name,
                    "clips": 0,
                    "imgs": 0,
                    "source": "yt"
                }

    return {"found": False}

def main():
    if len(sys.argv) > 1:
        artistas = sys.argv[1:]
    else:
        # Listar todas las carpetas con clips
        print(f"\n{'Carpeta':<35} {'Clips':>6} {'Imgs':>5}")
        print("-" * 50)
        if ICLOUD_ART.exists():
            for d in sorted(ICLOUD_ART.iterdir()):
                if not d.is_dir(): continue
                clips = len([f for f in d.glob("*.mp4") if "_zp" not in f.stem])
                imgs  = len([f for f in d.iterdir()
                              if f.suffix.lower() in ('.jpg','.jpeg','.png','.webp')])
                if clips + imgs > 0:
                    print(f"{d.name:<35} {clips:>6} {imgs:>5}")
        return

    print(f"\n{'Artista':<25} {'Estado':<8} {'Carpeta':<30} {'Clips':>6}")
    print("-" * 75)
    for nombre in artistas:
        r = buscar_artista(nombre)
        if r["found"]:
            estado = "✅"
            info = f"{r['folder'][:28]:<30} {r['clips']:>6}"
        else:
            estado = "❌"
            info = "Sin carpeta"
        print(f"{nombre:<25} {estado}       {info}")

if __name__ == "__main__":
    main()
