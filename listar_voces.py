#!/usr/bin/env python3
"""
listar_voces.py — Lista voces disponibles en AI33 por proveedor.
Uso:
    python3 listar_voces.py minimax
    python3 listar_voces.py fishaudio
    python3 listar_voces.py edge
    python3 listar_voces.py elevenlabs
    python3 listar_voces.py minimax --gender Male
    python3 listar_voces.py fishaudio --language es
"""

import sys, json, pathlib, urllib.request, urllib.parse

HOME    = pathlib.Path.home()
KEY_FILE = HOME / ".ai33_key"
BASE    = "https://api.ai33.pro"

VALID_PROVIDERS = ["elevenlabs", "minimax", "clone", "edge", "kokoro", "vbee", "fishaudio"]


def read_key():
    try:
        return KEY_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        print(f"ERROR: No encontré API key en {KEY_FILE}")
        sys.exit(1)


def listar(provider, extra_params=None, page=1, page_size=50):
    api_key = read_key()
    params  = {"provider": provider, "page": str(page), "page_size": str(page_size)}
    if extra_params:
        params.update(extra_params)
    url = f"{BASE}/v3/voices?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(url, headers={"xi-api-key": api_key})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"Error al consultar API: {e}")
        sys.exit(1)

    if not data.get("success"):
        print(f"Error en respuesta: {data}")
        sys.exit(1)

    voces    = data.get("data", [])
    pag_info = data.get("pagination", {})

    print(f"\n{'='*70}")
    print(f"  VOCES — {provider.upper()}")
    print(f"  Total: {pag_info.get('total', '?')} | Página {pag_info.get('page',1)} de {((pag_info.get('total',0)-1)//page_size)+1}")
    print(f"{'='*70}")
    print(f"  {'VOICE_ID':<45} {'NOMBRE':<25} {'GÉNERO':<8} {'IDIOMA'}")
    print(f"  {'-'*44} {'-'*24} {'-'*7} {'-'*10}")

    for v in voces:
        vid  = v.get("voice_id", "")
        name = v.get("name", "")[:24]
        gen  = v.get("gender", "")[:7]
        lang = v.get("language", "")[:12]
        print(f"  {vid:<45} {name:<25} {gen:<8} {lang}")

    print(f"{'='*70}")
    if pag_info.get("has_more"):
        print(f"  Hay más voces — usá --page {pag_info.get('page',1)+1} para ver más")
    print()
    print("  Para usar una voz, guardala en ~/.ai33_voice_seduccion:")
    print("  Ejemplo: echo 'minimax_male-qn-qingse' > ~/.ai33_voice_seduccion")
    print()


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    provider = sys.argv[1].lower()
    if provider not in VALID_PROVIDERS:
        print(f"Provider inválido: '{provider}'")
        print(f"Opciones: {', '.join(VALID_PROVIDERS)}")
        sys.exit(1)

    extra = {}
    args  = sys.argv[2:]
    page  = 1
    for i, arg in enumerate(args):
        if arg == "--gender"   and i+1 < len(args): extra["gender"]   = args[i+1]
        if arg == "--language" and i+1 < len(args): extra["language"] = args[i+1]
        if arg == "--search"   and i+1 < len(args): extra["search"]   = args[i+1]
        if arg == "--page"     and i+1 < len(args): page = int(args[i+1])

    listar(provider, extra_params=extra if extra else None, page=page)


if __name__ == "__main__":
    main()
