#!/usr/bin/env python3
"""
footage_harvester.py — Busca y descarga footage B-roll para cada escena del guion.

Flujo por escena:
  1. Pexels API   (video gratis, legal) → ~/.pexels_key
  2. Pixabay API  (video gratis, legal) → ~/.pixabay_key
  3. Brave Search (imagen real → Ken Burns) → ~/.brave_key
  4. Si nada sirve → genera imagen IA con muapi.ai y la anima → ~/.muapi_key

Uso:
    python3 footage_harvester.py <carpeta_video>
    python3 footage_harvester.py seduccion/no_eres_malo/

Estructura de salida:
    <carpeta_video>/
    ├── footage/
    │   ├── clip_001.mp4
    │   ├── clip_002.mp4
    │   └── ...
    └── metadata.json  (sección "footage" actualizada)

API keys requeridas:
    ~/.pexels_key   — https://www.pexels.com/api/
    ~/.pixabay_key  — https://pixabay.com/api/docs/
    ~/.muapi_key    — https://api.muapi.ai (fallback IA)
"""

import sys, os, json, time, subprocess, urllib.request, urllib.error, urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from zoompan_clip import make_zoompan  # NUNCA reescribir zoompan inline — z=1.5 fijo

FFMPEG  = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
if not Path(FFMPEG).exists():
    FFMPEG  = "/usr/local/bin/ffmpeg"
    FFPROBE = "/usr/local/bin/ffprobe"

PEXELS_KEY_FILE  = Path.home() / ".pexels_key"
PIXABAY_KEY_FILE = Path.home() / ".pixabay_key"
BRAVE_KEY_FILE   = Path.home() / ".brave_key"
MUAPI_KEY_FILE   = Path.home() / ".muapi_key"

CLIP_MAX_SECONDS = 5
TARGET_W         = 1920
TARGET_H         = 1080

VERDE    = "\033[92m"
ROJO     = "\033[91m"
AMARILLO = "\033[93m"
RESET    = "\033[0m"

def ok(msg):   print(f"  {VERDE}✓{RESET} {msg}")
def err(msg):  print(f"  {ROJO}✗{RESET} {msg}")
def warn(msg): print(f"  {AMARILLO}⚠{RESET} {msg}")


# ── Lectura de keys ───────────────────────────────────────────────────────────

def leer_key(path, nombre):
    if not Path(path).exists():
        return None
    k = Path(path).read_text().strip()
    return k if k else None


# ── Extracción de segmentos desde SRT ────────────────────────────────────────

# Stop words español para filtrar al extraer keywords
_STOP_ES = {
    "de","la","el","en","que","y","a","los","las","un","una","se","del","por",
    "con","no","una","su","al","lo","como","más","pero","sus","le","ya","o","fue",
    "este","ha","si","ser","hay","era","muy","todo","esta","también","cuando",
    "años","año","entre","sin","sobre","les","esto","porque","todo","hasta",
    "después","durante","desde","donde","quien","qué","él","ella","ellos","ellas",
    "nos","me","te","mi","tu","es","son","fue","han","para","así","esto","eso",
    "ese","esa","esos","esas","me","le","les","nos","mis","tus","sus","nuestro",
    "nuestra","había","han","dos","tres","uno","unos","unas","tanto","tan",
}

# Traducciones básicas ES→EN para términos frecuentes en contenido biográfico
_TRAD = {
    "mansión": "luxury mansion", "mansion": "luxury mansion",
    "millones": "money wealth", "millonario": "wealthy man",
    "fortuna": "wealth fortune", "dinero": "money cash",
    "lujo": "luxury lifestyle", "lujoso": "luxury",
    "playa": "beach tropical", "mar": "ocean sea",
    "ciudad": "city urban", "ciudad": "city",
    "niño": "child", "niña": "girl child", "joven": "young man",
    "hospital": "hospital medical", "trasplante": "hospital surgery",
    "pulmón": "lung hospital", "enfermedad": "illness hospital",
    "familia": "family", "hijos": "children family", "hijas": "daughters family",
    "esposa": "wife couple", "matrimonio": "wedding marriage",
    "divorcio": "divorce separation", "amor": "love couple",
    "música": "music concert", "cantante": "singer performer",
    "escenario": "stage concert", "concierto": "concert live music",
    "televisión": "television studio", "tv": "television studio",
    "empresario": "businessman office", "negocio": "business office",
    "éxito": "success achievement", "fama": "fame celebrity",
    "carrera": "career success", "trabajo": "work professional",
    "muerte": "dramatic dark", "vida": "life lifestyle",
    "nació": "birth childhood", "nacimiento": "birth",
    "hollywood": "Hollywood movies", "cine": "cinema film",
    "actuación": "acting performance", "actor": "actor performance",
    "rancho": "ranch countryside", "hacienda": "ranch estate",
    "campo": "countryside nature", "naturaleza": "nature landscape",
    "lucha": "struggle effort", "drama": "dramatic emotional",
    "reconciliación": "family reunion emotional",
}

def _srt_ts_to_sec(ts):
    """'00:01:23,456' → 83.456"""
    ts = ts.replace(",", ".")
    h, m, s = ts.split(":")
    return int(h)*3600 + int(m)*60 + float(s)


def parsear_srt(srt_path):
    """Lee el SRT y retorna lista de {start_s, end_s, text}."""
    texto = Path(srt_path).read_text(encoding="utf-8", errors="ignore")
    bloques = texto.strip().split("\n\n")
    captions = []
    for bloque in bloques:
        lineas = bloque.strip().split("\n")
        if len(lineas) < 3:
            continue
        try:
            tiempos = lineas[1].split(" --> ")
            start_s = _srt_ts_to_sec(tiempos[0].strip())
            end_s   = _srt_ts_to_sec(tiempos[1].strip())
            txt     = " ".join(lineas[2:]).strip()
            captions.append({"start_s": start_s, "end_s": end_s, "text": txt})
        except Exception:
            continue
    return captions


def agrupar_por_ventana(captions, ventana_s=30):
    """Agrupa captions en bloques de ventana_s segundos."""
    if not captions:
        return []
    grupos = []
    bloque_start = captions[0]["start_s"]
    bloque_texts = []
    for cap in captions:
        if cap["start_s"] - bloque_start >= ventana_s:
            if bloque_texts:
                grupos.append({
                    "start_s": bloque_start,
                    "text":    " ".join(bloque_texts),
                })
            bloque_start = cap["start_s"]
            bloque_texts = [cap["text"]]
        else:
            bloque_texts.append(cap["text"])
    if bloque_texts:
        grupos.append({"start_s": bloque_start, "text": " ".join(bloque_texts)})
    return grupos


def texto_a_query_en(texto_es, personaje=""):
    """
    Convierte texto en español a query de búsqueda en inglés.
    Estrategia: traducciones directas + palabras sin stop words.
    """
    t = texto_es.lower()
    partes = []

    # 1. Aplicar traducciones directas
    for es, en in _TRAD.items():
        if es in t:
            partes.append(en)
            if len(partes) >= 2:
                break

    # 2. Extraer palabras con mayúscula del texto original (proper nouns: nombres, ciudades)
    propios = [w.strip(".,;:()¿?¡!\"'") for w in texto_es.split()
               if w and w[0].isupper() and len(w) > 3
               and w.lower() not in _STOP_ES and not w.isdigit()]
    # Excluir el personaje mismo para no buscar su cara (usamos B-roll genérico)
    slug = personaje.replace("_", " ").lower()
    propios = [p for p in propios if p.lower() not in slug.split()][:2]
    partes.extend(propios)

    if not partes:
        # Fallback: palabras largas que no sean stop words
        palabras = [w.strip(".,;:()¿?¡!\"'") for w in t.split()
                    if len(w) > 5 and w not in _STOP_ES][:3]
        partes.extend(palabras)

    query = " ".join(dict.fromkeys(partes))[:80]  # dedup, max 80 chars
    return query or "cinematic lifestyle documentary"


def extraer_segmentos_srt(carpeta, ventana_s=30):
    """
    Lee el .srt de la carpeta, agrupa en bloques de ventana_s segundos
    y extrae un query de búsqueda en inglés para cada bloque.
    Retorna lista de {idx, start_s, query_en, prompt_ia}.
    """
    nombre   = carpeta.name
    srt_path = carpeta / f"{nombre}.srt"
    if not srt_path.exists():
        srts = list(carpeta.glob("*.srt"))
        if not srts:
            return []
        srt_path = srts[0]

    captions = parsear_srt(srt_path)
    grupos   = agrupar_por_ventana(captions, ventana_s)

    segmentos = []
    for i, g in enumerate(grupos, 1):
        query = texto_a_query_en(g["text"], nombre)
        segmentos.append({
            "idx":      i,
            "start_s":  round(g["start_s"], 1),
            "query_en": query,
            "prompt_ia": f"cinematic photorealistic scene: {query}, 16:9 wide shot, dramatic lighting",
        })
    return segmentos


# ── Pexels API ────────────────────────────────────────────────────────────────

def buscar_pexels(query, api_key, per_page=3):
    """Busca videos en Pexels. Retorna lista de URLs de descarga."""
    params = urllib.parse.urlencode({
        "query": query,
        "per_page": per_page,
        "orientation": "landscape",
        "size": "medium",
    })
    url = f"https://api.pexels.com/videos/search?{params}"
    req = urllib.request.Request(url, headers={"Authorization": api_key})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        videos = data.get("videos", [])
        resultados = []
        for v in videos:
            # Preferir HD 1080p, sino la de mayor resolución disponible
            files = v.get("video_files", [])
            files_hd = [f for f in files if f.get("height", 0) >= 720 and f.get("width", 0) >= 1280]
            if not files_hd:
                files_hd = sorted(files, key=lambda x: x.get("height", 0), reverse=True)
            if files_hd:
                resultados.append({
                    "url": files_hd[0]["link"],
                    "fuente": "pexels",
                    "id": str(v["id"]),
                    "duracion": v.get("duration", 0),
                })
        return resultados
    except Exception as e:
        return []


# ── Pixabay API ───────────────────────────────────────────────────────────────

def buscar_pixabay(query, api_key, per_page=3):
    """Busca videos en Pixabay. Retorna lista de URLs."""
    params = urllib.parse.urlencode({
        "key": api_key,
        "q": query,
        "video_type": "film",
        "per_page": per_page,
        "safesearch": "true",
    })
    url = f"https://pixabay.com/api/videos/?{params}"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
        hits = data.get("hits", [])
        resultados = []
        for h in hits:
            videos = h.get("videos", {})
            # Preferir large (1920), sino medium (1280), sino small
            for calidad in ["large", "medium", "small"]:
                v = videos.get(calidad, {})
                if v.get("url"):
                    resultados.append({
                        "url": v["url"],
                        "fuente": "pixabay",
                        "id": str(h["id"]),
                        "duracion": h.get("duration", 0),
                    })
                    break
        return resultados
    except Exception as e:
        return []


# ── Descarga y procesamiento FFmpeg ──────────────────────────────────────────

def descargar(url, destino):
    """Descarga un archivo desde URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        Path(destino).write_bytes(r.read())


def procesar_clip(src, dst):
    """
    Normaliza a 1080p 16:9, recorta a máx 5s, elimina audio.
    """
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", str(src),
        "-t", str(CLIP_MAX_SECONDS),
        "-vf", f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,crop={TARGET_W}:{TARGET_H}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-an",
        "-y", str(dst)
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode()[:300])


# ── Brave Search — imágenes reales → Ken Burns ───────────────────────────────

BLOCKED_DOMAINS = ["alamy", "gettyimages", "shutterstock", "istockphoto",
                   "dreamstime", "123rf", "depositphotos", "freepik"]

def buscar_brave_imagen(query, api_key, count=5):
    """Busca imágenes reales en Brave. Retorna lista de URLs filtradas."""
    params = urllib.parse.urlencode({
        "q": query, "count": count, "safesearch": "strict",
    })
    url = f"https://api.search.brave.com/res/v1/images/search?{params}"
    req = urllib.request.Request(url, headers={
        "X-Subscription-Token": api_key, "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        results = data.get("results", [])
        urls = []
        for r in results:
            src = (r.get("url") or "").lower()
            if any(d in src for d in BLOCKED_DOMAINS):
                continue
            props = r.get("properties", {})
            img_url = props.get("url") or r.get("thumbnail", {}).get("src")
            if img_url:
                urls.append(img_url)
        return urls
    except Exception:
        return []


def imagen_url_a_clip(img_url, clip_final, footage_dir, idx):
    """Descarga imagen de URL y la convierte a clip Ken Burns."""
    tmp_img = footage_dir / f"_tmp_brave_{idx:03d}.jpg"
    descargar(img_url, tmp_img)
    imagen_a_clip(tmp_img, clip_final, index=idx)
    tmp_img.unlink(missing_ok=True)


# ── Generación IA (muapi fallback) ───────────────────────────────────────────

MUAPI_BASE = "https://api.muapi.ai/api/v1"

def generar_imagen_ia(prompt, api_key):
    """Genera imagen con flux-schnell y retorna URL."""
    payload = json.dumps({"prompt": prompt, "width": 1024, "height": 576}).encode()
    req = urllib.request.Request(
        f"{MUAPI_BASE}/flux-schnell-image",
        data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        resp = json.loads(r.read())

    task_id = resp.get("request_id") or resp.get("data", {}).get("id")
    if not task_id:
        raise RuntimeError(f"Sin task_id: {resp}")

    # Polling
    poll_url = f"{MUAPI_BASE}/predictions/{task_id}/result"
    for _ in range(15):
        time.sleep(8)
        req2 = urllib.request.Request(poll_url, headers={"x-api-key": api_key})
        with urllib.request.urlopen(req2, timeout=30) as r2:
            data = json.loads(r2.read())
        d = data.get("data", data)
        if d.get("status") == "completed":
            outputs = d.get("outputs", [])
            if outputs:
                return outputs[0]
        if d.get("status") == "failed":
            raise RuntimeError(f"IA falló: {d.get('error')}")
    raise TimeoutError("IA no completó en 120s")


def imagen_a_clip(img_path, dst, index=0):
    """Convierte imagen estática a clip animado con Ken Burns via zoompan_clip."""
    ok = make_zoompan(Path(img_path), Path(dst), CLIP_MAX_SECONDS, index=index)
    if not ok:
        raise RuntimeError(f"zoompan falló para {img_path}")


# ── Metadata ──────────────────────────────────────────────────────────────────

def cargar_metadata(carpeta):
    meta_path = carpeta / "metadata.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text(encoding="utf-8"))
    return {}


def guardar_metadata(carpeta, meta):
    meta_path = carpeta / "metadata.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    carpeta = Path(sys.argv[1]).resolve()
    if not carpeta.is_dir():
        sys.exit(f"[ERROR] Carpeta no encontrada: {carpeta}")

    footage_dir = carpeta / "footage"
    footage_dir.mkdir(exist_ok=True)

    # Leer keys
    pexels_key  = leer_key(PEXELS_KEY_FILE, "Pexels")
    pixabay_key = leer_key(PIXABAY_KEY_FILE, "Pixabay")
    brave_key   = leer_key(BRAVE_KEY_FILE,   "Brave")
    muapi_key   = leer_key(MUAPI_KEY_FILE,   "Muapi")

    print(f"\n{'='*60}")
    print(f"  FOOTAGE HARVESTER — {carpeta.name.upper()}")
    print(f"  Pexels:  {'✓' if pexels_key  else '✗ sin key'}")
    print(f"  Pixabay: {'✓' if pixabay_key else '✗ sin key'}")
    print(f"  Brave:   {'✓' if brave_key   else '✗ sin key'} (imágenes reales → Ken Burns)")
    print(f"  Muapi:   {'✓' if muapi_key   else '✗ sin key'} (fallback IA)")
    print(f"{'='*60}\n")

    # Extraer segmentos desde el SRT (bloques de 30s con keywords en inglés)
    segmentos = extraer_segmentos_srt(carpeta)
    if not segmentos:
        sys.exit("[ERROR] No se encontró archivo .srt en la carpeta.")

    print(f"  {len(segmentos)} segmentos detectados en el guion\n")

    # Metadata
    meta = cargar_metadata(carpeta)
    if "footage" not in meta:
        meta["footage"] = {}

    resultados = []
    ia_pendientes = []

    for seg in segmentos:
        idx        = seg["idx"]
        clip_name  = f"clip_{idx:03d}.mp4"
        clip_final = footage_dir / clip_name
        query      = seg["query_en"]
        start_s    = seg["start_s"]

        # Si ya existe y está aprobado, saltar
        estado_previo = meta["footage"].get(clip_name, {}).get("estado")
        if clip_final.exists() and estado_previo == "aprobado":
            ok(f"[{idx}/{len(segmentos)}] {clip_name} — ya aprobado, saltando")
            resultados.append({"clip": clip_name, "fuente": meta["footage"][clip_name]["fuente"], "ok": True})
            continue

        print(f"  [{idx}/{len(segmentos)}] {start_s:.0f}s → \"{query}\"")

        clip_descargado = False
        fuente_usada    = None
        tmp_raw = footage_dir / f"_tmp_{idx:03d}.mp4"

        # 1️⃣ Pexels
        if pexels_key and not clip_descargado:
            resultados_pexels = buscar_pexels(query, pexels_key)
            if resultados_pexels:
                try:
                    descargar(resultados_pexels[0]["url"], tmp_raw)
                    procesar_clip(tmp_raw, clip_final)
                    tmp_raw.unlink(missing_ok=True)
                    clip_descargado = True
                    fuente_usada = "pexels"
                    ok(f"     → Pexels: descargado y procesado")
                except Exception as e:
                    warn(f"     → Pexels: falló procesamiento ({e})")
                    tmp_raw.unlink(missing_ok=True)

        # 2️⃣ Pixabay
        if pixabay_key and not clip_descargado:
            resultados_pixabay = buscar_pixabay(query, pixabay_key)
            if resultados_pixabay:
                try:
                    descargar(resultados_pixabay[0]["url"], tmp_raw)
                    procesar_clip(tmp_raw, clip_final)
                    tmp_raw.unlink(missing_ok=True)
                    clip_descargado = True
                    fuente_usada = "pixabay"
                    ok(f"     → Pixabay: descargado y procesado")
                except Exception as e:
                    warn(f"     → Pixabay: falló procesamiento ({e})")
                    tmp_raw.unlink(missing_ok=True)

        # 3️⃣ Brave Search — imagen real → Ken Burns
        if brave_key and not clip_descargado:
            urls_brave = buscar_brave_imagen(query, brave_key)
            for img_url in urls_brave:
                try:
                    imagen_url_a_clip(img_url, clip_final, footage_dir, idx)
                    clip_descargado = True
                    fuente_usada = "brave"
                    ok(f"     → Brave: imagen real → clip Ken Burns")
                    break
                except Exception as e:
                    continue

        # 4️⃣ IA (muapi.ai — flux-schnell)
        if not clip_descargado:
            if muapi_key:
                ia_pendientes.append((idx, clip_name, clip_final, seg["prompt_ia"]))
                warn(f"     → sin footage real → cola IA ({seg['prompt_ia'][:60]}...)")
                fuente_usada = "ia"
                meta["footage"][clip_name] = {
                    "estado":   "pendiente_ia",
                    "fuente":   "ia",
                    "keywords": query,
                }
            else:
                err(f"     → sin footage ni key de Muapi para IA")
                meta["footage"][clip_name] = {
                    "estado":   "faltante",
                    "fuente":   "ninguna",
                    "keywords": query,
                }
            resultados.append({"clip": clip_name, "fuente": fuente_usada or "ninguna", "ok": False})
            continue

        # Registrar en metadata con estado pendiente (requiere aprobación en dashboard)
        meta["footage"][clip_name] = {
            "estado":   "pendiente",
            "fuente":   fuente_usada,
            "keywords": query,
        }
        resultados.append({"clip": clip_name, "fuente": fuente_usada, "ok": True})
        guardar_metadata(carpeta, meta)
        print()

    # Generar clips IA en lote
    if ia_pendientes:
        print(f"\n{'='*60}")
        print(f"  GENERANDO {len(ia_pendientes)} CLIPS CON IA (flux-schnell)")
        print(f"  Costo estimado: ~${len(ia_pendientes) * 0.003:.3f} USD")
        print(f"{'='*60}")

        for (idx, clip_name, clip_final, prompt) in ia_pendientes:
            print(f"\n  [{idx}] {prompt[:70]}...")
            try:
                img_url = generar_imagen_ia(prompt, muapi_key)
                tmp_img = footage_dir / f"_tmp_ia_{idx:03d}.jpg"
                descargar(img_url, tmp_img)
                imagen_a_clip(tmp_img, clip_final, index=idx)
                tmp_img.unlink(missing_ok=True)
                ok(f"     → clip IA generado: {clip_name}")
                meta["footage"][clip_name]["estado"] = "pendiente"
                resultados = [r for r in resultados if r["clip"] != clip_name]
                resultados.append({"clip": clip_name, "fuente": "ia", "ok": True})
            except Exception as e:
                err(f"     → IA falló: {e}")
                meta["footage"][clip_name]["estado"] = "faltante"
            guardar_metadata(carpeta, meta)
            time.sleep(2)

    # Resumen final
    guardar_metadata(carpeta, meta)

    ok_count   = len([r for r in resultados if r["ok"]])
    fail_count = len([r for r in resultados if not r["ok"]])

    print(f"\n{'='*60}")
    print(f"  RESUMEN FOOTAGE")
    print(f"{'='*60}")
    pexels_n  = len([r for r in resultados if r["fuente"] == "pexels"])
    pixabay_n = len([r for r in resultados if r["fuente"] == "pixabay"])
    ia_n      = len([r for r in resultados if r["fuente"] == "ia" and r["ok"]])
    faltantes = len([r for r in resultados if not r["ok"]])
    print(f"  Pexels:   {pexels_n} clips")
    print(f"  Pixabay:  {pixabay_n} clips")
    print(f"  IA:       {ia_n} clips")
    print(f"  Faltantes:{faltantes} clips")
    print(f"  TOTAL:    {ok_count}/{len(resultados)} clips listos")
    print(f"\n  Estado en metadata.json: PENDIENTE DE APROBACIÓN")
    print(f"  → Abrí el dashboard (python3 dashboard.py) para aprobar clip por clip")
    print(f"{'='*60}\n")

    if faltantes > 0:
        print(f"  {AMARILLO}⚠ {faltantes} clips faltantes — el render puede quedar con huecos{RESET}")
        print(f"  → Agregá manualmente en footage/ o conseguí más keys\n")


if __name__ == "__main__":
    main()
