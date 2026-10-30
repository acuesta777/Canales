---
name: feedback_puerto_dinamico_approval
description: approval_solo.py debe usar puerto dinámico (primer libre desde 5099) cuando hay múltiples videos en paralelo
metadata:
  type: feedback
---

Nunca hardcodear `port=5099` en `approval_solo.py`. Con 3+ videos en paralelo todos chocan en el mismo puerto.

**Why:** El usuario corre múltiples videos simultáneamente; si todos intentan usar 5099 el segundo y tercero fallan silenciosamente.

**How to apply:** `approval_solo.py` ya tiene `_find_free_port(5099)` y abre el navegador automáticamente (1.2s delay). Puerto en runtime: arg CLI > `approval_port` en timeline.json > primer libre desde 5099 hasta 5120. NUNCA hardcodear port=5099.
