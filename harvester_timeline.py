#!/usr/bin/env python3
"""
harvester_timeline.py — Genera/descarga imágenes para cualquier canal.

Lee config/<canal>.json → source_order, prompt_suffix, clip_secs, ken_burns_flip.
Lee 05-montaje/timeline.json → genera img_XXXX.mp4 en 03-imagenes/.

Uso:
    python3 harvester_timeline.py seduccion/7_errores/ --canal seduccion
    python3 harvester_timeline.py riqueza/victoria_ruffo/ --canal riqueza
    python3 harvester_timeline.py seduccion/7_errores/ --canal seduccion --desde 50
    python3 harvester_timeline.py seduccion/7_errores/              # infiere canal del padre
"""

import sys, json, time, subprocess, urllib.request, urllib.error, pathlib, random, re, base64

# zoompan centralizado — NUNCA reescribir inline
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from zoompan_clip import make_zoompan, ZOOMPAN_MASTER_DUR

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
if not pathlib.Path(FFMPEG).exists():
    FFMPEG  = "/usr/local/bin/ffmpeg"
    FFPROBE = "/usr/local/bin/ffprobe"

HOME                 = pathlib.Path.home()
MUAPI_KEY_FILE       = HOME / ".muapi_key"
PEXELS_KEY_FILE      = HOME / ".pexels_key"
PIXABAY_KEY_FILE     = HOME / ".pixabay_key"
BRAVE_KEY_FILE       = HOME / ".brave_key"
GOOGLE_CSE_KEY_FILE  = HOME / ".google_cse_key"   # AIza...
GOOGLE_CSE_CX_FILE   = HOME / ".google_cse_cx"    # cx=...:......
OPENROUTER_KEY_FILE  = HOME / ".openrouter_key"

# Registro global de URLs ya usadas — persiste entre videos
CLIPS_USADOS_FILE = pathlib.Path(__file__).parent / "clips_usados.json"

# ── Clasificador de escenas ───────────────────────────────────────────────────
#
# Determina la cadena de fuentes óptima según el tipo de escena.
# trigger_type viene del timeline.json; si no existe, se infiere del prompt.
#
# Cadenas por tipo:
#   lugar     → brave → google_cse → ia
#   persona   → brave → ia
#   evento    → brave → google_cse → ia
#   album     → brave → ia
#   lujo      → pexels → pixabay → ia
#   negocio   → pexels → pixabay → ia
#   generico  → ia   (stock nunca tiene esto bien)

CADENAS_POR_TIPO = {
    "lugar":    ["brave", "google_cse", "ia"],
    "persona":  ["brave", "ia"],
    "evento":   ["brave", "google_cse", "ia"],
    "album":    ["brave", "ia"],
    "lujo":     ["pexels", "pixabay", "brave", "ia"],
    "negocio":  ["pexels", "pixabay", "brave", "ia"],
    "generico": ["pexels", "pixabay", "brave", "ia"],
}

# Palabras que indican lugar específico (no genérico)
_KW_LUGAR = {"municipio","ciudad","pueblo","barrio","colombia","venezuela","méxico",
              "valledupar","medellín","bogotá","cartagena","bolívar","atlántico",
              "vista aérea","aerial","mahates","capital","departamento","club campestre"}
_KW_PERSONA = {"retrato","portrait","coronado","rey","rey vallenato","coronación",
               "face","foto de","imagen de"}
_KW_EVENTO  = {"festival","concierto","ceremonia","gala","festival vallenato",
               "award","álbum","carátula","cover"}
_KW_LUJO    = {"mansión","mansion","finca","rancho","yate","ferrari","porsche","bmw",
               "rolls","lamborghini","infinity pool","piscina","lujo","luxury","villa"}
_KW_NEGOCIO = {"empresa","negocios","business","billetes","pesos","dólares","finanzas",
               "gráfico","inversión","contrato","documentos","office"}

def detectar_tipo_escena(prompt_es: str, trigger_type: str = "") -> str:
    """Clasifica una escena y devuelve su tipo para elegir la cadena de fuentes."""
    # Si el timeline ya viene con trigger_type reconocido, lo respetamos
    _map = {
        "property": "lujo", "car": "lujo", "fashion": "lujo",
        "person": "persona", "childhood": "lugar",
        "music": "album", "award": "evento", "event": "evento",
        "business": "negocio", "income": "negocio",
        "place": "lugar", "origin": "lugar",
    }
    if trigger_type and trigger_type in _map:
        return _map[trigger_type]
    pl = prompt_es.lower()
    if any(kw in pl for kw in _KW_LUGAR):    return "lugar"
    if any(kw in pl for kw in _KW_PERSONA):  return "persona"
    if any(kw in pl for kw in _KW_EVENTO):   return "evento"
    if any(kw in pl for kw in _KW_LUJO):     return "lujo"
    if any(kw in pl for kw in _KW_NEGOCIO):  return "negocio"
    return "generico"

def cadena_fuentes(prompt_es: str, trigger_type: str = "",
                   pexels_key=None, pixabay_key=None,
                   brave_key=None, google_cse_key=None,
                   google_cse_cx=None, muapi_key=None) -> list:
    """Devuelve la cadena de fuentes disponibles para esta escena."""
    tipo = detectar_tipo_escena(prompt_es, trigger_type)
    chain = list(CADENAS_POR_TIPO.get(tipo, ["pexels","pixabay","brave","ia"]))
    # Filtrar fuentes sin credenciales
    disponibles = set()
    if pexels_key:     disponibles.add("pexels")
    if pixabay_key:    disponibles.add("pixabay")
    if brave_key:      disponibles.add("brave")
    if google_cse_key and google_cse_cx: disponibles.add("google_cse")
    if muapi_key:      disponibles.add("ia")
    # wikimedia eliminado — causaba más problemas que soluciones
    filtered = [s for s in chain if s in disponibles]
    # ia siempre al final si está disponible
    if muapi_key and "ia" not in filtered:
        filtered.append("ia")
    return filtered

def siguiente_fuente_en_escalada(fuente_actual: str, prompt_es: str,
                                  trigger_type: str = "", **keys) -> list:
    """Para rerun: devuelve las fuentes que vienen DESPUÉS de la fuente que falló."""
    chain = cadena_fuentes(prompt_es, trigger_type, **keys)
    try:
        idx = chain.index(fuente_actual)
        return chain[idx + 1:]
    except ValueError:
        return chain  # fuente desconocida → usar toda la cadena

def es_escena_generica(prompt: str) -> bool:
    return detectar_tipo_escena(prompt) == "generico"

MUAPI_BASE = "https://api.muapi.ai/api/v1"

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"

def ok(msg):   print(f"  {VERDE}✓{RESET} {msg}", flush=True)
def err(msg):  print(f"  {ROJO}✗{RESET} {msg}", flush=True)
def warn(msg): print(f"  {AMARILLO}⚠{RESET} {msg}", flush=True)


# ── Config ────────────────────────────────────────────────────────────────────

def cargar_config(canal):
    script_dir = pathlib.Path(__file__).parent
    cfg_path   = script_dir / "_config" / f"{canal}.json"
    if not cfg_path.exists():
        cfg_path = pathlib.Path(f"_config/{canal}.json")
    if not cfg_path.exists():
        canales = [p.stem for p in (script_dir / "_config").glob("*.json")]
        print(f"{ROJO}✗{RESET} No encontré config/{canal}.json — disponibles: {canales}", flush=True)
        sys.exit(1)
    return json.loads(cfg_path.read_text(encoding="utf-8"))


# ── Keys ──────────────────────────────────────────────────────────────────────

def leer_key(path):
    try:
        return pathlib.Path(path).read_text().strip()
    except Exception:
        return None


# ── Metadata ──────────────────────────────────────────────────────────────────

def cargar_metadata(carpeta):
    p = carpeta / "metadata.json"
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
    else:
        data = {}
    data.setdefault("footage", {})
    return data

def guardar_metadata(carpeta, meta):
    p = carpeta / "metadata.json"
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _fallback_clips_faltantes(carpeta, img_dir, seg_by_id):
    """Detecta clips flow faltantes tras cualquier descarga y los genera con ai33pro.
    Último recurso: copia del pool img_*_zp.mp4. Se llama al final de modo normal y download-only."""
    tl_path = carpeta / '05-montaje' / 'timeline.json'
    if not tl_path.exists():
        return
    tl_all = json.load(open(tl_path))
    all_flow_segs = [s for s in tl_all.get('visual_timeline', [])
                     if s.get('source', 'flow') in ('flow', 'brave', 'ia')]
    faltantes = []
    for seg_obj in all_flow_segs:
        sid = seg_obj.get('segment_id', 0)
        zp  = img_dir / f'flow_{sid:04d}_zp.mp4'
        if not (zp.exists() and zp.stat().st_size > 10000):
            faltantes.append(seg_obj)
    if not faltantes:
        return
    warn(f'  {len(faltantes)} clips faltantes: {[s.get("segment_id") for s in faltantes]}')
    warn(f'  ⛔ ai33pro automático DESACTIVADO — render.py manejará los faltantes.')


# ── muapi.ai ──────────────────────────────────────────────────────────────────

def generar_imagen_ia(prompt, api_key, img_w, img_h, ref_image_url=None):
    # Sanitizar a ASCII — tildes y caracteres especiales causan HTTP 400 en muapi
    prompt = prompt.encode('ascii', 'ignore').decode('ascii')
    body = {"prompt": prompt, "width": img_w, "height": img_h}
    if ref_image_url:
        body["image_url"] = ref_image_url
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{MUAPI_BASE}/flux-schnell-image",
        data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key},
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        resp = json.loads(r.read())
    task_id = resp.get("request_id") or resp.get("data", {}).get("id")
    if not task_id:
        raise RuntimeError(f"Sin task_id: {resp}")

    poll_url = f"{MUAPI_BASE}/predictions/{task_id}/result"
    for _ in range(20):
        time.sleep(6)
        with urllib.request.urlopen(
            urllib.request.Request(poll_url, headers={"x-api-key": api_key}), timeout=8
        ) as r2:
            data = json.loads(r2.read())
        d = data.get("data", data)
        if d.get("status") == "completed":
            outputs = d.get("outputs", [])
            if outputs:
                return outputs[0]
        if d.get("status") == "failed":
            raise RuntimeError(f"IA falló: {d.get('error')}")
    raise TimeoutError("muapi no completó en 120s")


def buscar_foto_referencia(nombre_personaje, brave_key, carpeta):
    """
    Busca una foto real del personaje en Brave y la descarga como ref_foto.jpg.
    Devuelve la URL pública de la imagen (para pasarla directamente a muapi).
    """
    ref_path = carpeta / "ref_foto.jpg"
    if ref_path.exists() and ref_path.stat().st_size > 5000:
        # Ya descargada — devolver URL de muapi cdn si existe, o subir
        # Por ahora devolvemos la ruta local y construimos data URI
        return str(ref_path)

    queries = [
        f"{nombre_personaje} face portrait photo",
        f"{nombre_personaje} footballer photo",
        f"{nombre_personaje} jugador futbol foto",
    ]
    for q in queries:
        resultados = buscar_brave_imagenes(q, brave_key, count=8)
        for img_url, titulo, desc in resultados:
            # Preferir fotos de cara/retrato
            texto = f"{titulo} {desc}".lower()
            if any(w in texto for w in ["portrait", "face", "foto", "jugador", nombre_personaje.split()[0].lower()]):
                if descargar_url(img_url, ref_path) and ref_path.stat().st_size > 10000:
                    ok(f"  Foto de referencia: {titulo[:50]}")
                    return img_url  # URL pública para muapi
    return None


# ── Pexels ────────────────────────────────────────────────────────────────────

def buscar_pexels(query, api_key, skip=0):
    import urllib.parse
    url = f"https://api.pexels.com/videos/search?query={urllib.parse.quote(query)}&per_page=5&size=medium"
    req = urllib.request.Request(url, headers={"Authorization": api_key})
    with urllib.request.urlopen(req, timeout=8) as r:
        data = json.loads(r.read())
    encontrados = 0
    for v in data.get("videos", []):
        for f in v.get("video_files", []):
            if f.get("width", 0) >= 1280:
                if encontrados >= skip:
                    return f["link"]
                encontrados += 1
    return None


# ── Pixabay ───────────────────────────────────────────────────────────────────

def buscar_pixabay(query, api_key, skip=0):
    import urllib.parse
    url = (f"https://pixabay.com/api/videos/?key={api_key}"
           f"&q={urllib.parse.quote(query)}&per_page=5&video_type=film")
    with urllib.request.urlopen(url, timeout=8) as r:
        data = json.loads(r.read())
    encontrados = 0
    for h in data.get("hits", []):
        for quality in ["large", "medium"]:
            v = h.get("videos", {}).get(quality)
            if v and v.get("width", 0) >= 1280:
                if encontrados >= skip:
                    return v["url"]
                encontrados += 1
    return None


# ── Brave Image Search ────────────────────────────────────────────────────────

def buscar_brave_imagenes(query, api_key, count=5):
    """Devuelve lista de (url_imagen, titulo, descripcion) desde Brave Images."""
    import urllib.parse
    url = f"https://api.search.brave.com/res/v1/images/search?q={urllib.parse.quote(query)}&count={count}&safesearch=off"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    })
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read()
            try:
                import gzip
                raw = gzip.decompress(raw)
            except Exception:
                pass
            data = json.loads(raw)
        results = []
        for item in data.get("results", []):
            img_url = item.get("properties", {}).get("url") or item.get("url", "")
            title   = item.get("title", "")
            desc    = item.get("description", "") or title
            if img_url and img_url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                results.append((img_url, title, desc))
        return results
    except Exception as e:
        warn(f"Brave falló: {e}")
        return []


# ── Wikimedia Commons ─────────────────────────────────────────────────────────

def buscar_wikimedia(query, count=6):
    """
    Busca imágenes en Wikimedia Commons. Gratuito, sin API key.
    Devuelve lista de (url_imagen, titulo, descripcion).
    Ideal para: personas históricas, lugares, álbumes, eventos documentados.
    """
    import urllib.parse
    # Paso 1: buscar archivos de imagen en Commons
    search_url = (
        "https://commons.wikimedia.org/w/api.php"
        f"?action=query&list=search&srsearch={urllib.parse.quote(query)}"
        f"&srnamespace=6&srlimit={count * 2}&format=json"
    )
    try:
        req = urllib.request.Request(search_url, headers={"User-Agent": "CanalesBot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        titles = [item["title"] for item in data.get("query", {}).get("search", [])]
        if not titles:
            return []

        # Paso 2: obtener URLs directas de las imágenes
        titles_str = "|".join(titles[:count])
        info_url = (
            "https://commons.wikimedia.org/w/api.php"
            f"?action=query&titles={urllib.parse.quote(titles_str)}"
            "&prop=imageinfo&iiprop=url|mime&format=json"
        )
        req2 = urllib.request.Request(info_url, headers={"User-Agent": "CanalesBot/1.0"})
        with urllib.request.urlopen(req2, timeout=8) as r2:
            info_data = json.loads(r2.read())

        results = []
        for page in info_data.get("query", {}).get("pages", {}).values():
            title = page.get("title", "")
            for ii in page.get("imageinfo", []):
                mime = ii.get("mime", "")
                url  = ii.get("url", "")
                if mime.startswith("image/") and url and not url.endswith(".svg"):
                    desc = title.replace("File:", "").replace("_", " ")
                    results.append((url, desc, desc))
        return results[:count]
    except Exception as e:
        warn(f"Wikimedia falló: {e}")
        return []


# ── Google Custom Search Engine ───────────────────────────────────────────────

def buscar_google_cse(query, api_key, cx, count=5):
    """
    Búsqueda de imágenes via Google Custom Search API.
    Requiere ~/.google_cse_key y ~/.google_cse_cx.
    100 búsquedas gratis/día, luego $5/1000.
    Devuelve lista de (url_imagen, titulo, descripcion).
    """
    import urllib.parse
    url = (
        "https://www.googleapis.com/customsearch/v1"
        f"?key={api_key}&cx={cx}&searchType=image"
        f"&q={urllib.parse.quote(query)}&num={min(count, 10)}"
        "&imgSize=large&safe=off"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CanalesBot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        results = []
        for item in data.get("items", []):
            img_url = item.get("link", "")
            title   = item.get("title", "")
            snippet = item.get("snippet", "") or title
            if img_url and img_url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                results.append((img_url, title, snippet))
        return results
    except Exception as e:
        warn(f"Google CSE falló: {e}")
        return []


# ── Juez de relevancia ────────────────────────────────────────────────────────

def _keywords(text):
    """Extrae palabras clave de longitud ≥4 en minúsculas."""
    return set(w.lower() for w in re.findall(r"[a-záéíóúñüa-z]{4,}", text,
                                              flags=re.IGNORECASE))

def juzgar_relevancia(prompt_or_query, titulo_o_tags, umbral=0.15):
    """
    Devuelve True si el clip/imagen es relevante para el prompt.
    Compara keywords del prompt contra título/tags del resultado.
    umbral=0.15 → al menos 15% de las palabras del prompt deben coincidir.
    """
    kw_prompt = _keywords(prompt_or_query)
    kw_result = _keywords(titulo_o_tags)
    if not kw_prompt:
        return True
    overlap = kw_prompt & kw_result
    score = len(overlap) / len(kw_prompt)
    return score >= umbral

def juzgar_imagen_vision(img_path, descripcion_escena, openrouter_key, titulo_fuente=""):
    """
    Juez visual: envía la imagen a Gemini Flash via OpenRouter y pregunta si
    es apropiada para la escena descrita. Devuelve True si aprueba, False si rechaza.
    En caso de error de red o API, deja pasar (True) para no bloquear el pipeline.
    """
    if not openrouter_key:
        return True  # Sin key → dejar pasar
    try:
        img_bytes = pathlib.Path(img_path).read_bytes()
        b64 = base64.b64encode(img_bytes).decode()
        # Detectar mime type por magic bytes
        if img_bytes[:3] == b'\xff\xd8\xff':
            mime = "image/jpeg"
        elif img_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            mime = "image/png"
        elif img_bytes[:6] in (b'GIF87a', b'GIF89a'):
            mime = "image/gif"
        else:
            mime = "image/jpeg"

        payload = json.dumps({
            "model": "anthropic/claude-haiku-4-5",
            "max_tokens": 5,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": (
                        f"La escena del video necesita mostrar: \"{descripcion_escena}\".\n"
                        + (f"El título/fuente de esta imagen es: \"{titulo_fuente}\".\n" if titulo_fuente else "")
                        + f"Responde SI si la imagen es visualmente apropiada para esa escena "
                        f"(puede ser una foto histórica, grupal o en blanco y negro donde aparezca "
                        f"la persona o el tema solicitado).\n"
                        f"Responde NO SOLO si la imagen muestra claramente algo irrelevante: "
                        f"un edificio/estación/señal con el nombre pero sin la persona, "
                        f"o contenido totalmente distinto.\n"
                        f"Responde SOLO con SI o NO."
                    )}
                ]
            }]
        }).encode()

        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
        answer = data["choices"][0]["message"]["content"].strip().upper()
        return answer.startswith("S")  # SI → True, NO → False
    except Exception:
        return True  # Error de red/API → dejar pasar


# ── Descarga ──────────────────────────────────────────────────────────────────

def cargar_clips_usados() -> set:
    """Carga el registro global de URLs ya usadas en videos anteriores."""
    if CLIPS_USADOS_FILE.exists():
        try:
            data = json.loads(CLIPS_USADOS_FILE.read_text(encoding="utf-8"))
            return set(data.get("urls", []))
        except Exception:
            return set()
    return set()

def guardar_clips_usados(urls: set):
    """Persiste el registro global de URLs usadas."""
    try:
        CLIPS_USADOS_FILE.write_text(
            json.dumps({"urls": sorted(urls)}, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        warn(f"No se pudo guardar clips_usados.json: {e}")


def descargar_url(url, dest):
    r = subprocess.run(["curl", "-sL", "-o", str(dest), url], timeout=20, capture_output=True)
    if r.returncode != 0 or dest.stat().st_size < 1000:
        return False
    # Validar que el archivo es una imagen real con dimensiones válidas
    probe = subprocess.run(
        [FFPROBE, "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(dest)],
        capture_output=True, text=True, timeout=5
    )
    dims = probe.stdout.strip()
    if not dims or dims == "0,0" or "," not in dims:
        return False
    w, h = dims.split(",")[:2]
    return int(w) > 0 and int(h) > 0


# ── Ken Burns sobre imagen estática ──────────────────────────────────────────

def imagen_a_clip(img_path, dst, duracion, cfg_harvester, index=0):
    return make_zoompan(pathlib.Path(img_path), pathlib.Path(dst), duracion, index=index)


# ── Normalizar clip de video ──────────────────────────────────────────────────

def normalizar_clip(src, dst, duracion):
    r = subprocess.run([
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(src), "-t", str(duracion),
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an", "-y", str(dst)
    ], capture_output=True)
    return r.returncode == 0


# ── Main ──────────────────────────────────────────────────────────────────────

def rerun_rechazados(carpeta, cfg, cfg_harvester, source_order, clip_secs, img_w, img_h, prompt_suffix,
                     muapi_key, pexels_key, pixabay_key, brave_key=None,
                     google_cse_key=None, google_cse_cx=None, openrouter_key=None):
    """Re-busca clips rechazados con resultados alternativos."""
    use_ref_photo = cfg_harvester.get("use_reference_photo", False)
    _ref_cache = {}  # lazy: se busca solo si IA va a generar
    meta = cargar_metadata(carpeta)
    img_dir = carpeta / "03-imagenes"

    timeline_f = carpeta / "05-montaje" / "timeline.json"
    segments_by_name = {}
    if timeline_f.exists():
        tdata = json.loads(timeline_f.read_text(encoding="utf-8"))
        for seg in tdata.get("visual_timeline", []):
            idx = seg.get("segment_id", 0)
            clip_name = f"img_{idx:04d}.mp4"
            segments_by_name[clip_name] = seg

    rechazados = [k for k, v in meta["footage"].items() if v.get("estado") == "rechazado"]
    if not rechazados:
        print("  No hay clips rechazados.", flush=True)
        return

    print(f"\n{'='*60}", flush=True)
    print(f"  RERUN — {len(rechazados)} clip(s) rechazado(s)")
    print(f"{'='*60}\n", flush=True)

    for clip_name in rechazados:
        seg = segments_by_name.get(clip_name, {})
        raw_prompt = seg.get("prompt_or_query", meta["footage"][clip_name].get("prompt", ""))
        start_s = seg.get("start_seconds", meta["footage"][clip_name].get("timestamp", 0))
        desc = seg.get("scene_description_es", clip_name)[:50]
        clip_path = img_dir / clip_name

        ia_prompt_spec_rerun = seg.get("ia_prompt") or raw_prompt
        has_specific_rerun = bool(seg.get("ia_prompt"))
        prompt = ia_prompt_spec_rerun
        if prompt_suffix and not has_specific_rerun and prompt_suffix not in prompt:
            prompt = f"{ia_prompt_spec_rerun}, {prompt_suffix}"

        print(f"  Buscando alternativa para {clip_name} — {desc}", flush=True)
        # Marcar como pendiente para que no bloquee el render mientras buscamos
        meta["footage"][clip_name]["estado"] = "buscando"
        guardar_metadata(carpeta, meta)

        fuente_usada = None
        exito = False

        query_original = raw_prompt[:80]
        query_corta    = " ".join(raw_prompt.split(",")[0].split()[:3])[:60]

        # Escalada inteligente: arrancar desde la fuente SIGUIENTE a la que falló
        fuente_previa = meta["footage"].get(clip_name, {}).get("fuente", "")
        trigger_type  = seg.get("trigger_type", "")
        desc_es       = seg.get("scene_description_es", raw_prompt)
        _keys_rerun = dict(pexels_key=pexels_key, pixabay_key=pixabay_key,
                           brave_key=brave_key, google_cse_key=google_cse_key,
                           google_cse_cx=google_cse_cx, muapi_key=muapi_key)
        rerun_sources = siguiente_fuente_en_escalada(fuente_previa, desc_es, trigger_type, **_keys_rerun)
        if not rerun_sources:
            rerun_sources = ["wikimedia", "google_cse", "brave", "ia"]
        tipo_det = detectar_tipo_escena(desc_es, trigger_type)
        print(f"    Fuente previa: {fuente_previa} | tipo: {tipo_det} | rerun: {' → '.join(rerun_sources)}")

        for fuente in rerun_sources:
            if fuente == "wikimedia":
                try:
                    resultados_w = buscar_wikimedia(desc_es, count=15)
                    for img_url_w, titulo_w, desc_w in resultados_w:
                        if not juzgar_relevancia(desc_es, f"{titulo_w} {desc_w}", umbral=0.08):
                            continue
                        tmp_img = img_dir / f"_rerun_wiki_{clip_name.replace('.mp4','.jpg')}"
                        if descargar_url(img_url_w, tmp_img) and tmp_img.exists() and tmp_img.stat().st_size > 5000:
                            if not juzgar_imagen_vision(tmp_img, desc_es, openrouter_key):
                                warn(f"  Wikimedia: juez visual rechazó '{titulo_w[:40]}' — siguiente")
                                tmp_img.unlink(missing_ok=True)
                                continue
                            tmp_clip_w = img_dir / f"_rerun_{clip_name}"
                            if imagen_a_clip(tmp_img, tmp_clip_w, clip_secs, cfg_harvester):
                                tmp_img.unlink(missing_ok=True)
                                tmp_clip_w.replace(clip_path)
                                fuente_usada = "wikimedia"
                                exito = True
                                ok(f"  Wikimedia ({titulo_w[:40]}) → {clip_name}")
                                break
                        tmp_img.unlink(missing_ok=True)
                    if exito:
                        break
                except Exception as e:
                    warn(f"  Wikimedia falló: {e}")

            elif fuente == "google_cse":
                if not (google_cse_key and google_cse_cx):
                    warn("Sin Google CSE — configura ~/.google_cse_key y ~/.google_cse_cx"); continue
                try:
                    resultados_g = buscar_google_cse(desc_es, google_cse_key, google_cse_cx, count=5)
                    for img_url_g, titulo_g, desc_g in resultados_g:
                        if not juzgar_relevancia(desc_es, f"{titulo_g} {desc_g}", umbral=0.08):
                            continue
                        tmp_img = img_dir / f"_rerun_goog_{clip_name.replace('.mp4','.jpg')}"
                        if descargar_url(img_url_g, tmp_img) and tmp_img.exists() and tmp_img.stat().st_size > 5000:
                            if not juzgar_imagen_vision(tmp_img, desc_es, openrouter_key):
                                warn(f"  Google CSE: juez visual rechazó '{titulo_g[:40]}' — siguiente")
                                tmp_img.unlink(missing_ok=True)
                                continue
                            tmp_clip_g = img_dir / f"_rerun_{clip_name}"
                            if imagen_a_clip(tmp_img, tmp_clip_g, clip_secs, cfg_harvester):
                                tmp_img.unlink(missing_ok=True)
                                tmp_clip_g.replace(clip_path)
                                fuente_usada = "google_cse"
                                exito = True
                                ok(f"  Google CSE ({titulo_g[:40]}) → {clip_name}")
                                break
                        tmp_img.unlink(missing_ok=True)
                    if exito:
                        break
                except Exception as e:
                    warn(f"  Google CSE falló: {e}")

            elif fuente == "ia":
                if not muapi_key:
                    warn("Sin muapi key"); continue
                try:
                    img_path = img_dir / clip_name.replace(".mp4", ".png")
                    _ref_url = None
                    if use_ref_photo and brave_key:
                        if "ref" not in _ref_cache:
                            nombre = carpeta.name
                            nombre_display = nombre.replace("_", " ").title()
                            _ref_cache["ref"] = buscar_foto_referencia(nombre_display, brave_key, carpeta)
                        _ref_url = _ref_cache.get("ref")
                    img_url = generar_imagen_ia(prompt, muapi_key, img_w, img_h, ref_image_url=_ref_url)
                    if descargar_url(img_url, img_path):
                        tmp_clip = img_dir / f"_rerun_{clip_name}"
                        if imagen_a_clip(img_path, tmp_clip, clip_secs, cfg_harvester):
                            tmp_clip.replace(clip_path)
                            fuente_usada = "ia"
                            exito = True
                            ok(f"  IA → {clip_name}")
                            break
                except Exception as e:
                    warn(f"  IA falló: {e}")

            elif fuente == "brave":
                if not brave_key:
                    warn("Sin brave key"); continue
                try:
                    # Usar brave_query específico del timeline si existe
                    _brave_q = (seg.get("brave_query") or raw_prompt)[:120]
                    resultados = buscar_brave_imagenes(_brave_q, brave_key, count=10)
                    for img_url_b, titulo_b, desc_b in resultados:
                        texto_meta = f"{titulo_b} {desc_b}"
                        if not juzgar_relevancia(_brave_q, texto_meta, umbral=0.08):
                            warn(f"  Brave: '{titulo_b[:40]}' no relevante")
                            continue
                        tmp_img = img_dir / f"_rerun_brave_{clip_name.replace('.mp4','.jpg')}"
                        if descargar_url(img_url_b, tmp_img) and tmp_img.exists() and tmp_img.stat().st_size > 5000:
                            if not juzgar_imagen_vision(tmp_img, desc_es, openrouter_key):
                                warn(f"  Brave: juez visual rechazó '{titulo_b[:35]}' — siguiente")
                                tmp_img.unlink(missing_ok=True)
                                continue
                            tmp_clip2 = img_dir / f"_rerun_{clip_name}"
                            if imagen_a_clip(tmp_img, tmp_clip2, clip_secs, cfg_harvester):
                                tmp_img.unlink(missing_ok=True)
                                tmp_clip2.replace(clip_path)
                                fuente_usada = "brave"
                                exito = True
                                ok(f"  Brave ({titulo_b[:35]}) → {clip_name}")
                                break
                        tmp_img.unlink(missing_ok=True)
                    if exito:
                        break
                except Exception as e:
                    warn(f"  Brave falló: {e}")

            elif fuente == "pexels":
                if not pexels_key:
                    warn("Sin pexels key"); continue
                for q, sk in [(query_original, 1), (query_corta, 0), (query_original, 2)]:
                    try:
                        video_url = buscar_pexels(q, pexels_key, skip=sk)
                        if video_url:
                            tmp = img_dir / f"_tmp_rerun_{clip_name}"
                            if descargar_url(video_url, tmp):
                                if normalizar_clip(tmp, clip_path, clip_secs):
                                    tmp.unlink(missing_ok=True)
                                    if juzgar_clip_frame(clip_path, raw_prompt):
                                        fuente_usada = "pexels"
                                        exito = True
                                        ok(f"  Pexels (q={q[:30]}, skip={sk}) → {clip_name}")
                                        break
                                    else:
                                        clip_path.unlink(missing_ok=True)
                    except Exception as e:
                        warn(f"  Pexels falló: {e}")
                if exito:
                    break

            elif fuente == "pixabay":
                if not pixabay_key:
                    warn("Sin pixabay key"); continue
                for q, sk in [(query_original, 1), (query_corta, 0), (query_original, 2)]:
                    try:
                        video_url = buscar_pixabay(q, pixabay_key, skip=sk)
                        if video_url:
                            tmp = img_dir / f"_tmp_rerun_{clip_name}"
                            if descargar_url(video_url, tmp):
                                if normalizar_clip(tmp, clip_path, clip_secs):
                                    tmp.unlink(missing_ok=True)
                                    fuente_usada = "pixabay"
                                    exito = True
                                    ok(f"  Pixabay (q={q[:30]}, skip={sk}) → {clip_name}")
                                    break
                    except Exception as e:
                        warn(f"  Pixabay falló: {e}")
                if exito:
                    break

        if exito:
            meta["footage"][clip_name] = {
                "estado": "pendiente",
                "fuente": fuente_usada,
                "prompt": raw_prompt[:200],
                "timestamp": start_s,
            }
            ok(f"  {clip_name} → pendiente (revisar en dashboard)")
        else:
            meta["footage"][clip_name]["estado"] = "rechazado"
            err(f"  No se encontró alternativa para {clip_name}")

        guardar_metadata(carpeta, meta)

    nicho = carpeta.parent.name
    nombre = carpeta.name
    print(f"\n  Dashboard: http://localhost:5001/aprobar/{nicho}/{nombre}/\n", flush=True)


# ── Flow / ZIP mode ─────────────────────────────────────────────────────────
# Baserow eliminado. El flujo ahora es: ZIP con JPEGs → zoompan → flow_NNNN_zp.mp4

def harvest_via_flow(carpeta, segments, cfg_harvester, desde=0, hasta=None, force_upload=False, zip_path=None):
    """
    Procesa un ZIP con los JPEGs generados por Google Flow/VEO y los convierte
    a clips zoompan flow_NNNN_zp.mp4 listos para el dashboard.
    zip_path: ruta al archivo ZIP descargado de veo-folder-1.
    """
    import zipfile
    img_dir = carpeta / '03-imagenes'
    img_dir.mkdir(parents=True, exist_ok=True)
    meta = cargar_metadata(carpeta)

    if not zip_path or not pathlib.Path(zip_path).exists():
        print(f'  ✗ ERROR: ZIP no encontrado: {zip_path}', flush=True)
        print(f'  Uso: python3 harvester_timeline.py <carpeta> --canal <canal> --zip <ruta.zip>', flush=True)
        return

    segs = [s for s in segments if s.get('segment_id', 0) >= desde
            and s.get('source') not in ('yt_clip', 'hyperframe')]
    if hasta is not None:
        segs = [s for s in segs if s.get('segment_id', 0) <= hasta]

    with zipfile.ZipFile(zip_path) as z:
        import re as _re
        all_names = sorted(z.namelist())
        # Filtrar solo imágenes reales (ignorar __MACOSX, .DS_Store, etc.)
        names = [n for n in all_names if _re.search(r'\.(jpg|jpeg|png|webp)$', n, _re.I)
                 and not n.startswith('__MACOSX') and not n.startswith('.')]

        # ── Leer video_prompts.txt para saber cuántos prompts vio el usuario en la UI ──
        vp_file = carpeta / '05-montaje' / 'video_prompts.txt'
        if vp_file.exists():
            _vp_prompts = [p for p in vp_file.read_text(encoding='utf-8').split('\n\n') if p.strip()]
            n_esperados = len(_vp_prompts)
            fuente_esperados = f'video_prompts.txt ({n_esperados} prompts exportados a la UI)'
        else:
            n_esperados = len(segs)
            fuente_esperados = f'timeline.json ({n_esperados} segmentos flow)'

        print(f'\n  ZIP: {pathlib.Path(zip_path).name}', flush=True)
        print(f'  {len(names)} imágenes → {n_esperados} esperados ({fuente_esperados})', flush=True)

        # ── VALIDACIÓN 1: total de imágenes vs prompts exportados a la UI ────
        if len(names) < n_esperados:
            print(f'\n  ⚠ ALERTA: ZIP tiene {len(names)} imágenes pero se esperan {n_esperados}', flush=True)
            print(f'  Faltan {n_esperados - len(names)} imágenes — se usará fallback para los faltantes', flush=True)
        elif len(names) > n_esperados:
            print(f'  ℹ ZIP tiene {len(names) - n_esperados} imágenes extra (se ignorarán)', flush=True)
        else:
            print(f'  ✓ Total imágenes coincide exactamente con prompts exportados', flush=True)

        # ── VALIDACIÓN 2 y 3: detectar numeración al inicio del nombre ────────
        seg_ids_esperados = {seg.get('segment_id', i+1) for i, seg in enumerate(segs)}
        _num_pat = _re.compile(r'^\[?(\d+)\]?[_\-\s]?')
        imgs_con_numero = {}   # numero → nombre_archivo
        imgs_sin_numero = []   # nombres sin número al inicio

        for n in names:
            base = pathlib.Path(n).name
            m = _num_pat.match(base)
            if m:
                num = int(m.group(1))
                imgs_con_numero[num] = n
            else:
                imgs_sin_numero.append(n)

        if imgs_sin_numero:
            print(f'\n  ⚠ ALERTA: {len(imgs_sin_numero)} imagen(es) SIN número al inicio del nombre:', flush=True)
            for nombre in imgs_sin_numero[:10]:
                print(f'    - {pathlib.Path(nombre).name}', flush=True)
            if len(imgs_sin_numero) > 10:
                print(f'    ... y {len(imgs_sin_numero) - 10} más', flush=True)
            print(f'  Estas imágenes se asignarán por posición (sin match garantizado)', flush=True)

        # ── VALIDACIÓN 4: imágenes faltantes por número de segmento ──────────
        # Solo verificar por ID cuando los counts NO coinciden (hay imágenes de menos).
        # Si len(names) == n_esperados, la asignación por posición ya cubre todo —
        # los segment_ids pueden tener huecos (por YT_CLIP insertados por el juez)
        # pero eso no significa que falten imágenes reales.
        if imgs_con_numero and len(names) < n_esperados:
            faltantes = [sid for sid in sorted(seg_ids_esperados) if sid not in imgs_con_numero]
            if faltantes:
                print(f'\n  ⚠ ALERTA: Faltan imágenes para {len(faltantes)} segmento(s):', flush=True)
                print(f'  Segmentos sin imagen: {faltantes[:20]}', flush=True)
                if len(faltantes) > 20:
                    print(f'  ... y {len(faltantes) - 20} más', flush=True)
        elif imgs_con_numero:
            print(f'  ✓ Todos los segmentos tienen imagen numerada correspondiente', flush=True)

        print('', flush=True)

        # ── Construir mapa de asignación: seg_id → nombre en ZIP ─────────────
        # Siempre por posición: imagen 1 → segmento 1, imagen 2 → segmento 2, etc.
        # (el número en el nombre del ZIP refleja el orden de generación en Flow,
        #  no el segment_id del timeline, que puede tener huecos)
        names_sorted = sorted(names, key=lambda n: int(re.search(r'\[?(\d+)\]?', pathlib.Path(n).name).group(1)) if re.search(r'\[?(\d+)\]?', pathlib.Path(n).name) else 9999)
        asignacion = {}
        for j, seg in enumerate(segs):
            sid = seg.get('segment_id', 0)
            if j < len(names_sorted):
                asignacion[sid] = names_sorted[j]
            # else: None → se manejará como faltante en el loop

        # ⛔ REGLA DURA: borrar clips flow anteriores antes de procesar el ZIP
        # Excepción: respetar clips source=hyperframe (generados por harvester_actors_hyperframe.py)
        hf_ids = {s.get('segment_id') for s in segments if s.get('source') == 'hyperframe'}
        viejos = [v for v in sorted(img_dir.glob('flow_*_zp.mp4'))
                  if not any(f'flow_{hid:04d}_zp.mp4' == v.name for hid in hf_ids)]
        if viejos:
            for v in viejos:
                v.unlink()
            print(f'  🗑  {len(viejos)} clips anteriores eliminados — reemplazando con ZIP nuevo', flush=True)

        generadas = 0
        errores = 0
        for i, seg in enumerate(segs):
            seg_id = seg.get('segment_id', 0)
            start_s = seg.get('start_seconds', 0)
            dur = seg.get('end_seconds', start_s + 6) - start_s
            dur = min(round(dur, 3), 8.0)
            raw_prompt = seg.get('ia_prompt') or seg.get('prompt_or_query', '')
            clip_name = f'flow_{seg_id:04d}_zp.mp4'
            clip_path = img_dir / clip_name

            jpg_name = asignacion.get(seg_id)
            if not jpg_name:
                # Sin imagen en ZIP → usar clip YT aleatorio de 02-clips/
                clips_dir = carpeta / '02-clips'
                yt_clips = sorted(clips_dir.glob('clip_*.mp4')) if clips_dir.exists() else []
                if yt_clips:
                    import random as _rnd
                    import shutil as _sh
                    yt_src = _rnd.choice(yt_clips)
                    _sh.copy2(str(yt_src), str(clip_path))
                    meta['footage'][clip_name] = {
                        'estado': 'pendiente',
                        'fuente': 'yt_clip',
                        'prompt': seg.get('ia_prompt', '')[:200],
                        'timestamp': seg.get('start_seconds', 0),
                        'yt_src': yt_src.name,
                    }
                    guardar_metadata(carpeta, meta)
                    ok(f'[{seg_id}] Sin imagen ZIP → clip YT: {yt_src.name}')
                    generadas += 1
                else:
                    err(f'[{seg_id}] Sin imagen en ZIP y sin clips YT disponibles')
                    errores += 1
                continue

            jpg_path = img_dir / f'flow_{seg_id:04d}.jpg'
            with z.open(jpg_name) as src, open(jpg_path, 'wb') as dst:
                dst.write(src.read())

            try:
                make_zoompan(jpg_path, clip_path, dur, index=seg_id)
                jpg_path.unlink(missing_ok=True)

                clip_dur = float(subprocess.run(
                    ['ffprobe','-v','quiet','-show_entries','format=duration',
                     '-of','csv=p=0', str(clip_path)],
                    capture_output=True, text=True).stdout.strip() or 0)

                if clip_dur > 0.5:
                    generadas += 1
                    meta['footage'][clip_name] = {
                        'estado': 'pendiente', 'fuente': 'flow',
                        'prompt': raw_prompt[:200], 'timestamp': start_s,
                    }
                    ok(f'[{seg_id}] → {clip_name} ({clip_dur:.1f}s)')
                else:
                    errores += 1
                    err(f'[{seg_id}] zoompan produjo clip vacío')
            except Exception as e:
                errores += 1
                err(f'[{seg_id}] zoompan falló: {e}')
                jpg_path.unlink(missing_ok=True)

            guardar_metadata(carpeta, meta)

    seg_by_id = {s.get('segment_id', i): s for i, s in enumerate(segments)}
    _fallback_clips_faltantes(carpeta, img_dir, seg_by_id)

    print(f'\n{"="*60}', flush=True)
    print(f'  Flow ZIP: {generadas} generadas  |  {errores} errores', flush=True)
    print(f'  Dashboard: http://localhost:5001/aprobar/{carpeta.parent.name}/{carpeta.name}/', flush=True)
    print(f'{"="*60}\n', flush=True)

    # Con ZIP todos los segmentos ya fueron procesados — no hay pendientes de flow/brave
    pendientes = []

    # ── Paso previo: resolver segmentos brave ANTES de ir a Baserow ──────────
    # Los segmentos con source="brave" se buscan ahora con validación visual.
    # Si se encuentra imagen válida → zoompan mp4 + registrar en metadata.
    # Si no se encuentra → reclasificar como "flow" para ir a Baserow.
    brave_key  = leer_key(BRAVE_KEY_FILE)
    or_key     = leer_key(OPENROUTER_KEY_FILE) if OPENROUTER_KEY_FILE.exists() else None
    cfg_harv   = cfg_harvester
    clip_secs_brave = cfg_harv.get('clip_secs', 6)

    flow_pendientes = []   # solo estos van a Baserow
    for seg in pendientes:
        if seg.get('source') != 'brave':
            flow_pendientes.append(seg)
            continue

        seg_id    = seg.get('segment_id', 0)
        query     = (seg.get('brave_query') or seg.get('scene_description_es', ''))[:120]
        desc_es   = seg.get('scene_description_es', query)
        clip_name = f'flow_{seg_id:04d}_zp.mp4'   # mismo nombre que flow para que dashboard lo encuentre
        dest_clip = img_dir / clip_name

        if dest_clip.exists():
            ok(f'[{seg_id}] brave — clip ya existe, saltando')
            continue

        if not brave_key:
            warn(f'[{seg_id}] Sin brave key — convirtiendo a flow')
            seg['source'] = 'flow'
            flow_pendientes.append(seg)
            continue

        print(f'  [{seg_id}] 🔍 Brave: "{query[:70]}"', flush=True)
        resultados = buscar_brave_imagenes(query, brave_key, count=10)
        encontrado = False
        for img_url, titulo, desc_r in resultados:
            texto_meta = f"{titulo} {desc_r}"
            if not juzgar_relevancia(query, texto_meta, umbral=0.05):
                continue
            tmp_jpg = img_dir / f'_brave_{seg_id:04d}.jpg'
            if not descargar_url(img_url, tmp_jpg):
                tmp_jpg.unlink(missing_ok=True)
                continue
            if not tmp_jpg.exists() or tmp_jpg.stat().st_size < 5_000:
                tmp_jpg.unlink(missing_ok=True)
                continue
            # Juez visual
            if or_key and not juzgar_imagen_vision(tmp_jpg, desc_es, or_key, titulo):
                warn(f'  [{seg_id}] Juez visual rechazó "{titulo[:40]}" — siguiente')
                tmp_jpg.unlink(missing_ok=True)
                continue
            if imagen_a_clip(tmp_jpg, dest_clip, clip_secs_brave, cfg_harv):
                tmp_jpg.unlink(missing_ok=True)
                ok(f'[{seg_id}] brave ✓ "{titulo[:45]}" → {clip_name}')
                # Registrar con la clave flow_ para que el dashboard muestre BRAVE correctamente
                meta.setdefault('footage', {})[clip_name] = {
                    'fuente': 'brave', 'query': query, 'titulo': titulo,
                    'estado': 'pendiente', 'costo': 0, 'segment_id': seg_id,
                    'timestamp': seg.get('start_seconds', 0),
                }
                guardar_metadata(carpeta, meta)
                encontrado = True
                break
            tmp_jpg.unlink(missing_ok=True)

        if not encontrado:
            warn(f'[{seg_id}] Brave sin resultado — convirtiendo a flow')
            seg['source'] = 'flow'
            if not seg.get('ia_prompt'):
                seg['ia_prompt'] = (
                    f"{desc_es}, vintage archival documentary photograph, "
                    "black and white, film grain, high contrast, no text, no letters"
                )
            flow_pendientes.append(seg)

    if not flow_pendientes:
        print('  Brave resolvió todos los segmentos — nada que subir a Baserow.', flush=True)
        return

    # ── Revisión de prompts antes de subir a Baserow ──────────────────────────
    # Si hay segmentos marcados como animate: True (Modo B, primeros 120s),
    # mostrar los prompts al usuario antes de subir para que pueda corregirlos.
    # ── VALIDADOR DE PROMPTS ÚNICOS (bloquea si hay duplicados consecutivos) ──
    all_prompts = [s.get('ia_prompt', '').strip() for s in flow_pendientes]
    max_consec = 1; cuenta_c = 1
    for i in range(1, len(all_prompts)):
        if all_prompts[i] and all_prompts[i] == all_prompts[i-1]:
            cuenta_c += 1; max_consec = max(max_consec, cuenta_c)
        else:
            cuenta_c = 1
    total_dup = len(all_prompts) - len(set(p for p in all_prompts if p))
    if max_consec > 2:
        print(f'\n  ✗ ERROR: {total_dup} prompts duplicados ({max_consec} consecutivos iguales).')
        print(f'  ✗ Regenera los prompts con un generador por segmento antes de subir a Baserow.')
        print(f'  ✗ Subida cancelada para proteger la calidad del video.')
        return
    elif total_dup > 0:
        print(f'\n  ⚠ Advertencia: {total_dup} prompts duplicados (máx {max_consec} consecutivos). Continuando...')
    # ── FIN VALIDADOR ──

    animate_segs = [s for s in flow_pendientes if s.get('animate')]
    if animate_segs:
        print(f'\n  ┌─ REVISIÓN PREVIA — {len(animate_segs)} segmentos VEO (animate, 0-120s) ─────────────')
        print(f'  │  Revisa los ia_prompt antes de subir a Baserow/Flow.')
        print(f'  │  Estos se animarán con VEO y deben incluir los logos de las empresas.')
        print(f'  │')
        for s in animate_segs:
            t   = s.get('start_seconds', 0)
            sid = s.get('segment_id', 0)
            print(f'  │  [{sid:02d}] {int(t//60)}:{int(t%60):02d}  brand={s.get("brand","—")}')
            print(f'  │        {s.get("ia_prompt","")[:100]}')
        print(f'  └──────────────────────────────────────────────────────────────────')
        print(f'\n  Presiona Enter para continuar con la subida a Baserow, o Ctrl+C para abortar...')
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            print('\n  ✗ Subida cancelada por el usuario.')
            return
        print(f'  ✓ Confirmado. Subiendo {len(flow_pendientes)} segmentos...')

    print(f'\n  Cargando {len(flow_pendientes)} segmentos Flow a Baserow...')

    # Verificar estado de filas existentes antes de borrar
    existing_check = _baserow_curl('GET', f'/database/rows/table/{BASEROW_TABLE_ID}/?user_field_names=true&size=200')
    existing_rows = existing_check.get('results', [])

    if existing_rows and not force_upload:
        pending_existing = [r for r in existing_rows if
            (isinstance(r.get('Status'), dict) and r['Status'].get('value') == 'pending') or
            (isinstance(r.get('Status'), str) and r['Status'] == 'pending')]
        completed_existing = [r for r in existing_rows if
            (isinstance(r.get('Status'), dict) and r['Status'].get('value') == 'completed') or
            (isinstance(r.get('Status'), str) and r['Status'] == 'completed')]

        # ⛔ REGLA DURA: si hay CUALQUIER fila completada → preguntar SIEMPRE antes de borrar
        if completed_existing:
            print(f'\n  ⛔  HAY {len(completed_existing)} fila(s) COMPLETADAS en Baserow — borrarlas significa perder imágenes ya generadas.')
            if pending_existing:
                print(f'       También hay {len(pending_existing)} fila(s) pendientes.')
            print(f'  ¿Borrar todo y subir {len(flow_pendientes)} nuevos segmentos? (s/N): ', end='', flush=True)
            try:
                resp = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                resp = 'n'
            if resp not in ('s', 'si', 'sí', 'y', 'yes'):
                print('  ✗ Cancelado. Usa --download-only para descargar las ya generadas, o --force para forzar.', flush=True)
                return
        elif pending_existing:
            # Solo pending, ninguna completada → preguntar también
            print(f'  ⚠️  HAY {len(pending_existing)} fila(s) en pending en Baserow.')
            print(f'  ¿Borrar todo y subir {len(flow_pendientes)} nuevos segmentos? (s/N): ', end='', flush=True)
            try:
                resp = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                resp = 'n'
            if resp not in ('s', 'si', 'sí', 'y', 'yes'):
                print('  ✗ Cancelado. Usa --download-only para descargar las ya generadas, o --force para forzar.', flush=True)
                return

    # Borrar filas existentes
    existing_ids = [r['id'] for r in existing_rows]
    for rid in existing_ids:
        _baserow_curl('DELETE', f'/database/rows/table/{BASEROW_TABLE_ID}/{rid}/')

    # Crear filas nuevas — solo Flow/IA van aquí
    items = []
    seg_map = {}
    for i, seg in enumerate(flow_pendientes):
        ia_p   = (seg.get('ia_prompt') or '').strip()
        seg_id = seg.get('segment_id', 0)
        desc   = seg.get('scene_description_es', '')
        veo_p  = seg.get('video_prompt', '').strip() or f'[{seg_id}] Slow cinematic zoom in, {desc}'
        items.append({
            'Image Prompt': ia_p,
            'VEO Prompt':   veo_p,
            'Mode':         'Imagegen',
            'Status':       'pending',
        })
        seg_map[i] = seg

    # Validar que las columnas del item coincidan con las de la tabla
    EXPECTED_COLS = {'Image Prompt', 'VEO Prompt', 'Mode', 'Status'}
    item_cols = set(items[0].keys()) if items else set()
    if item_cols != EXPECTED_COLS:
        raise RuntimeError(
            f'❌ Columnas Baserow incorrectas.\n'
            f'   Esperadas: {sorted(EXPECTED_COLS)}\n'
            f'   Enviadas:  {sorted(item_cols)}\n'
            f'   Revisa el código antes de subir.'
        )
    # Verificar contra la tabla real
    sample = _baserow_curl('GET', f'/database/rows/table/{BASEROW_TABLE_ID}/?user_field_names=true&size=1')
    if sample.get('results'):
        table_cols = set(sample['results'][0].keys()) - {'id', 'order'}
        missing = EXPECTED_COLS - table_cols
        if missing:
            raise RuntimeError(
                f'❌ Columnas faltantes en la tabla Baserow: {missing}\n'
                f'   Columnas en tabla: {sorted(table_cols)}'
            )

    result = _baserow_curl('POST', f'/database/rows/table/{BASEROW_TABLE_ID}/batch/?user_field_names=true', {'items': items})
    created_rows = result.get('items', [])
    ok(f'  {len(created_rows)} filas creadas en Baserow')

    # Mapear row_id → segment_id
    rowid_to_seg = {}
    for i, row in enumerate(created_rows):
        rowid_to_seg[row['id']] = seg_map[i]

    print(f'\n  26 prompts listos en Baserow. Avisa cuando termines.\n', flush=True)

    # Polling hasta que todas estén completed o failed
    max_wait_minutes = 60
    poll_interval    = 15
    waited           = 0
    completed_rows   = {}

    while waited < max_wait_minutes * 60:
        time.sleep(poll_interval)
        waited += poll_interval

        data = _baserow_curl('GET', f'/database/rows/table/{BASEROW_TABLE_ID}/?user_field_names=true&size=200')
        rows = data.get('results', [])

        total      = len(rows)
        n_done     = sum(1 for r in rows if isinstance(r.get('Status'), dict) and r['Status'].get('value') in ('completed', 'failed')
                         or isinstance(r.get('Status'), str) and r['Status'] in ('completed', 'failed'))
        n_complete = sum(1 for r in rows if isinstance(r.get('Status'), dict) and r['Status'].get('value') == 'completed'
                         or isinstance(r.get('Status'), str) and r['Status'] == 'completed')

        print(f'  [{waited}s] {n_done}/{total} procesadas ({n_complete} completadas)...')

        for r in rows:
            status_val = r.get('Status', '')
            if isinstance(status_val, dict):
                status_val = status_val.get('value', '')
            if status_val == 'completed' and r['id'] not in completed_rows:
                url = r.get('Video_URL', '')
                if url and url.startswith('http'):
                    completed_rows[r['id']] = {'url': url, 'row': r}

        if n_done >= total:
            break

    print(f'\n  Descargando {len(completed_rows)} imágenes...')

    generadas   = 0
    errores     = 0
    genaipro_n  = 0          # contador de imágenes enviadas a GenAIPro i2v
    GENAIPRO_MAX = 0         # siempre zoompan — GenAIPro muy lento para producción

    for row_id, info in completed_rows.items():
        seg      = rowid_to_seg.get(row_id)
        if not seg:
            continue
        idx       = seg.get('segment_id', 0)
        # Nombre estándar: flow_NNNN_zp.mp4 (4 dígitos) — render.py lo busca así
        clip_name = f'flow_{idx:04d}_zp.mp4'
        clip_path = img_dir / clip_name
        img_url   = info['url']
        start_s   = seg.get('start_seconds', 0)
        dur       = seg.get('duration', seg.get('end_seconds', start_s + 6) - start_s)
        dur       = min(round(dur, 3), 8.0)
        raw_prompt   = seg.get('ia_prompt') or seg.get('prompt_or_query', '')
        veo_prompt   = info['row'].get('Veo Prompt', '').strip()
        usar_genaipro = genaipro_n < GENAIPRO_MAX

        # Flow genera IMÁGENES ESTÁTICAS (1 frame mjpeg), no videos.
        # Flujo: descargar imagen Flow → extraer JPEG → convertir a zoompan
        # Intentos en orden: yt-dlp → curl+cookies Brave → curl directo → ai33pro
        raw_clip = img_dir / f'flow_{idx:04d}_raw.mp4'
        jpg_path = img_dir / f'flow_{idx:04d}.jpg'
        descarga_ok = False

        # Intento 1: yt-dlp con cookies de Brave + Referer obligatorio para Flow
        print(f'  [{idx}] Descargando (yt-dlp)...', flush=True)
        r = subprocess.run([
            '/opt/homebrew/bin/yt-dlp',
            '--cookies-from-browser', f'brave:{str(pathlib.Path.home())}/Library/Application Support/BraveSoftware/Brave-Browser/Default',
            '--add-header', 'Referer:https://labs.google/',
            '--add-header', 'Origin:https://labs.google',
            '-o', str(raw_clip),
            '--no-playlist', '-q',
            img_url
        ], capture_output=True, timeout=60)
        if raw_clip.exists() and raw_clip.stat().st_size >= 5000:
            subprocess.run(['ffmpeg', '-y', '-i', str(raw_clip), '-frames:v', '1', '-q:v', '1', str(jpg_path)],
                capture_output=True, timeout=15)
            raw_clip.unlink(missing_ok=True)
            if jpg_path.exists():
                descarga_ok = True

        # Intento 2: curl con cookies de Brave (mejor para URLs de Google Labs)
        if not descarga_ok:
            print(f'  [{idx}] yt-dlp falló, probando curl+cookies...', flush=True)
            raw_clip.unlink(missing_ok=True)
            r2 = subprocess.run([
                'curl', '-sL', '--max-time', '30',
                '--cookie-jar', '/tmp/flow_cookies.txt',
                '--cookie', '/tmp/flow_cookies.txt',
                '-A', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                '-H', 'Referer: https://labs.google/',
                '-o', str(raw_clip),
                img_url
            ], capture_output=True, timeout=45)
            if raw_clip.exists() and raw_clip.stat().st_size >= 5000:
                # Puede ser JPEG directo o mp4
                mime = subprocess.run(['file', '-b', '--mime-type', str(raw_clip)],
                    capture_output=True, text=True).stdout.strip()
                if 'jpeg' in mime or 'png' in mime or 'webp' in mime:
                    raw_clip.rename(jpg_path)
                else:
                    subprocess.run(['ffmpeg', '-y', '-i', str(raw_clip), '-frames:v', '1', '-q:v', '1', str(jpg_path)],
                        capture_output=True, timeout=15)
                    raw_clip.unlink(missing_ok=True)
                if jpg_path.exists():
                    descarga_ok = True

        # Intento 3: curl sin cookies (URL puede ser pública tras redirect)
        if not descarga_ok:
            print(f'  [{idx}] curl+cookies falló, probando curl directo...', flush=True)
            raw_clip.unlink(missing_ok=True)
            r3 = subprocess.run([
                'curl', '-sL', '--max-time', '30', '-o', str(raw_clip), img_url
            ], capture_output=True, timeout=45)
            if raw_clip.exists() and raw_clip.stat().st_size >= 5000:
                mime = subprocess.run(['file', '-b', '--mime-type', str(raw_clip)],
                    capture_output=True, text=True).stdout.strip()
                if 'jpeg' in mime or 'png' in mime or 'webp' in mime:
                    raw_clip.rename(jpg_path)
                else:
                    subprocess.run(['ffmpeg', '-y', '-i', str(raw_clip), '-frames:v', '1', '-q:v', '1', str(jpg_path)],
                        capture_output=True, timeout=15)
                    raw_clip.unlink(missing_ok=True)
                if jpg_path.exists():
                    descarga_ok = True

        # Intento 4: ai33pro — SOLO si no hay URL de Baserow (status != completed o URL vacía)
        # REGLA DURA: si img_url existe (row completed con URL), NO usar ai33pro — reportar error
        if not descarga_ok:
            raw_clip.unlink(missing_ok=True)
            if img_url:
                err(f'  [{idx}] FALLO descarga — URL existe en Baserow pero no se pudo descargar. NO se usa ai33pro. Reintenta manualmente.')
                errores += 1
                continue
            print(f'  [{idx}] Sin URL en Baserow → ai33pro fallback...', flush=True)
            ai33_script = pathlib.Path(__file__).parent / 'imagen_ai33pro.py'
            r4 = subprocess.run(
                ['python3', str(ai33_script), str(carpeta), '--seg', str(idx)],
                capture_output=True, timeout=300
            )
            if clip_path.exists() and clip_path.stat().st_size > 50_000:
                ok(f'  [{idx}] ai33pro ✓ → {clip_name}')
                generadas += 1
                meta['footage'][clip_name] = {
                    'estado': 'pendiente', 'fuente': 'ai33pro',
                    'prompt': raw_prompt[:200], 'timestamp': start_s,
                }
                guardar_metadata(carpeta, meta)
            else:
                err(f'  [{idx}] ai33pro también falló')
                errores += 1
            continue

        if not jpg_path.exists():
            err(f'  [{idx}] No se pudo extraer JPEG')
            errores += 1
            continue

        # ── Segmentos animate:True → guardar JPEG para VEO3, no hacer zoompan ──
        if seg.get('animate'):
            ok(f'  [{idx}] JPEG listo para VEO3 → flow_{idx:04d}.jpg (no zoompan)')
            # El _zp.mp4 queda como placeholder vacío para que el dashboard no rompa
            # El usuario reemplaza con el mp4 animado por VEO3
            generadas += 1
            meta['footage'][clip_name] = {
                'estado':    'pendiente_veo3',
                'fuente':    'flow',
                'prompt':    raw_prompt[:200],
                'timestamp': start_s,
                'jpeg_path': str(jpg_path),
            }
            guardar_metadata(carpeta, meta)
            continue

        # ── Animación: GenAIPro i2v (primeras 10) o zoompan (resto) ──────────
        if usar_genaipro:
            anim_prompt = veo_prompt or raw_prompt or "Slow cinematic zoom in"
            print(f'  [{idx}] GenAIPro i2v: "{anim_prompt[:60]}"', flush=True)
            gai_script  = Path(__file__).parent / 'genaipro_i2v.py'
            out_base    = img_dir / f'flow_{idx:04d}_zp'   # sin extensión
            r_gai = subprocess.run([
                'python3', str(gai_script),
                str(jpg_path),
                '--prompt', anim_prompt,
                '--out', str(out_base),
            ], capture_output=True, text=True, timeout=300)
            # El script descarga el mp4 como flow_NNNN_zp.mp4
            if clip_path.exists() and clip_path.stat().st_size > 50_000:
                genaipro_n += 1
                jpg_path.unlink(missing_ok=True)
            else:
                # Fallback a zoompan si GenAIPro falla
                err(f'  [{idx}] GenAIPro falló ({r_gai.stderr[-120:]}), usando zoompan')
                usar_genaipro = False   # cae al bloque de abajo

        if not usar_genaipro:
            dur_frames = int(dur * 25)
            make_zoompan(jpg_path, clip_path, dur, index=idx)
            jpg_path.unlink(missing_ok=True)

        # También generar preview 640x360 para el dashboard (mismo jpg → preview)
        preview_path = img_dir / f'flow_{idx:04d}_preview.mp4'
        if clip_path.exists():
            subprocess.run([
                'ffmpeg', '-y', '-i', str(clip_path),
                '-vf', 'scale=640:360', '-t', '3',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28', '-an',
                str(preview_path)
            ], capture_output=True, timeout=30)

        clip_dur_actual = float(subprocess.run(
            ['ffprobe','-v','quiet','-show_entries','format=duration','-of','csv=p=0', str(clip_path)],
            capture_output=True, text=True).stdout.strip() or 0)

        if clip_dur_actual > 0.5:
            generadas += 1
            meta['footage'][clip_name] = {
                'estado':    'pendiente',
                'fuente':    'flow',
                'prompt':    raw_prompt[:200],
                'timestamp': start_s,
            }
            ok(f'  [{idx}] → {clip_name} ({clip_dur_actual:.1f}s)')
        else:
            errores += 1
            err(f'  [{idx}] re-encode falló')

        guardar_metadata(carpeta, meta)

    seg_by_id = {s.get('segment_id', i): s for i, s in enumerate(segments)}
    _fallback_clips_faltantes(carpeta, img_dir, seg_by_id)



def download_only_flow(carpeta, segments, cfg_harvester):
    """OBSOLETO — Baserow eliminado. Usar --zip en su lugar."""
    print('  ✗ download-only ya no aplica. Usar: --zip <ruta.zip>', flush=True)




def main():
    # Forzar line-buffering para que el log aparezca en tiempo real aunque corra en background
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    if len(sys.argv) < 2:
        print("Uso: python3 harvester_timeline.py <carpeta_video> --canal <canal> [--desde N] [--hasta N] [--rerun] [--source flow] [--download-only]", flush=True)
        sys.exit(1)

    carpeta = pathlib.Path(sys.argv[1])
    nombre  = carpeta.name

    canal = None
    if "--canal" in sys.argv:
        canal = sys.argv[sys.argv.index("--canal") + 1]
    else:
        canal = carpeta.parent.name
        print(f"  {AMARILLO}⚠{RESET} --canal no especificado, infiriendo: {canal}", flush=True)

    rerun = "--rerun" in sys.argv
    download_only = "--download-only" in sys.argv
    force_upload = "--force" in sys.argv

    _approval_port = 5099
    if "--port" in sys.argv:
        _approval_port = int(sys.argv[sys.argv.index("--port") + 1])

    source = None
    if "--source" in sys.argv:
        source = sys.argv[sys.argv.index("--source") + 1]

    zip_path = None
    if "--zip" in sys.argv:
        zip_path = sys.argv[sys.argv.index("--zip") + 1]

    # Cargar config del canal para leer default_source si no se pasó --source
    cfg          = cargar_config(canal)
    cfg_harvester = cfg.get("harvester", {})
    if source is None:
        source = cfg_harvester.get("default_source")

    desde = 0
    hasta = None
    if "--desde" in sys.argv:
        desde = int(sys.argv[sys.argv.index("--desde") + 1])
    if "--hasta" in sys.argv:
        hasta = int(sys.argv[sys.argv.index("--hasta") + 1])

    source_order   = cfg_harvester.get("source_order", ["ia"])
    clip_secs      = cfg_harvester.get("clip_secs", 6)
    img_w          = cfg_harvester.get("img_w", 1024)
    img_h          = cfg_harvester.get("img_h", 576)
    prompt_suffix  = cfg_harvester.get("prompt_suffix", "")
    use_ref_photo  = cfg_harvester.get("use_reference_photo", False)

    muapi_key      = leer_key(MUAPI_KEY_FILE)
    pexels_key     = leer_key(PEXELS_KEY_FILE)
    pixabay_key    = leer_key(PIXABAY_KEY_FILE)
    brave_key      = leer_key(BRAVE_KEY_FILE)
    google_cse_key = leer_key(GOOGLE_CSE_KEY_FILE)
    google_cse_cx  = leer_key(GOOGLE_CSE_CX_FILE)
    openrouter_key = leer_key(OPENROUTER_KEY_FILE)

    _keys = dict(pexels_key=pexels_key, pixabay_key=pixabay_key,
                 brave_key=brave_key, google_cse_key=google_cse_key,
                 google_cse_cx=google_cse_cx, muapi_key=muapi_key)

    # Foto de referencia: se busca lazy (solo cuando IA va a generar)
    _ref_image_cache = {}

    if rerun:
        rerun_rechazados(
            carpeta, cfg, cfg_harvester, source_order, clip_secs, img_w, img_h,
            prompt_suffix, muapi_key, pexels_key, pixabay_key,
            brave_key=brave_key, google_cse_key=google_cse_key, google_cse_cx=google_cse_cx,
            openrouter_key=openrouter_key,
        )
        return

    timeline_f = carpeta / "05-montaje" / "timeline.json"
    img_dir    = carpeta / "03-imagenes"
    img_dir.mkdir(parents=True, exist_ok=True)

    if not timeline_f.exists():
        print(f"ERROR: No existe {timeline_f}"); sys.exit(1)

    data     = json.loads(timeline_f.read_text(encoding="utf-8"))
    segments = data["visual_timeline"]
    meta     = cargar_metadata(carpeta)

    # ── Modo download-only: descarga sin tocar Baserow ────────────────────────
    if download_only:
        download_only_flow(carpeta, segments, cfg_harvester)
        return

    # ── Modo Flow / ZIP ──────────────────────────────────────────────────────
    if source == "flow" or zip_path:
        if not zip_path:
            import glob as _glob
            zips = sorted(_glob.glob(str(pathlib.Path.home() / 'Downloads/veo-folder-1/*.zip')),
                          key=lambda p: pathlib.Path(p).stat().st_mtime, reverse=True)
            if zips:
                zip_path = zips[0]
                print(f'  ZIP auto-detectado: {zip_path}', flush=True)
            else:
                print('  ✗ No se encontró ZIP en ~/Downloads/veo-folder-1/', flush=True)
                return
        harvest_via_flow(carpeta, segments, cfg_harvester,
                         desde=desde, hasta=hasta,
                         force_upload=force_upload, zip_path=zip_path)
        return
    # ─────────────────────────────────────────────────────────────────────────

    total = len(segments)
    print(f"\n{'='*60}", flush=True)
    print(f"  HARVESTER [{cfg['nombre_display']}] — {nombre.upper()}")
    rango_str = f"{desde}–{hasta}" if hasta else f"{desde}–{total}"
    print(f"  Segmentos: {total} | Rango: {rango_str} | Fuentes: {source_order}", flush=True)
    print(f"{'='*60}\n", flush=True)

    generadas = 0
    errores   = 0
    # Registro global: URLs ya usadas en videos anteriores + las de esta sesión
    used_urls: set = cargar_clips_usados()

    for seg in segments:
        idx = seg.get("segment_id", 0)
        if idx < desde:
            continue
        if hasta is not None and idx > hasta:
            break

        clip_name = f"img_{idx:04d}.mp4"
        img_name  = f"img_{idx:04d}.png"
        clip_path = img_dir / clip_name
        img_path  = img_dir / img_name
        start_s   = seg.get("start_seconds", 0)
        desc      = seg.get("scene_description_es", "")[:50]
        raw_prompt = seg.get("prompt_or_query", "")
        desc_es    = seg.get("scene_description_es", raw_prompt)

        # Queries específicas por fuente (nuevo formato de timeline)
        # Si no existen, caen al raw_prompt genérico como fallback
        brave_query_spec   = seg.get("brave_query")   or raw_prompt
        pexels_query_spec  = seg.get("pexels_query")  or raw_prompt
        pixabay_query_spec = seg.get("pixabay_query") or raw_prompt
        ia_prompt_spec     = seg.get("ia_prompt")     or raw_prompt

        # Construir prompt IA: si hay ia_prompt específico en el timeline, usarlo tal cual.
        # El prompt_suffix solo se agrega cuando el prompt es genérico (sin ia_prompt explícito).
        has_specific_ia_prompt = bool(seg.get("ia_prompt"))
        prompt = ia_prompt_spec
        if prompt_suffix and not has_specific_ia_prompt and prompt_suffix not in prompt:
            prompt = f"{ia_prompt_spec}, {prompt_suffix}"

        # Saltar segmentos yt_clip — son clips de YouTube, no imágenes IA
        if seg.get("source") == "yt_clip":
            continue

        # Saltar si ya existe y está aprobado
        estado_previo = meta["footage"].get(clip_name, {}).get("estado")
        if clip_path.exists() and estado_previo == "aprobado":
            ok(f"[{idx}/{total}] {clip_name} — ya aprobado")
            continue

        print(f"  [{idx:03d}/{total}] {start_s:.1f}s — {desc}", flush=True)

        fuente_usada = None
        exito        = False

        trigger_type = seg.get("trigger_type", "")
        effective_sources = cadena_fuentes(
            seg.get("scene_description_es", raw_prompt), trigger_type, **_keys
        )
        tipo_det = detectar_tipo_escena(seg.get("scene_description_es", raw_prompt), trigger_type)
        print(f"    tipo={tipo_det} → cadena: {' → '.join(effective_sources)}")

        for fuente in effective_sources:

            if fuente == "ia":
                if not muapi_key:
                    warn("Sin muapi key"); continue
                try:
                    # Buscar foto de referencia del personaje si el canal lo pide
                    _ref_url = None
                    if use_ref_photo and brave_key:
                        if "ref" not in _ref_image_cache:
                            nombre_display = nombre.replace("_", " ").title()
                            _ref_image_cache["ref"] = buscar_foto_referencia(nombre_display, brave_key, carpeta)
                        _ref_url = _ref_image_cache.get("ref")
                    img_url = generar_imagen_ia(prompt, muapi_key, img_w, img_h, ref_image_url=_ref_url)
                    if descargar_url(img_url, img_path):
                        if imagen_a_clip(img_path, clip_path, clip_secs, cfg_harvester):
                            fuente_usada = "ia"
                            exito = True
                            ok(f"  IA → {clip_name}")
                            break
                except Exception as e:
                    warn(f"  IA falló: {e}")

            elif fuente == "brave":
                if not brave_key:
                    warn("Sin brave key"); continue
                try:
                    resultados = buscar_brave_imagenes(brave_query_spec[:120], brave_key, count=10)
                    for img_url_b, titulo_b, desc_b in resultados:
                        texto_meta = f"{titulo_b} {desc_b}"
                        if not juzgar_relevancia(brave_query_spec, texto_meta, umbral=0.10):
                            warn(f"  Brave: '{titulo_b[:40]}' no relevante — siguiente")
                            continue
                        tmp_img = img_dir / f"_tmp_{idx:04d}_brave.jpg"
                        if descargar_url(img_url_b, tmp_img) and tmp_img.stat().st_size > 5000:
                            if not juzgar_imagen_vision(tmp_img, desc_es, openrouter_key, titulo_fuente=titulo_b):
                                warn(f"  Brave: juez visual rechazó '{titulo_b[:35]}' — siguiente")
                                tmp_img.unlink(missing_ok=True)
                                continue
                            if imagen_a_clip(tmp_img, clip_path, clip_secs, cfg_harvester):
                                tmp_img.unlink(missing_ok=True)
                                fuente_usada = "brave"
                                exito = True
                                ok(f"  Brave ({titulo_b[:35]}) → {clip_name}")
                                break
                        tmp_img.unlink(missing_ok=True)
                    if exito:
                        break
                except Exception as e:
                    warn(f"  Brave falló: {e}")

            elif fuente == "wikimedia":
                try:
                    desc_es = seg.get("scene_description_es", raw_prompt)
                    resultados_w = buscar_wikimedia(desc_es, count=15)
                    for img_url_w, titulo_w, desc_w in resultados_w:
                        if not juzgar_relevancia(desc_es, f"{titulo_w} {desc_w}", umbral=0.08):
                            warn(f"  Wikimedia: '{titulo_w[:40]}' no relevante — siguiente")
                            continue
                        tmp_img = img_dir / f"_tmp_{idx:04d}_wiki.jpg"
                        if descargar_url(img_url_w, tmp_img) and tmp_img.exists() and tmp_img.stat().st_size > 5000:
                            if not juzgar_imagen_vision(tmp_img, desc_es, openrouter_key, titulo_fuente=titulo_w):
                                warn(f"  Wikimedia: juez visual rechazó '{titulo_w[:40]}' — siguiente")
                                tmp_img.unlink(missing_ok=True)
                                continue
                            if imagen_a_clip(tmp_img, clip_path, clip_secs, cfg_harvester):
                                tmp_img.unlink(missing_ok=True)
                                fuente_usada = "wikimedia"
                                exito = True
                                ok(f"  Wikimedia ({titulo_w[:40]}) → {clip_name}")
                                break
                        tmp_img.unlink(missing_ok=True)
                    if exito:
                        break
                except Exception as e:
                    warn(f"  Wikimedia falló: {e}")

            elif fuente == "google_cse":
                if not (google_cse_key and google_cse_cx):
                    warn("Sin Google CSE key/cx"); continue
                try:
                    desc_es = seg.get("scene_description_es", raw_prompt)
                    resultados_g = buscar_google_cse(desc_es, google_cse_key, google_cse_cx, count=5)
                    for img_url_g, titulo_g, desc_g in resultados_g:
                        if not juzgar_relevancia(desc_es, f"{titulo_g} {desc_g}", umbral=0.08):
                            warn(f"  Google CSE: '{titulo_g[:40]}' no relevante — siguiente")
                            continue
                        tmp_img = img_dir / f"_tmp_{idx:04d}_goog.jpg"
                        if descargar_url(img_url_g, tmp_img) and tmp_img.exists() and tmp_img.stat().st_size > 5000:
                            if not juzgar_imagen_vision(tmp_img, desc_es, openrouter_key):
                                warn(f"  Google CSE: juez visual rechazó '{titulo_g[:40]}' — siguiente")
                                tmp_img.unlink(missing_ok=True)
                                continue
                            if imagen_a_clip(tmp_img, clip_path, clip_secs, cfg_harvester):
                                tmp_img.unlink(missing_ok=True)
                                fuente_usada = "google_cse"
                                exito = True
                                ok(f"  Google CSE ({titulo_g[:40]}) → {clip_name}")
                                break
                        tmp_img.unlink(missing_ok=True)
                    if exito:
                        break
                except Exception as e:
                    warn(f"  Google CSE falló: {e}")

            elif fuente == "pexels":
                if not pexels_key:
                    warn("Sin pexels key"); continue
                try:
                    video_url = buscar_pexels(pexels_query_spec[:80], pexels_key)
                    if video_url:
                        if video_url in used_urls:
                            warn(f"  Pexels: URL duplicada — siguiente fuente")
                        else:
                            tmp = img_dir / f"_tmp_{idx:04d}.mp4"
                            if descargar_url(video_url, tmp):
                                if normalizar_clip(tmp, clip_path, clip_secs):
                                    tmp.unlink(missing_ok=True)
                                    # Juez visual: extraer frame y validar contenido
                                    _frame = img_dir / f"_judge_{idx:04d}.jpg"
                                    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error",
                                        "-nostdin", "-ss", "2", "-i", str(clip_path),
                                        "-vframes", "1", "-q:v", "3", "-y", str(_frame)],
                                        capture_output=True, timeout=8)
                                    _aprobado = True
                                    if _frame.exists():
                                        _aprobado = juzgar_imagen_vision(_frame, desc_es, openrouter_key, titulo_fuente=pexels_query_spec)
                                        _frame.unlink(missing_ok=True)
                                    if _aprobado:
                                        used_urls.add(video_url)
                                        guardar_clips_usados(used_urls)
                                        fuente_usada = "pexels"
                                        exito = True
                                        ok(f"  Pexels → {clip_name}")
                                        break
                                    else:
                                        warn(f"  Pexels: juez visual rechazó — siguiente fuente")
                                        clip_path.unlink(missing_ok=True)
                except Exception as e:
                    warn(f"  Pexels falló: {e}")

            elif fuente == "pixabay":
                if not pixabay_key:
                    warn("Sin pixabay key"); continue
                try:
                    import urllib.parse as _up
                    _url = (f"https://pixabay.com/api/videos/?key={pixabay_key}"
                            f"&q={_up.quote(pixabay_query_spec[:80])}&per_page=10&video_type=film")
                    with urllib.request.urlopen(_url, timeout=8) as _r:
                        _data = json.loads(_r.read())
                    video_url = None
                    tags_str  = ""
                    for h in _data.get("hits", []):
                        tags_str = h.get("tags", "")
                        if not juzgar_relevancia(pixabay_query_spec, tags_str, umbral=0.10):
                            warn(f"  Pixabay tags '{tags_str[:40]}' no relevantes — siguiente hit")
                            continue
                        candidate_url = None
                        for quality in ["large", "medium"]:
                            v = h.get("videos", {}).get(quality)
                            if v and v.get("width", 0) >= 1280:
                                candidate_url = v["url"]
                                break
                        if candidate_url and candidate_url not in used_urls:
                            video_url = candidate_url
                            break
                        elif candidate_url:
                            warn(f"  Pixabay: URL duplicada ({tags_str[:30]}) — siguiente hit")
                    if video_url:
                        tmp = img_dir / f"_tmp_{idx:04d}.mp4"
                        if descargar_url(video_url, tmp):
                            if normalizar_clip(tmp, clip_path, clip_secs):
                                tmp.unlink(missing_ok=True)
                                # Juez visual: extraer frame y validar contenido
                                _frame = img_dir / f"_judge_{idx:04d}.jpg"
                                subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error",
                                    "-nostdin", "-ss", "2", "-i", str(clip_path),
                                    "-vframes", "1", "-q:v", "3", "-y", str(_frame)],
                                    capture_output=True, timeout=8)
                                _aprobado = True
                                if _frame.exists():
                                    _aprobado = juzgar_imagen_vision(_frame, desc_es, openrouter_key, titulo_fuente=tags_str)
                                    _frame.unlink(missing_ok=True)
                                if not _aprobado:
                                    warn(f"  Pixabay: juez visual rechazó '{tags_str[:30]}' — siguiente")
                                    clip_path.unlink(missing_ok=True)
                                    continue
                                used_urls.add(video_url)
                                guardar_clips_usados(used_urls)
                                fuente_usada = "pixabay"
                                exito = True
                                ok(f"  Pixabay ({tags_str[:30]}) → {clip_name}")
                                break
                except Exception as e:
                    warn(f"  Pixabay falló: {e}")

        if exito:
            generadas += 1
            meta["footage"][clip_name] = {
                "estado": "pendiente",
                "fuente": fuente_usada,
                "prompt": raw_prompt[:200],
                "timestamp": start_s,
            }
        else:
            errores += 1
            err(f"  [{idx}/{total}] Sin imagen para {clip_name}")

        guardar_metadata(carpeta, meta)

    print(f"\n{'='*60}", flush=True)
    print(f"  Generadas: {generadas}  |  Errores: {errores}", flush=True)
    print(f"  Aprobá en: http://localhost:5001/aprobar/{carpeta.parent.name}/{carpeta.name}/", flush=True)
    print(f"{'='*60}\n", flush=True)

if __name__ == "__main__":
    main()
