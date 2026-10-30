# FARANDULA.MD — MANUAL COMPLETO DEL PROYECTO
## Canal de YouTube en Español sobre Famosos

---

## ÍNDICE

1. [Contexto del proyecto](#1-contexto-del-proyecto)
2. [Pregunta obligatoria antes de cada guion](#2-pregunta-obligatoria-antes-de-cada-guion)
3. [Versión larga — estructura completa](#3-versión-larga--estructura-completa)
4. [Versión corta — estructura completa](#4-versión-corta--estructura-completa)
5. [Estructura de archivos](#5-estructura-de-archivos)
6. [Dónde guardar los archivos](#6-dónde-guardar-los-archivos)
7. [Tono y contenido — reglas permanentes](#7-tono-y-contenido--reglas-permanentes)
8. [Hook — fórmula completa](#8-hook--fórmula-completa)
9. [Estructura de cada artista](#9-estructura-de-cada-artista)
10. [Estrategia de orden para retención](#10-estrategia-de-orden-para-retención)
11. [Suscripción — cuándo y cómo](#11-suscripción--cuándo-y-cómo)
12. [Cierre](#12-cierre)
13. [Prompts de imagen y video](#13-prompts-de-imagen-y-video)
14. [Cálculo de caracteres — proceso obligatorio](#14-cálculo-de-caracteres--proceso-obligatorio)
15. [Proceso completo de trabajo](#15-proceso-completo-de-trabajo)
16. [Fórmulas de títulos](#16-fórmulas-de-títulos)
17. [Competidor de referencia](#17-competidor-de-referencia)
18. [Registro de guiones producidos](#18-registro-de-guiones-producidos)
19. [Artistas ya utilizados por tema](#19-artistas-ya-utilizados-por-tema)

---

## 1. CONTEXTO DEL PROYECTO

Canal de YouTube en español sobre famosos mexicanos e internacionales. Objetivo: replicar y superar el estilo viral del competidor **"Estación Estelar"** (15K suscriptores).

El canal produce dos tipos de videos:
- **Videos de larga duración** sobre temas oscuros, polémicos o emotivos (enfermedades, drogas, pobreza, escándalos, muertes)
- **Videos de formato corto** sobre series y películas (cómo lucen los actores hoy, cambios de look, nuevos roles)

Las transcripciones de videos de competidores sirven como base para generar guiones propios con diferente orden, ángulos nuevos y más profundidad.

---

## 2. PREGUNTA OBLIGATORIA ANTES DE CADA GUION

**SIEMPRE** preguntar esto antes de arrancar:

> **¿Formato INDIVIDUAL o MULTI? ¿Versión larga o corta?**

Si el usuario pega una URL, identificar el formato desde el título (ver sección 17B) antes de preguntar.

Sin esta respuesta no se empieza nada.

---

## 3. VERSIÓN LARGA — ESTRUCTURA COMPLETA

### Rango de caracteres
| Elemento | Chars |
|---|---|
| **Total del guion** | 25,000 – 33,000 |
| **Hook mínimo** | 1,000 |
| **Cierre** | ~250–300 |
| **Por artista** | Se calcula dividiendo el resto entre el número de artistas |

### Temas para versión larga
- Actores con enfermedades graves (cáncer, Alzheimer, etc.)
- Destruidos por las drogas o el alcohol
- Famosos en la pobreza
- Muertes trágicas o inesperadas
- Escándalos no contados
- Caídas desde el éxito al anonimato
- Temas polémicos de identidad, orientación, género

### Fórmula de cálculo rápido
```
Chars por artista = (Total objetivo - Hook - Cierre) / Número de artistas

Ejemplo con 15 artistas:
(29,000 - 1,000 - 300) / 15 = ~1,847 chars por artista
```

---

## 4. VERSIÓN CORTA — ESTRUCTURA COMPLETA

### Rango de caracteres
| Elemento | Chars |
|---|---|
| **Total del guion** | 18,000 – 24,000 |
| **Hook mínimo** | 1,000 |
| **Por artista** | ~1,200–1,800 chars (no pasarse) |

### Temas para versión corta
- Cómo lucen hoy los actores de una serie o película específica
- Cambios de look radicales vinculados a nuevos proyectos
- Nuevos roles que nadie esperaba

### Estilo — NUNCA es un "antes y después" simple

Cada artista en la versión corta debe tener:
- **Contexto actual:** nuevo papel, nueva temporada, proyecto en desarrollo
- **Ángulo de curiosidad:** ¿el cambio físico está vinculado al personaje?
- **Guiño a teorías:** ¿camuflaje para la trama? ¿señal de algo que viene?
- **Conexión con lo que el fan ya sabe** y quiere descubrir

**Ejemplo correcto:**
> "Lee Jung-jae ahora luce así para su nuevo papel en Star Wars. ¿Podría esto afectar su agenda para grabar el final de Squid Game?"

**Ejemplo incorrecto:**
> "Así lucía Lee Jung-jae en 2010 y así luce hoy a sus 52 años."

---

## 5. ESTRUCTURA DE ARCHIVOS

Todos los guiones siguen exactamente esta estructura de archivos:

```
00_HOOK.txt              ← Hook completo + transición al primer artista integrada
01_NOMBRE ARTISTA.txt    ← Bloque del primer artista
02_NOMBRE ARTISTA.txt    ← Bloque del segundo artista
03_NOMBRE ARTISTA.txt
...
XX_CIERRE.txt            ← Cierre final
artistas.txt             ← Lista de todos los artistas, uno por línea, en orden
```

### Reglas de nomenclatura
- El hook y la transición van en el **mismo archivo** `00_HOOK.txt` — nunca separados
- Los artistas se numeran con dos dígitos: `01_`, `02_`, `03_`...
- El nombre del artista en el filename es en MAYÚSCULAS con tildes si corresponde
- Ejemplo: `05_EDITH GONZÁLEZ.txt`, `12_CHRISTIAN BACH.txt`

---

## 6. DÓNDE GUARDAR LOS ARCHIVOS

**Directorio de trabajo:** `/Users/anyelocuesta/Downloads/Canales/Farandula/NOMBRE_DEL_VIDEO/`

Cada video tiene su propia subcarpeta dentro de `/Users/anyelocuesta/Downloads/Canales/Farandula/`. Los TXT del guion van DIRECTAMENTE ahí, NO en ningún otro lugar.

**Ejemplo real:**
```
/Users/anyelocuesta/Downloads/Canales/Farandula/VIVIENDO DE FAVOR TELEVISA/
  00_HOOK.txt
  01_ROGELIO GUERRA.txt
  02_CARLOS VILLAGRAN.txt
  ...
  09_CIERRE.txt
  artistas.txt
```

**Crear la carpeta del video:**
```bash
mkdir -p "/Users/anyelocuesta/Downloads/Canales/Farandula/NOMBRE DEL VIDEO"
```

**Verificación de tamaño:**
```bash
CARPETA="/Users/anyelocuesta/Downloads/Canales/Farandula/NOMBRE DEL VIDEO"
total=0; for f in "$CARPETA"/*.txt; do c=$(wc -m < "$f"); total=$((total+c)); echo "$c $f"; done; echo "TOTAL: $total"
```

---

## 7. TONO Y CONTENIDO — REGLAS PERMANENTES

### La mentalidad correcta
Pensar como **el chisme que el espectador quiere saber** del artista sobre el tema que se está tratando.

### Lo que debe provocar cada artista
- ✅ *"Tengo que ver esto"*
- ✅ *"¿Cómo es posible que alguien que lo tuvo TODO terminara así?"*
- ✅ Contraste brutal entre la gloria y el abandono/caída
- ✅ Indignación, tristeza o shock genuino
- ✅ Sensación de estar descubriendo algo que la industria intentó esconder

### Lo que hay que evitar
- ❌ Narrar una biografía informativa en tono neutral
- ❌ Listar datos como si fuera un artículo de Wikipedia
- ❌ Contar la caída sin hacer sentir el peso emocional
- ❌ Explicaciones teóricas largas sin gancho emocional
- ❌ Bullet points en el guion (todo es prosa directa)

### Principios de contenido
| Correcto | Incorrecto |
|---|---|
| Priorizar momentos de "¡lo mantuvo oculto!" | Dar contexto histórico sin gancho |
| Contenido que se siente como información privilegiada | Resumen de la vida pública ya conocida |
| Datos sorprendentes y poco convencionales | Datos que cualquiera puede buscar en Wikipedia |
| Experiencia EMOCIONAL del espectador | Experiencia informativa del espectador |
| "¿Sabías que fue aceite de cocina lo que le inyectaron?" | "Lyn May sufrió daños estéticos irreversibles" |

---

## 8. HOOK — FÓRMULA COMPLETA

### Versión larga — mínimo 1,000 caracteres

El hook debe contener estos 4 elementos en orden:

**1. Escenario identificable**
El espectador debe poder verse reflejado en la situación de apertura. No empieces con datos. Empieza con una imagen o escenario que cualquiera pueda reconocer.

**2. Idea central contraintuitiva**
Algo que va en contra de lo que el espectador asume. La pregunta que hace que no pueda cerrar el video.

**3. Elemento de "conocimiento prohibido"**
La promesa de información que no está en los homenajes oficiales, que la industria prefiere que no se sepa, que no aparece en las biografías públicas.

**4. Llamado a suscripción**
Dentro del hook, no al final. Vinculado emocionalmente al tema.

**5. Anticipar la historia más impactante**
Mencionar que "la última historia de este video" tiene algo que el espectador no espera. Esto dispara la retención hasta el final.

### Versión corta — mínimo 1,000 caracteres

El hook de versión corta sigue la misma estructura pero adaptado al tema de serie/película:
- ¿Cuánto tiempo ha pasado desde que se estrenó?
- La pregunta que el fan se hace sobre qué fue de los actores
- Promesa de datos actuales que los canales de "antes y después" no cuentan
- Llamado a suscripción
- Anticipo del artista más sorprendente o misterioso de la lista

---

## 9. ESTRUCTURA DE CADA ARTISTA

### Arco narrativo obligatorio (versión larga)
```
Gloria → Grieta → Caída → Silencio → Consecuencia
```

Cada artista debe recorrer este arco aunque sea brevemente. No saltar directo a la caída sin establecer la gloria primero (aunque sea en 1-2 líneas).

### Arranque de cada artista
- Empezar directo con el **nombre del artista**
- Nunca con frases genéricas de transición
- El nombre es el gancho. Después viene el desarrollo.

### Cuerpo del artista
- El dato más impactante o desconocido va primero, no al final
- Cada párrafo debe terminar dejando ganas de leer el siguiente
- Los hechos concretos (nombres, fechas, cifras) tienen más impacto que las descripciones
- Evitar frases vacías como "una situación difícil" — nombrar exactamente qué pasó

### Final de cada artista — 2 elementos obligatorios

**1. Siembra del siguiente artista**
Una imagen mental específica que anticipa la siguiente historia. NUNCA genérica.

❌ Mal: *"Y el siguiente también tuvo problemas."*
✅ Bien: *"Y la siguiente también perdió todo, pero lo que ningún canal contó es que su asistente desapareció la noche que ocurrió."*

**2. Pregunta de interacción**
Una pregunta concreta dirigida a los comentarios. Idealmente relacionada con un dato específico del artista que se acaba de contar.

❌ Mal: *"¿Qué opinas de esta historia?"*
✅ Bien: *"¿Sabías que fue aceite de cocina lo que le inyectaron? Escríbelo en los comentarios."*

---

## 10. ESTRATEGIA DE ORDEN PARA RETENCIÓN

### Los 3 bloques

| Bloque | Posición | Qué poner |
|---|---|---|
| **Apertura** | Primeros 2–3 artistas | Nombres MÁS reconocibles. Enganchar desde el minuto 1 |
| **Bloque medio** | Artistas 4 hasta el penúltimo | Historias más emotivas, polémicas o con datos más oscuros |
| **Cierre** | Último artista | 1 nombre grande O la historia más impactante/inesperada |

### Regla del cierre
Guardar **UN** nombre grande o la historia más brutal para el final. El espectador que sabe que "falta alguien importante" no cierra el video. Esta anticipación se siembra en el hook.

### Por qué el bloque medio no lleva los nombres más grandes
El bloque medio es donde más espectadores abandonan. Por eso necesita las historias más emotivas y polémicas, no necesariamente los nombres más famosos. Los nombres famosos ya engancharon en la apertura. Ahora se retiene con impacto emocional.

---

## 11. SUSCRIPCIÓN — CUÁNDO Y CÓMO

### Regla: estratégica, no repetitiva

| Cuándo | Cómo |
|---|---|
| **Siempre en el hook** | Integrada, no al final del hook como frase separada |
| **1–2 veces en el bloque medio** | Intercalada entre artistas, no al final de cada uno |
| **En el artista de cierre** | Como parte del llamado a compartir |

### Fórmula de la suscripción con emoción
```
Sentimiento hacia el artista + Identidad del fan + Acción de suscripción
```

**Ejemplos:**
- *"Si eres fan de verdad de X, ya sabes lo que tienes que hacer."*
- *"Si esta historia te llegó de verdad, suscríbete al canal y compártela ahora porque estas historias necesitan llegar a más personas."*
- *"Suscríbete al canal antes de que empiece — aquí seguimos contando lo que la industria prefiere que no conozcas."*

**Lo que NUNCA hacer:**
- Pedir suscripción al final de cada artista (se vuelve mecánico y el espectador lo ignora)
- Usar la misma fórmula dos veces en el mismo video

---

## 12. CIERRE

### Reglas
- Máximo 2–3 líneas
- Reflexión ultracorta con golpe emocional
- Invitación al siguiente video
- Corte limpio — sin despedidas largas

### Fórmula
```
[Resumen del tema en 1 línea devastadora] + [Invitación al siguiente video]
```

**Ejemplos aprobados:**
- *"Diecisiete historias. Una misma industria que llenó taquillas durante décadas sin construir ningún sistema para proteger a quienes las llenaron. El espectáculo continuó. Ellos pagaron el precio. El siguiente video ya está esperándote. Dale play ahora."*
- *"Quince batallas que ocurrieron mientras el mundo las veía actuar, reír y triunfar en pantalla. El siguiente video ya está listo. Dale play ahora."*

---

## 13. ARTISTAS.TXT — LISTA DE ARTISTAS

Archivo de texto con los nombres de todos los artistas del guion, uno por línea, en el orden final aprobado.

```
ELENA MERLINN
COLINA
CHINO MIRANDA
...
```

---

## 14. CÁLCULO DE CARACTERES — PROCESO OBLIGATORIO

### Antes de empezar a escribir

1. Definir el total objetivo dentro del rango
2. Restar hook y cierre
3. Dividir entre el número de artistas
4. Respetar ese límite por artista durante la escritura

```
Fórmula:
Chars por artista = (Total objetivo - 1,000 hook - 300 cierre) / N artistas
```

### Verificación final con bash

```bash
total=0
for f in /mnt/user-data/outputs/0*.txt /mnt/user-data/outputs/[0-9]*.txt; do
  chars=$(wc -c < "$f")
  total=$((total + chars))
  printf "%6d | %s\n" $chars "$(basename "$f")"
done
printf "TOTAL: %d chars\n" $total
```

### Si el total está fuera de rango

**Bajo el mínimo:** Expandir los artistas más cortos añadiendo:
- Un párrafo adicional con contexto o dato nuevo
- Una consecuencia o efecto que no se mencionó
- Una pregunta de interacción más desarrollada

**Sobre el máximo:** Recortar los artistas más largos eliminando:
- Párrafos de contexto que no aportan emoción
- Repetición de ideas ya establecidas
- Descripciones que se pueden comprimir en una línea

---

## 15. PROCESO COMPLETO DE TRABAJO

### Paso 1 — Recibir la transcripción
El usuario pega la transcripción del video competidor. Se analiza para extraer todos los artistas con desarrollo propio en el guion.

### Paso 2 — Preguntar versión
Antes de cualquier otra acción: **¿versión larga o versión corta?**

### Paso 3 — Proponer la lista

**PRIMERO QUE TODO — antes de proponer artistas:**

1. Correr `verificar_icloud.py` con los artistas propuestos
2. Si el nombre artístico no coincide exactamente con la carpeta, alertar:
   > ⚠️ "Lalo España" → carpeta encontrada: "Eduardo EspañA" — ¿es ese?
3. Solo usar artistas donde la carpeta sea confirmada o el match sea inequívoco
4. Mostrar tabla con clips disponibles por artista SIEMPRE

```bash
python3 Farandula/verificar_icloud.py "Artista 1" "Artista 2" ...
```

**Tabla obligatoria antes de cualquier propuesta:**
```
| # | Artista        | Carpeta iCloud         | Clips |
|---|----------------|------------------------|-------|
| 1 | Nombre real    | Nombre carpeta         |  297  |
```

- Proponer orden optimizado por retención (más conocido/impactante primero)
- Para videos MULTI: order DIFERENTE al video competidor (no copiar su secuencia)
- **Esperar aprobación** antes de escribir el guion

Si el usuario pide segunda o tercera lista → proponer **3 opciones (A, B, C)** con lógica diferente y esperar que elija.

### Paso 3.5 — Pre-verificación iCloud (reglas críticas)

⚠️ **REGLAS DE MATCHING — nunca asumir, siempre verificar:**
- Nombre artístico ≠ nombre real → carpeta puede estar bajo el nombre real
- Si match parcial: mostrar qué carpeta encontró y preguntar "¿es ese?"
- Buscar también en `iCloud/yt/` con el apellido como keyword
- Falsos positivos comunes: "Lalo España" → "Eduardo EspañA" ✅, "Arturo Manrique" → "Arturo de Córdova" ❌

**Script verificar_icloud.py ya avisa** cuando el nombre de carpeta difiere del query.

---

### Paso 4.5 — Fotos → clips (DESPUÉS del TTS, ANTES del dashboard)

Este paso se ejecuta una vez que el TTS está listo y se conoce la duración de cada segmento.

**Fórmula de clips necesarios:**
```python
slots    = ceil(duracion_segmento / 7.5)
objetivo = slots + 3 + max(5, ceil(slots * 0.5))  # 30-50% extra para rechazos
```

**⚠️ NUNCA calcular cuántas hacen falta SIN tener el audio TTS** — no hay forma de saberlo antes.

**Para artistas con fotos pero sin clips MP4:**
1. Convertir TODAS las fotos existentes con `fotos_a_clips.py` — no calcular cuántas, convertir todas
2. Después del TTS: calcular `objetivo` con la fórmula y ver si hay déficit
3. Si déficit → buscar más fotos con Brave y convertir también
4. **Siempre tener MÁS del objetivo** — el usuario rechazará clips y necesita reemplazos
5. **Borrar imágenes originales** después de confirmar que los `_zp.mp4` se generaron correctamente

```bash
python3 Farandula/fotos_a_clips.py "Nombre Artista"
# Convierte todas las fotos → img_001_zp.mp4, img_002_zp.mp4 ...
# Borra imágenes originales automáticamente al confirmar éxito
```

### Paso 4 — Calcular caracteres
Hacer el cálculo antes de escribir la primera línea.

### Paso 5 — Crear carpeta del video
```bash
mkdir -p "/Users/anyelocuesta/Downloads/Canales/Farandula/NOMBRE DEL VIDEO"
```
Los TXT van ahí directamente. NO usar /tmp ni /mnt ni ninguna otra ruta.

### Paso 6 — Generar los archivos
En orden:
1. `00_HOOK.txt`
2. Artistas en orden numerado
3. `XX_CIERRE.txt`
4. `artistas.txt`

### Paso 7 — Verificar el total
Loop de `wc -c` sobre todos los archivos. Si está fuera de rango, ajustar antes de presentar.

### Paso 8 — Presentar los archivos
Usar `present_files` con todos los archivos en orden. Mostrar la tabla de verificación final.

---

## 16. FÓRMULAS DE TÍTULOS

### Versión larga — títulos que funcionan

**Fórmula 1: Número + tema + consecuencia impactante**
```
[N] Famosos que [acción] y [consecuencia que nadie esperaba]
```
- *15 Actrices de Telenovelas que Murieron de Cáncer y Quizás Nunca lo Supiste*
- *20 Famosos del Cine de Ficheras que lo Tuvieron Todo y Terminaron Sin Nada*
- *75 Famosos que Pasaron del Éxito a la Pobreza Total*

**Fórmula 2: El secreto oculto**
```
La verdad que nadie contó sobre [tema]
Lo que [industria/canal/medio] no quiere que sepas de [artistas]
```

**Fórmula 3: Contraste brutal**
```
[Artistas famosos] que [logro en la cima] y hoy [situación contraria]
```
- *Estrellas de Telemundo que Ganaban Millones y Desaparecieron Sin Explicación*

**Fórmula 4: La pregunta que el fan se hace**
```
¿Qué pasó con [artistas/serie/película]? La historia real que nadie contó
```

### Versión corta — títulos que funcionan

**Fórmula base:**
```
Así lucen hoy los actores de [Serie/Película] en [año actual]
```
- *Así Lucen Hoy los Actores de Karate Kid 2010 en 2026*

**Con ángulo de curiosidad:**
```
[N] años después: Así lucen y qué hacen hoy los actores de [Serie/Película]
```

**Con dato sorprendente:**
```
El actor de [personaje] en [Serie] ahora luce así — y lo que hace hoy te va a sorprender
```

### Reglas para todos los títulos
- Siempre en español
- Números en dígitos, no en palabras (15, no quince)
- Mayúscula en cada palabra relevante
- No usar signos de interrogación en exceso — uno máximo por título
- El año actual en títulos de "así lucen hoy" — ayuda al SEO

---

## 17. COMPETIDOR DE REFERENCIA

**Canal de referencia:** FAMIX (@FAMIX2.0) — 14.9K suscriptores, 72 videos.
Canal sobre famosos mexicanos/latinos: ascensos, caídas, fortunas perdidas, olvido.

### Análisis de los 5 videos más vistos (agosto 2026)

| # | Título | Vistas | Formato |
|---|--------|--------|---------|
| 1 | MIRA LO QUE TE ESCONDEN SOBRE LA CASA DEL ACTOR EN MÉXICO | 1M | MULTI-TEMA |
| 2 | ¿RECUERDAS A LA CHUPITOS? NOS HIZO REÍR A TODOS Y LO PERDIÓ CASI TODO | 743K | INDIVIDUAL |
| 3 | ¿RECUERDAS A CONSUELO DUVAL? ABANDONÓ LA FAMILIA P. LUCHE... | 525K | INDIVIDUAL |
| 4 | LA CASA DEL ACTOR EN MÉXICO: NADIE IMAGINA LO QUE REALMENTE PASA AHÍ | 470K | MULTI-TEMA |
| 5 | ¿RECUERDAS A LUIS DE ALBA? TRAS PERDER CASI TODO... ASÍ VIVE HOY | 294K | INDIVIDUAL |

---

## 17B. DOS FORMATOS DEL CANAL — CÓMO IDENTIFICARLOS Y ESCRIBIRLOS

### Cómo identificar el formato desde el título del video de referencia

| Señal en el título | Formato |
|---|---|
| "¿RECUERDAS A [NOMBRE]?" | INDIVIDUAL |
| "¿QUÉ FUE DE [NOMBRE]?" | INDIVIDUAL |
| "¿QUÉ PASÓ CON [NOMBRE]?" | INDIVIDUAL |
| "MIRA N [ARTISTAS] DE LOS AÑOS..." | MULTI |
| "N FAMOSOS QUE..." | MULTI |
| "N GALANES / VEDETTES / CANTANTES..." | MULTI |

---

### FORMATO A — INDIVIDUAL (un solo artista, 18–25 min)

**Trigger emocional del hook:**
- Pregunta directa al espectador: *"¿Te acuerdas de...?"*
- O imagen mental: *"Piensa en aquellas tardes de antes, la familia reunida..."*
- Luego: clip o frase icónica del personaje → nombrar al personaje → giro oscuro

**Arco narrativo — 7 actos:**

```
1. RECONOCIMIENTO (0:00–1:00)
   Hook nostalgia → el personaje en la memoria del espectador

2. ORIGEN (1:00–4:00)
   Infancia humilde, orígenes, primeras batallas — con detalles específicos

3. ASCENSO (4:00–8:00)
   Cómo llegó a la fama, momentos icónicos, la cima

4. GRIETA (8:00–13:00)
   El primer crack silencioso: problema oculto, traición, enfermedad, adicción

5. CAÍDA (13:00–17:00)
   El momento en que todo se rompe — con nombres, fechas, consecuencias concretas

6. PRESENTE (17:00–21:00)
   ¿Dónde y cómo vive hoy? La realidad actual sin romantizar

7. REFLEXIÓN/CIERRE (21:00–fin)
   Lección moral devastadora en 2–3 líneas. La paradoja entre el personaje y la persona.
```

**Fórmula de hook INDIVIDUAL (verificada en videos virales):**
```
[Imagen mental de familia/infancia] + [Sonido/frase icónica del personaje] +
[Nombre + logro cumbre] + [Giro: "pero lo que nadie te contó..."] +
[Anticipo de la revelación más oscura]
```

**Ejemplo del hook real de La Chupitos (743K):**
> "¿Te acuerdas de Chupitos? Seguro que sí. Y lo más bonito es que no reías tú solo, reía toda la familia al mismo tiempo. Aparecía esa mujer del cabello alborotado, los labios pintados de cualquier manera y esa botellita en la mano..."

**Ejemplo del hook real de Consuelo Duval (525K):**
> "Piensa un momento en aquellas tardes de antes, la familia reunida, la comida en la mesa, la tele prendida y de repente esa risa, esa peluca, esa voz que ya no se te olvida. Federica, la mamá loca de la familia Peluche..."

**Ángulo diferenciador — NUNCA copiar el mismo ángulo del competidor:**
- Competidor habla de la caída económica → Nosotros: el precio emocional detrás de la risa
- Competidor habla del escándalo público → Nosotros: lo que pasó en privado antes del escándalo
- Competidor habla del hoy → Nosotros: el momento bisagra que nadie notó cuando ocurrió

---

### FORMATO B — MULTI (N artistas, un tema común, 25–35 min)

**Trigger emocional del hook:**
- Pregunta filosófica sobre la fama y el tiempo
- Evoca arquetipos sin nombrar a nadie todavía (el galán de la novela, la villana, el cómico)
- Promesa: "hoy te vamos a mostrar N [artistas] que [tema]"
- Gancho de retención: "y el último de esta lista tiene una historia que nadie imaginó"

**Arco narrativo — estructura por artista (mini-arco de 3 actos):**

```
Por cada artista:
  1. NOMBRE + presentación de quién fue en su cima (2–3 líneas)
  2. EL SHOCK: qué pasó, cómo quedó, qué cambió (3–4 líneas)
  3. HOY: foto/estado actual + dato que nadie sabe (2 líneas)
  4. SIEMBRA: imagen específica que anticipa al siguiente
```

**Distribución de artistas (estrategia de retención):**
```
Posiciones 1–2: Nombres MÁS reconocibles → enganche inmediato
Posiciones 3 al penúltimo: Historias más oscuras o emotivas
Último: El más impactante O el nombre que prometiste en el hook
```

**Fórmula de hook MULTI (verificada en videos virales):**
```
[Pregunta filosófica sobre qué pasa cuando la fama se acaba] +
[Evocación de arquetipos que el espectador vivió] +
[El dato que nadie esperaba: "muchos terminaron..."] +
[Promesa: "hoy te vamos a mostrar N que..."] +
[Anticipo del último: "el número [N] tiene una historia que nadie imaginó"]
```

**Ejemplo del hook real de Casa del Actor (1M):**
> "¿Alguna vez te has preguntado qué pasa con un actor famoso cuando los reflectores se apagan? Cuando el teléfono deja de sonar, cuando los contratos desaparecen y el dinero que parecía infinito simplemente se acaba. En la televisión eran intocables. El galán de la novela de las 9. La villana que todo México odiaba, el cómico que te hacía llorar de risa después de la cena. Eran parte de tu casa, de tus noches, de tu vida sin que te dieras cuenta..."

---

### Cierre de FAMIX — patrón verificado

El cierre siempre contiene:
1. Una paradoja o contradicción entre el personaje público y la persona real
2. Una frase que deja pensando — no un resumen
3. CTA a suscripción integrado a la emoción del cierre

**Ejemplo real (La Chupitos):**
> "Y detrás del escenario siempre hubo un recadito silencioso, uno que vale mucho la pena escuchar: cuidado con el trago, tómalo con medida, porque nadie quiere terminar como termina la borrachita. Lo que parecía pura risa en el fondo también parecía..."

---

**Lo que se hace diferente en nuestros guiones:**
- Orden completamente diferente al de la transcripción original
- Ángulos nuevos — nunca el mismo ángulo que el competidor
- Más profundidad emocional y datos que el competidor no menciona
- Hook con mayor duración y trigger emocional más específico
- Sembra del siguiente artista más cinematográfica y específica

**Cuando hay segunda lista del mismo tema:**
El segundo guion debe tener no solo orden diferente sino **ángulos completamente distintos**. El espectador que vio el primero debe sentir que el segundo cuenta otra historia aunque sean los mismos nombres.

---

## 18. REGISTRO DE GUIONES PRODUCIDOS

| # | Tema | Versión | Artistas | Chars | Lista |
|---|---|---|---|---|---|
| 1 | Actrices mexicanas con enfermedades | Larga | 14 | ~29,000 | A |
| 2 | Actrices mexicanas con enfermedades | Larga | 14 | 29,109 | B |
| 3 | Estrellas de Telemundo que desaparecieron | Larga | 9 | 25,015 | v1 |
| 4 | Estrellas de Telemundo | Larga | 9 | 24,996 | A |
| 5 | Estrellas de Telemundo (expandida) | Larga | 9 | 30,042 | A |
| 6 | Hollywood LGBTQ | Larga | 10 | 26,057 | v1 |
| 7 | Hollywood LGBTQ | Larga | 10 | 26,857 | B |
| 8 | Actores mexicanos gays | Larga | 10 | 28,118 | v1 |
| 9 | Actores mexicanos gays | Larga | 10 | 27,317 | C |
| 10 | Destruidos por las drogas | Larga | 16 | 30,042 | v1 |
| 11 | Destruidos por las drogas | Larga | 16 | 33,405 | B |
| 12 | Cine de ficheras — pobreza | Larga | 17 | 32,150 | v1 |
| 13 | Cine de ficheras — pobreza | Larga | 17 | 31,626 | A |
| 14 | Mujeres que dicen son hombres | Larga | 11 | 25,057 | combinada |
| 15 | Famosos en la pobreza | Larga | 18 | 26,271 | v1 |
| 16 | Famosos en la pobreza | Larga | 18 | 31,626 | A |
| 17 | Karate Kid 2010 | **Corta** | 12 | 15,753 | aprobada |
| 18 | Actrices telenovelas murieron de cáncer | Larga | 15 | 26,892 | combinada |
| 19 | Actrices telenovelas muertes trágicas | Larga | 12 | 25,142 | combinada |

---

## 19. ARTISTAS YA UTILIZADOS POR TEMA

### Actrices con enfermedades / cáncer / muertes trágicas
Thalía, Alejandra Guzmán, Verónica Castro, Victoria Ruffo, Maribel Guardia, Lucía Méndez, Cynthia Clitbo, Andrea Legarreta, Litzy, Alicia Machado, Frida Sofía, Liliana Arriaga, Violeta Isfel, Pilar Montenegro, Edith González, Lorena Rojas, Christian Bach, Rebeca Jones, Verónica Tusán, Rosita Pelayo, Elena Rojo, Magda Guzmán, Irán Eory, Adamari López, Rebeca de Alba, Mónica Miguel, Renata del Castillo, Angélica Arenas, Jiromi Hayakawa, Irma Lozano, María Rubio, Margarita Isabel, Evangelina Elísondo, Mariana Levy, Carla Álvarez, Silvia Derbez, Lourdes de Shams, Renata Flores

### Estrellas de Telemundo
Fernando Colunga, Rafael Amaya, Lorena Rojas, Mario Cimarro, Gabi Espino, Sonya Smith, Marlene Fabela, Ailin Mujica, Jean Carlos Canela

### Hollywood LGBTQ
Caitlyn Jenner, Marlene Dietrich, Greta Garbo, James Dean, Caroline Cossey, April Ashley, Candy Darling, Christine Jorgensen, Pete Burns, Laverne Cox

### Actores mexicanos gays
Cristian Chávez, Sebastián Ligarde, David Cepeda, Eduardo España, Felipe Nájera, Alejandro Tomasi, Eleazar Gómez, Mauricio Mejía, Mauricio Martínez, Alan Estrada

### Destruidos por las drogas
Amy Winehouse, Heath Ledger, Whitney Houston, Kurt Cobain, Britney Spears, River Phoenix, Johnny Depp, Judy Garland, Charlie Sheen, Philip Seymour Hoffman, Lindsay Lohan, Marilyn Monroe, Jean-Claude Van Damme, Macaulay Culkin, Demi Lovato, Amanda Bynes

### Cine de ficheras — pobreza / abandono
Lyn May, Angélica Chain, Isela Vega, Sasha Montenegro, Alberto Rojas El Caballo, Abril Campillo, Pedro Weber Chatanuga, Alfonso Sayas, Sergio Ramos El Comanche, Lina Santos, Roberto Flaco Guzmán, Miguel Inclán, Tun Tun, Héctor Lechuga, Polo Polo, Lalo El Mimo, Jorge Labat

### Mujeres famosas que dicen son hombres
Michelle Obama, Lady Gaga, Lorena Herrera, Nicki Minaj, Ivy Queen, Lucha Villa, Caster Semenya, Ana Gabriela Guevara, Jamie Lee Curtis, Alaska, Vicky y Marisol Terrazas

### Famosos en la pobreza / caída económica
Isabel Pantoja, Laura Bozzo, Mario Cimarro, Chayanne, Araceli Arámbula, Carmen Campusano, Carlos Villagrán, Yadira Carrillo, Jorge Salinas, Niurka Marcos, Cynthia Clitbo, Carlos Peniche, Ingrid Coronado, Alfredo Adame, Laura Zapata, Marisol Santa Cruz, Carlos Bonavides, Sergio Goiri

### Karate Kid 2010 (versión corta)
Jackie Chan, Jaden Smith, Taraji P. Henson, Zhenwei Wang (Zhenwei Wang), Wenwen Han, Yu Rongguang, Wang Ji, Luke Carberry, Lü Shijia, Zhensu Wu, Zhiheng Wang, Tess Liu

---

## 13. PROMPTS DE IMAGEN Y VIDEO — HOOK

### Regla principal — contexto visual del video ⚠️

**SIEMPRE** enfocar los prompts del hook en el universo visual específico del tema. El espectador debe saber de qué trata el video solo mirando las imágenes, sin necesitar al narrador.

| Tema del video | Base visual obligatoria para los prompts |
|---|---|
| El Chavo del Ocho | La vecindad, el barril, puertas numeradas, set Televisa 1970s |
| Segunda Guerra Mundial | Blanco y negro, uniformes militares, trincheras, escombros |
| Narcos / cartel | Calles oscuras, maletines, ambiente clandestino, México o Colombia |
| Fútbol | Estadios, canchas, trofeos, multitudes en las gradas |
| Telenovelas | Sets de novela, vestuario de época, camerinos, luces de estudio |
| Pobreza / caída económica | Contraste lujo vs miseria usando el entorno del artista |
| Drogas | Ambientes nocturnos, escenas oscuras, contraste antes/después |
| Época antigua (antes 1940) | Fotografía B&W, sepia, texturas de época |

**Nunca:** wallets genéricos, contratos sin contexto, fotos abstractas que no identifiquen el tema. El 80% de los prompts del hook deben mostrar elementos reconocibles del universo visual del video.

---

## NOTAS FINALES

- **Grok permite nombres reales de artistas** en los prompts → siempre incluirlos
- La versión corta de Karate Kid quedó en **15,753 chars** (sobre el límite) — el usuario aprobó dejarlo así
- El hook de los guiones de "pobreza" puede ser más corto (~484–600 chars) y funciona — arrancar directo es parte del estilo para ese tema
- **Nunca usar bullet points dentro de los guiones** — todo es prosa directa
- Para segundas listas del mismo tema: cambiar no solo el orden sino los **ángulos** de cada artista completamente
- Antes de proponer artistas de transcripciones nuevas, verificar si ya fueron usados en guiones anteriores y preferir artistas frescos
- Cuando se combinan dos transcripciones del mismo tema, eliminar los artistas repetidos y construir la lista con los más impactantes de cada una

---

*Última actualización: Julio 2026*
