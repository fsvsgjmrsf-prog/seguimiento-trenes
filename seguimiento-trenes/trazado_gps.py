"""Construye el trazado de la vía Valencia J. Sorolla - Madrid Chamartín con las
posiciones GPS reales de los trenes que publica Renfe.

En cada ejecución guarda las posiciones de los trenes que circulan por un tramo
de esta línea (en <carpeta>/posiciones.json) y rehace <carpeta>/trazado.json:
los puntos se ordenan a lo largo de la línea aproximada de Renfe y los huecos
que aún no tienen observaciones se rellenan con esa línea aproximada.
Cuantos más días pasen, más fiel es el trazado.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from seguimiento import CHAMARTIN, FLOTA_URL, RUTAS_URL, VALENCIA, descargar  # noqa: E402

APROXIMADO = os.path.join(os.path.dirname(__file__), "..", "grafana", "trazado.json")
MAX_POSICIONES = 30000
MAX_DESVIO_KM = 12   # puntos más lejos de la línea aproximada se descartan
HUECO_KM = 5         # huecos mayores se rellenan con la línea aproximada


def km(a, b):
    dy = (a[0] - b[0]) * 111.2
    dx = (a[1] - b[1]) * 111.2 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def tramos_de_la_linea(rutas):
    """Pares de estaciones consecutivas de los trenes Valencia <-> Chamartín."""
    pares = set()
    for t in rutas.get("trenes", []):
        cods = [p.get("p") for p in t.get("estaciones", [])]
        if VALENCIA in cods and CHAMARTIN in cods:
            i, j = sorted((cods.index(VALENCIA), cods.index(CHAMARTIN)))
            for a, b in zip(cods[i:j], cods[i + 1:j + 1]):
                pares.add(frozenset((a, b)))
    return pares


def posiciones_nuevas(flota, rutas):
    pares = tramos_de_la_linea(rutas)
    out = []
    for t in flota.get("trenes", []):
        try:
            lat, lon = float(t["latitud"]), float(t["longitud"])
        except (KeyError, TypeError, ValueError):
            continue
        if not lat or not lon:
            continue
        if frozenset((t.get("codEstAnt"), t.get("codEstSig"))) in pares:
            out.append([round(lat, 4), round(lon, 4)])
    return out


def proyectar(p, linea, acumulado):
    """Distancia recorrida a lo largo de la línea y desvío lateral, en km."""
    mejor = (1e9, 0.0)
    for i, (a, b) in enumerate(zip(linea, linea[1:])):
        cx = math.cos(math.radians(a[0]))
        ax, ay, bx, by, px, py = a[1] * cx, a[0], b[1] * cx, b[0], p[1] * cx, p[0]
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy or 1e-12
        u = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
        q = (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
        d = km(p, q)
        if d < mejor[0]:
            mejor = (d, acumulado[i] + km(a, b) * u)
    return mejor[1], mejor[0]


def densificar(pts, paso_km=1.2):
    out = []
    for a, b in zip(pts, pts[1:]):
        k = max(1, math.ceil(km(a, b) / paso_km))
        out += [(a[0] + (b[0] - a[0]) * i / k, a[1] + (b[1] - a[1]) * i / k) for i in range(k)]
    out.append(pts[-1])
    return out


def acumular(linea):
    acum = [0.0]
    for a, b in zip(linea, linea[1:]):
        acum.append(acum[-1] + km(a, b))
    return acum


def curva(puntos, linea, tramo_km):
    """Agrupa los puntos por tramos a lo largo de `linea` y devuelve sus centros."""
    acum = acumular(linea)
    grupos = {}
    for p in puntos:
        s, d = proyectar(p, linea, acum)
        if d <= MAX_DESVIO_KM:
            grupos.setdefault(int(s // tramo_km), []).append((s, p))
    centros = []
    for k in sorted(grupos):
        g = grupos[k]
        centros.append((sum(x for x, _ in g) / len(g),
                        (sum(p[0] for _, p in g) / len(g), sum(p[1] for _, p in g) / len(g))))
    # Huecos sin observaciones: tramo de la línea de referencia.
    pts, previo = [linea[0]], 0.0
    for sc, c in centros + [(acum[-1], linea[-1])]:
        if sc - previo > HUECO_KM:
            pts += [linea[i] for i in range(len(linea)) if previo < acum[i] < sc]
        pts.append(c)
        previo = sc
    return pts


def suavizar(pts, n=1):
    out = list(pts)
    for i in range(n, len(pts) - n):
        v = pts[i - n:i + n + 1]
        out[i] = (sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v))
    return out


def construir(posiciones, linea):
    ref = linea
    # Se repite: cada vuelta ordena los puntos sobre la curva obtenida en la anterior.
    for tramo in (4.0, 3.0, 2.0, 1.5):
        ref = suavizar(curva(posiciones, ref, tramo))
    return densificar(ref), len(ref)


def main():
    carpeta = sys.argv[1] if len(sys.argv) > 1 else "."
    ruta_pos = os.path.join(carpeta, "posiciones.json")
    try:
        with open(ruta_pos) as f:
            posiciones = json.load(f)
    except (OSError, ValueError):
        posiciones = []

    try:
        nuevas = posiciones_nuevas(descargar(FLOTA_URL), descargar(RUTAS_URL))
    except RuntimeError as e:
        print(f"Aviso: sin posiciones nuevas ({e})")
        nuevas = []
    vistas = {tuple(p) for p in posiciones}
    posiciones += [p for p in nuevas if tuple(p) not in vistas]
    posiciones = posiciones[-MAX_POSICIONES:]
    with open(ruta_pos, "w") as f:
        json.dump(posiciones, f, separators=(",", ":"))

    with open(APROXIMADO) as f:
        aprox = [(q["lat"], q["lon"]) for q in json.load(f)["puntos"]]
    linea = aprox[::6] + [aprox[-1]]
    pts, n = construir(posiciones, linea)
    with open(os.path.join(carpeta, "trazado.json"), "w") as f:
        json.dump({"fuente": "gps", "observaciones": len(posiciones), "tramos_gps": n,
                   "puntos": [{"lat": round(a, 5), "lon": round(b, 5)} for a, b in pts]}, f,
                  separators=(",", ":"))
    print(f"Trazado: {len(posiciones)} posiciones GPS (+{len(nuevas)}), {len(pts)} puntos")


if __name__ == "__main__":
    main()
