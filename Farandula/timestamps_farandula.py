#!/usr/bin/env python3
"""
Timestamps Farandula — Busca el nombre de cada artista en el SRT completo
para obtener el segundo exacto donde empieza cada sección.

Uso: python3 timestamps_farandula.py /ruta/carpeta/video/

Genera timestamps.json con start/end exactos por sección.
"""

import sys, json, re, pathlib, unicodedata, difflib

SRT_ENTRY = re.compile(
    r"\d+\n(\d{2}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2}):(\d{2}):(\d{2}),(\d{3})\n(.*?)(?=\n\n|\Z)",
    re.DOTALL
)

def ts_to_sec(h, m, s, ms):
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000

def normalize(text):
    """Minúsculas sin tildes ni puntuación para comparar nombres."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", "", text)

def parse_srt(srt_text):
    entries = []
    for m in SRT_ENTRY.finditer(srt_text):
        start = ts_to_sec(m.group(1), m.group(2), m.group(3), m.group(4))
        end   = ts_to_sec(m.group(5), m.group(6), m.group(7), m.group(8))
        text  = m.group(9).replace("\n", " ").strip()
        entries.append({"start": start, "end": end, "text": text, "norm": normalize(text)})
    return entries

def fuzzy_contains(text_norm, word, max_dist=2):
    """Devuelve True si alguna palabra de text_norm está a distancia ≤ max_dist de word."""
    words = text_norm.split()
    for w in words:
        if abs(len(w) - len(word)) > max_dist:
            continue
        # Levenshtein simplificado via difflib
        ratio = difflib.SequenceMatcher(None, w, word).ratio()
        dist = int((1 - ratio) * max(len(w), len(word)) + 0.5)
        if dist <= max_dist:
            return True
    return False

def find_artist_start(entries, artist_name, search_from=0.0, search_until=None):
    """
    Busca el primer bloque del SRT que contenga el nombre del artista
    después de search_from segundos. Devuelve el timestamp de inicio.
    search_until: si se especifica, no busca más allá de ese segundo.
    """
    name_norm = normalize(artist_name)
    parts = name_norm.split()
    apellido = parts[-1] if parts else name_norm

    candidates = [e for e in entries
                  if e["start"] >= search_from
                  and (search_until is None or e["start"] <= search_until)]

    # Un solo pass cronológico: exacto tiene prioridad, fuzzy como fallback inmediato
    # Esto evita que una referencia cruzada posterior (exacta) gane sobre una variante
    # fonética anterior (ej: "Goiri" en texto de Capetillo vs "Goyri" en intro real)
    fuzzy_min = len(apellido) >= 5  # solo fuzzy para apellidos de 5+ chars

    for e in candidates:
        words = e["norm"].split()
        # 1. Nombre completo exacto
        if name_norm in e["norm"]:
            return e["start"]
        # 2. Apellido exacto como palabra
        if apellido in words:
            return e["start"]
        # 3. Fuzzy dist=1 (Goiri↔Goyri); SOLO si el nombre completo también está cerca
        #    para evitar que "goiri" en referencia cruzada gane sobre "goyri" en intro
        if fuzzy_min and fuzzy_contains(e["norm"], apellido, max_dist=1):
            # Validar: debe haber alguna parte del nombre en el mismo texto
            nombre_parts = name_norm.split()
            if any(p in e["norm"] for p in nombre_parts):
                return e["start"]

    return None

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 timestamps_farandula.py /ruta/carpeta/video/")
        sys.exit(1)

    folder = pathlib.Path(sys.argv[1])
    sections_file  = folder / "sections.json"
    out_timestamps = folder / "timestamps.json"

    # Buscar SRT (audio.srt o cualquier .srt)
    srt_file = folder / "audio.srt"
    if not srt_file.exists():
        srts = list(folder.glob("*.srt"))
        if srts:
            srt_file = srts[0]
        else:
            print(f"ERROR: No existe SRT en {folder}")
            sys.exit(1)

    if not sections_file.exists():
        print(f"ERROR: No existe {sections_file} — corre primero tts_farandula.py")
        sys.exit(1)

    sections = json.loads(sections_file.read_text(encoding="utf-8"))
    srt_text = srt_file.read_text(encoding="utf-8")
    srt_entries = parse_srt(srt_text)

    if not srt_entries:
        print("ERROR: SRT vacío.")
        sys.exit(1)

    audio_end = srt_entries[-1]["end"]
    print(f"SRT: {len(srt_entries)} entradas | duración total: {audio_end:.1f}s ({audio_end/60:.1f} min)")
    print()

    timestamps = []
    last_end   = 0.0

    for i, sec in enumerate(sections):
        label    = sec["label"]
        parts    = label.split("_", 1)
        name     = parts[1] if len(parts) > 1 else label
        is_hook  = "HOOK"   in label.upper()
        is_cierre= "CIERRE" in label.upper() or "OUTRO" in label.upper()

        if is_hook:
            t_start = 0.0
        elif is_cierre:
            t_start = last_end
        else:
            # Buscar nombre del artista en el SRT a partir del final de la sección anterior
            # search_until: hasta 60% del audio hacia adelante para evitar referencias cruzadas
            window_end = min(audio_end, last_end + (audio_end - last_end) * 0.7)
            found = find_artist_start(srt_entries, name,
                                      search_from=max(0, last_end - 5),
                                      search_until=window_end)
            if found is not None:
                t_start = found
                print(f"  ✓ '{name}' encontrado en SRT a {t_start:.1f}s")
            else:
                # Fallback: interpolación por proporción de chars
                ratio   = sec["char_start"] / sections[-1]["char_end"]
                t_start = round(ratio * audio_end, 2)
                print(f"  ⚠ '{name}' NO encontrado en SRT — usando interpolación: {t_start:.1f}s")

        # El fin de esta sección = inicio de la siguiente (o fin del audio)
        if i + 1 < len(sections):
            next_sec   = sections[i + 1]
            next_label = next_sec["label"]
            next_name  = next_label.split("_", 1)[1] if "_" in next_label else next_label
            next_is_cierre = "CIERRE" in next_label.upper() or "OUTRO" in next_label.upper()

            if next_is_cierre:
                # Simpler: just use the last 8 seconds for cierre
                t_end = audio_end - 8
            else:
                next_window = min(audio_end, t_start + (audio_end - t_start) * 0.7)
                found_next = find_artist_start(srt_entries, next_name,
                                               search_from=t_start + 10,
                                               search_until=next_window)
                t_end = found_next if found_next else audio_end
        else:
            t_end = audio_end

        t_start = round(t_start, 2)
        t_end   = round(t_end, 2)
        last_end = t_end  # para la búsqueda del siguiente: empezar desde donde terminó este

        entry = {
            "label":     label,
            "name":      name,
            "start":     t_start,
            "end":       t_end,
            "duration":  round(t_end - t_start, 2),
            "is_hook":   is_hook,
            "is_cierre": is_cierre,
            "folder":    None if (is_hook or is_cierre) else name,
        }
        timestamps.append(entry)
        tag = "HOOK" if is_hook else ("CIERRE" if is_cierre else "artista")
        print(f"  [{tag:7s}] {name:30s} {t_start:7.1f}s → {t_end:7.1f}s  ({entry['duration']:.1f}s)")

    out_timestamps.write_text(json.dumps(timestamps, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ timestamps.json guardado → {out_timestamps}")

if __name__ == "__main__":
    main()
