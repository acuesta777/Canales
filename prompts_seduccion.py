#!/usr/bin/env python3
"""
prompts_seduccion.py — Genera el CSV de prompts de imagen para el canal Enigma Estoica.

A diferencia de prompts_single.py (canal riqueza/mansiones), este script genera
prompts cinematográficos de atmósfera masculina: situaciones sociales, interacción,
psicología, presencia — sin menciones de lujo ni propiedades.

Uso:
    python3 prompts_seduccion.py <carpeta_video>
    python3 prompts_seduccion.py seduccion/no_eres_malo/

Salida:
    <carpeta_video>/<nombre>_prompts.csv
    Campos: seg_inicio, prompt, descripcion_es
"""

import sys, re, pathlib, csv

# ── Temas detectables en guion de seducción ──────────────────────────────────

TEMAS = [
    {
        "id": "apertura_contraste",
        "es": "Apertura — dos hombres, resultados opuestos",
        "keywords": ["hombre a", "hombre b", "mientras uno", "algunos hombres", "hay hombres que",
                     "contraste", "diferencia entre"],
        "prompt": "two men in contrasting social situations, one confident talking to a woman, one alone looking down, cinematic warm lighting, dramatic shadows, photorealistic, 16:9",
    },
    {
        "id": "dolor_social",
        "es": "Escena de dolor — quedarse sin palabras",
        "keywords": ["sin palabras", "cabeza en blanco", "te bloqueás", "te paraliz", "silencio incómodo",
                     "no sabes qué decir", "te quedás mudo", "sensación de hundimiento"],
        "prompt": "man standing awkwardly near a woman in a social setting, looking tense, urban cafe environment, cinematic burnt orange tones, photorealistic, 16:9",
    },
    {
        "id": "confianza_masculina",
        "es": "Hombre seguro — presencia y postura",
        "keywords": ["confianza", "seguro de sí", "seguridad", "autoestima", "presencia",
                     "magnético", "carisma", "hombre que sabe"],
        "prompt": "confident man standing tall with strong posture in an urban street at golden hour, dramatic side lighting, masculine atmosphere, cinematic, 16:9",
    },
    {
        "id": "conversacion_atraccion",
        "es": "Conversación con atracción — dos personas conectando",
        "keywords": ["conversación", "conversar", "hablar con ella", "atracción", "conexión",
                     "diálogo", "charla", "hablar con mujeres", "iniciar"],
        "prompt": "man and woman having an engaging conversation at a warm cafe, leaning in, natural chemistry, cinematic warm tones, photorealistic, 16:9",
    },
    {
        "id": "error_comun",
        "es": "El error — paradigma mental erróneo",
        "keywords": ["error", "equivocación", "trampa", "ilusión", "el problema es",
                     "lo que hacen mal", "por qué falla", "incorrecto", "mal hábito"],
        "prompt": "man sitting alone at a bar looking frustrated and thoughtful, dark warm ambiance, cinematic, photorealistic, 16:9",
    },
    {
        "id": "lenguaje_corporal",
        "es": "Lenguaje corporal — postura, mirada, gestos",
        "keywords": ["lenguaje corporal", "postura", "mirada", "contacto visual", "gestos",
                     "cómo te movés", "cómo te parás"],
        "prompt": "close up of man's confident posture and eye contact, warm dramatic lighting, cinematic atmosphere, 16:9, no face clearly visible",
    },
    {
        "id": "psicologia_atraccion",
        "es": "Psicología — por qué funciona la atracción",
        "keywords": ["psicología", "cerebro", "mente", "subconsciente", "biología",
                     "estudio", "según la ciencia", "investigación", "psicológico"],
        "prompt": "abstract visualization of human minds connecting, warm orange and dark tones, cinematic atmosphere, 16:9",
    },
    {
        "id": "rechazo_indiferencia",
        "es": "Rechazo — la mujer que ignora",
        "keywords": ["rechazo", "ignorado", "ella te ignora", "indiferencia", "frialdad",
                     "no te nota", "sin interés"],
        "prompt": "woman looking away from man in an urban setting, cold body language, dramatic cinematic lighting, photorealistic, 16:9",
    },
    {
        "id": "transformacion",
        "es": "Transformación — el cambio que propone el video",
        "keywords": ["cambio", "transformación", "cuando aprendas", "una vez que", "si aplicas",
                     "vas a notar", "vas a ver", "resultado"],
        "prompt": "man walking forward confidently through a city street at night, warm street lights, silhouette, cinematic, photorealistic, 16:9",
    },
    {
        "id": "ambiente_social",
        "es": "Ambiente social — bar, evento, calle",
        "keywords": ["bar", "fiesta", "evento", "salir", "noche", "reunión", "social",
                     "ambiente", "lugar", "café"],
        "prompt": "warm dimly lit bar with people socializing in the background, bokeh lights, cinematic atmosphere, photorealistic, 16:9",
    },
    {
        "id": "observacion_detalles",
        "es": "Observación — notar detalles, estar presente",
        "keywords": ["observar", "notar", "detalles", "presente", "atención",
                     "percibir", "escuchar de verdad"],
        "prompt": "man observing his surroundings thoughtfully, warm bokeh background, cinematic close-up, photorealistic, 16:9",
    },
    {
        "id": "framework_tecnica",
        "es": "Framework — los elementos del sistema",
        "keywords": ["elemento", "componente", "parte", "los tres", "los siete", "los cinco",
                     "primer elemento", "segundo elemento", "primer punto", "primero"],
        "prompt": "cinematic split composition showing three distinct masculine environments, warm orange and dark brown tones, photorealistic, 16:9",
    },
    {
        "id": "cierre_reflexion",
        "es": "Cierre filosófico — reflexión final",
        "keywords": ["al final del día", "en definitiva", "lo que importa", "la verdad es",
                     "recordá que", "llevate esto", "el objetivo no es", "lo que realmente"],
        "prompt": "man standing alone at night looking at city lights below, contemplative mood, cinematic warm tones, silhouette, photorealistic, 16:9",
    },
]

TEMA_GENERICO = {
    "id": "generico",
    "es": "Escena masculina — atmósfera general",
    "prompt": "cinematic masculine atmosphere, man in urban environment, warm burnt orange and dark brown tones, dramatic lighting, photorealistic, 16:9",
}

# ── Parsear SRT ──────────────────────────────────────────────────────────────

def parsear_srt(srt_path):
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

# ── Detectar temas ────────────────────────────────────────────────────────────

def detectar_temas(entradas, max_segundos=600):
    """
    Analiza los primeros max_segundos (10 min por defecto).
    Cada tema solo se usa una vez. Una imagen por cada ~45s de contenido.
    """
    temas_vistos = set()
    resultado = []
    ultima_imagen_seg = -45

    for (seg, texto) in entradas:
        if seg >= max_segundos:
            break

        # No poner dos imágenes en menos de 45 segundos
        if seg - ultima_imagen_seg < 45:
            continue

        texto_low = texto.lower()
        tema_asignado = None

        for tema in TEMAS:
            if tema["id"] in temas_vistos:
                continue
            if any(kw in texto_low for kw in tema["keywords"]):
                tema_asignado = tema
                temas_vistos.add(tema["id"])
                break

        # Si no matchea nada y hace >90s que no pusimos imagen, ponemos genérica
        if not tema_asignado and seg - ultima_imagen_seg >= 90:
            tema_asignado = {**TEMA_GENERICO, "id": f"generico_{seg}"}

        if tema_asignado:
            resultado.append((seg, tema_asignado))
            ultima_imagen_seg = seg

    return resultado


def segundos_a_ts(seg):
    h = seg // 3600
    m = (seg % 3600) // 60
    s = seg % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 prompts_seduccion.py <carpeta_video>")
        sys.exit(1)

    carpeta = pathlib.Path(sys.argv[1])
    nombre  = carpeta.name

    # Buscar SRT
    srt_file = carpeta / f"{nombre}.srt"
    if not srt_file.exists():
        srts = list((carpeta / "02-locucion").glob("*.srt")) if (carpeta / "02-locucion").exists() else []
        if srts:
            srt_file = srts[0]
        else:
            print(f"ERROR: No encontré SRT en {carpeta}"); sys.exit(1)

    csv_out = carpeta / f"{nombre}_prompts.csv"

    entradas   = parsear_srt(srt_file)
    detecciones = detectar_temas(entradas, max_segundos=600)

    if not detecciones:
        print("ERROR: No se detectaron temas en el SRT"); sys.exit(1)

    print(f"\n{'='*58}")
    print(f"  PROMPTS SEDUCCIÓN — {nombre.upper()}")
    print(f"  Imágenes: {len(detecciones)}")
    print(f"{'='*58}")

    filas = []
    for (seg, tema) in detecciones:
        ts = segundos_a_ts(seg)
        filas.append({
            "seg_inicio":    ts,
            "prompt":        tema["prompt"],
            "descripcion_es": tema["es"],
        })
        print(f"\n  [{ts}] {tema['es']}")
        print(f"         → {tema['prompt'][:80]}...")

    print(f"\n{'='*58}")
    print(f"  Total: {len(filas)} imágenes")
    print(f"{'='*58}\n")

    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["seg_inicio", "prompt", "descripcion_es"])
        w.writeheader()
        w.writerows(filas)

    print(f"✓ CSV guardado: {csv_out}")

if __name__ == "__main__":
    main()
