#!/usr/bin/env python3
"""
validar_srt.py — Compara el SRT generado por TTS contra el TXT original.
Detecta:
  1. Frases en inglés insertadas por el TTS (alucinaciones)
  2. Texto repetido (el TTS repite un bloque)
  3. Texto del SRT que NO aparece en el TXT (inventado)

Uso: python3 validar_srt.py <archivo.txt> <archivo.srt>
"""
import sys, re
from pathlib import Path

VERDE  = "\033[92m"
ROJO   = "\033[91m"
AMARILLO = "\033[93m"
RESET  = "\033[0m"
NEGRITA = "\033[1m"

# Palabras muy comunes en inglés que no deben aparecer en un guion en español
ENGLISH_MARKERS = [
    r"\bthe\b", r"\band\b", r"\bof\b", r"\bto\b", r"\bin\b", r"\bis\b",
    r"\bwas\b", r"\bfor\b", r"\bthat\b", r"\bwith\b", r"\bhis\b", r"\bher\b",
    r"\bthis\b", r"\bfrom\b", r"\bthey\b", r"\bwere\b", r"\bwhen\b",
    r"\bhave\b", r"\bwill\b", r"\byou\b", r"\bnot\b", r"\bare\b",
    r"\bour\b", r"\bvery\b", r"\bdistrust\b", r"\bexpensive\b",
    r"\btrust\b", r"\bpeople\b", r"\btime\b", r"\bknow\b", r"\bjust\b",
]

def parse_srt(srt_path):
    """Retorna lista de (timestamp_str, texto)."""
    content = Path(srt_path).read_text(encoding="utf-8")
    blocks = content.strip().split("\n\n")
    result = []
    for b in blocks:
        lines = b.strip().split("\n")
        if len(lines) < 3:
            continue
        ts = lines[1]
        text = " ".join(lines[2:]).strip()
        result.append((ts, text))
    return result

def ts_to_sec(ts_line):
    """'00:02:14,722 --> ...' → segundos del inicio."""
    m = re.match(r"(\d+):(\d+):(\d+)", ts_line)
    if m:
        return int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3))
    return 0

def detect_english(text):
    """Retorna True si el texto tiene 2+ palabras en inglés."""
    hits = sum(1 for pat in ENGLISH_MARKERS if re.search(pat, text, re.IGNORECASE))
    return hits >= 2

def detect_repetition(blocks, window=5):
    """Detecta bloques consecutivos con el mismo texto."""
    problems = []
    for i in range(len(blocks) - window):
        texts = [b[1].lower().strip() for b in blocks[i:i+window]]
        for j in range(1, window):
            if texts[j] == texts[0] and len(texts[0]) > 20:
                secs = ts_to_sec(blocks[i+j][0])
                problems.append((secs, texts[0][:60]))
                break
    return problems

def text_in_original(srt_text, original_words):
    """Verifica si las palabras del bloque SRT están en el original."""
    words = re.findall(r'\b\w{5,}\b', srt_text.lower())
    if not words:
        return True
    found = sum(1 for w in words if w in original_words)
    return found / len(words) >= 0.5  # al menos 50% de palabras presentes

def validar(txt_path, srt_path):
    print(f"\n{NEGRITA}{'='*60}{RESET}")
    print(f"{NEGRITA}  VALIDADOR SRT — DETECCIÓN DE ALUCINACIONES TTS{RESET}")
    print(f"{'='*60}")
    print(f"  TXT: {txt_path}")
    print(f"  SRT: {srt_path}\n")

    original = Path(txt_path).read_text(encoding="utf-8").lower()
    original_words = set(re.findall(r'\b\w{5,}\b', original))

    blocks = parse_srt(srt_path)
    print(f"  Bloques SRT: {len(blocks)}")

    errores = []
    advertencias = []

    # ── 1. FRASES EN INGLÉS ──────────────────────────────────────
    print(f"\n{NEGRITA}[1] DETECCIÓN DE INGLÉS EN EL SRT{RESET}")
    english_blocks = []
    for ts, text in blocks:
        if detect_english(text):
            secs = ts_to_sec(ts)
            mins = secs // 60
            segs = secs % 60
            english_blocks.append((f"{mins:02d}:{segs:02d}", text))

    if english_blocks:
        for t, txt in english_blocks:
            print(f"  {ROJO}✗ {t} — \"{txt[:80]}\"{RESET}")
        errores.append(f"{len(english_blocks)} bloque(s) en inglés")
    else:
        print(f"  {VERDE}✓ Sin frases en inglés detectadas{RESET}")

    # ── 2. TEXTO REPETIDO ────────────────────────────────────────
    print(f"\n{NEGRITA}[2] DETECCIÓN DE REPETICIONES{RESET}")
    reps = detect_repetition(blocks)
    if reps:
        for secs, txt in reps[:5]:
            mins = secs // 60; s = secs % 60
            print(f"  {ROJO}✗ {mins:02d}:{s:02d} — repetición: \"{txt}\"{RESET}")
        errores.append(f"{len(reps)} bloque(s) repetido(s)")
    else:
        print(f"  {VERDE}✓ Sin repeticiones detectadas{RESET}")

    # ── 3. TEXTO NO PRESENTE EN EL ORIGINAL ─────────────────────
    print(f"\n{NEGRITA}[3] TEXTO INVENTADO (no está en el TXT original){RESET}")
    inventados = []
    for ts, text in blocks:
        if not text_in_original(text, original_words):
            secs = ts_to_sec(ts)
            mins = secs // 60; s = secs % 60
            inventados.append((f"{mins:02d}:{s:02d}", text))

    if inventados:
        for t, txt in inventados[:8]:
            print(f"  {AMARILLO}⚠ {t} — \"{txt[:80]}\"{RESET}")
        advertencias.append(f"{len(inventados)} bloque(s) con texto posiblemente inventado")
    else:
        print(f"  {VERDE}✓ Todo el texto del SRT corresponde al original{RESET}")

    # ── RESULTADO ────────────────────────────────────────────────
    print(f"\n{NEGRITA}{'='*60}{RESET}")
    if errores:
        print(f"{ROJO}{NEGRITA}  ❌ SRT INVÁLIDO — corregir MP3 antes de renderizar{RESET}")
        for e in errores:
            print(f"  {ROJO}• {e}{RESET}")
    elif advertencias:
        print(f"{AMARILLO}{NEGRITA}  ⚠ SRT CON ADVERTENCIAS — revisar manualmente{RESET}")
        for a in advertencias:
            print(f"  {AMARILLO}• {a}{RESET}")
    else:
        print(f"{VERDE}{NEGRITA}  ✅ SRT OK — listo para render{RESET}")
    print(f"{'='*60}\n")

    return len(errores) == 0

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python3 validar_srt.py <archivo.txt> <archivo.srt>")
        sys.exit(1)
    ok = validar(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)
