# Research — Secretos Mexicanos
*Extraído de 5 transcripts reales + análisis de 30 videos del canal de referencia: La Verdad de los Famosos (@LaVerdaddelosFamososBH)*

---

## ⛔ CHECKLIST PIPELINE — LEER ANTES DE CADA PASO

| Paso | Acción | Regla dura a verificar ANTES |
|------|--------|------------------------------|
| 1 | Proponer ángulos | Leer sección "Ángulos verificados" de este archivo — SOLO los 10 permitidos |
| 2 | Proponer título | Adjetivo de poder en PRIMER tramo antes de `...` — NUNCA al final |
| 3 | Validar ángulo en guion | Correr `validar_angulo_guion.py` — hook + cada tercio + densidad ≥ 2.0 |
| 4 | Validar guion | Correr `validador_guion_secretos-mexicanos.py` — 11/11 verde |
| 5 | TTS | Números en letras, chars 38k–44k, voz `l1zE9xgNpUTaQCZzpNJa` |
| 6 | Timeline | `timeline_approval.py` — leer log ANTES de mencionar :5099; si ya dice "guardado+Baserow" → no mostrar UI |
| 7 | Zoompan | Verificar duplicados por prefijo numérico — DETENER si hay más de 1 por número |
| 8 | Dashboard | `lsof -ti:5003 \| xargs kill -9` primero → lanzar → dar URL `/aprobar/<canal>/<personaje>` |
| 9 | Render | Verificar clips/ > 0 Y flow_*_zp.mp4 > 0 Y metadata pendientes = 0 antes de lanzar |
| 10 | Pack subida — miniatura | Leer `datos/base_viral.md` → sección "Fórmulas de miniatura completas" — NUNCA improvisar líneas sin consultar esa base |
| 11 | Textos óvalo miniatura | Dar 3 opciones → usuario elige → luego dar prompt — NUNCA dar prompt directo |
| 12 | veo-folder-1 | NUNCA borrar sin instrucción explícita del usuario |

---

## Fórmula de título

### Fórmula exacta (verificada en 9 videos recientes del canal):
```
[ARTISTA]: [ADJETIVO CAPS + acción en el primer tramo]... [Consecuencia dramática].
```

⚠️ REGLA DURA: El ADJETIVO DE PODER va SIEMPRE en el **primer tramo**, antes de los `...`. NUNCA al final.
✅ CORRECTO: `Camilo Sesto: La ASQUEROSA Doble Vida que Tuvo... Y el Hijo que Robó.`
❌ MAL: `Camilo Sesto: Tuvo una Doble Vida... La ASQUEROSA Verdad.`

**La palabra ASQUEROSO/A es la firma del canal — aparece en 6/9 títulos recientes. Usarla siempre que aplique.**

**Adjetivos de alto impacto obligatorios (en CAPS en el título):**
- ASQUEROSO / ASQUEROSA ← el más poderoso, usar por defecto
- BRUTAL
- ESCALOFRIANTE
- DESCARADA / DESCARADO
- OSCURO

**Sustantivos narrativos de alto impacto:**
Doble Vida · Saqueo · Maltrato · Karma · Catálogo · Secreto · Exilio · Prófugo · Traición · Ruina · Monstruo · Sanguijuela · Parásito

**Ejemplos reales del canal (verificados):**
- `Alfonso Zayas: Destruyó 7 Matrimonios... La ASQUEROSA Doble Vida del 'Ídolo' Cómico.`
- `El Tigre Azcárraga: Escalofriante Catálogo VIP... Y la ASQUEROSA Guerra de Viudas por su Fortuna`
- `Irma Serrano: El ASQUEROSO Saqueo de 'Amigos'... Y el BRUTAL Karma de Morir en la Ruina.`
- `Adela Noriega: Borrada de la TV... El ASQUEROSO Secreto que la Obligó al Exilio.`
- `Romero Deschamps: La Sanguijuela de PEMEX... Y el BRUTAL Karma de Morir Rodeado de Odio y Oro.`
- `Cantinflas: 30 años de Secretos... El Oscuro Final Del Payaso Que Todos Amaron.`
- `Elsa Aguirre: De ser Deseada por TODOS... Al ASQUEROSO Maltrato que la DESFIGURÓ.`
- `Chiquis Rivera: Desheredada por Jenni Rivera... Heredó su ASQUEROSO Patrón de Maltrato y Vicios.`
- `Enrique Peña Nieto: El ASQUEROSO Saqueo... Y la DESCARADA Vida del Prófugo Intocable.`

**Formato B — "Los odios" (videos cortos 12-26 min, máximo viral):**
`A los [EDAD], [Artista] nombró a los [N] [cantantes/actores] que más odia.`
`Antes de morir, [Artista] REVELÓ a los [N] artistas que más odiaba.`

**Regla de oro del título:** Nunca revelar el secreto completo — solo la tensión. El título promete, el video entrega. Los "..." son separador obligatorio entre el setup y el golpe final.

---

## Fórmula de miniatura

**Estructura visual (verificada en 9 miniaturas recientes):**
- **Fondo:** escena dramática — calle pobre, hospital, prisión, cuarto oscuro
- **Foto izquierda:** artista en su gloria (a color, glamoroso, joven)
- **Óvalo derecho:** artista ahora / en desgracia (sufriendo, viejo, arruinado, pobre)
- **Flecha amarilla:** apuntando de la foto izquierda al óvalo (el "así cayó")
- **Texto overlay:** 2 líneas en bold amarillo/blanco en la parte inferior

**Fórmula del texto en miniatura (2 líneas):**
```
Línea 1: LA/EL [COSA] MÁS [ADJETIVO NEGATIVO]    ← amarillo grande, bold
Línea 2: LO QUE [ACCIÓN]... / ASÍ [CONSECUENCIA]... ← blanco o amarillo, más chico
```

**Ejemplos reales del texto en miniatura:**
- `LA TRAICIÓN MÁS VIL / ASÍ BURLÓ A SUS VÍCTIMAS...`
- `EL CATÁLOGO MÁS SUCIO / LO QUE ENCONTRARON SUS VIUDAS...`
- `LA TRAICIÓN MÁS SUCIA / ASÍ LA DEJARON EN LA CALLE...`
- `¡ARRUINARON SU VIDA! / LO QUE EL PRESIDENTE LE HIZO...`
- `EL PARÁSITO MÁS VORAZ / SU ORO NO PUDO SALVARLO...`
- `30 AÑOS DE MENTIRAS / LO QUE OCULTÓ HASTA EL FINAL.`
- `MUTILADA EN SILENCIO / EL MONSTRUO QUE LO HIZO...`
- `LA VERDAD MÁS SUCIA / LO QUE LE HIZO A SU MADRE...`
- `LA BURLA MÁS SUCIA / EL PACTO PARA NO METERLO PRES...`

**Adjetivos para miniatura (Línea 1):** MÁS VIL · MÁS SUCIO/A · MÁS VORAZ · MÁS BRUTAL · MÁS OSCURO/A · MÁS CRUEL
**Verbos para miniatura (Línea 2):** ARRUINARON · MUTILARON · DESTRUYERON · OCULTÓ · TRAICIONÓ · DESFIGURÓ

---

## Estructura del guion (beats con minutaje)

### Beat 1 — APERTURA CINEMATOGRÁFICA (0:00–1:30) ~225 palabras
**Lo más importante:** NO empieza con el nombre del artista. Empieza con escena.

**Formato A — Escena con fecha (el más común):**
- Lugar + fecha específica (día, mes, año)
- Descripción sensorial del ambiente (luz, sonidos, objetos físicos concretos)
- Momento de máximo impacto de la historia (quirófano, mansión oculta, muerte, entrevista íntima)
- Última frase revela al artista y conecta con el título

Ejemplo real: *"14 de agosto de 1997. En un quirófano de Monterrey, un cuerpo yace inmóvil bajo una luz blanca que no perdona. Afuera, una enfermera corre por el pasillo... El monitor cardíaco deja escapar un pitido largo, seco, definitivo."*

**Formato B — Apertura con el RESULTADO (técnica de alto impacto):**
Abrir directamente con el desenlace más impactante — la cifra, la sentencia, el objeto — y dejar que la historia explique cómo se llegó ahí. Crea curiosidad inversa: el espectador sabe el fin pero no el camino.

Ejemplo: *"60,000 euros devueltos por los tribunales. Dos cartas escritas con letra infantil que nunca debieron existir como prueba. Y una mujer que tardó diez años en entender que la familia de él siempre supo."*

Usar Formato B cuando el resultado final del caso es más impactante que cualquier escena intermedia.

### Beat 2 — TEASE DE REVELACIONES (1:30–3:30) ~300 palabras
- Enumerar 3–4 revelaciones numeradas que el video va a develar
- **HYPER-ESPECIFICIDAD OBLIGATORIA** — cada revelación debe incluir: nombre / fecha / cantidad / documento real. NUNCA vaga.
  - ❌ MAL: "La traición que sufrió de su mejor amigo"
  - ✅ BIEN: "El 4 de noviembre de 2025, cuando José Manuel ya había firmado los documentos de divorcio frente a un notario, Angélica todavía estaba cenando con él y sus hijos"
- Siempre: "La cuarta/tercera es la más incómoda de todas" → retiene al espectador
- Frase de enganche: "Si te vas antes del final, te pierdes la [N]"

### Beat 3 — CONTEXTO DEL PERSONAJE (3:30–6:00) ~375 palabras
- Quién fue en su momento de gloria (datos duros: records, premios, dominio del mercado)
- Por qué importaba / por qué era intocable
- Primer indicio de la sombra detrás del brillo

### Beat 4 — ORIGEN HUMILDE (6:00–12:00) ~900 palabras
- Ciudad natal + año + descripción poética de la pobreza/sencillez
- Cómo era México en esa época (contextualización histórica)
- La familia: quién lo formó, quién lo marcó
- El talento descubierto como única salida posible

### Beat 5 — ASCENSO AL PODER (12:00–20:00) ~1,200 palabras
- El camino a la fama (obstáculos, primeras traiciones menores)
- El momento cúspide — cuando lo tenía todo
- Datos específicos de su dominio (números, récords, territorios)
- Las primeras señales de lo que vendrá (siempre presentes en retrospectiva)

### Beat 6 — EL SECRETO / TRAICIÓN CENTRAL (20:00–34:00) ~2,100 palabras
- El núcleo dramático del video — lo que da título al canal
- Presentado como investigación: "grabaciones filtradas", "documentos legales", "testimonios que nunca salieron al aire"
- Revelaciones numeradas presentadas en orden de impacto creciente
- Nunca juzga directamente — deja que los hechos hablen
- Frases recurrentes: "Lo que nadie se atrevió a contar", "Un testimonio que nunca fue declarado"
- **PROFUNDIDAD PSICOLÓGICA OBLIGATORIA** — no basta decir QUÉ pasó, hay que explicar POR QUÉ:
  - Mecanismos de defensa del protagonista (negación, racionalización, dependencia emocional)
  - Presiones estructurales: clase social, dinámicas de poder en la industria, miedo real
  - La "complicidad" del protagonista — cómo sus propias decisiones contribuyeron al drama
  - Esto hace el contenido más humano, más discutible, más real. NO simple víctima/victimario.
- **DETALLES FÍSICOS CONCRETOS cada 2 párrafos** — objetos, texturas, temperaturas, sonidos:
  - ✅ "La carpeta de documentos que su abogado dejó sobre la mesa tenía la esquina doblada. Alguien la había hojeado muchas veces."
  - ✅ "Esa noche, el refrigerador estaba vacío excepto por un frasco de mermelada que nadie había cerrado bien."
  - Los detalles físicos anclan la narración y activan la imaginación del espectador → retención

### Beat 7 — LA CAÍDA / EL PRECIO (34:00–40:00) ~900 palabras
- Las consecuencias: enfermedad, exilio, silencio forzado, pobreza, muerte
- Sin redención fácil — el precio es real y permanente
- Perspectiva de quienes estuvieron cerca (hijos, familia, excolaboradores)

### Beat 8 — CIERRE FILOSÓFICO (40:00–44:00) ~600 palabras
- Reflexión sobre lo que dice esta historia del sistema/la industria/México
- No cancela al sujeto, lo contextualiza en una verdad mayor
- Sin CTA agresivo — solo: "Esta es la historia que nadie quiso terminar"
- **CTA CON PREGUNTA DIRIGIDA A MUJERES** — la audiencia del canal es mayoritariamente femenina 50+:
  - La pregunta del cierre debe conectar con la experiencia vivida de la audiencia, no ser retórica
  - ❌ MAL: "¿Acaso la fama tiene un precio demasiado alto?"
  - ✅ BIEN: "¿Tú sabías que este matrimonio duró solo veinte días? ¿Conocías esta parte de su historia?"
  - ✅ BIEN: "¿Alguna vez rodeaste de silencio algo que merecía ser dicho? Cuéntanos en los comentarios."
  - ✅ BIEN: "¿Crees que ella debió irse antes, o entiendes por qué esperó tanto?"
  - Opcionalmente usar "nosotras" para incluir a la audiencia: "Muchas de nosotras guardamos cosas que merecían ser dichas."
  - **Los comentarios son señal de engagement para el algoritmo — la pregunta debe invitar a responder, no a reflexionar en silencio**

**Total: ~6,600 palabras ≈ 44 min a 150 palabras/min**

---

## Guía de estilo

**Tono:** Narrador omnisciente, periodista de investigación, solemne sin ser aburrido. Nunca amarillista directo — siempre hay peso moral en la voz.

**Ritmo:** Alterna frases cortas y contundentes con una frase larga que explica. Pausa dramática entre revelaciones.

**Lenguaje cinematográfico:**
- "No hay cámaras, no hay alfombras rojas, no hay aplausos"
- "Una luz blanca que no perdona"
- "El silencio se convirtió en moneda de cambio"

**Palabras de transición características (re-hooks entre bloques — OBLIGATORIO cada 2-3 min):**
- "Pero lo verdaderamente inquietante..."
- "Y entonces ocurrió algo que define toda esta historia"
- "Para entender cómo llegó tan alto, hay que volver al principio"
- "Aquí no hablamos de chismes, hablamos de..."
- "Hoy, casi [N] décadas después, las preguntas siguen abiertas"
- **Frases de re-hook nivel competencia (extraídas de guiones virales reales):**
  - "Lo que encontramos después lo cambia todo."
  - "Pero hay algo que los reportes no dicen. Y lo veremos en un momento."
  - "Y aquí es donde la historia deja de tener sentido oficial."
  - "Eso fue lo que dijo. Lo que hizo después es otra cosa."
  - "Eso es lo que nadie contó bien en su momento."
  - "Esta fue la primera vez que ese patrón apareció. No sería la última."
  - "Para entonces, [nombre] ya llevaba años cargando algo que nadie sabía."
  - "Presta atención a lo que viene, porque aquí es donde el silencio se vuelve elocuente."

**Lo que NUNCA hace este canal:**
- Nombrar al artista en los primeros 30 segundos
- Revelar el secreto completo en el hook
- Usar lenguaje de chisme/tabloid ("dizque", "se rumorea")
- Dar veredictos morales directos — siempre invita al espectador a juzgar
- Terminar con redención fácil — el drama permanece

**Recursos narrativos recurrentes:**
- La "cuarta revelación" siempre es la más poderosa
- Comparar al artista con su momento de gloria vs su situación actual
- Usar fechas exactas para dar credibilidad periodística
- "Lo que su propia familia mantuvo en silencio durante años"
- El silencio como decisión de poder, no como derrota

---

## Categorías temáticas del canal

1. **Poder sin límites** — conductores, productores, figuras de la industria que controlaban carreras (Raúl Velasco, Televisa, padrinos del espectáculo)
2. **Amores con el poder político** — actrices/artistas vinculadas a presidentes, gobernadores, narcos
3. **Hijos ocultos y familias secretas** — la verdad sobre descendencia que alguien protegió con dinero o silencio
4. **Traición entre colegas** — rivalidades, vetos, humillaciones dentro de la industria
5. **El cuerpo como precio** — enfermedades, operaciones, adicciones ligadas al sistema del espectáculo
6. **Crimen y narco en el espectáculo** — artistas vinculados al narco (voluntaria o forzosamente)
7. **El exilio como sobrevivencia** — artistas que desaparecieron para protegerse
8. **Legados rotos** — lo que quedó cuando el ídolo cayó (hijos, familias, carreras destruidas)

---

## ⚠️ REGLA DURA — Ángulos verificados con datos reales (30 videos analizados)

**NUNCA proponer ángulos genéricos. SIEMPRE usar uno de estos 10, verificados por vistas reales del canal de referencia.**

Fuente: análisis de @LaVerdaddelosFamososBH — 30 videos, ordenados por rendimiento:

| # | Ángulo | Descripción concreta | Referencia real |
|---|---|---|---|
| 1 | **Poder que somete + karma** | Figura de poder que controlaba carreras/personas y cayó después | Raúl Velasco 1.2M |
| 2 | **Amores con el poder político + hijo oculto** | Artista + presidente/narco/magnate + hijo secreto que escondió | Adela Noriega 988K |
| 3 | **El poderoso que te destruyó** | Un hombre con poder específico destruyó a la figura — no "traición" genérica | Pilar Montenegro 629K |
| 4 | **Narco/crimen en el espectáculo** | Vínculo directo con narco (cama, amenaza, sobrevivencia) | Lucha Villa 575K |
| 5 | **Secreto de origen / pobreza oculta** | La miseria real detrás del glamour que nunca contó | AMLO 530K |
| 6 | **Hijo/a secreto con magnate o político** | Descendencia escondida por dinero o poder | India María 496K |
| 7 | **Lo que encontraron al morir** | Caja fuerte, testamento, confesión, deuda oculta revelada post-mortem | Cantinflas 474K |
| 8 | **Hijo que destruye o fue destruido por el padre** | El hijo como arma o víctima directa del famoso | Verónica Castro 457K |
| 9 | **Traición de sangre + crimen** | Familiar que vendió/traicionó + consecuencia criminal concreta | Valentín Elizalde 372K |
| 10 | **Exilio forzado + humillación 20-30 años** | Artista que desapareció por presión de poder y nadie preguntó | Adela Noriega exilio 379K |

**Palabras de poder verificadas en títulos exitosos del nicho:**
```
DISGUSTING · FILTHY · PARASITE · KARMA · SOLD OUT · LOOTED/SAQUEÓ
TIRANO · DESTROYED · FAKE · HELL/INFIERNO · SECRET · "Te Hará Llorar"
"paid the price" · MALDICIÓN · CONFINAMIENTO
```

**Formatos de título verificados por vistas:**
```
1. [Artista]: The [ADJETIVO CAPS] [Sustantivo]... [Consecuencia].
2. [Artista]: From [situación A] to [situación B opuesta].
3. [Artista]: [Lo que todos creen / apodo]... [La verdad destructiva].
4. [Artista]: [KARMA/FAKE/PARASITE]... [Lo que pagó / perdió].
5. A los [N] años, [Artista] nombró a los [N] que más odia.  ← formato corto viral
```

---

## 10 ideas de video para Secretos Mexicanos

**IDEA 1**
IDEA: El productor más poderoso de Televisa en los 80-90 que exigía "favores" para dar telenovelas
TITLE: El Productor que VENDÍA Papeles... Y Nadie en Televisa Quiso Detenerlo
ANGLE: El sistema que lo protegió es el mismo que sigue operando hoy
CATEGORY: Poder sin límites

**IDEA 2**
IDEA: Artista mexicana que tuvo un hijo con un narco de alto perfil y lo mantuvo en secreto décadas
TITLE: La Cantante que Tuvo un HIJO con el Narco... Y lo Escondió 30 Años
ANGLE: El niño que hoy vive con otro apellido y no puede reclamar el suyo
CATEGORY: Hijos ocultos y familias secretas

**IDEA 3**
IDEA: El día que un cantante ranchero famoso fue amenazado por el cartel y eligió callar para siempre
TITLE: [Artista]: El Cartel le Dijo "Cállate o Muere"... Y Eligió el Silencio
ANGLE: Las canciones que dejó de cantar tienen un nombre que nadie pronuncia
CATEGORY: Crimen y narco en el espectáculo

**IDEA 4**
IDEA: Actriz de telenovelas de los 90 que fue vetada por rechazar a un ejecutivo poderoso
TITLE: La Actriz que Dijo NO... Y Televisa la Borró de la Historia
ANGLE: Su carrera duró exactamente hasta el día que rechazó lo que no debía rechazar
CATEGORY: Poder sin límites

**IDEA 5**
IDEA: El hijo de una leyenda de la música mexicana que heredó solo deudas y secretos
TITLE: El Hijo de [Leyenda]: Heredó el Apellido... Y También la Maldición
ANGLE: Lo que el padre construyó en escenarios, el hijo lo pagó en silencio
CATEGORY: Legados rotos

**IDEA 6**
IDEA: Presentadora de TV que supo demasiado sobre un político y fue destruida públicamente
TITLE: Sabía Demasiado... Y la Destruyeron Antes de que Pudiera Hablar
ANGLE: El silencio fue el precio de seguir con vida pública
CATEGORY: Amores con el poder político

**IDEA 7**
IDEA: Cantante de grupero que pasó de millonario a indigente por las personas en que confió
TITLE: Tenía Todo... Y los que Amaba se lo Quitaron Todo (La Cruel Verdad)
ANGLE: La traición no vino de enemigos sino de su círculo más cercano
CATEGORY: Traición entre colegas

**IDEA 8**
IDEA: El escándalo de una operación de cirugía estética en los 90 que destruyó la carrera de una actriz
TITLE: La Operación que NADIE Ordenó... Y que le Robó la Cara y la Carrera
ANGLE: Alguien tomó esa decisión por ella. Nunca fue castigado.
CATEGORY: El cuerpo como precio

**IDEA 9**
IDEA: Artista que desapareció del ojo público porque alguien poderoso lo exigió
TITLE: Desapareció de la Noche a la Mañana... La Orden Vino de Arriba
ANGLE: No fue un retiro, fue una sentencia sin juicio
CATEGORY: El exilio como sobrevivencia

**IDEA 10**
IDEA: La verdad detrás de la muerte de un ídolo mexicano que la familia nunca confirmó
TITLE: Murió Solo... Y lo que Encontraron Después Cambió Todo (La Verdad Oculta)
ANGLE: El silencio de la familia no fue por dolor, fue por miedo
CATEGORY: Legados rotos
