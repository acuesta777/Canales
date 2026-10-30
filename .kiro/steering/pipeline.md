---
inclusion: auto
---

# Reglas del pipeline de producción de videos

## Pack de subida — SIEMPRE hacer las dos cosas:

1. **Mostrar el pack completo en el chat** (título, descripción con timestamps, tags, prompt miniatura)
2. **Crear el archivo `<personaje>/<personaje>_pack.txt`** con todo el contenido del pack

El archivo `_pack.txt` debe incluir:
- Ficha técnica del video (archivo, duración, tamaño, clips, imágenes, chars guion)
- Título
- Descripción completa con timestamps
- Tags
- Prompt miniatura

Nunca entregar el pack solo en el chat sin crear el archivo. Nunca crear solo el archivo sin mostrarlo en el chat. Las dos cosas siempre, sin excepción.

---

## Pipeline fútbol — Mix de material visual

**CLIPS** → solo del MP4 descargado (videos de 5s del video de referencia)

**IMÁGENES** → todo lo demás, todas convertidas a MP4 con zoom/pan (Ken Burns) ANTES del render:
- Frames extraídos del video → `frames_extraidos/` (script: `/tmp/extract_frames.py`)
- Imágenes web de Brave → `imagenes_web/` (script: `buscar_imagenes.py`)
- Imágenes IA generadas → `imagenes/` (script: `imagen_clips.py`)
- Conversión a MP4: `/tmp/animar_web.py <carpeta/>`

**Carpetas del personaje fútbol:**
```
futbol/<personaje>/
  clips/              ← clips 5s del video descargado
  frames_extraidos/   ← frames JPG+MP4 rescatados de clips
  imagenes_web/       ← imágenes reales Brave JPG+MP4
  imagenes/           ← imágenes IA JPG+MP4
  <personaje>.txt / .mp3 / .srt
  <personaje>_prompts.csv   ← 4 imágenes IA en timestamps fijos
  <personaje>_sync.csv      ← imágenes sincronizadas con guion (ver abajo)
  <personaje>_final.mp4
  <personaje>_pack.txt
```

---

## Sincronización imagen-guion (OBLIGATORIO — NUNCA omitir)

**El problema recurrente:** imágenes que no coinciden con lo que se narra, imágenes repetidas.

### Flujo obligatorio:

1. **Leer el SRT** (primeros 10 min tienen timestamps exactos)
2. **Inventariar material visual:** describir qué muestra cada imagen disponible
3. **Match imagen-guion:** para cada ~20s del guion, elegir la imagen que mejor encaja
4. **Generar `<personaje>_sync.csv`** con timestamps y paths — cada imagen aparece UNA sola vez
5. **Sin repeticiones:** render.py detecta duplicados en sync CSV y los omite automáticamente
6. **Pool de relleno:** imágenes NO usadas en sync + frames_extraidos — también sin repetir (pool finito, no loop)

### Formato sync CSV:
```csv
seg_inicio,fuente,archivo,descripcion
00:00:00,imagenes_web,1.jpg,Adriano Inter Milan accion
00:00:16,imagenes,1.jpg,IA apartamento Milan Navidad
...
```

### Regla de oro: cada imagen = 1 sola aparición en todo el video. Sin excepciones.

---

## render.py — Arquitectura actual

Ubicación: `/Users/anyelocuesta/Downloads/Canales/render.py`

**Tipos de segmentos en el timeline:**
- `clip` — clip del video de referencia (shuffled_cycle, puede repetir)
- `sync` — imagen del `_sync.csv`, en timestamp exacto, path absoluta
- `img` — imagen IA del `_prompts.csv`, en timestamp exacto, índice
- `web` — imagen del pool de relleno (pool FINITO, sin repetir)

**Funciones clave:**
- `load_sync(char_folder)` → lee `*_sync.csv`, retorna `(lista, set_usadas)`, detecta duplicados
- `load_web_pool(char_folder, sync_used)` → carga `imagenes_web/*.mp4` + `frames_extraidos/*.mp4` excluyendo las ya en sync, mezcla aleatoria, lista finita
- `build_timeline(audio_dur, clip_durs, inserts, web_pool, sync_inserts)` → usa `iter()` sobre el pool, nunca repite

**⚠️ PROBLEMA PENDIENTE (julio 2026):**
El video de Adriano sigue mostrando imágenes repetidas visualmente aunque el código usa pool finito. La causa probable es que `frames_extraidos/` contiene frames del MISMO video de referencia que los clips — así que visualmente se ve "repetido" aunque técnicamente sean archivos distintos. Los frames extraídos son del video del canal de referencia (otro canal de YouTube), no de material original de Adriano.

**Solución pendiente:**
- Conseguir más imágenes REALES y VARIADAS de Adriano (no del video de referencia)
- Fuentes: Getty Images vía Brave, ESPN, Goal.com, Wikipedia Commons, diez.hn galería
- O usar solo imágenes web + IA como relleno y descartar los frames del video de referencia para el relleno visual

---

## Estado del proyecto Adriano (julio 2026)

**Carpeta:** `/Users/anyelocuesta/Downloads/Canales/futbol/adriano/`
**Video final:** `adriano_final.mp4` — 138 MB, 17.2 min
**Guion:** `adriano.txt` — 16,081 chars
**Pack:** `adriano_pack.txt`

**Sync CSV:** 13 imágenes sincronizadas con momentos del guion
**Pool relleno:** 263 imágenes (18 web + 245 frames) — pero los 245 frames son del video de referencia del otro canal → visualmente parecen repetidas
**Problema sin resolver:** el video visualmente sigue pareciendo repetitivo

---

## Scripts disponibles en /Users/anyelocuesta/Downloads/Canales/

| Script | Uso |
|---|---|
| `tts_single.py <carpeta>` | Genera MP3 desde TXT via AI33 |
| `srt_single.py <carpeta>` | Genera SRT desde MP3 via AssemblyAI |
| `clips.py <url> <carpeta>` | Descarga video YouTube → corta clips 5s |
| `buscar_imagenes.py <carpeta> --queries ...` | Descarga imágenes Brave Search |
| `imagen_clips.py <carpeta>` | Genera imágenes IA con flux-schnell |
| `animar_clips.py <carpeta>` | Ken Burns zoom/pan sobre imagenes/ |
| `render.py <carpeta>` | Renderiza video final |
| `verificar_render.py <carpeta>` | Verifica duración y clips de imagen |
| `/tmp/animar_web.py <carpeta/>` | Ken Burns sobre cualquier carpeta de imágenes |
| `/tmp/extract_frames.py <carpeta>` | Extrae frames centrales de clips a frames_extraidos/ |

## Credenciales
- AI33: `~/.ai33_key` y `~/.ai33_voice_id`
- AssemblyAI: `~/.assemblyai_key`
- Brave Search: `~/.brave_key`
- Telegram: `~/.telegram_token` y `~/.telegram_chat_id`
