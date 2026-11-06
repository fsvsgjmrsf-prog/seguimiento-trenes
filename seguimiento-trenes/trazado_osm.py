"""Descarga una vez el trazado real de la vía Valencia J. Sorolla - Madrid Chamartín
desde OpenStreetMap y lo guarda en <carpeta>/trazado.json para el mapa de Grafana.

Busca el camino más corto por la red ferroviaria entre las dos estaciones,
dando preferencia a las vías de alta velocidad. Si algo falla, no toca el archivo.
"""
import heapq
import json
import math
import os
import sys
import urllib.parse
import urllib.request

VALENCIA = (39.45986, -0.3823)
CHAMARTIN = (40.47423, -3.68151)
SERVIDORES = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
# Línea aproximada de Renfe: solo se piden las vías (sin apartaderos) a menos de 15 km de ella.
LINEA = "39.4599,-0.3823,39.4597,-0.5232,39.4708,-0.7050,39.4651,-0.8869,39.4978,-1.0566,39.5343,-1.2253,39.5394,-1.4040,39.5249,-1.5897,39.5235,-1.7771,39.5945,-1.9327,39.7265,-1.9786,39.8623,-2.0286,39.9903,-2.1132,40.0404,-2.2631,40.0516,-2.4456,40.0367,-2.6234,40.0110,-2.8016,39.9800,-2.9813,39.9739,-3.1614,39.9563,-3.3473,40.0254,-3.4994,40.1118,-3.6446,40.2114,-3.7436,40.3366,-3.6716,40.4679,-3.6830,40.4742,-3.6815"
CONSULTA = f'[out:json][timeout:170];way(around:15000,{LINEA})["railway"="rail"][!"service"];out body;>;out skel qt;'



def km(a, b):
    dy = (a[0] - b[0]) * 111.2
    dx = (a[1] - b[1]) * 111.2 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def descargar():
    datos = urllib.parse.urlencode({"data": CONSULTA}).encode()
    for url in SERVIDORES:
        try:
            req = urllib.request.Request(url, data=datos, headers={"User-Agent": "seguimiento-trenes"})
            with urllib.request.urlopen(req, timeout=200) as r:
                return json.load(r)
        except Exception as e:  # probar el siguiente servidor
            print(f"Overpass {url}: {e}")
    return None


def camino(osm):
    nodos = {e["id"]: (e["lat"], e["lon"]) for e in osm["elements"] if e["type"] == "node"}
    grafo = {}
    nodos_av = set()
    for w in osm["elements"]:
        if w["type"] != "way":
            continue
        t = w.get("tags", {})
        if t.get("service") in ("yard", "siding", "spur", "crossover"):
            continue
        vmax = t.get("maxspeed", "")
        av = t.get("highspeed") == "yes" or (vmax.isdigit() and int(vmax) >= 200)
        coste = 1.0 if av else 2.5
        ns = [n for n in w["nodes"] if n in nodos]
        for a, b in zip(ns, ns[1:]):
            d = km(nodos[a], nodos[b]) * coste
            grafo.setdefault(a, []).append((b, d))
            grafo.setdefault(b, []).append((a, d))
            if av:
                nodos_av.update((a, b))
    if not grafo:
        return None
    candidatos = nodos_av or set(grafo)
    ini = min(candidatos, key=lambda n: km(nodos[n], VALENCIA))
    fin = min(grafo, key=lambda n: km(nodos[n], CHAMARTIN))
    dist, prev, cola = {ini: 0.0}, {}, [(0.0, ini)]
    while cola:
        d, n = heapq.heappop(cola)
        if n == fin:
            break
        if d > dist[n]:
            continue
        for m, c in grafo[n]:
            nd = d + c
            if nd < dist.get(m, 1e18):
                dist[m], prev[m] = nd, n
                heapq.heappush(cola, (nd, m))
    if fin not in prev:
        return None
    ruta, n = [fin], fin
    while n != ini:
        n = prev[n]
        ruta.append(n)
    return [nodos[n] for n in reversed(ruta)]


def densificar(pts, paso_km=1.2):
    out = []
    for a, b in zip(pts, pts[1:]):
        k = max(1, math.ceil(km(a, b) / paso_km))
        out += [(a[0] + (b[0] - a[0]) * i / k, a[1] + (b[1] - a[1]) * i / k) for i in range(k)]
    out.append(pts[-1])
    return out


def main():
    carpeta = sys.argv[1] if len(sys.argv) > 1 else "."
    destino = os.path.join(carpeta, "trazado.json")
    try:
        with open(destino) as f:
            if json.load(f).get("fuente") == "osm":
                print("Trazado OSM ya guardado")
                return
    except (OSError, ValueError):
        pass
    osm = descargar()
    pts = camino(osm) if osm else None
    if not pts:
        print("No se pudo calcular el trazado")
        return
    largo = sum(km(a, b) for a, b in zip(pts, pts[1:]))
    if not 330 <= largo <= 480 or km(pts[0], VALENCIA) > 3 or km(pts[-1], CHAMARTIN) > 3:
        print(f"Trazado descartado: {largo:.0f} km")
        return
    puntos = [{"lat": round(a, 5), "lon": round(b, 5)} for a, b in densificar(pts)]
    with open(destino, "w") as f:
        json.dump({"fuente": "osm", "km": round(largo), "puntos": puntos}, f)
    print(f"Trazado OSM guardado: {largo:.0f} km, {len(puntos)} puntos")


if __name__ == "__main__":
    main()
