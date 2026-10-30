---
name: pipeline
description: Produce un video completo para canal de lujo o fútbol. Pasos: guion → TTS → SRT → timeline → Flow/harvester → dashboard → render → subida. Invocar con /pipeline.
---

# Pipeline de Producción — Canales YouTube

---

## 🚀 ARRANCAR NUEVO VIDEO DESDE CELULAR

**Trigger:** cuando el usuario dé un nombre de personaje sin pegar URL (ej: "Carlos Slim", "Bad Bunny", "Shakira").

### Paso A — Buscar el personaje en los dos canales de referencia

Buscar ese nombre en estos dos canales usando el browser:

- `https://www.youtube.com/@LosHechosOcultos/videos`
- `https://www.youtube.com/@RiquezayFama/videos`

Para cada canal: buscar si existe un video sobre ese personaje (título que contenga el nombre). Obtener la URL del video y su thumbnail.

### Paso B — Mostrar miniaturas al usuario

Mostrar un widget con los resultados encontrados:
- Si se encontró en uno o ambos canales: mostrar miniatura + título + canal
- Si no se encontró en ninguno: decirlo y pedir URL directamente

Usar `mcp__visualize__show_widget` con las miniaturas encontradas.

### Paso C — Esperar que el usuario confirme cuál usar como referencia

El usuario dice "ese" / "el de RiquezayFama" / "el otro" o da un número.

### Paso D — Arrancar el pipeline con ese video como referencia

- Usar la URL del video elegido
- Continuar con el flujo normal desde **PASO 1** usando esa URL

---

## LO PRIMERO QUE DEBES HACER
Antes de cualquier otra cosa, leer estos archivos en este orden:
1. `/Users/anyelocuesta/Downloads/Canales/riqueza.md` — manual editorial obligatorio para el guion
2. Si el usuario pegó una URL, **abrirla y leerla** antes de buscar o escribir (evita confundir personas con mismo nombre)
3. Si es canal de fútbol, también leer: `/Users/anyelocuesta/Downloads/Canales/futbol/futbol.md` (prevalece sobre riqueza.md en conflictos)

No escribas ni una sola línea del guion sin haber leído esos archivos primero.

---

## Directorio base
`/Users/anyelocuesta/Downloads/Canales/`

## Claves API
- Muapi: `~/.muapi_key`
- Pexels: `~/.pexels_key`
- Pixabay: `~/.pixabay_key`
- Brave: `~/.brave_key`
- Google CSE key: `~/.google_cse_key` (opcional — 100 búsquedas gratis/día)
- Google CSE cx: `~/.google_cse_cx` (opcional)
- Wikimedia Commons: sin key — siempre disponible gratis
- YouTube OAuth: `_jsonytapi/tokens/<Canal>.pickle`
- YouTube credentials: `_jsonytapi/<Canal>.json`

## Canales configurados
Antes de subir, SIEMPRE listar los canales disponibles y preguntar al usuario cuál usar:
```bash
ls _jsonytapi/*.json | grep -v token | grep -v pickle
```
Mostrar la lista numerada y pedir que elija. **NUNCA asumir canal por defecto.**

## Estructura de carpetas
```
Canales/
├── riqueza.md                        # Manual editorial — LEER SIEMPRE PRIMERO
├── riqueza/<personaje>/              # Canal de lujo
│   ├── <personaje>.txt               # Guion
│   ├── <personaje>.mp3               # Audio TTS
│   ├── <personaje>.srt               # Subtítulos
│   ├── <personaje>_prompts.csv       # Prompts de imagen
│   ├── <personaje>_final.mp4         # Video final
│   ├── clips/                        # Clips YouTube descargados
│   ├── 03-imagenes/                  # Clips de footage (harvester_timeline)
│   ├── 05-montaje/timeline.json      # Timeline de inserts 0-5 min
│   ├── miniatura_1.jpg               # Miniaturas generadas
│   ├── miniatura_2.jpg
│   ├── miniatura_3.jpg
│   ├── upload_pack.json              # Pack de subida YouTube
│   ├── upload_info.json              # ID y fecha subida
│   └── metadata.json                 # Estado del pipeline (leído por dashboard)
├── futbol/<personaje>/               # Canal de fútbol (misma estructura)
├── referencias/<personaje>.jpg       # Foto de referencia para miniatura
├── jsonytapi/<Canal>.json            # Credenciales OAuth YouTube
├── jsonytapi/tokens/<Canal>.pickle   # Token guardado — NUNCA borrar
├── logs/                             # Logs de todos los procesos
├── config/riqueza.json               # Config harvester: source_order, clip_secs, etc.
├── config/futbol.json
└── dashboard.py                      # Panel web → http://localhost:5001
```

---

## PASO 1 — Clips de referencia
```bash
bash run_timeout.sh 900 clips python3 clips.py "<youtube_url>" <nicho>/<personaje>/
```
- SIEMPRE usar `/opt/homebrew/bin/yt-dlp`
- Descarga y corta en clips 5s en `<nicho>/<personaje>/clips/`
- Log: `logs/clips_<personaje>.log`

### ⚠️ ANTI-CONTENT ID — SHUFFLE EN EL CORTE
clips.py hace shuffle inmediato dentro de `cut_clips()` justo después de ffmpeg:
- ffmpeg genera `__seg_%06d.mp4` (patrón temporal, un guion)
- Shuffle Fisher-Yates + derangement → renombra a `__seg__%06d.mp4` (doble guion, orden aleatorio)
- trim y rename posteriores trabajan sobre los ya shuffleados
- Al final, segundo shuffle en `shuffle_clips()` → doble mezcla total

**Aunque el proceso muera por timeout después del corte, los clips ya están en orden aleatorio.**

Al crear `metadata.json` manualmente:
- `deleted_yt_clips` y `rejected_yt_clips` → SIEMPRE `{}` (dict), NUNCA `[]` (lista)
- `clips_order` → OMITIR para que el dashboard haga shuffle; si se pone con `sorted()` queda secuencial → Content ID strike

## PASO 2 — Guion

### ⛔ REGLA DURA — SELECCIÓN DE ARCO NARRATIVO ANTES DE ESCRIBIR UNA SOLA LÍNEA

**NUNCA empezar el guion sin que el usuario haya elegido el arco narrativo.**

Antes de escribir el guion, desplegar SIEMPRE esta lista numerada y esperar que el usuario responda con el número:

```
¿Qué arco narrativo usamos para <personaje>?

1. Arco Riqueza — pobreza → ascenso → cima (11 bloques, 24,500–25,500 chars)
2. Arco "La Mujer Que Controló la Versión" — 8 beats, imagen icónica → poder real (27,000–30,000 chars)
3. Arco "Porque Vive Así" — por qué un famoso eligió esta vida (9 bloques, 24,500–25,500 chars)
4. Arco "Detrás de Cámaras" — secretos del elenco de una producción icónica (series/, 20,000–22,000 chars)

Escribe el número y avanzo:
```

- **Arco 1** → leer `riqueza.md` y seguir su estructura
- **Arco 2** → leer `riqueza/arco_narrativo_2.md` y seguir su estructura
- **Arco 3** → leer `riqueza/arco_narrativo_pva.md` y seguir su estructura
- **Arco 4** → leer `series/arco_narrativo_3.md` y seguir su estructura — carpeta `series/<produccion>/`, script `generar_timeline_arco3.py`

**Solo cuando el usuario responda con un número → leer el archivo del arco elegido y continuar.**
No proponer arco por defecto ni continuar sin respuesta.

---

### Reglas según el arco elegido

**Si el usuario eligió Arco 1 o Arco 2:**
- Seguir al pie de la letra `riqueza.md` (ya leído)
- Riqueza/Farándula: 24,500–25,500 chars — medir con `wc -m` antes de continuar
- Fútbol: ~16,000 chars
- Título fijo: `"Así fue/es la lujosa vida de X — [tríada extraída del guion]"` máx 100 chars
- Buscar en internet datos reales del personaje antes de escribir
- Guardar en `<nicho>/<personaje>/<personaje>.txt`

**Si el usuario eligió Arco 3 ("Porque Vive Así"):**
- ⛔ NO usar el título "Así es/fue la lujosa vida de X" — usar formato PVA del archivo del arco
- ⛔ NO correr `validador_guion.py` en el PASO 3 — saltarlo completamente
- Longitud: 24,500–25,500 chars — medir con `wc -m`
- Seguir EXACTAMENTE los 9 bloques de `riqueza/arco_narrativo_pva.md` (ya leído)
- Anotar subtipo en línea 1: `[SUBTIPO PVA: A/B/C/D/E]`
- Buscar en internet datos reales del personaje antes de escribir
- Guardar en `<nicho>/<personaje>/<personaje>.txt`

**Si el usuario eligió Arco 4 ("Detrás de Cámaras"):**
- ⛔ NO usar el título "Así es/fue la lujosa vida de X" — usar formato del arco (ver `series/arco_narrativo_3.md`)
- ⛔ NO correr `validador_guion.py` — saltarlo completamente
- Longitud: 20,000–22,000 chars — medir con `wc -m`
- Seguir EXACTAMENTE la estructura de `series/arco_narrativo_3.md` (ya leído)
- Carpeta: `series/<produccion>/` (NO en riqueza/)
- Script de timeline: `generar_timeline_arco3.py series/<produccion>/`
- Buscar en internet datos reales de la producción antes de escribir
- Guardar en `series/<produccion>/<produccion>.txt`

## PASO 3 — Validar guion
⛔ **Si el arco elegido fue Arco 3 (PVA) o Arco 4 (Detrás de Cámaras) → SALTARSE ESTE PASO COMPLETAMENTE. Ir directo al PASO 4.**

```bash
python3 validador_guion.py <nicho>/<personaje>/
```
Verifica arco de riqueza en primeros 10 min. OBLIGATORIO antes de TTS para Arco 1 y Arco 2.
- Si falla: corregir y volver a validar hasta APROBADO

## PASO 4 — TTS
```bash
bash run_timeout.sh 300 tts python3 tts_single.py <nicho>/<personaje>/
```
- Log: `logs/tts_<personaje>.log`

## PASO 5 — SRT
```bash
bash run_timeout.sh 360 srt python3 srt_single.py <nicho>/<personaje>/
```
- Corta MP3 a 10 min antes de subir a AssemblyAI
- Log: `logs/srt_<personaje>.log`

## PASO 6 — Timeline de footage (0–5 min)
```bash
python3 generar_timeline_riqueza.py <nicho>/<personaje>/
# Para fútbol:
python3 generar_timeline_futbol.py <nicho>/<personaje>/
```
- Genera `05-montaje/timeline.json` con 7-15 inserts específicos en timestamps exactos

### ⚠️ VERIFICACIÓN OBLIGATORIA DESPUÉS DE GENERAR — ANTES DE PASAR AL PASO 7

**REGLA CRÍTICA: el prompt de cada segmento debe ilustrar EXACTAMENTE lo que dice el audio en ese segundo. NUNCA contrastes, NUNCA lujo cuando el audio habla de pobreza.**

Correr este check completo contra el SRT:
```python
python3 -c "
import re, json
from pathlib import Path
srt = Path('<nicho>/<personaje>/<personaje>.srt').read_text()
blocks = re.split(r'\n\n+', srt.strip())
entries = []
for b in blocks:
    lines = b.strip().split('\n')
    if len(lines) < 2: continue
    m = re.match(r'(\d+:\d+:\d+[,\.]\d+)\s*-->\s*(\d+:\d+:\d+[,\.]\d+)', lines[1] if len(lines)>1 else '')
    if not m: continue
    def to_sec(t):
        t = t.replace(',','.')
        h,mi,s = t.split(':')
        return int(h)*3600+int(mi)*60+float(s)
    entries.append((to_sec(m.group(1)), to_sec(m.group(2)), ' '.join(lines[2:])))
tl = json.load(open('<nicho>/<personaje>/05-montaje/timeline.json'))
for seg in tl['visual_timeline']:
    ss, se = seg['start_seconds'], seg['end_seconds']
    audio = ' '.join(e[2] for e in entries if e[1] > ss and e[0] < se)
    mins = int(ss//60); secs = int(ss%60)
    print(f\"SEG {seg['segment_id']:02d} [{mins}:{secs:02d}] AUDIO: {audio[:100]}\")
    print(f\"  PROMPT: {seg['ia_prompt'][:100]}\")
    print()
"
```

Revisar TODOS los segmentos. Si algún prompt no coincide con el audio → corregir `ia_prompt` Y `scene_description_es` del mismo segmento en el JSON ANTES de continuar.

Ejemplos de errores a detectar:
- Audio: "cortaba caña de azúcar" → prompt con hacienda lujosa ❌
- Audio: "durmió en autos ajenos" → prompt con interior lujoso de auto ❌
- Audio: "llegó sin dinero a la capital" → prompt con mansión ❌
- Audio: "sus padres eran..." → prompt con mansión colonial ❌

**Cuando corriges un prompt:** actualizar SIEMPRE los dos campos: `ia_prompt` Y `scene_description_es`.

### ⛔ REGLA DURA — LANZAR TIMELINE APROBACIÓN INMEDIATAMENTE DESPUÉS DE VALIDAR

**Una vez que el check de prompts pasa (todos coinciden con el audio), lanzar el UI de aprobación del timeline SIN PARAR, SIN preguntar, SIN esperar confirmación del usuario.**

```bash
# Matar instancias viejas si existen
lsof -ti:5099,5100,5101,5102,5103,5104,5105 | xargs kill -9 2>/dev/null; sleep 1
# Lanzar UI de aprobación — timeline_approval.py es librería, NO script directo
PYTHONUNBUFFERED=1 python3 -c "
import json, sys, socket
sys.path.insert(0, '.')
from timeline_approval import run_approval

def find_free_port(start=5099):
    for p in range(start, start+50):
        try:
            s = socket.socket(); s.bind(('', p)); s.close(); return p
        except: pass
    return start

carpeta = '<nicho>/<personaje>'
tl = json.load(open(f'{carpeta}/05-montaje/timeline.json'))
segments = tl['visual_timeline']
port = find_free_port(5099)
print(f'Puerto: {port}', flush=True)
print(f'URL: http://localhost:{port}/', flush=True)
approved, fuente = run_approval(segments, '<Personaje>', carpeta=carpeta, port=port)
print(f'Aprobados: {len(approved)}, fuente: {fuente}')
" > logs/timeline_approval_<personaje>.log 2>&1 &
```

⚠️ **La URL correcta es siempre `http://localhost:<puerto>/` — NUNCA incluir `/timeline/...` en la ruta, esa ruta NO existe en Flask.**

Leer el puerto del log: `grep "Puerto:" logs/timeline_approval_<personaje>.log`
Mostrar al usuario: `http://localhost:<puerto>/` (donde `<puerto>` es el valor del log, típicamente 5099+)

**NUNCA lanzar el harvester antes de que el usuario apruebe el timeline en la UI.**
**El harvester se lanza DESPUÉS de que el usuario da OK en la UI de aprobación.**

### ⛔ REGLA DURA — FLUJO CELULAR: SALTAR UI DE APROBACIÓN → PREGUNTAR MUAPI

**Cuando el video fue iniciado desde celular** (usuario dio nombre sin URL):

1. Generar el timeline y validar prompts normalmente (igual que desktop)
2. **NO lanzar la UI de aprobación del timeline** — el usuario no puede abrirla desde el celular
3. En cambio, preguntar directamente en el chat:

> ¿Deseas enviar los segmentos a generar con muapi?

**Si dice SÍ → ejecutar este flujo completo:**

```bash
# Paso A: lanzar harvester con --source ia (muapi, modelo barato)
python3 harvester_timeline.py <nicho>/<personaje>/ --canal <nicho> --source ia
```
- Esperar que termine (procesa TODOS los segmentos del timeline)
- Log: `logs/harvester_<personaje>.log`
- Al terminar verificar N/N clips generados:
  ```bash
  python3 -c "
  import json; from pathlib import Path
  tl = json.load(open('<nicho>/<personaje>/05-montaje/timeline.json'))
  img_dir = Path('<nicho>/<personaje>/03-imagenes')
  found = sum(1 for s in tl['visual_timeline'] if (img_dir/f\"flow_{s['segment_id']:04d}_zp.mp4\").exists())
  print(f'{found}/{len(tl[\"visual_timeline\"])} clips encontrados')
  "
  ```
- Si N/N → arrancar dashboard y mostrar URL ngrok al usuario
- Si no N/N → reportar cuáles faltan, relanzar solo los faltantes con `--desde <seg_id>`

```bash
# Paso B: arrancar dashboard (si no está corriendo)
pkill -f "python3 dashboard.py" 2>/dev/null; sleep 1
PYTHONUNBUFFERED=1 python3 dashboard.py > logs/dashboard.log 2>&1 &
sleep 2

# Paso C: lanzar ngrok y mostrar URL pública
pkill -f "ngrok http 5001" 2>/dev/null; sleep 1
ngrok http 5001 --log=stdout > /tmp/ngrok_dashboard.log 2>&1 &
sleep 4
NGROK_URL=$(grep -oE 'https://[a-z0-9-]+\.ngrok-free\.app' /tmp/ngrok_dashboard.log | head -1)
echo "📱 Dashboard mobile: ${NGROK_URL}/aprobar/<nicho>/<personaje>/"
```

Mostrar al usuario la URL ngrok. El `/aprobar/` detecta celular y redirige a `/mobile/` automáticamente.

**Si dice NO:** continuar con el flujo normal de Flow (PASO 7 estándar — esperar ZIP del usuario).

**Si el usuario pegó URL desde el inicio → flujo normal: sí lanzar UI de aprobación del timeline.**

## PASO 7 — Footage con Google Flow (TODOS los canales usan Flow)

⚠️ **Este paso se lanza SOLO después de que el usuario aprobó el timeline en `http://localhost:<puerto>/`.**

### ⚠️ FIX OBLIGATORIO: ZIP con espacios en el nombre

Los ZIPs de veo-folder-1 siempre tienen espacios (`oct 18 - 16_54.zip`). El regex del guard falla con espacios y deja `03-imagenes/` vacío. **Siempre copiar el ZIP sin espacios antes de pasarlo:**

```bash
# 1. Copiar el ZIP más reciente sin espacios
cp "/Users/anyelocuesta/Downloads/veo-folder-1/oct DD - HH_MM.zip" /tmp/personaje_v1.zip

# 2. Poner la carpeta del personaje AL FINAL (el regex la extrae limpia así)
python3 harvester_timeline.py --canal <nicho> --zip /tmp/personaje_v1.zip <nicho>/<personaje>/
```

Si NO se pasa `--zip`, el harvester detecta el ZIP desde veo-folder-1 automáticamente — pero el path con espacios igual corrompe la extracción del guard. Siempre copiar.

```bash
# Comando sin --zip (el harvester busca el ZIP solo — igual copiar antes):
python3 harvester_timeline.py <nicho>/<personaje>/ --canal <nicho>
```

El harvester sube los prompts a Google Flow y descarga automáticamente los clips generados.

### ⚠️ REGLA CRÍTICA: NUNCA DOS HARVESTERS AL MISMO TIEMPO

Cuando hay múltiples videos en paralelo, **los harvesters DEBEN correr en SERIE**, nunca simultáneamente.

**Razón:** El harvester necesita tiempo exclusivo de generación en Flow. Si dos corren al mismo tiempo se mezclan las imágenes generadas y no se pueden mapear correctamente.

**Protocolo obligatorio para videos en paralelo:**
1. Correr harvester del VIDEO 1 → esperar que descargue todos los clips
2. Confirmar descarga completa del VIDEO 1
3. Solo entonces: correr harvester del VIDEO 2

**Si el harvester termina con "0 generadas":** el proceso de generación no completó. Revisar el log y relanzar.

**Para descarga manual de clips ya generados:**
```python
# yt-dlp → extraer JPEG → zoompan → guardar como flow_{:04d}_zp.mp4
```

### ⚠️ REGLAS CRÍTICAS DE FLOW — LEER ANTES DE TOCAR CUALQUIER CÓDIGO

**Flow genera IMÁGENES ESTÁTICAS (modo Imagegen), NO videos.**
El archivo descargado es siempre 1 frame JPEG en contenedor mp4 (duración: 0.04s).
El harvester extrae el JPEG y lo convierte a zoompan con la duración exacta del segmento.

**Descarga:** SIEMPRE con `/opt/homebrew/bin/yt-dlp --cookies-from-browser brave`. NUNCA curl.
Las URLs `labs.google/fx/api/trpc/media.getMediaUrlRedirect` requieren sesión autenticada.

**Nombre de archivo:** `flow_{seg_id:04d}_zp.mp4` (4 dígitos zero-padded). NUNCA 3 dígitos.

**Zoompan OBLIGATORIO — usar siempre `zoompan_clip.py`:**
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from zoompan_clip import make_zoompan

make_zoompan(Path(jpg_path), Path(out_mp4), dur, index=seg_id)
```
⚠️ NUNCA escribir el comando ffmpeg zoompan inline en ningún script.
⚠️ NUNCA usar `z` incremental (`1+0.15*(on/N)`) — produce zoom 1.0→1.15 imperceptible, se ve como foto estática.
La fórmula correcta es `z=1.5` fijo con pan rotativo a 1920x1080 — está en `zoompan_clip.py`.
Cualquier script nuevo de generación de imágenes (proveedor IA, scraper, etc.) DEBE importar `make_zoompan` desde el primer momento.

Usar `seg.get('ia_prompt') or seg.get('prompt_or_query', '')`.
La clave correcta en el timeline es `ia_prompt`, no `prompt_or_query`.

**NUNCA correr `imagen_clips.py` ni `prompts_single.py`** — eliminados del pipeline. El timeline genera todos los prompts visuales (autos, mansiones, dinero, etc.).

**render.py lee el config** `_config/<nicho>.json` → `harvester.default_source`:
- `"flow"` → busca `flow_{:04d}_zp.mp4` primero
- `"higgsfield"` → busca `hf_{:04d}_zp.mp4` primero
- Todos los canales tienen `"default_source": "flow"` actualmente

**render.py sync block:** los clips de Flow se convierten a ref_fps con `strip_and_trim`.
El fps filter preserva el zoompan (confirmado). Si hay "moov atom not found" en el mp4 final,
es porque hay clips con fps distinto mezclados en el concat — verificar que strip_and_trim se aplica.

### Verificación OBLIGATORIA antes del render
```bash
python3 -c "
import json; from pathlib import Path
tl = json.load(open('<nicho>/<personaje>/05-montaje/timeline.json'))
img_dir = Path('<nicho>/<personaje>/03-imagenes')
found = sum(1 for s in tl['visual_timeline'] if (img_dir/f\"flow_{s['segment_id']:04d}_zp.mp4\").exists())
print(f'{found}/{len(tl[\"visual_timeline\"])} clips encontrados')
"
```
Si no es N/N → no lanzar render.

## PASO 8 — Dashboard de aprobación ⚠️ OBLIGATORIO
**NUNCA saltarse este paso.**

Cuando termina el harvester (PASO 7), arrancar el dashboard si no está corriendo:
```bash
pkill -f "python3 dashboard.py"; sleep 1
PYTHONUNBUFFERED=1 python3 dashboard.py > logs/dashboard.log 2>&1 &
```

### ⛔ REGLA DURA — LEVANTAR NGROK SIEMPRE AL ARRANCAR EL DASHBOARD

Inmediatamente después de lanzar el dashboard, levantar ngrok y mostrar la URL pública:

```bash
# Matar ngrok viejo si existe
pkill -f "ngrok http 5001" 2>/dev/null; sleep 1
# Lanzar ngrok en background
ngrok http 5001 --log=stdout > /tmp/ngrok_dashboard.log 2>&1 &
sleep 3
# Extraer URL pública
NGROK_URL=$(grep -o 'https://[a-z0-9-]*\.ngrok-free\.dev\|https://[a-z0-9-]*\.ngrok-free\.app' /tmp/ngrok_dashboard.log | head -1)
echo "URL pública: $NGROK_URL"
```

Mostrar al usuario **las dos URLs**:
- Local: `http://localhost:5001/aprobar/<nicho>/<personaje>/`
- **Celular (ngrok): `$NGROK_URL/aprobar/<nicho>/<personaje>/`** ← esta es la que se abre desde el gym

### Diseño del dashboard unificado
- **Un solo grid** con Flow (borde morado) y YT (borde naranja) en orden de render intercalados
- **Número `#N` en cada card** — visible en la esquina superior izquierda para identificar al rechazar
- **Paginación de 80** — con botón "Mostrar más" para el resto (evita que Flask se atasque con 300+ preloads)
- `preload="metadata"` — el video carga al pasar el mouse

### Flujo de rechazo — SIEMPRE quirúrgico (nunca recargar el grid completo)
**Flow clips (morado):**
  - NO hay botón "✓ Aprobar" individual — la aprobación es SOLO global con "✓ Aprobar todos"
  - ✗ Rechazar → confirmación "¿Seguro quieres rechazar este clip de Flow?" → si confirma, busca clip YT disponible y lo pone en ese slot
  - El reemplazo se registra en `metadata.json["flow_replaced_by_yt"]`
  - NUNCA va a Flow ni espera generación para reemplazar un clip rechazado — usar clip YT disponible directamente

**YT clips (naranja):**
  1. ✗ Rechazar y reemplazar → busca reemplazo entre clips NO visibles en el grid actual:
     ```js
     const visiblesEnGrid = new Set(
       Array.from(document.querySelectorAll('#unified-timeline [id^="ytrow-"]'))
            .map(el => el.id.replace('ytrow-', ''))
     );
     ```
     ⚠️ Buscar en VISIBLES DEL GRID, no en `_timelineSegments` (todos ya están usados en el timeline)
  2. Reemplaza solo el video/nombre/botón de esa card — el resto del grid no cambia
  3. Guarda en `metadata.json["rejected_yt_clips"]` — render.py los excluye automáticamente

### Aprobar todos
- Botón "✓ Aprobar todos" → llama `/api/footage_approve_all/` → actualiza solo cards Flow visualmente
- **NUNCA llama `cargar()`** — evita re-shuffle de YT que cambia los clips mostrados
- Solo actualiza stats en background con `fetch(/api/footage/).then(renderStats)`

### Estado visual al cargar
- Flow `estado="aprobado"` → muestra "✓ Aprobado" en verde (sin botones Aprobar/Rechazar)
- Flow `estado="pendiente"` → muestra botones

- **NO continuar al render hasta que `/api/footage/<personaje>` devuelva `stats.pendiente == 0`**

### Cómo descargar clips rechazados individualmente
```python
# 1. Identificar cuáles fueron rechazados:
#    python3 -c "import json; m=json.load(open('<nicho>/<per>/metadata.json')); [print(k) for k,v in m['footage'].items() if v.get('estado')=='rechazado']"
# 2. Identificar segment_id del nombre del archivo (flow_0013_zp.mp4 → seg 13)
# 3. Obtener Video_URL de la fila con status=completed
# 4. Descargar con yt-dlp --cookies-from-browser brave
# 5. Extraer frame con ffmpeg → aplicar zoompan con duración del segmento
# 6. Actualizar metadata: estado=pendiente
```

## PASO 9 — Verificación de clips antes del render ⚠️ OBLIGATORIO
```bash
python3 -c "
import json; from pathlib import Path
tl = json.load(open('<nicho>/<personaje>/05-montaje/timeline.json'))
img_dir = Path('<nicho>/<personaje>/03-imagenes')
found = sum(1 for s in tl['visual_timeline'] if (img_dir/f\"flow_{s['segment_id']:04d}_zp.mp4\").exists())
print(f'{found}/{len(tl[\"visual_timeline\"])} clips encontrados por render.py')
"
```
Si no es N/N → los clips no van a aparecer en el video. No lanzar render hasta que sea N/N.

## PASO 10 — Render
```bash
bash run_timeout.sh 3600 render python3 render.py <nicho>/<personaje>/
```
⛔ NUNCA usar `render_timeline.py` para riqueza o fútbol — ese script concatena segmentos seguidos sin timestamps, produce video roto. Solo aplica a Farandula/Secretos.
- Encoding: ultrafast+crf28+128k
- Anti-fingerprint: flip50%+speed±2%+zoom4% — SIN noise ni vignette
- **Orden clips:** `shuffled_cycle(n, ordered=True)` + `build_timeline(..., ordered=bool(_clips_order))` — propagar flag hasta el generador
- **Re-encode SIEMPRE:** todos los clips YT pasan por `apply_effects(clip, dst, flip, ref_fps, ref_w, ref_h)` — NUNCA concat directo. Sin esto los clips a 25fps quedan congelados (timebase mismatch con referencia 30fps)
- **Clips rechazados:** leer AMBAS claves: `deleted_yt_clips` (borrados del dashboard) Y `rejected_yt_clips`
- **Clips reciclados:** van al final; anti-detect agresivo: hflip + vflip30% + hue±8° + gblur + speed±4% + crop asimétrico
- Los clips de footage (timeline.json) se insertan en segundos exactos
- El resto del video usa clips de YouTube en el orden del dashboard
- Salida: `<nicho>/<personaje>/<personaje>_final.mp4`

### Copy a iCloud — MANUAL, después de aprobados
Cuando el usuario confirme que los clips están aprobados, Claude dispara:
```bash
curl -s -X POST http://localhost:5001/api/riq/copy_to_icloud/<nicho>/<personaje>
```
- Si iCloud tiene ≥ clips locales → omite
- Si iCloud tiene < clips locales → borra carpeta y copia todos los nuevos
- Si no existe → crea y copia
**NUNCA automático al cargar la página — esperar confirmación del usuario.**

## PASO 11 — Verificar render
```bash
python3 verificar_render.py <nicho>/<personaje>/
python3 validar_orden_render.py <nicho>/<personaje>/
```
- `verificar_render.py` — verifica nb_frames, duración y peso del archivo
- `validar_orden_render.py` — compara el orden de clips del render contra el aprobado en el dashboard (`clips_order` en metadata.json). ✅ si coinciden, ❌ con posición exacta si hay diferencia.

### ⚠️ BUG SISTÉMICO: `-shortest` corta ~3.5s de audio en riqueza/fútbol

`render.py` acumula ~9ms de error de timebase por segmento. Con ~377 segs → ~3.4s de déficit de video → `-shortest` corta la narración antes de que termine (se pierde el CTA).

**Detectar:** `verificar_render.py` reporta `Δ=Xs`. Si Δ > 1.5s → aplicar fix.

**Fix post-render cuando Δ > 1.5s:**
```bash
# 1. Re-encodear un clip como "tail" con timebase fijo (CRÍTICO: -video_track_timescale 11988)
ffmpeg -y -stream_loop -1 -i <nicho>/<personaje>/clips/ULTIMO.mp4 \
  -t DEFICIT -vf "hflip,hue=h=15,scale=640:360" \
  -r 30000/1001 -video_track_timescale 11988 \
  -c:v libx264 -preset ultrafast -crf 28 -an tail.mp4

# 2. Strip audio del final.mp4
ffmpeg -y -i <personaje>_final.mp4 -an -c:v copy vonly.mp4

# 3. Concat video + tail
printf "file 'vonly.mp4'\nfile 'tail.mp4'" > concat_tail.txt
ffmpeg -y -f concat -safe 0 -i concat_tail.txt -c copy vfull.mp4

# 4. Remux con audio completo
ffmpeg -y -i vfull.mp4 -i <personaje>.mp3 \
  -map 0:v -map 1:a -c:v copy -c:a aac -b:a 128k \
  -t AUDIO_DUR <personaje>_final.mp4
```
⚠️ Sin `-video_track_timescale 11988` en paso 1, el concat produce duración corrupta (~4482s).

## PASO 12 — Pack de subida

⚠️ **ANTES de escribir el título, verificar si el personaje está vivo o muerto:**
- **Vivo → "Así es la lujosa vida de X"**
- **Muerto → "Así fue la lujosa vida de X"**
Buscar en el guion o en internet. Si hay duda, usar "es".

Crear `<nicho>/<personaje>/upload_pack.json`:
```json
{
  "titulo": "Así es/fue la lujosa vida de X — subtítulo",
  "descripcion": "...",
  "tags": ["tag1", "tag2"],
  "timestamps": ["0:00 — Intro", "..."],
  "prompt_miniatura": "...",
  "ficha_tecnica": {}
}
```

## PASO 13 — Miniaturas ⚠️ NO BLOQUEA LA SUBIDA

**El usuario hace las miniaturas manual en YouTube Studio. NUNCA esperar la miniatura para subir.**

- Saltar este paso completamente y continuar al PASO 14 → PASO 15
- Si el usuario pide miniatura explícitamente, generarla DESPUÉS de subir o en paralelo
- No preguntar por miniatura antes de subir

## PASO 14 — metadata.json
Crear/actualizar `<nicho>/<personaje>/metadata.json`:
```json
{
  "titulo": "...",
  "descripcion": "...",
  "tags": [],
  "estado": "pendiente",
  "youtube_id": null,
  "youtube_url": null,
  "fecha_generacion": "YYYY-MM-DD",
  "fecha_subida": null,
  "canal": "NombreCanal",
  "personaje": "<personaje>",
  "nicho": "<nicho>",
  "privacidad": "private",
  "miniaturas": {"miniatura_1": "pendiente", "miniatura_2": "pendiente", "miniatura_3": "pendiente"},
  "pipeline": {
    "titulo": "completado", "guion": "completado", "audio": "completado",
    "subtitulos": "completado", "imagenes": "completado", "video": "completado",
    "miniaturas": "completado", "youtube": "pendiente"
  }
}
```

## PASO 15 — Subir a YouTube
```bash
# 1. Listar canales disponibles:
ls _jsonytapi/*.json | grep -v token | grep -v pickle
# 2. Mostrar lista numerada al usuario y esperar que elija
# 3. Subir (pasar SOLO el nombre del archivo, sin ruta — el script agrega _jsonytapi/ solo):
python3 youtube_upload.py <nicho>/<personaje>/ --headless --canal <Canal>.json --privacidad private
```
- `containsSyntheticMedia: True` activado automáticamente
- Token guardado en `_jsonytapi/tokens/<Canal>.pickle` — NUNCA borrar
- Después de subir: actualizar metadata.json con youtube_id, youtube_url, fecha_subida, estado=subido
- La miniatura se sube manual desde YouTube Studio — no esperar

---

## Dashboard visual
```bash
# SIEMPRE matar instancias viejas antes de arrancar:
pkill -f "python3 dashboard.py"; sleep 1
PYTHONUNBUFFERED=1 python3 dashboard.py > logs/dashboard.log 2>&1 &
```
- Aprobación de footage: `http://localhost:5001/aprobar/<nicho>/<personaje>/`
- Rechazo de clip: textarea editable solo tras clic en ✗ Rechazar
- NO hay rerun automático — el usuario genera desde la extensión VEO y avisa
- Auto-refresh cada 30 segundos

---

## Reglas críticas

### Guion
- ⛔ SIEMPRE preguntar el arco narrativo (lista 1–7) y esperar número ANTES de escribir el guion
- SIEMPRE leer `riqueza.md` antes de escribir el guion
- SIEMPRE abrir URLs de referencia antes de buscar o escribir
- NUNCA lanzar TTS sin validar longitud del guion con `validador_guion.py`

### Flow — reglas no negociables
- Flow genera IMÁGENES ESTÁTICAS (1 JPEG en mp4 de 0.04s) — NUNCA videos
- Descargar SIEMPRE con `yt-dlp --cookies-from-browser brave` — nunca curl
- Nombre: `flow_{seg_id:04d}_zp.mp4` — 4 dígitos siempre
- Zoompan: SIEMPRE `from zoompan_clip import make_zoompan` — NUNCA ffmpeg inline ni `z` incremental
- Image Prompt de Flow: clave `ia_prompt`, NO `prompt_or_query`
- `imagen_clips.py` y `prompts_single.py` están eliminados del pipeline — no correrlos
- render.py lee `_config/<nicho>.json` para saber el prefijo del clip — no hardcodear

### Dashboard ⚠️ OBLIGATORIO
- SIEMPRE matar dashboard viejo con `pkill -f "python3 dashboard.py"` antes de arrancar uno nuevo
- Después del harvester → SIEMPRE mostrar `http://localhost:5001/aprobar/<nicho>/<personaje>/`
- NO renderizar hasta que todos los clips estén aprobados
- Rechazo = marcar slot como rechazado → buscar clip YT de reemplazo
- Descarga de rechazados: por segment_id → yt-dlp → zoompan → metadata pendiente

### Subida
- NUNCA esperar la miniatura para subir — subir siempre al terminar render
- Pasar SOLO el nombre del archivo JSON al `--canal` (sin ruta, el script agrega `_jsonytapi/`)
- SIEMPRE `--privacidad private`
- SIEMPRE preguntar el canal antes de subir
- NUNCA borrar archivos `.pickle` de tokens OAuth

### General
- SIEMPRE usar `/opt/homebrew/bin/yt-dlp`
- SIEMPRE crear/actualizar `metadata.json`
- Pipeline 100% automático — monitorear cada proceso y lanzar el siguiente en cuanto termina
- Pausas obligatorias: (1) aprobar footage en dashboard, (2) elegir canal — el timeline NO requiere aprobación
- Si un proceso falla, leer el log con `grep -E "ERROR|Traceback|error" logs/<log>.log`
- Timeouts: clips 900s · TTS 300s · SRT 360s · imágenes 900s · render 3600s
- Formato run_timeout.sh: `bash run_timeout.sh <segundos> <etiqueta> <comando...>`

---

## Configurar canal nuevo (OAuth) — solo lo hace el usuario
1. console.cloud.google.com con el Gmail del canal nuevo
2. Crear proyecto → Activar YouTube Data API v3
3. Credenciales → OAuth 2.0 → Desktop app → descargar JSON
4. Pantalla de consentimiento: External + Test user = Gmail del canal
5. Guardar JSON en `jsonytapi/<NombreCanal>.json`
6. Primera subida: Claude captura la URL con `script -q` y se la envía al usuario
7. Usuario abre URL en Chrome con el Gmail del canal y autoriza
8. Token se guarda automáticamente en `jsonytapi/tokens/<NombreCanal>.pickle`
