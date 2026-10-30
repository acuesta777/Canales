#!/usr/bin/env python3
"""
generar_sync.py — Genera el CSV de sincronización imagen-narración automáticamente.
Lee el SRT completo, detecta el tema de cada segmento y asigna la imagen más relevante.

Uso: python3 generar_sync.py <personaje> [--srt archivo.srt] [--output sync.csv]

Ejemplo:
  python3 generar_sync.py adriano
  python3 generar_sync.py caniggia --srt caniggia.srt --output caniggia_sync.csv
"""
import sys, re, csv, os
from pathlib import Path

BASE = Path("/Users/anyelocuesta/Downloads/Canales/futbol")

# ── DICCIONARIO SEMÁNTICO ─────────────────────────────────────────────────────
# Cada entrada: (palabras_clave, descripcion, prioridad)
# Palabras separadas por | = OR. Las primeras entradas tienen mayor prioridad.
CATEGORIAS = [
    # Infancia / favela / pobreza
    (["favela","villa","barrio","pobreza","niño","niños","descalzo","callejón",
      "tierra","kiosco","amigos de siempre","dominó","creció","nació en",
      "vila cruzeiro","nana","naná","pequeño","infancia","humilde",
      "comunidad","barrio pobre"],
     "favela infancia barrio", "infancia"),

    # Padre / muerte / duelo
    (["padre","papá","murió","muriero","muerte","falleci","falleció","duelo",
      "perder","perdió","dolor","luto","lloró","lloraba","lagri"],
     "padre muerte duelo familia", "padre"),

    # Madre / familia
    (["madre","mamá","familia","hermano","hermana","abuela","rosilda","wanda",
      "casa","llamada","teléfono","brasil","rio"],
     "madre familia Brasil", "familia"),

    # Inter de Milán
    (["inter","milán","milan","san siro","moratti","hernan crespo","campeão",
      "scudetto","champions","serie a","italia","hat-trick","porto",
      "2005","2004","2003","sucesor ronaldo","mejor jugador"],
     "Inter Milan Europa", "inter"),

    # Selección Brasil
    (["selección","brasil","brasileña","seleção","canarinha","copa america",
      "mundial","confederaciones","gol","goleador","27 goles","argentina",
      "amarilla","verde","cancha","estadio nacional"],
     "selección Brasil Copa América", "brasil"),

    # Parma / inicio carrera
    (["parma","mutu","debut","primera","joven","talento","italia","serie b",
      "22 goles","traspaso","fichaje","empezó","comenzó"],
     "Parma inicio carrera", "parma"),

    # Alcohol / adicción / caída
    (["vodka","alcohol","bebida","bebiendo","copa","botella","fiesta",
      "noche","apartamento","solo","soledad","depresión","deprimido",
      "navidad","tristeza","perdido","caída","declive"],
     "soledad alcohol caída", "caida"),

    # Regreso favela / retiro actual
    (["regresó","volvió","retiro","hoy","43 años","barra da tijuca",
      "actual","ahora","kiosco","copa en la mano","convicción",
      "elige vivir","villa cruz"],
     "regreso favela vida actual", "retiro"),

    # Goles / estadio / gloría
    (["gol","golazo","anotó","marcó","metió","hat-trick","rugido",
      "estadio","tribuna","afición","celebra","celebración","campeón"],
     "goles estadio gloria", "goles"),

    # Flamengo / inicio Brasil
    (["flamengo","cantera","río","juvenil","base","primera vez","llegó",
      "debut","1997","1998","rio de janeiro"],
     "Flamengo cantera juvenil", "flamengo"),

    # Reflexión / cierre filosófico
    (["qué es","preguntarse","reflexión","verdad","felicidad","éxito",
      "definir","eso sí","aprendió","legado","recuerda","leyenda","historia",
      "paradoja","pregunta","lección","destino","así termina","así acaba"],
     "reflexión filosófica cierre", "reflexion"),

    # Hook de intro / grandeza / millones / contratos
    (["millones","euros","contrato","marcas internacionales","sucesor","rey",
      "mundo del fútbol","7 millones","ganaba","apartamento en mil",
      "séptimo mejor","elegido","mejor del mundo","balón de oro"],
     "gloria contratos éxito máximo", "gloria"),
]

# Mapa de categoría → lista de imágenes de imagenes_web recomendadas
# Esto se define POR PERSONAJE en el diccionario de abajo.
# La llave es (personaje, categoria)
IMAGENES_POR_CATEGORIA = {
    # ── ADRIANO ──────────────────────────────────────────────────
    ("adriano", "infancia"):  ["11.jpg","24.jpg","12.jpg","13.jpg"],
    ("adriano", "padre"):     ["12.jpg","13.jpg","11.jpg"],
    ("adriano", "familia"):   ["12.jpg","11.jpg","13.jpg"],
    ("adriano", "inter"):     ["1.jpg","2.jpg","3.jpg","19.jpg","7.jpg"],
    ("adriano", "brasil"):    ["6.jpg","8.jpg","15.jpg","5.jpg","17.jpg"],
    ("adriano", "parma"):     ["21.jpg","4.jpg","22.jpg"],
    ("adriano", "caida"):     ["9.jpg","14.jpg","10.jpg","16.jpg"],
    ("adriano", "retiro"):    ["26.jpg","11.jpg","12.jpg","27.jpg"],
    ("adriano", "goles"):     ["2.jpg","3.jpg","7.jpg","8.jpg","15.jpg"],
    ("adriano", "flamengo"):  ["6.jpg","5.jpg","20.jpg"],
    ("adriano", "reflexion"): ["26.jpg","13.jpg","17.jpg"],
    ("adriano", "gloria"):    ["1.jpg","2.jpg","3.jpg","7.jpg","17.jpg"],

    # ── CANIGGIA ─────────────────────────────────────────────────
    # (se completará cuando tenga imagenes_web de caniggia)
}

def parse_srt(srt_path):
    """Retorna lista de (segundos_inicio, texto)."""
    content = Path(srt_path).read_text(encoding="utf-8")
    blocks = content.strip().split("\n\n")
    result = []
    for b in blocks:
        lines = b.strip().split("\n")
        if len(lines) < 3:
            continue
        ts = lines[1]
        text = " ".join(lines[2:]).strip()
        m = re.match(r"(\d+):(\d+):(\d+)", ts)
        if m:
            secs = int(m.group(1))*3600 + int(m.group(2))*60 + int(m.group(3))
            result.append((secs, text))
    return result

def secs_a_ts(secs):
    h = secs // 3600
    m = (secs % 3600) // 60
    s = secs % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def detectar_categoria(texto):
    """Devuelve la categoría con más coincidencias, o None."""
    texto_lower = texto.lower()
    scores = {}
    for keywords, desc, cat in CATEGORIAS:
        score = sum(1 for kw in keywords if kw in texto_lower)
        if score > 0:
            scores[cat] = scores.get(cat, 0) + score
    if not scores:
        return None
    return max(scores, key=scores.get)

def acumular_bloques(blocks, ventana_secs=15):
    """Agrupa bloques SRT en ventanas de N segundos para más contexto."""
    grupos = []
    i = 0
    while i < len(blocks):
        inicio = blocks[i][0]
        textos = []
        j = i
        while j < len(blocks) and blocks[j][0] < inicio + ventana_secs:
            textos.append(blocks[j][1])
            j += 1
        grupos.append((inicio, " ".join(textos)))
        i = j if j > i else i + 1
    return grupos

def generar_sync(personaje, srt_path, output_path, intervalo_secs=30):
    """
    Lee el SRT, agrupa en ventanas, detecta categoría, asigna imagen.
    Genera un cambio de imagen cada `intervalo_secs` segundos.
    """
    blocks = parse_srt(srt_path)
    if not blocks:
        print(f"ERROR: No se pudo leer {srt_path}")
        sys.exit(1)

    grupos = acumular_bloques(blocks, ventana_secs=20)
    total_secs = blocks[-1][0]

    print(f"  SRT: {len(blocks)} bloques, {total_secs//60} min {total_secs%60}s")
    print(f"  Grupos de 20s: {len(grupos)}")

    # Construir timeline de cambios cada `intervalo_secs`
    # Para cada punto de cambio, buscar el grupo SRT más cercano y su categoría
    filas = []
    img_usada = {}  # categoría → índice rotativo
    ultima_img = None

    usadas_global = set()  # evita repetir cualquier imagen en todo el CSV

    t = 0
    while t <= total_secs:
        # Texto alrededor de t
        texto_ventana = ""
        for secs, txt in blocks:
            if abs(secs - t) <= 20:
                texto_ventana += " " + txt

        cat = detectar_categoria(texto_ventana) if texto_ventana.strip() else None
        key = (personaje, cat) if cat else None
        imgs = IMAGENES_POR_CATEGORIA.get(key, []) if key else []

        # Buscar imagen no usada globalmente
        img = None
        if imgs:
            for offset in range(len(imgs)):
                idx = (img_usada.get(cat, 0) + offset) % len(imgs)
                candidata = imgs[idx]
                if candidata not in usadas_global:
                    img = candidata
                    img_usada[cat] = idx + 1
                    break
            # Si todas las de esta categoría ya se usaron, liberar y tomar la primera
            if img is None:
                for i_lib in imgs:
                    usadas_global.discard(i_lib)
                img_usada[cat] = 1
                img = imgs[0]
                usadas_global.add(img)

        if img:
            usadas_global.add(img)
            fuente = "imagenes_web"
            desc = f"{cat} — {texto_ventana.strip()[:60]}"
        else:
            # Sin categoría clara → saltar (render usará pool aleatorio)
            t += intervalo_secs
            continue

        filas.append({
            "seg_inicio": secs_a_ts(t),
            "fuente": fuente,
            "archivo": img,
            "descripcion": desc[:80]
        })
        ultima_img = img
        t += intervalo_secs

    # Escribir CSV
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["seg_inicio","fuente","archivo","descripcion"])
        writer.writeheader()
        writer.writerows(filas)

    print(f"  → {len(filas)} entradas escritas en {output_path}")
    return filas

def main():
    if len(sys.argv) < 2:
        print("Uso: python3 generar_sync.py <personaje> [--srt archivo.srt] [--output sync.csv]")
        sys.exit(1)

    personaje = sys.argv[1].lower()
    carpeta = BASE / personaje

    # Defaults
    srt_path = None
    output_path = carpeta / f"{personaje}_sync.csv"

    # Parsear args opcionales
    args = sys.argv[2:]
    i = 0
    while i < len(args):
        if args[i] == "--srt" and i+1 < len(args):
            srt_path = Path(args[i+1])
            i += 2
        elif args[i] == "--output" and i+1 < len(args):
            output_path = Path(args[i+1])
            i += 2
        else:
            i += 1

    # Buscar SRT automáticamente si no se especificó
    if srt_path is None:
        candidatos = list(carpeta.glob("*.srt"))
        if not candidatos:
            print(f"ERROR: No se encontró .srt en {carpeta}")
            sys.exit(1)
        srt_path = candidatos[0]

    print(f"\n{'='*60}")
    print(f"  GENERADOR DE SYNC SEMÁNTICO")
    print(f"{'='*60}")
    print(f"  Personaje: {personaje}")
    print(f"  SRT: {srt_path}")
    print(f"  Output: {output_path}")
    print(f"{'='*60}\n")

    filas = generar_sync(personaje, srt_path, output_path)

    print(f"\n{'='*60}")
    print(f"  ✅ Sync generado: {len(filas)} cambios de imagen")
    print(f"  Categorías asignadas:")
    cats = {}
    for f in filas:
        cat = f["descripcion"].split(" — ")[0]
        cats[cat] = cats.get(cat, 0) + 1
    for cat, cnt in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"    {cat}: {cnt}x")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
