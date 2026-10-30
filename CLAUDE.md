# REGLAS DURAS — Canal YouTube Pipeline

## ⛔ RENOMBRAR SESIÓN AL DETECTAR EL PERSONAJE

**OBLIGATORIO** — en cuanto identifiques el personaje (al abrir la URL o al leer el título del video), llamar inmediatamente:

```
mcp__ccd_session_mgmt__set_session_title(session_id="self", title="<Personaje> — Arco <N> <tipo>")
```

Hacerlo ANTES de cualquier otra acción del pipeline. No esperar al guion. No esperar confirmación del usuario.

---

## ⛔ GUION: ESCRIBIR A LONGITUD CORRECTA EN UN SOLO WRITE

**NUNCA** escribir el guion corto y expandirlo en rondas de edits.
Expandir en rondas cuesta el doble de tokens que escribirlo bien la primera vez.

**Cálculo obligatorio ANTES de abrir el archivo:**
- Arco 1 / Arco 2 / Arco 3 PVA: 24,500 chars ÷ bloques = chars por bloque
  - Arco PVA (9 bloques) = ~2,700 chars por bloque
  - Arco 1 (11 bloques) = ~2,200 chars por bloque
- Escribir cada bloque a esa longitud en el **primer y único Write**
- Margen aceptable: **±10% del total** (para 24,500 → rango válido: 22,050–26,950 chars)
- `wc -m` una sola vez al final — si cae en ese rango, listo. No expandir.

---

## ⛔ TRANSCRIPT = FUENTE PRIMARIA DEL GUION

**SIEMPRE** descargar y leer el transcript completo con `yt-dlp --write-auto-sub` antes de escribir una línea.
Buscar en internet **solo lo que el transcript no cubra** (cifras de fortuna, fechas no mencionadas).
NUNCA asumir nacionalidad, datos biográficos ni personajes a partir del título del video.
