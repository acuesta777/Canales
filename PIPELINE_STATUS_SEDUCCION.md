# PIPELINE STATUS — Canales YouTube
> Exportado: 2026-07-31 | Cuenta: anyelo.cuestas@oxaam.com

---

## 1. ESTRUCTURA DE CANALES

| Canal | Nicho | OAuth JSON | Estado |
|---|---|---|---|
| **CaxandoFamosos** | Lujo / biografías (riqueza) | `jsonytapi/CaxandoFamosos.json` | ✅ Activo |
| **Canal1FotosImpresionantes** | Lujo / biografías (riqueza) | `jsonytapi/Canal1FotosImpresionantes.json` | ✅ Activo |
| **CanalSeduccion** | Seducción / atracción masculina | `jsonytapi/CanalSeduccion.json` | ⚙️ OAuth configurado, sin videos |
| Farandula | Farándula | — | ⚠️ Carpeta existe, sin OAuth |

### Tokens OAuth
`jsonytapi/tokens/` — tokens de sesión generados por `youtube_upload.py` al autenticar.

---

## 2. SCRIPTS DEL PIPELINE — FUNCIÓN Y ESTADO

### Scripts principales (en `~/Downloads/Canales/`)

| Script | Función | Comando tipo |
|---|---|---|
| `tts_single.py` | TTS con AI33 (fallback AI84). Genera MP3 del guion. | `python3 tts_single.py riqueza/personaje/` |
| `srt_single.py` | Genera .SRT (subtítulos) desde el MP3 | `python3 srt_single.py riqueza/personaje/` |
| `prompts_single.py` | Genera CSV de prompts de imagen a partir de los primeros 10 min del SRT | `python3 prompts_single.py riqueza/personaje/` |
| `imagen_clips.py` | Genera imágenes con muapi.ai (flux-schnell) y las anima con zoompan | `python3 imagen_clips.py riqueza/personaje/` |
| `animar_clips.py` | Versión manual: anima imágenes ya generadas | `python3 animar_clips.py riqueza/personaje/` |
| `higgsfield_clips.py` | Genera clips de video con Higgsfield (automático) | `python3 higgsfield_clips.py riqueza/personaje/` |
| `clips.py` | Descarga clips de YouTube con yt-dlp | `/opt/homebrew/bin/yt-dlp ...` via clips.py |
| `render.py` | Renderiza el video final (ffmpeg). Concatena clips + audio + anti-fingerprint | `python3 render.py riqueza/personaje/` |
| `render_backup.py` | Versión de backup del render (sin modificaciones recientes) | — |
| `miniatura.py` | Genera 3 variantes de miniatura con Wan 2.6 Image Edit + Pillow | `python3 miniatura.py riqueza/personaje/` |
| `youtube_upload.py` | Sube video a YouTube via OAuth. SIEMPRE preguntar canal antes de ejecutar | `python3 youtube_upload.py riqueza/personaje/ CaxandoFamosos` |
| `dashboard.py` | Panel web de control en `http://localhost:5001` | `python3 dashboard.py` |
| `validador_guion.py` | Valida arco de riqueza en primeros 10 min del guion antes de TTS | `python3 validador_guion.py riqueza/personaje/` |
| `validador_prompts.py` | Valida el CSV de prompts antes de generar imágenes | `python3 validador_prompts.py riqueza/personaje/` |
| `validar_guion_futbol.py` | Validador específico para guiones del canal de fútbol | — |
| `validar_srt.py` | Verifica que el SRT esté bien formado | — |
| `validar_txt_pretts.py` | Verifica el TXT antes de enviarlo a TTS | — |
| `verificar_render.py` | Verifica el render final (duración, audio, resolución) | — |
| `generar_timeline.py` | Genera timeline.json para montaje | — |
| `generar_sync.py` | Sincroniza clips con el audio | — |
| `run_timeout.sh` | Wrapper de timeout. SIEMPRE usar con TTS/SRT/clips/render | `./run_timeout.sh "etiqueta" 300 python3 tts_single.py ...` |
| `buscar_imagenes.py` | Búsqueda de imágenes candidatas | — |
| `timing.py` | Mide tiempos del pipeline | — |
| `face_sort_clips.py` | Ordena clips por detección de rostro | — |
| `revisar_clips.py` | Revisión manual de clips descargados | — |
| `contact_sheets_futbol.py` | Hojas de contacto de clips para canal fútbol | — |
| `get_title.py` | Extrae título de video YouTube | — |
| `gen_paisaje.py` | Genera imágenes de paisaje / background | — |
| `tts_ai84.py` | TTS directo con AI84 (sin fallback) | — |

---

## 3. ESTADO DE VIDEOS POR NICHO

### Canal Riqueza (`~/Downloads/Canales/riqueza/`)

| Personaje | Render | Subido | Canal | URL | Pack Subida |
|---|---|---|---|---|---|
| agnetha_faltskog | ✅ 725 MB | ⏳ NO | — | — | ⏳ pendiente |
| alejandro_fernandez | ✅ 962 MB | ✅ SÍ | Canal1FotosImpresionantes | https://youtu.be/CXlMzf3V5pk | ✅ |
| chuck_norris | ✅ 552 MB | ⏳ NO | — | — | ⏳ pendiente |
| el_puma | ✅ 810 MB | ⏳ NO | — | — | ⏳ pendiente |
| maribel_guardia | ✅ 850 MB | ⏳ NO | — | — | `maribel_guardia_pack_subida.txt` ✅ |
| victoria_ruffo | ✅ 778 MB | ✅ SÍ | CaxandoFamosos | https://youtu.be/jhqL1t0RzUw | ✅ |
| xuxa | ✅ 181 MB | ✅ SÍ | CaxandoFamosos | https://youtu.be/aDXkvt9oG0U | ✅ |

**Videos riqueza pendientes de subir: agnetha_faltskog, chuck_norris, el_puma, maribel_guardia**

### Canal Fútbol (`~/Downloads/Canales/futbol/`)

| Personaje | Render | Subido | Pack Subida |
|---|---|---|---|
| ariel_ortega | ✅ 145 MB | ⏳ NO | `ariel_ortega_pack_subida.txt` ✅ |
| lamine_yamal | ✅ 829 MB | ⏳ NO | `lamine_yamal_pack_subida.txt` ✅ |
| pablo_aimar | ✅ 140 MB | ⏳ NO | `pablo_aimar_pack_subida.txt` ✅ |

**Todos los videos de fútbol tienen pack de subida listo — pendiente definir canal de YouTube para fútbol.**

### Canal Seducción (`~/Downloads/Canales/seduccion/`) — NUEVO
- Carpeta por crear en producción
- Canal Enigma Estoica — OAuth en `jsonytapi/CanalSeduccion.json`
- Skill instalada: `~/.claude/skills/enigma-estoica/SKILL.md`
- **Sin videos producidos aún**

---

## 4. CONFIGURACIONES IMPORTANTES

### APIs en uso

| Servicio | Para qué | Dónde está la key |
|---|---|---|
| **AI33** (TTS primario) | Text-to-Speech del guion | Hardcoded en `tts_single.py` — buscar `AI33` |
| **AI84** (TTS fallback) | Fallback si AI33 falla | `tts_ai84.py` y fallback en `tts_single.py` |
| **muapi.ai / flux-schnell** | Imágenes IA ($0.003/img, 1024x576) | Hardcoded en `imagen_clips.py` — buscar `muapi` |
| **Higgsfield** | Clips de video animados con IA | `higgsfield_clips.py` |
| **YouTube OAuth** | Subida a YouTube | `jsonytapi/*.json` + tokens en `jsonytapi/tokens/` |
| **yt-dlp** | Descarga clips de YouTube | `/opt/homebrew/bin/yt-dlp` (Homebrew — NO usar el de Python 3.9, está desactualizado y falla con 403/SABR) |

### OAuth YouTube — Canales configurados

| Archivo JSON | Canal | Project ID |
|---|---|---|
| `jsonytapi/CaxandoFamosos.json` | CaxandoFamosos | youtube-canal-3 |
| `jsonytapi/Canal1FotosImpresionantes.json` | Canal1FotosImpresionantes | — |
| `jsonytapi/CanalSeduccion.json` | Enigma Estoica | youtube-canal-3 |

### Dashboard
- Puerto: **5001** (`http://localhost:5001`)
- Iniciar: `python3 dashboard.py`
- APIs expuestas: upload, regen, approve
- Botones: Subir + Regenerar + tiempo relativo
- Ruta Flask: `path:personaje` en rutas

---

## 5. PARÁMETROS TÉCNICOS DE RENDER

```bash
# Anti-fingerprint obligatorio
flip 50% + speed ±2% + zoom 4%
# Encoding
-c:v libx264 -preset ultrafast -crf 28
-c:a aac -b:a 128k
# SIN noise ni vignette
```

### Timeouts (usar SIEMPRE `run_timeout.sh`)

| Proceso | Límite |
|---|---|
| TTS | 300s |
| SRT / transcripción | 360s |
| Generación de clips | 900s |
| Render final | 3600s |

Verificar proceso a los 30s de lanzarlo revisando el log.

---

## 6. REGLAS DEL PIPELINE (no modificar)

### Canal Riqueza (riqueza.md)
- Leer `riqueza.md` ANTES de escribir el guion
- Guion: **24,500–25,500 caracteres** (medir con `wc -m`)
- NUNCA lanzar TTS sin verificar longitud
- Validar arco de riqueza (propiedad, autos, fortuna) en primeros 10 min antes de TTS
- Título fijo: `"Así fue/es la lujosa vida de X — subtríada"` (máx 100 chars)
- Velocidad TTS: ~900 chars/min → 27-28 min de video

### Canal Fútbol (futbol/futbol.md)
- Leer `riqueza.md` + `futbol/futbol.md` (futbol.md gana en conflictos)
- Guion: ~16,000 caracteres
- Título: fórmula paradoja (ver futbol.md)
- Clips: sin marca de agua

### Canal Seducción (enigma-estoica skill)
- Skill en `~/.claude/skills/enigma-estoica/SKILL.md`
- Guion: 2,250–3,000 palabras (15-20 min)
- Fórmula: listicle con 5-7 puntos
- Estética: Fuego Interior (naranja quemado + marrón oscuro + crema)
- Presupuesto IA: <$2 USD/video
- Personas reales → foto real, NUNCA IA
- NUNCA contenido explícito ni vulgar

---

## 7. ESTRUCTURA DE CARPETAS POR NICHO

```
~/Downloads/Canales/
├── riqueza/
│   └── <personaje>/
│       ├── <personaje>.txt          ← guion
│       ├── <personaje>.mp3          ← TTS
│       ├── <personaje>.srt          ← subtítulos
│       ├── <personaje>_prompts.csv  ← prompts de imagen
│       ├── <personaje>_final.mp4    ← render final
│       ├── clips/                   ← clips de b-roll
│       ├── imagenes/                ← imágenes generadas + animadas
│       ├── miniatura_1/2/3.jpg      ← variantes de miniatura
│       ├── metadata.json            ← título, descripción, tags
│       ├── upload_info.json         ← ID YouTube si fue subido
│       └── upload_pack.json         ← pack completo de subida
├── futbol/
│   ├── futbol.md                    ← manual del canal fútbol
│   └── <personaje>/                 ← misma estructura que riqueza
├── seduccion/                       ← NUEVO — a crear con primer video
│   └── <slug-video>/
│       ├── 00-research/
│       ├── 01-guion/
│       ├── 02-locucion/
│       ├── 03-imagenes/
│       ├── 04-video-ia/
│       ├── 05-montaje/
│       ├── 06-master/
│       └── 07-metadatos/
├── Farandula/
│   └── <personaje>/                 ← guiones en .txt por sección
├── jsonytapi/                       ← OAuth credentials
│   ├── CaxandoFamosos.json
│   ├── Canal1FotosImpresionantes.json
│   ├── CanalSeduccion.json
│   └── tokens/
├── logs/                            ← logs de cada proceso
├── referencias/                     ← fotos de referencia para miniaturas
├── riqueza.md                       ← manual completo canal riqueza
├── run_timeout.sh                   ← wrapper timeout OBLIGATORIO
└── [scripts Python del pipeline]
```

---

## 8. PENDIENTES

### Urgente
- [ ] Subir **agnetha_faltskog** a YouTube (render ✅ 725 MB)
- [ ] Subir **chuck_norris** a YouTube (render ✅ 552 MB)
- [ ] Subir **el_puma** a YouTube (render ✅ 810 MB) — tiene pack_subida.txt
- [ ] Subir **maribel_guardia** a YouTube (render ✅ 850 MB) — tiene pack_subida.txt
- [ ] Definir canal YouTube para fútbol y subir los 3 videos (ariel_ortega, lamine_yamal, pablo_aimar)

### Canal Seducción — primer video
- [ ] Crear carpeta `seduccion/` dentro de `~/Downloads/Canales/`
- [ ] Primer video de Enigma Estoica (skill lista, canal OAuth configurado)
- [ ] Probar flujo completo con presupuesto <$2

### Miniatura
- [ ] `miniatura.py` funciona — pendiente afinar prompts y compositing
- [ ] Retomar cuando el usuario lo indique

### Mejoras técnicas
- [ ] Catalogar videos ya publicados en `seduccion/catalogo.json` (anti-duplicados)
- [ ] `full-output-enforcement` skill — instalar si se truncan guiones largos

---

## 9. SKILLS INSTALADAS

Ubicación: `~/.claude/skills/`

| Skill | Trigger | Estado |
|---|---|---|
| `enigma-estoica` | "próximo video", "video de Enigma", tema de seducción | ✅ Instalada hoy (2026-07-31) |
| `pipeline` | `/pipeline` | ✅ En `.claude/commands/pipeline.md` |
| `skill-creator` | Crear skills nuevas | ✅ Disponible (Anthropic) |
| `docx` | Generar .docx | ✅ Disponible (Anthropic) |
| `dataviz` | Gráficos y visualizaciones | ✅ Disponible (Anthropic) |

---

## 10. DECISIONES TÉCNICAS RELEVANTES

| Decisión | Razón |
|---|---|
| yt-dlp de Homebrew (`/opt/homebrew/bin/yt-dlp`) | El de Python 3.9 está desactualizado y falla con 403/SABR |
| ultrafast+crf28+128k para render | Balance velocidad/calidad para volumen de producción |
| Anti-fingerprint (flip50%+speed±2%+zoom4%) | Evita detección duplicado por YouTube |
| SIN noise ni vignette | Decisión de calidad visual tomada y fijada |
| muapi.ai / flux-schnell para imágenes | $0.003/img, ~4s, calidad aprobada, 1024x576 |
| Dashboard en puerto 5001 | Puerto 5000 ocupado por otros servicios |
| Cortar SRT/prompts a 10 min | Optimización: primeros 10 min definen retención |
| Validar arco de riqueza ANTES de TTS | Evitar re-hacer TTS (costoso) si el guion no cumple |
| Personas reales → foto real siempre | Evitar desinformación y problemas de derechos |
| SIEMPRE preguntar canal antes de `youtube_upload.py` | Evitar subir al canal equivocado |
