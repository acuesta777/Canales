---
name: feedback_clips_paso1_primero
description: PASO 1 clips.py SIEMPRE es lo primero que se lanza — antes del guion, antes de cualquier otra cosa
metadata:
  type: feedback
---

NUNCA saltarse el PASO 1. Al recibir una URL de YouTube, lo primero que se lanza es `clips.py` en background, simultáneo a leer la URL y riqueza.md. No esperar a terminar el guion.

**Why:** Sin clips no hay video. El render necesita los clips de YouTube. Si se salta el PASO 1, al llegar al dashboard no hay clips YT y el usuario tiene que esperar el proceso que debió correr desde el inicio.

**How to apply:** Inmediatamente al detectar la URL, lanzar `bash run_timeout.sh 900 clips python3 clips.py "<url>" <nicho>/<personaje>/` en background como primer comando, en paralelo con leer riqueza.md y la URL.
