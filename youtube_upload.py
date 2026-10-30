#!/usr/bin/env python3
"""
youtube_upload.py — Sube un video final a YouTube con OAuth por canal.

Uso:
    python3 youtube_upload.py <carpeta_personaje>

Ejemplo:
    python3 youtube_upload.py susana_gimenez/

Flujo:
    1. Lee título, descripción, tags del pack de subida (upload_pack.json o pregunta)
    2. Lista los JSONs de credenciales en jsonytapi/ y pregunta a cuál canal subir
    3. Pregunta visibilidad (público / no listado / privado)
    4. Abre navegador para OAuth si es la primera vez en ese canal
    5. Sube el video con resumable upload (soporta archivos grandes)
    6. Guarda youtube_id y fecha en <carpeta>/upload_info.json
"""

import sys
import os
import json
import pickle
import datetime
import pathlib
import time

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE_DIR   = pathlib.Path(__file__).parent
JSON_DIR   = BASE_DIR / "_jsonytapi"
TOKENS_DIR = BASE_DIR / "_jsonytapi" / "tokens"
SCOPES     = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

# ── colores ─────────────────────────────────────────────────────────────────
R = "\033[91m"; G = "\033[92m"; Y = "\033[93m"; B = "\033[94m"; E = "\033[0m"


def err(msg):
    print(f"{R}ERROR: {msg}{E}"); sys.exit(1)


def pick_canal():
    jsons = sorted(JSON_DIR.glob("*.json"))
    if not jsons:
        err(f"No hay archivos .json en {JSON_DIR}")

    print(f"\n{B}Canales disponibles:{E}")
    for i, f in enumerate(jsons, 1):
        print(f"  [{i}] {f.name}")

    while True:
        try:
            idx = int(input(f"\n{Y}¿A qué canal quieres subir? (número): {E}").strip())
            if 1 <= idx <= len(jsons):
                return jsons[idx - 1]
        except (ValueError, KeyboardInterrupt):
            pass
        print("Número inválido, intenta de nuevo.")


def pick_privacidad():
    opts = {"1": "public", "2": "unlisted", "3": "private"}
    print(f"\n{B}Visibilidad del video:{E}")
    print("  [1] Público")
    print("  [2] No listado")
    print(f"  [3] Privado  {G}← predeterminado{E}")
    while True:
        v = input(f"{Y}Elige (1/2/3) [Enter = privado]: {E}").strip()
        if v == "":
            return "private"
        if v in opts:
            return opts[v]
        print("Opción inválida.")


def get_credentials(client_json: pathlib.Path, oauth_code: str = None) -> Credentials:
    TOKENS_DIR.mkdir(exist_ok=True)
    token_file = TOKENS_DIR / (client_json.stem + ".pickle")

    creds = None
    if token_file.exists():
        with open(token_file, "rb") as f:
            creds = pickle.load(f)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        print(f"{Y}Renovando token OAuth...{E}")
        creds.refresh(Request())
    else:
        verifier_cache = token_file.parent / f"{token_file.stem}_cv.txt"

        import base64, hashlib, secrets as _secrets, requests as _requests

        with open(client_json) as _f:
            _client_cfg = json.load(_f)
        _client_id     = _client_cfg["installed"]["client_id"]
        _client_secret = _client_cfg["installed"]["client_secret"]
        _token_uri     = _client_cfg["installed"]["token_uri"]
        _redirect_uri  = "urn:ietf:wg:oauth:2.0:oob"

        if oauth_code and verifier_cache.exists():
            # PASO 2: exchange código con verifier guardado — usando requests directo
            saved_verifier = verifier_cache.read_text().strip()
            resp = _requests.post(_token_uri, data={
                "code":          oauth_code,
                "client_id":     _client_id,
                "client_secret": _client_secret,
                "redirect_uri":  _redirect_uri,
                "grant_type":    "authorization_code",
                "code_verifier": saved_verifier,
            })
            if resp.status_code != 200:
                print(f"\n{R}Error en token exchange: {resp.text}{E}")
                sys.exit(1)
            token_data = resp.json()
            verifier_cache.unlink(missing_ok=True)
            creds = Credentials(
                token=token_data["access_token"],
                refresh_token=token_data.get("refresh_token"),
                token_uri=_token_uri,
                client_id=_client_id,
                client_secret=_client_secret,
                scopes=SCOPES,
            )
        elif oauth_code:
            print(f"\n{R}Error: no hay code_verifier guardado para este código.{E}")
            print(f"{Y}Genera una nueva URL corriendo sin --code y vuelve a autorizar.{E}")
            sys.exit(1)
        else:
            # PASO 1: generar code_verifier/challenge manualmente, sin depender de la librería
            cv_bytes  = _secrets.token_urlsafe(64).encode("ascii")
            code_verifier  = cv_bytes.decode("ascii")
            code_challenge = base64.urlsafe_b64encode(
                hashlib.sha256(cv_bytes).digest()
            ).rstrip(b"=").decode("ascii")
            verifier_cache.write_text(code_verifier)

            # Construir URL manualmente para tener control total
            import urllib.parse
            params = {
                "response_type":         "code",
                "client_id":             _client_id,
                "redirect_uri":          _redirect_uri,
                "scope":                 " ".join(SCOPES),
                "prompt":                "consent",
                "access_type":           "offline",
                "code_challenge":        code_challenge,
                "code_challenge_method": "S256",
            }
            auth_url = "https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode(params)

            print(f"\n{Y}Autorización OAuth requerida.{E}")
            print(f"\n{B}Abre esta URL en tu navegador y autoriza:{E}")
            print(f"\n  {auth_url}\n")
            try:
                code = input(f"{Y}Pega aquí el código de autorización: {E}").strip()
                resp = _requests.post(_token_uri, data={
                    "code":          code,
                    "client_id":     _client_id,
                    "client_secret": _client_secret,
                    "redirect_uri":  _redirect_uri,
                    "grant_type":    "authorization_code",
                    "code_verifier": code_verifier,
                })
                if resp.status_code != 200:
                    print(f"\n{R}Error en token exchange: {resp.text}{E}")
                    sys.exit(1)
                token_data = resp.json()
                verifier_cache.unlink(missing_ok=True)
                creds = Credentials(
                    token=token_data["access_token"],
                    refresh_token=token_data.get("refresh_token"),
                    token_uri=_token_uri,
                    client_id=_client_id,
                    client_secret=_client_secret,
                    scopes=SCOPES,
                )
            except EOFError:
                print(f"{Y}Corre de nuevo con: --code <código_de_autorización>{E}\n")
                sys.exit(0)

    with open(token_file, "wb") as f:
        pickle.dump(creds, f)
    print(f"{G}✓ Token guardado en {token_file.name}{E}")
    return creds


def load_upload_pack(carpeta: pathlib.Path):
    for candidate in [carpeta / "upload_pack.json", carpeta / "07-metadatos" / "upload_pack.json"]:
        if candidate.exists():
            with open(candidate) as f:
                return json.load(f)

    print(f"\n{Y}No se encontró upload_pack.json — ingresa los datos manualmente:{E}\n")
    titulo      = input("Título del video: ").strip()
    descripcion = input("Descripción (Enter para vacío): ").strip()
    tags_raw    = input("Tags separados por coma (Enter para ninguno): ").strip()
    tags        = [t.strip() for t in tags_raw.split(",") if t.strip()]
    return {"titulo": titulo, "descripcion": descripcion, "tags": tags}


def find_final_mp4(carpeta: pathlib.Path) -> pathlib.Path:
    candidates = sorted(carpeta.glob("*_final.mp4"))
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        print(f"\n{B}Varios archivos _final.mp4 encontrados:{E}")
        for i, c in enumerate(candidates, 1):
            print(f"  [{i}] {c.name}")
        while True:
            try:
                idx = int(input(f"{Y}¿Cuál subir? (número): {E}").strip())
                if 1 <= idx <= len(candidates):
                    return candidates[idx - 1]
            except (ValueError, KeyboardInterrupt):
                pass
    err(f"No encontré ningún *_final.mp4 en {carpeta}")


def validate_titulo(titulo: str) -> str:
    MAX = 100
    length = len(titulo)
    if length > MAX:
        print(f"\n{R}ERROR: El título tiene {length} caracteres — YouTube solo permite {MAX}.{E}")
        print(f"  Título actual: {titulo}")
        print(f"  Sobran {length - MAX} caracteres. Edita upload_pack.json y vuelve a ejecutar.")
        sys.exit(1)
    print(f"  Título        : {titulo}  {G}({length}/{MAX} chars){E}")
    return titulo


def upload_video(service, mp4: pathlib.Path, pack: dict, privacidad: str) -> str:
    titulo = validate_titulo(pack["titulo"])
    body = {
        "snippet": {
            "title":       titulo,
            "description": pack.get("descripcion", ""),
            "tags":        pack.get("tags", []),
            "categoryId":  "22",
        },
        "status": {
            "privacyStatus": privacidad,
            "containsSyntheticMedia": True,
        },
    }

    media = MediaFileUpload(
        str(mp4),
        mimetype="video/mp4",
        resumable=True,
        chunksize=2 * 1024 * 1024,
    )

    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    import time as _time
    print(f"\n{B}Subiendo {mp4.name} ({mp4.stat().st_size / 1024 / 1024:.1f} MB)...{E}")
    response = None
    last_pct = -1
    retries  = 0
    while response is None:
        try:
            status, response = request.next_chunk()
        except (BrokenPipeError, TimeoutError, Exception) as e:
            retries += 1
            if retries > 10:
                raise
            print(f"\n  ⚠ Error de red ({type(e).__name__}), reintento {retries}/10...")
            _time.sleep(10 * retries)
            continue
        if status:
            pct = int(status.progress() * 100)
            if pct != last_pct:
                bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                print(f"\r  [{bar}] {pct}%", end="", flush=True)
                last_pct = pct

    print(f"\r  [{'█'*20}] 100%")
    return response["id"]


def upload_thumbnail(service, youtube_id: str, carpeta: pathlib.Path):
    """Sube la miniatura aprobada (miniatura_1/2/3.jpg) al video de YouTube."""
    # Buscar miniatura aprobada en metadata, si no existe tomar la primera disponible
    meta_file = carpeta / "metadata.json"
    thumb_path = None
    if meta_file.exists():
        with open(meta_file) as f:
            meta = json.load(f)
        for key, estado in meta.get("miniaturas", {}).items():
            if estado == "aprobada":
                candidate = carpeta / f"{key}.jpg"
                if candidate.exists():
                    thumb_path = candidate
                    break
    if not thumb_path:
        for nombre in ["miniatura_final.jpg", "miniatura_1.jpg", "miniatura_2.jpg", "miniatura_3.jpg"]:
            candidate = carpeta / nombre
            if candidate.exists():
                thumb_path = candidate
                break
    if not thumb_path:
        print(f"  {Y}⚠ Sin miniatura disponible — salta thumbnail{E}")
        return
    print(f"\n{B}Subiendo miniatura: {thumb_path.name}...{E}")
    try:
        service.thumbnails().set(
            videoId=youtube_id,
            media_body=MediaFileUpload(str(thumb_path), mimetype="image/jpeg"),
        ).execute()
        print(f"  {G}✓ Miniatura subida: {thumb_path.name}{E}")
    except Exception as e:
        print(f"  {Y}⚠ Miniatura no pudo subirse: {e}{E}")


def monetize_video(service, youtube_id: str):
    """Activa monetización completa: display, overlay, pre-roll, post-roll, mid-rolls automáticos."""
    print(f"\n{B}Configurando monetización...{E}")
    try:
        body = {
            "id": youtube_id,
            "monetizationDetails": {
                "access": {
                    "allowed": True,
                }
            },
        }
        service.videos().update(
            part="monetizationDetails",
            body=body,
        ).execute()
        print(f"  {G}✓ Monetización activada{E}")
    except Exception as e:
        print(f"  {Y}⚠ monetizationDetails: {e}{E}")

    # Anuncios de display, overlay, saltables y no saltables vía status
    try:
        body2 = {
            "id": youtube_id,
            "status": {
                "selfDeclaredMadeForKids": False,
            },
        }
        service.videos().update(
            part="status",
            body=body2,
        ).execute()
        print(f"  {G}✓ Not made for kids (habilita todos los formatos de anuncio){E}")
    except Exception as e:
        print(f"  {Y}⚠ status update: {e}{E}")

    print(f"  {B}ℹ Mid-rolls automáticos: YouTube los posiciona cuando el video supera 8 min{E}")
    print(f"  {B}ℹ Mid-rolls en posiciones exactas: configúralos en YouTube Studio o Nexlev{E}")


def save_upload_info(carpeta: pathlib.Path, youtube_id: str, canal: str, privacidad: str):
    info_file = carpeta / "upload_info.json"
    info = {}
    if info_file.exists():
        with open(info_file) as f:
            info = json.load(f)
    info.update({
        "youtube_id":   youtube_id,
        "youtube_url":  f"https://youtu.be/{youtube_id}",
        "canal":        canal,
        "privacidad":   privacidad,
        "fecha_subida": datetime.datetime.now().isoformat(timespec="seconds"),
    })
    with open(info_file, "w") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)


def update_metadata(carpeta: pathlib.Path, youtube_id: str, canal: str, privacidad: str, pack: dict):
    """Crea o actualiza metadata.json con info completa del video."""
    meta_file = carpeta / "metadata.json"
    meta = {}
    if meta_file.exists():
        with open(meta_file) as f:
            meta = json.load(f)

    now = datetime.datetime.now().isoformat(timespec="seconds")
    personaje = carpeta.name

    # Campos base si no existen
    meta.setdefault("personaje",        personaje)
    meta.setdefault("canal",            canal)
    meta.setdefault("fecha_generacion", now[:10])
    meta.setdefault("miniaturas",       {"miniatura_1": "pendiente", "miniatura_2": "pendiente", "miniatura_3": "pendiente"})
    meta.setdefault("pipeline", {
        "titulo":     "completado",
        "guion":      "completado",
        "audio":      "completado",
        "subtitulos": "completado",
        "imagenes":   "completado",
        "video":      "completado",
        "miniaturas": "pendiente",
        "youtube":    "pendiente",
    })

    # Actualizar con datos de subida
    meta.update({
        "titulo":       pack.get("titulo", ""),
        "descripcion":  pack.get("descripcion", ""),
        "tags":         pack.get("tags", []),
        "estado":       "subido",
        "youtube_id":   youtube_id,
        "youtube_url":  f"https://youtu.be/{youtube_id}",
        "privacidad":   privacidad,
        "fecha_subida": now,
    })
    meta["pipeline"]["youtube"] = "completado"

    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def main():
    # ── Parsear argumentos ────────────────────────────────────────────────────
    args = sys.argv[1:]
    headless   = "--headless" in args
    canal_arg  = None
    priv_arg   = None
    oauth_code = None
    args_clean = []
    i = 0
    while i < len(args):
        if args[i] == "--headless":
            i += 1
        elif args[i] == "--canal" and i + 1 < len(args):
            canal_arg = args[i + 1]; i += 2
        elif args[i] == "--privacidad" and i + 1 < len(args):
            priv_arg = args[i + 1]; i += 2
        elif args[i] == "--code" and i + 1 < len(args):
            oauth_code = args[i + 1]; i += 2
        else:
            args_clean.append(args[i]); i += 1

    if not args_clean:
        err("Uso: python3 youtube_upload.py <carpeta_personaje> [--headless --canal X.json --privacidad private]")

    carpeta = pathlib.Path(args_clean[0])
    if not carpeta.exists():
        carpeta = BASE_DIR / args_clean[0].rstrip("/")
    if not carpeta.is_dir():
        err(f"No existe la carpeta: {carpeta}")

    print(f"\n{'='*55}")
    print(f"  SUBIDA YOUTUBE — {carpeta.name.upper()}")
    print(f"{'='*55}")

    mp4  = find_final_mp4(carpeta)
    pack = load_upload_pack(carpeta)

    # Selección de canal — headless usa --canal arg, interactivo pregunta
    if headless and canal_arg:
        canal_json = JSON_DIR / canal_arg
        if not canal_json.exists():
            err(f"No existe {canal_json}")
    else:
        canal_json = pick_canal()

    # Visibilidad — headless usa --privacidad arg, interactivo pregunta
    privacidad = priv_arg if (headless and priv_arg) else pick_privacidad()

    titulo_len = len(pack["titulo"])
    titulo_ok  = f"{G}✓{E}" if titulo_len <= 100 else f"{R}✗ SUPERA 100 chars{E}"
    print(f"\n{B}Resumen antes de subir:{E}")
    print(f"  Video     : {mp4.name}")
    print(f"  Título    : {pack['titulo']}  [{titulo_len}/100] {titulo_ok}")
    print(f"  Canal     : {canal_json.name}")
    print(f"  Visibil.  : {privacidad}")

    if not headless:
        confirm = input(f"\n{Y}¿Confirmar subida? (s/n): {E}").strip().lower()
        if confirm not in ("s", "si", "sí", "y", "yes"):
            print("Cancelado."); sys.exit(0)

    creds   = get_credentials(canal_json, oauth_code=oauth_code)
    service = build("youtube", "v3", credentials=creds)

    youtube_id = upload_video(service, mp4, pack, privacidad)
    monetize_video(service, youtube_id)
    upload_thumbnail(service, youtube_id, carpeta)
    save_upload_info(carpeta, youtube_id, canal_json.stem, privacidad)
    update_metadata(carpeta, youtube_id, canal_json.stem, privacidad, pack)

    url = f"https://youtu.be/{youtube_id}"
    print(f"\n{G}✓ Video subido exitosamente{E}")
    print(f"  ID      : {youtube_id}")
    print(f"  URL     : {url}")
    print(f"  Canal   : {canal_json.stem}")
    print(f"  Info    : {carpeta.name}/upload_info.json")
    print(f"  Meta    : {carpeta.name}/metadata.json")
    print()


if __name__ == "__main__":
    main()
