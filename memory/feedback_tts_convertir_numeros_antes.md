---
name: feedback_tts_convertir_numeros_antes
description: Convertir números a letras es parte del flujo ANTES del TTS, no después. El validador de números debe correr antes de mostrar el guion al usuario para aprobación.
metadata:
  type: feedback
---

Convertir todos los números en dígitos a letras es obligatorio ANTES de presentar el guion al usuario para revisión y aprobación.

**Why:** El TTS lee los números en inglés si están en dígitos. El error debe detectarse y corregirse en el guion, no descubrirse cuando el TTS ya está corriendo.

**How to apply:** Orden correcto:
1. Escribir guion
2. Convertir todos los números a letras (fechas, años, edades, cifras)
3. Mostrar guion al usuario para revisión
4. Usuario aprueba
5. Lanzar TTS

Nunca mostrar el guion con números en dígitos. Nunca lanzar TTS con números en dígitos.
