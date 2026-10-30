# Arco Narrativo PVA — "Porque Vive Así"

## Títulos que activan este arco
- "Por qué vive así [Personaje] después de ganarlo todo"
- "Cómo vive hoy [Personaje] con [X millones]"
- "Por qué [Personaje] eligió esta vida después de la fama"
- "El estilo de vida de [Personaje] que nadie esperaba"

## Cuándo usar este arco
- El personaje tuvo fama y/o fortuna notable (deportes, música, política, artes)
- Su estilo de vida ACTUAL contrasta con lo que el público esperaría dado su nivel de éxito
- El contraste puede ser en cualquier dirección: más humilde de lo esperado, más filantrópico, más excéntrico, más retirado, más activo
- La pregunta central que mueve el video es: **¿Por qué vive así?**
- NO es un arco de ruina ni de ascenso — es un arco de **elección de vida**
- Sin esa indicación → usar Arco 1 (riqueza) o el arco que corresponda al canal

---

## ⚠️ ERROR FRECUENTE — EL CONTRASTE NO REQUIERE POBREZA

**Este arco NO requiere que el personaje sea pobre ni que haya perdido su dinero.**

El Arco 1 habla de la vida de lujo. El Arco 3 habla de **por qué elige vivir como vive**, sea cual sea esa vida.

El contraste puede funcionar perfectamente con un personaje rico y famoso si:
- Tiene acceso a mucho más (apellido poderoso, contactos, oportunidades) pero **no los capitaliza** de la manera que el público esperaría
- Eligió una vida centrada en algo distinto al dinero o la fama: sus hijos, su fe, su arte, su comunidad
- Su historia personal (divorcio, pérdida, crisis) cambió sus prioridades de forma visible
- El público se pregunta "con todo lo que tiene, ¿por qué vive así?" — y la respuesta es una elección, no una derrota

**Ejemplo:** Lili Estefan tiene el apellido Estefan, 27 años en Univision, $10–14M estimados. Podría tener una línea de productos, un emporio de entretenimiento, una marca global. No lo tiene. Eligió ser conductora, reconstruirse sola después del divorcio, y hablar de su dolor en público. **Eso es el contraste PVA** — no que viva en pobreza.

### La pregunta que debes responder ANTES de escribir una sola línea:
> "¿Qué esperaría el público de alguien con su nivel de fama y conexiones, y qué eligió en cambio?"

Si hay una brecha entre lo esperado y lo real → Arco 3 PVA.
Si la vida del personaje ES exactamente lo que el público esperaría (mucho lujo, mucha fama, mucho dinero bien gastado) → Arco 1.

---

---

## ⚠️ VARIANTE: Personaje MUERTO

Si el personaje del video **ya murió**, el arco cambia de "¿por qué vive así?" a **"¿por qué vivió como pobre aunque tenía riqueza?"**

### Eje obligatorio
El eje central NO es narrar su vida — es establecer el contraste:
> **Tenía fama / dinero / contratos disponibles → PERO eligió (o terminó) viviendo con poco**

### Preguntas que DEBE responder el guion
1. ¿Cuánto llegó a tener o ganar en su pico?
2. ¿Cuándo y por qué empezó a alejarse de esa riqueza o a no acumularla?
3. ¿Fue decisión deliberada o circunstancias?
4. ¿Cómo murió y en qué condiciones económicas o de vida?

### Hook para personaje muerto
El hook NO puede empezar describiendo su muerte ni su pobreza final — eso es el desenlace, no la apertura.
El hook debe establecer primero la **magnitud de lo que TUVO**, para que el contraste funcione:

✅ "Este hombre ganó el campeonato mundial. Protagonizó veinte películas. Llenó las arenas durante décadas. Tuvo el mismo acceso a contratos y dinero que los más grandes. Y sin embargo, vivió toda su vida diciéndole al mundo lo mismo: solo soy un luchador profesional."

❌ "Este hombre murió solo en una estación de metro a los 78 años, sin que nadie lo reconociera." (esto es el cierre, no el gancho)

### Comparación con pares (obligatoria para muertos)
El contraste más poderoso es **compararlo con un contemporáneo del mismo nivel que SÍ construyó una fortuna**. Esto hace visible que la pobreza fue elección, no falta de oportunidad.

Ejemplo: Blue Demon vs El Santo — misma fama, mismo acceso, destinos distintos.

### Subtipo para personaje muerto
- Si eligió deliberadamente no acumular → **Subtipo A (sencillez elegida)**
- Si tuvo dinero y lo perdió/gastó → **Subtipo B (el dinero que se fue)**
- Si dejó la fama para dedicarse a otra cosa → **Subtipo C (giro de vida)**

---

## Longitud objetivo
**24,500–25,500 caracteres** — medir con `wc -m` antes del TTS

---

## Pipeline — qué cambia y qué no

| Paso | ¿Cambia? | Nota |
|------|----------|------|
| clips.py | NO | Igual que siempre — PASO 1 obligatorio |
| TTS / voz | NO | Misma voz del canal |
| Timeline / harvester | NO | Sin cambios |
| Dashboard / render | NO | Sin cambios |
| **Guion** | **SÍ** | Seguir la estructura de 9 bloques de este arco |
| **Título** | **SÍ** | No usa "Así es/fue la lujosa vida de X" — usar formato PVA (ver abajo) |
| **validador_guion.py** | **SALTAR** | Este arco no tiene arco de riqueza en los primeros 10 min — el validador fallará por diseño |

### Título para este arco
**NO usar** el formato de Arco 1 ("Así es la lujosa vida de X").

Usar uno de estos formatos según lo que el video responde:
- `"Por qué [Personaje] vive así después de [logro clave]"`
- `"Cómo vive hoy [Personaje] — [detalle sorprendente]"`
- `"[Logro] y sin embargo vive así: la historia de [Personaje]"`

Máximo 100 caracteres. El título debe generar curiosidad por el contraste, no prometer lujo.

---

## PASO PREVIO — Identificar el tipo de contraste antes de escribir

Antes de abrir el archivo del guion, responder esta pregunta con base en la investigación:

**¿Cuál es el contraste central de la vida actual del personaje?**

| Si el contraste es... | Subtipo |
|---|---|
| Tiene fama/logros enormes pero vive con sencillez deliberada | **A — La sencillez elegida** |
| Tuvo mucho dinero pero lo perdió / gastó / donó y ahora vive distinto | **B — El dinero que se fue** |
| Dejó la fama en su pico para dedicarse a algo completamente diferente | **C — El giro de vida** |
| Su vida actual está dominada por la fe, el servicio o una causa mayor | **D — La vocación más grande** |
| Vive de forma excéntrica o inesperada que no encaja con ninguna categoría | **E — La vida inesperada** |

**Anotar el subtipo en la primera línea del archivo del guion:**
`[SUBTIPO PVA: A / B / C / D / E]`

Los guiones de referencia usados para construir este arco:
- Roberto Durán → **B + A** (dinero que se fue + sencillez elegida)
- Rubén Blades → **C + A** (giro de vida político + sencillez elegida)
- Mariano Rivera → **D** (vocación más grande que la fama deportiva)

---

## Estructura de 9 Bloques

### BLOQUE 1 — LA IMAGEN QUE NADIE ESPERABA (anzuelo)

**Fórmula obligatoria del hook — 4 movimientos en orden:**

1. **Lugar físico específico** — una calle, un edificio, un barrio, una ciudad. Con nombre real. Sin abstracciones.
2. **Detalle ordinario o contradictorio** — algo que no encaja con la fama del personaje. Lo cotidiano chocando con lo extraordinario.
3. **Los logros en números fríos** — cuánto ganó, cuántos títulos, cuántos premios. Sin adjetivos. Solo la cifra.
4. **La pregunta que no cierra** — no la respondas. Déjala abierta. El espectador tiene que necesitar saber.

**Estructura de frase para el hook:**
> "Hay [lugar concreto] en [ciudad]. [Detalle ordinario que sorprende]. [Nombre del personaje] tiene [edad]. [Logro 1]. [Logro 2]. [Cifra de lo que ganó]. Y sin embargo, hoy [contraste con su vida actual]. ¿Cómo llegó aquí? ¿Por qué vive así?"

**Ejemplos reales extraídos de los guiones de referencia:**
- "Hay una estatua en Ciudad de Panamá que mira hacia una calle cualquiera de un barrio llamado el Cangrejo. Y si caminas una cuadra desde esa estatua, puede que te cruces con el hombre de bronce caminando en carne y hueso. 75 años. Las manos que un día fueron las más temidas del boxeo mundial. Hoy sostienen una bolsa del mercado."
- "Hay un edificio de piedra gris de 107 años en una calle de New Rochelle, Nueva York, justo al lado de los edificios de la policía y de la corte. Durante décadas fue una iglesia abandonada. La ciudad terminó vendiéndola por un solo dólar."
- "Tiene 78 años, nueve Grammy, un Máster en Harvard. Y en 2009 grabó su mejor disco en el garaje de su casa."

**Lo que NO hacer en el hook:**
- ❌ Empezar con el nombre del personaje — la identidad se revela después del contraste
- ❌ Empezar con "Hoy vamos a hablar de..." o cualquier presentación
- ❌ Usar adjetivos como "increíble", "impresionante", "sorprendente" — dejar que el hecho sorprenda solo
- ❌ Responder la pregunta en el mismo bloque — el anzuelo no se cierra, se abre

> Función: enganchar con el contraste antes de dar cualquier contexto.
> El espectador ya tiene la pregunta antes de saber quién es el personaje.
> Duración: 90–120 segundos.

---

### BLOQUE 2 — DÓNDE VIVE Y CÓMO ES ESE LUGAR
Describir el entorno actual del personaje con precisión geográfica y emocional.
- Ciudad, barrio, tipo de vida visible desde afuera
- Qué hay cerca (vecinos, estatuas, gimnasios, iglesias, garajes, fundaciones)
- Cómo lo recibe la gente local — ¿es una celebridad o es "el del barrio"?
- **REGLA CRÍTICA:** Solo describir lo que se puede confirmar. No inventar interiores de casas.
  Si no hay descripción pública del interior → decirlo explícitamente y centrarse en lo verificable.

> Función: anclar al espectador en un lugar real y concreto.
> El espectador debe poder imaginar ese lugar aunque nunca lo haya visto.

---

### BLOQUE 3 — LO QUE HACE HOY (la vida cotidiana real)
Detallar las actividades, proyectos y rutinas actuales del personaje.
- Proyectos concretos (gimnasios, iglesias, fundaciones, discos grabados en garajes, podcasts)
- Con quién comparte su vida (pareja, hijos, colaboradores)
- Qué hace con su tiempo que NO es acumular dinero ni mantener fama
- Una imagen específica que resuma su rutina actual (la orquesta de Durán, el garaje de Blades, la iglesia de Rivera)

> Función: mostrar que hay una vida activa y con propósito detrás del contraste.
> No es retiro ni resignación — es elección.

---

### BLOQUE 4 — LOS NÚMEROS (qué queda del dinero)
Presentar cifras reales con fuente y con contexto comparativo.
- Fortuna actual estimada (Celebrity Net Worth u otra fuente especializada — siempre como estimación)
- Fortuna en el pico de la carrera o bolsas/contratos más grandes documentados
- Comparar con pares del mismo nivel hoy para dar escala
- Si hubo pérdidas, gastos o donaciones conocidas: mencionarlas sin moralizarlos

> Función: dar datos concretos que explican (sin juzgar) la brecha entre lo que ganó y lo que tiene hoy.
> El espectador entiende que hay una historia detrás de los números.

> **REGLA:** Siempre presentar cifras como estimaciones. Nunca afirmar patrimonio como hecho verificado.

---

### BLOQUE 5 — EL ORIGEN (de dónde viene todo)
Narrar la infancia y el punto de partida del personaje.
- Lugar de origen exacto (barrio, pueblo, ciudad)
- Condición económica y familiar real
- El padre, la madre, los hermanos — quiénes eran y qué aportaron
- La primera señal del talento o la vocación
- El obstáculo principal que tuvo que superar antes de que hubiera carrera posible

> Función: dar al espectador la base emocional para entender las elecciones del personaje hoy.
> El origen no es backstory — es la clave para leer el presente.

---

### BLOQUE 6 — EL ASCENSO (cómo llegó a la cima)
Narrar la trayectoria profesional con ritmo y especificidad.
- Inicio concreto (fecha, lugar, rival, primer logro)
- Los años de construcción silenciosa antes del gran reconocimiento
- El momento de consagración — la pelea, el disco, el partido que lo cambió todo
- Los logros más importantes numerados o contextualizados para el espectador de hoy
- La presión específica de ese nivel — lo que pocos saben que implica estar en esa cima

> Función: recordar al espectador la magnitud real de lo que el personaje logró.
> Esto hace más poderoso el contraste con su vida actual.

---

### BLOQUE 7 — EL MOMENTO DE QUIEBRE O ELECCIÓN
El instante o proceso en que el personaje eligió (o fue empujado a) su vida actual.
- Puede ser una pérdida (fortuna, salud, relación)
- Puede ser una decisión deliberada (dejar la carrera en el pico, donar el dinero, cambiar de vida)
- Puede ser una crisis que reveló lo que de verdad importaba (enfermedad, pandemia, derrota)
- Una frase real del personaje que resume su visión del mundo en ese momento

> Función: este es el corazón emocional del video.
> El espectador entiende por qué vive así — no como falla sino como respuesta a algo verdadero.

---

### BLOQUE 8 — LAS PÉRDIDAS Y LO QUE QUEDÓ
Lo que el personaje perdió (dinero, fama, tiempo, relaciones) y lo que conservó.
- No romantizar las pérdidas — nombrarlas sin drama
- Pero también nombrar lo que sobrevivió: la familia, la pareja, la vocación, el barrio, la gente
- Un episodio humano concreto que muestre a la persona real detrás del personaje público
  (una enfermedad, un hijo no reconocido, una demanda, una crisis que superó)

> Función: hacer al personaje humano y complejo, no un héroe ni un fracasado.
> El espectador se identifica porque ve a alguien que también tuvo que decidir qué conservar.

---

### BLOQUE 9 — POR QUÉ IMPORTA (cierre)
Cerrar respondiendo explícitamente la pregunta del título.
- Resumir en 2-3 frases la elección de vida del personaje
- Conectar esa elección con algo que millones de personas enfrentan también
- Una imagen final que cierre el círculo con la apertura del Bloque 1
- NO terminar con moraleja genérica — terminar con una imagen concreta

> Ejemplos de cierres efectivos:
> - "Roberto Durán sigue siendo hoy el niño del Chorrillo que lustraba zapatos, caminando cada día por una calle que comparte con su propia estatua."
> - "78 años después de nacer en una casa de huéspedes, Rubén Blades sigue demostrando que la sencillez y la grandeza no solo pueden convivir — en su caso una explica exactamente a la otra."
> - "Millones se identifican con Rivera porque su historia demuestra que el verdadero salvamento no ocurre en un campo de béisbol, sino en la vida de las personas a las que uno decide dedicar su tiempo."

> Función: dejar al espectador con una idea que le pertenece, no con un resumen del video.

---

## Notas editoriales del arco

### Tono
- **No es un video de ruina.** No tratar al personaje como víctima de sus propias decisiones.
- **No es un video de virtud.** No presentar la sencillez o la filantropía como superioridad moral.
- **Es un video de curiosidad genuina.** La pregunta "¿por qué vive así?" se hace con respeto, no con juicio.

### Voz narrativa
- Segunda persona dirigida al espectador: "Imagina...", "Ven conmigo...", "Piensa en..."
- Primera persona del narrador al invitar: "Acompáñame...", "Vamos a..."
- Nunca: juicios de valor sobre las decisiones del personaje

### Cifras
- Siempre con fuente ("según estimaciones publicadas por Celebrity Net Worth...")
- Siempre como estimación, nunca como hecho ("ronda los X millones")
- Siempre comparadas con algo concreto para dar escala

### Imágenes que NO usar en el timeline
- Para el Bloque 4 (números): NUNCA mostrar mansiones ni lujo cuando el audio habla de pérdidas o sencillez
- Para el Bloque 5 (origen): mostrar SIEMPRE el entorno real de pobreza o humildad — nunca lujo anacrónico
- Para el Bloque 7 (quiebre): imágenes austeras, humanas, íntimas — no deportivas ni de escenario

---

## Checklist antes del TTS

- [ ] Subtipo PVA anotado en línea 1 del guion
- [ ] Bloque 1 abre con imagen concreta y específica (no abstracta)
- [ ] Bloque 2 no describe interiores no verificados
- [ ] Bloque 4 presenta cifras como estimaciones con fuente
- [ ] Bloque 7 incluye frase real del personaje
- [ ] Longitud medida con `wc -m`: entre 24,500 y 25,500 chars
- [ ] Título en formato PVA (no "Así es/fue la lujosa vida de X")
- [ ] validador_guion.py **NO correr** — este arco no tiene arco de riqueza en primeros 10 min

---

## Títulos virales — patrones analizados de canales de referencia

### GRUPO A — "Leyendas en Silencio" (lugar + contraste NUNCA)
Formato miniatura corto + descripción larga:
- `Así vive/vivía [Nombre] en [Ciudad]` (texto miniatura)
- `[Logro/apodo] que NUNCA [abandonó/salió de] [lugar] pese a [fama]`

Ejemplos reales:
- `La casa de El Santo en Iztapalapa` → `Nadie ESPERABA que EL SANTO viviera así a pesar de sus 40 años de fama`
- `Así vive Guty Espadas en Mérida` → `Por Qué Guty Espadas NUNCA SALIÓ de Mérida Pese a Ser Campeón del Mundo`
- `Así vive Lupe Pintor en Cuajimalpa` → `el barrio POBRE que el Doble Campeón Mundial NUNCA ABANDONÓ`

### GRUPO B — "¿Por qué vive así?" (pregunta + verdadera razón)
Formato título largo con pregunta directa:
- `¿Por qué [Nombre] vivió/vive como un hombre común pese a [logro]? La VERDADERA razón`
- `La Casa de [Nombre] en [Ciudad] — La HUMILDE vida de [apodo] a sus [edad] años`
- `Nadie ESPERABA Que [Nombre] Viviera Así Pese a [logro]`

Ejemplos reales:
- `¿Por qué Rubén Blades vive como un hombre común con 9 Grammy y Harvard? La VERDADERA razón`
- `¿Por qué Mariano Rivera vive como un hombre común tras ganar millones? La VERDADERA razón`
- `La Casa de Roberto Durán en Panamá — La HUMILDE vida de Mano de Piedra a sus 75 años`

### Reglas de título para Arco 3 (aplicar SIEMPRE)
1. Ciudad/barrio siempre presente
2. CAPS en: HUMILDE, NUNCA, VERDADERA, ESPERABA, JAMÁS
3. Muertos → "vivió/vivía" | Vivos → "vive/vivía"
4. Edad incluida cuando refuerza el contraste ("a sus 75 años")
5. Logro ANTES del contraste para activar la pregunta
6. "La VERDADERA razón" como cierre de pregunta
7. Máximo 100 chars

### Fórmulas listas para usar
```
¿Por qué [Nombre] vivió/vive así pese a [N películas/títulos/años]? La VERDADERA razón
Nadie ESPERABA que [NOMBRE] viviera así a pesar de sus [N] años de fama
La Casa de [Nombre] en [Ciudad] — La HUMILDE vida de [apodo] a sus [edad] años
Por qué [Nombre] NUNCA abandonó [lugar/vida sencilla] pese a [logro]. La VERDADERA razón
```
