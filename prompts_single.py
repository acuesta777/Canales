#!/usr/bin/env python3
"""
prompts_single.py — Genera prompts de imagen analizando los 10 primeros minutos del SRT.
- Detecta si la persona está viva o muerta → estilo moderno vs rancho/hacienda antigua
- Detecta temas: fortuna, mansión, autos, lugar de nacimiento, patrimonio, etc.
- Prompts simples en inglés para el generador, descripción en español para el usuario
- ~1 imagen por minuto de SRT (hasta 10)
"""

import sys, re, pathlib, csv

# ── Temas a detectar ────────────────────────────────────────────────────────
TEMAS = [
    # Fortuna/dinero → SIEMPRE mansión, nunca billetes ni trofeos
    {
        "id": "fortuna",
        "es": "Fortuna / patrimonio",
        "keywords": ["fortuna", "millones", "dólares", "patrimonio", "rico", "riqueza",
                     "dinero", "ingresos", "ganancias", "reales", "billete", "estimada"],
        "prompt_vivo":   "Aerial view of a large modern luxury mansion with swimming pool and gardens, tropical setting, realistic photo, 16:9",
        "prompt_muerto": "Aerial view of a large old hacienda with courtyard fountain and green fields, realistic photo, 16:9",
    },
    # Mansión/propiedad → mansión de lujo
    {
        "id": "mansion",
        "es": "Mansión / propiedad de lujo",
        "keywords": ["mansión", "penthouse", "villa", "residencia", "propiedad",
                     "apartamento", "suite", "hacienda", "rancho", "piscina"],
        "prompt_vivo":   "Modern luxury mansion with infinity pool overlooking the ocean at sunset, realistic photo, 16:9",
        "prompt_muerto": "Grand old Mexican hacienda with red tile roof and bougainvillea, realistic photo, 16:9",
    },
    # Lugar de nacimiento → pueblo humilde
    {
        "id": "nacimiento",
        "es": "Lugar de nacimiento / pueblo humilde",
        "keywords": ["nació", "pueblo", "ciudad natal", "infancia", "creció",
                     "humilde", "pobre", "barrio", "clase trabajadora", "provincia"],
        "prompt_vivo":   "Small humble town with cobblestone streets and simple colorful houses, realistic photo, 16:9",
        "prompt_muerto": "Small humble town with dirt roads and old buildings, 1940s style, realistic photo, 16:9",
    },
    # Autos → colección de autos, sin rostros
    {
        "id": "autos",
        "es": "Colección de autos de lujo",
        "keywords": ["auto", "carro", "coche", "ferrari", "lamborghini", "cadillac",
                     "audi", "colección", "garaje", "vehículo", "deportivo", "calhambeque"],
        "prompt_vivo":   "Collection of luxury sports cars lined up inside a large private modern garage, realistic photo, 16:9",
        "prompt_muerto": "Row of classic vintage luxury cars in a large private garage, 1960s style, realistic photo, 16:9",
    },
    # Jet privado → jet, no personas
    {
        "id": "jet",
        "es": "Jet privado",
        "keywords": ["jet", "avión", "vuelo", "hangar", "privado", "aeronave"],
        "prompt_vivo":   "Luxury private white jet parked on a sunny airport tarmac, no people, realistic photo, 16:9",
        "prompt_muerto": "Vintage private propeller plane on a 1950s airport tarmac, no people, realistic photo, 16:9",
    },
    # Escenario → público visible, NO primer plano del artista
    {
        "id": "carrera",
        "es": "Escenario de concierto con público",
        "keywords": ["escenario", "concierto", "estadio", "show", "gira", "televisión",
                     "programa", "actuó", "cantó", "grabó", "discos", "álbum", "orquesta",
                     "presentación", "espectáculo"],
        "prompt_vivo":   "Wide shot of a massive concert stage with colorful lights and a huge crowd of thousands, no close up of artist face, realistic photo, 16:9",
        "prompt_muerto": "Wide shot of a 1960s television variety show stage with large studio audience, vintage look, no close up of artist face, realistic photo, 16:9",
    },
    # Premios → SIEMPRE mansión, nunca trofeo
    {
        "id": "premios",
        "es": "Premios / éxito → mansión de lujo",
        "keywords": ["grammy", "premio", "trayectoria", "reconocimiento", "galardón",
                     "persona del año", "globo", "nominado", "latin grammy"],
        "prompt_vivo":   "Modern luxury mansion with large swimming pool and palm trees at night with lights, realistic photo, 16:9",
        "prompt_muerto": "Large old elegant mansion with gardens lit up at night, vintage style, realistic photo, 16:9",
    },
    # Negocios/inversiones → edificio o mansión, sin personas
    {
        "id": "negocios",
        "es": "Negocios / inversiones",
        "keywords": ["negocio", "empresa", "inversión", "constructora", "socio",
                     "edificio", "inmueble", "derechos de autor"],
        "prompt_vivo":   "Modern luxury high-rise apartment building in a big city at night, no people, realistic photo, 16:9",
        "prompt_muerto": "Old elegant commercial building in a city in the 1950s, no people, realistic photo, 16:9",
    },
    # Yate → yate, sin personas
    {
        "id": "yacht",
        "es": "Yate de lujo",
        "keywords": ["yate", "barco", "navegó", "mar", "bahía", "embarcación"],
        "prompt_vivo":   "Large white luxury yacht anchored in a tropical bay with clear blue water, no people, realistic photo, 16:9",
        "prompt_muerto": "Classic wooden luxury yacht moored in a calm marina, 1960s style, no people, realistic photo, 16:9",
    },
    # Familia/amor → NO incluir, podría mostrar cara inventada
    # Se omite intencionalmente
]

# ── Parsear SRT ──────────────────────────────────────────────────────────────
def parsear_srt(srt_path):
    """Devuelve lista de (segundos_float, texto) por cada bloque SRT."""
    contenido = pathlib.Path(srt_path).read_text(encoding="utf-8")
    bloques = re.split(r'\n\n+', contenido.strip())
    resultado = []
    for bloque in bloques:
        lineas = bloque.strip().split('\n')
        if len(lineas) < 3 or '-->' not in lineas[1]:
            continue
        inicio = lineas[1].split('-->')[0].strip()
        partes = re.split(r'[:,]', inicio)
        segundos = int(partes[0]) * 3600 + int(partes[1]) * 60 + int(partes[2])
        texto = ' '.join(lineas[2:])
        resultado.append((segundos, texto))
    return resultado

# ── Detectar si vive o murió ──────────────────────────────────────────────────
def detectar_estado(guion):
    g = guion.lower()
    if "así fue la lujosa vida" in g:
        return "muerto"
    patrones = [r'falleció en \d{4}', r'murió en \d{4}', r'murió el \d',
                r'fallecimiento', r'muerte en \d{4}']
    for p in patrones:
        if re.search(p, g):
            return "muerto"
    return "vivo"

# ── Detectar temas por segundo exacto ────────────────────────────────────────
def detectar_temas_por_segundo(entradas, max_segundos=300):
    """
    Recorre cada bloque SRT en orden. Si el texto menciona una keyword de riqueza,
    registra el segundo exacto de ese bloque. Un tema solo se usa una vez.
    Solo procesa los primeros max_segundos (5 min por defecto).
    """
    temas_vistos = set()
    resultado = []
    for (seg, texto) in entradas:
        if seg >= max_segundos:
            break
        texto_low = texto.lower()
        for tema in TEMAS:
            if tema["id"] in temas_vistos:
                continue
            if any(kw in texto_low for kw in tema["keywords"]):
                resultado.append((seg, tema))
                temas_vistos.add(tema["id"])
                break
    return resultado

def segundos_a_timestamp(seg):
    h = seg // 3600
    m = (seg % 3600) // 60
    s = seg % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Uso: python3 prompts_single.py <carpeta_personaje>")
        sys.exit(1)

    carpeta = pathlib.Path(sys.argv[1])
    nombre  = carpeta.name
    srt_file = carpeta / f"{nombre}.srt"
    txt_file = carpeta / f"{nombre}.txt"
    csv_out  = carpeta / f"{nombre}_prompts.csv"

    if not srt_file.exists():
        print(f"ERROR: No encontré {srt_file}"); sys.exit(1)
    if not txt_file.exists():
        print(f"ERROR: No encontré {txt_file}"); sys.exit(1)

    guion   = txt_file.read_text(encoding="utf-8")
    estado  = detectar_estado(guion)
    key     = f"prompt_{estado}"

    entradas    = parsear_srt(srt_file)
    detecciones = detectar_temas_por_segundo(entradas, max_segundos=300)

    if not detecciones:
        print("ERROR: No se detectaron temas en el SRT"); sys.exit(1)

    print(f"\n{'='*58}")
    print(f"  PROMPTS — {nombre.upper()}")
    print(f"  Estado: {estado.upper()} | Imágenes: {len(detecciones)}")
    print(f"{'='*58}")

    filas = []
    for (seg, tema) in detecciones:
        ts        = segundos_a_timestamp(seg)
        prompt_en = tema[key]
        desc_es   = tema["es"]
        filas.append({"seg_inicio": ts, "prompt": prompt_en, "descripcion_es": desc_es})
        print(f"\n  [{ts}] {desc_es}")
        print(f"         → {prompt_en}")

    print(f"\n{'='*58}")
    print(f"  Total: {len(filas)} imágenes detectadas")
    print(f"{'='*58}\n")

    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["seg_inicio", "prompt", "descripcion_es"])
        w.writeheader()
        w.writerows(filas)

    print(f"✓ CSV guardado: {csv_out}")

if __name__ == "__main__":
    main()
