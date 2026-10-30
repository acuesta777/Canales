#!/usr/bin/env python3
"""
buscar_imagenes.py — Busca imágenes reales en internet (Brave Search) para el pipeline de fútbol.

Uso:
    python3 buscar_imagenes.py <carpeta_personaje> --queries "query 1" "query 2" ...
    python3 buscar_imagenes.py <carpeta_personaje> --csv queries.csv

Por cada query descarga hasta N candidatas a <carpeta>/web_candidatas/<query_slug>/
para revisión visual (Claude las ve y descarta watermarks/texto).
Las aprobadas se mueven a <carpeta>/imagenes_web/ numeradas.

API key: ~/.brave_key
Límite plan free: 2,000 búsquedas/mes — usar queries con criterio.
"""

import sys, json, time, re, urllib.request, urllib.parse
from pathlib import Path

KEY_FILE   = Path.home() / ".brave_key"
PER_QUERY  = 6   # candidatas a descargar por query

BLOCKED_DOMAINS = [
    "alamy", "gettyimages", "shutterstock", "istockphoto", "dreamstime",
    "123rf", "depositphotos", "vectorstock", "freepik", "pngtree",
]
NEGATIVE_WORDS = [
    "cartoon", "illustration", "vector", "icon", "logo", "clipart",
    "meme", "drawing", "wallpaper hd", "png",
]


def get_key():
    if not KEY_FILE.exists():
        sys.exit(f"[ERROR] Falta {KEY_FILE}")
    return KEY_FILE.read_text().strip()


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:50]


def brave_search(query, key, count=30):
    url = "https://api.search.brave.com/res/v1/images/search?" + urllib.parse.urlencode({
        "q": query, "count": count, "safesearch": "strict",
        "search_lang": "es", "spellcheck": "true",
    })
    req = urllib.request.Request(url, headers={
        "X-Subscription-Token": key, "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read()).get("results", [])


def score_result(r):
    props  = r.get("properties", {})
    title  = (r.get("title") or "").lower()
    source = (r.get("url") or "").lower()
    w = props.get("width", 0) or 0
    h = props.get("height", 0) or 0

    if any(d in source for d in BLOCKED_DOMAINS):
        return -1
    if any(nw in title for nw in NEGATIVE_WORDS):
        return -1
    if h > w:          # vertical — no sirve para 16:9
        return -1
    if w and w < 640:  # muy pequeña
        return -1

    score = 0
    if w >= 1200: score += 3
    elif w >= 800: score += 1
    return score


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        data = r.read()
    if len(data) < 15_000:   # probablemente placeholder/error
        raise RuntimeError("archivo muy pequeño")
    dest.write_bytes(data)
    return len(data)


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__); sys.exit(1)

    carpeta = Path(args[0]).resolve()
    carpeta.mkdir(parents=True, exist_ok=True)

    queries = []
    if "--queries" in args:
        i = args.index("--queries")
        queries = args[i + 1:]
    elif "--csv" in args:
        import csv as csvmod
        i = args.index("--csv")
        with open(args[i + 1], newline="", encoding="utf-8") as f:
            queries = [row["query"] for row in csvmod.DictReader(f)]
    if not queries:
        sys.exit("[ERROR] Sin queries")

    key      = get_key()
    cand_dir = carpeta / "web_candidatas"
    cand_dir.mkdir(exist_ok=True)
    manifest = []

    print(f"\n{'='*60}")
    print(f"  BÚSQUEDA DE IMÁGENES — {carpeta.name.upper()}")
    print(f"  {len(queries)} queries × {PER_QUERY} candidatas")
    print(f"{'='*60}\n")

    for qi, query in enumerate(queries, 1):
        slug  = slugify(query)
        qdir  = cand_dir / f"{qi:02d}_{slug}"
        qdir.mkdir(exist_ok=True)
        print(f"[{qi}/{len(queries)}] \"{query}\"")

        try:
            results = brave_search(query, key)
        except Exception as e:
            print(f"  ✗ búsqueda falló: {e}\n")
            continue

        scored = [(score_result(r), r) for r in results]
        scored = sorted([x for x in scored if x[0] >= 0], key=lambda x: -x[0])

        saved = 0
        for score, r in scored:
            if saved >= PER_QUERY:
                break
            props   = r.get("properties", {})
            img_url = props.get("url") or ""
            if not img_url:
                continue
            ext  = ".jpg"
            dest = qdir / f"{saved+1}{ext}"
            try:
                size = download(img_url, dest)
                saved += 1
                manifest.append({
                    "query": query, "file": str(dest.relative_to(carpeta)),
                    "source_url": img_url, "page": r.get("url", ""),
                    "width": props.get("width"), "height": props.get("height"),
                })
                print(f"  ✓ {dest.name} ({size//1024} KB, {props.get('width')}x{props.get('height')})")
            except Exception:
                continue
        print(f"  → {saved} candidatas guardadas\n")
        time.sleep(1.2)   # respetar rate limit del plan free

    mpath = cand_dir / "manifest.json"
    mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"{'='*60}")
    print(f"  {len(manifest)} imágenes en {cand_dir}")
    print(f"  Manifest: {mpath}")
    print(f"  SIGUIENTE: revisión visual (descartar watermarks/texto)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
