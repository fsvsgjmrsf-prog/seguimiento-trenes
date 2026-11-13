#!/usr/bin/env python3
"""Seguimiento de puntualidad de trenes Valencia Joaquín Sorolla <-> Madrid Chamartín.

Cada ejecución lee la posición en tiempo real de los trenes de Renfe (datos abiertos),
guarda el último retraso conocido de cada tren del trayecto y regenera el informe.

Uso: python seguimiento.py <carpeta_de_datos>
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

FLOTA_URL = "https://tiempo-real.renfe.com/renfe-visor/flotaLD.json"
RUTAS_URL = "https://tiempo-real.renfe.com/renfe-visor/trenesConEstacionesLD.json"

VALENCIA = "03216"  # Valencia Joaquín Sorolla
CHAMARTIN = "17000"  # Madrid Chamartín Clara Campoamor
NOMBRES = {VALENCIA: "Valencia J. Sorolla", CHAMARTIN: "Madrid Chamartín"}

# Último día en que se recogen datos (después solo se mantiene el informe).
FIN_SEGUIMIENTO = "2026-11-22"

# Tu viaje (Iryo): se comparan los trenes de Renfe que salen de Valencia a una hora parecida.
MI_FECHA = "2026-11-21"
MI_SALIDA = "13:57"
MARGEN_FRANJA_MIN = 90

TIPOS = {
    2: "AVE", 3: "Avant", 4: "Talgo", 10: "Euromed", 11: "Alvia",
    13: "Intercity", 25: "AVE TGV", 28: "AVLO",
}

TZ = ZoneInfo("Europe/Madrid")
MARGEN_DESAPARECIDO = timedelta(minutes=25)


def descargar(url, intentos=3):
    ultimo_error = None
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "seguimiento-trenes/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # red, JSON roto, etc.
            ultimo_error = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"No se pudo descargar {url}: {ultimo_error}")


def cargar(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return defecto


def a_int(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def actualizar(registros, flota, rutas, ahora):
    viajes = registros.setdefault("viajes", {})
    paradas_por_tren = {}
    for t in (rutas or {}).get("trenes", []):
        paradas_por_tren[t.get("idTren")] = t.get("estaciones", [])

    fecha_feed = flota.get("fechaActualizacion")
    momento = datetime.fromisoformat(fecha_feed).replace(tzinfo=TZ) if fecha_feed else ahora
    fecha = momento.date().isoformat()
    vistos = set()

    for tren in flota.get("trenes", []):
        cod = tren.get("codComercial")
        paradas = paradas_por_tren.get(cod) or []
        codigos = [p.get("p") for p in paradas] or [tren.get("codOrigen"), tren.get("codDestino")]
        if VALENCIA not in codigos or CHAMARTIN not in codigos:
            continue

        i_vlc, i_cha = codigos.index(VALENCIA), codigos.index(CHAMARTIN)
        salida, llegada = (VALENCIA, CHAMARTIN) if i_vlc < i_cha else (CHAMARTIN, VALENCIA)
        i_llegada = codigos.index(llegada)
        i_sig = codigos.index(tren.get("codEstSig")) if tren.get("codEstSig") in codigos else None

        clave = f"{fecha}_{cod}"
        viaje = viajes.get(clave)
        ya_paso = i_sig is not None and i_sig > i_llegada
        if ya_paso:
            # El tren ya dejó atrás nuestra estación de llegada: su retraso posterior no cuenta.
            if viaje:
                viaje["estado"] = "llegado"
                vistos.add(clave)
            continue

        retraso = a_int(tren.get("ultRetraso"))
        if retraso is None:
            continue

        horas = {p.get("p"): p for p in paradas}
        if viaje and not viaje.get("salida_prevista") and horas:
            viaje["salida_prevista"] = (horas.get(salida) or {}).get("hs", "")
            viaje["llegada_prevista"] = (horas.get(llegada) or {}).get("h", "")
        if not viaje:
            viaje = viajes[clave] = {
                "fecha": fecha,
                "tren": cod,
                "tipo": TIPOS.get(tren.get("codProduct"), f"Tipo {tren.get('codProduct')}"),
                "sentido": f"{NOMBRES[salida]} → {NOMBRES[llegada]}",
                "salida_prevista": (horas.get(salida) or {}).get("hs", ""),
                "llegada_prevista": (horas.get(llegada) or {}).get("h", ""),
                "retraso_max": retraso,
                "observaciones": 0,
            }
        if viaje.get("estado") == "llegado":
            vistos.add(clave)
            continue

        viaje["retraso_final"] = retraso
        viaje["retraso_max"] = max(viaje.get("retraso_max", retraso), retraso)
        viaje["observaciones"] = viaje.get("observaciones", 0) + 1
        viaje["ultima_obs"] = momento.isoformat(timespec="minutes")
        viaje["estado"] = "en_ruta"
        if tren.get("codEstAnt") == llegada and tren.get("codEstSig") == llegada:
            viaje["estado"] = "llegado"
        vistos.add(clave)

    # Los trenes que ya no aparecen en el feed han terminado su recorrido.
    for clave, viaje in viajes.items():
        if viaje.get("estado") != "en_ruta" or clave in vistos:
            continue
        ultima = datetime.fromisoformat(viaje["ultima_obs"])
        if momento - ultima > MARGEN_DESAPARECIDO:
            viaje["estado"] = "llegado"

    registros["ultima_actualizacion"] = momento.isoformat(timespec="minutes")


def categoria(retraso):
    if retraso <= 5:
        return 0
    if retraso <= 15:
        return 1
    if retraso <= 30:
        return 2
    if retraso <= 60:
        return 3
    return 4


CATEGORIAS = ["Puntual (≤5 min)", "6–15 min", "16–30 min", "31–60 min", "Más de 60 min"]


def pct(n, total):
    return f"{100 * n / total:.0f} %" if total else "–"


def resumen(viajes):
    total = len(viajes)
    cats = [0] * 5
    for v in viajes:
        cats[categoria(v["retraso_final"])] += 1
    medio = sum(v["retraso_final"] for v in viajes) / total if total else 0
    maximo = max((v["retraso_final"] for v in viajes), default=0)
    return total, cats, medio, maximo


def minutos(hhmm):
    try:
        h, m = hhmm.split(":")[:2]
        return int(h) * 60 + int(m)
    except (AttributeError, ValueError):
        return None


def en_mi_franja(v):
    salida = minutos(v.get("salida_prevista", ""))
    return (v["sentido"].startswith(NOMBRES[VALENCIA]) and salida is not None
            and abs(salida - minutos(MI_SALIDA)) <= MARGEN_FRANJA_MIN)


def seccion_mi_viaje(registros, terminados, en_ruta):
    mi_fecha = datetime.fromisoformat(MI_FECHA).date()
    dias_semana = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    nombre_dia = dias_semana[mi_fecha.weekday()]
    ini = minutos(MI_SALIDA) - MARGEN_FRANJA_MIN
    fin = minutos(MI_SALIDA) + MARGEN_FRANJA_MIN
    franja_txt = f"{ini // 60:02d}:{ini % 60:02d} y las {fin // 60:02d}:{fin % 60:02d}"

    l = [f"## 🎯 Tu viaje: {nombre_dia} {mi_fecha.strftime('%d/%m')}, Iryo de las {MI_SALIDA} "
         "Valencia → Madrid Chamartín", ""]
    hoy = registros.get("ultima_actualizacion", "")[:10]
    if hoy:
        faltan = (mi_fecha - datetime.fromisoformat(hoy).date()).days
        if faltan > 0:
            l += [f"Faltan **{faltan} días**.", ""]
    l += [f"Iryo usa las mismas vías, así que se miran los trenes de Renfe que salen de Valencia "
          f"entre las {franja_txt}. Complétalo con la app de Iryo o la de Adif.", ""]

    franja = [v for v in terminados if en_mi_franja(v)]
    mismo_dia = [v for v in franja
                 if datetime.fromisoformat(v["fecha"]).weekday() == mi_fecha.weekday()]
    l.append("| Trenes de Renfe en tu franja | Trenes | Puntual (≤5 min) | Más de 15 min | "
             "Más de 30 min | Retraso medio | Máximo |")
    l.append("|---|---|---|---|---|---|---|")
    for nombre, grupo in [("Todos los días", franja), (f"Solo {nombre_dia}s", mismo_dia)]:
        total, cats, medio, maximo = resumen(grupo)
        if total:
            l.append(f"| {nombre} | {total} | {pct(cats[0], total)} | {pct(sum(cats[2:]), total)} | "
                     f"{pct(sum(cats[3:]), total)} | {medio:.1f} min | {maximo} min |")
        else:
            l.append(f"| {nombre} | 0 | – | – | – | – | – |")
    l.append("")

    total, cats, _, _ = resumen(franja)
    if total >= 5:
        puntual = cats[0] / total
        if puntual >= 0.85:
            veredicto = "🟢 La línea va bien a esa hora: la gran mayoría de trenes llegan puntuales."
        elif puntual >= 0.7:
            veredicto = "🟡 Hay retrasos de vez en cuando a esa hora: deja algo de margen si tienes una cita."
        else:
            veredicto = "🔴 Hay retrasos frecuentes a esa hora: conviene dejar un buen margen a la llegada."
        l += [veredicto, ""]
    else:
        l += ["Aún hay pocos datos en tu franja para sacar conclusiones.", ""]

    ahora = [v for v in en_ruta if en_mi_franja(v)]
    if ahora:
        l.append("Ahora mismo en ruta en tu franja: " + ", ".join(
            f"{v['tipo']} {v['tren']} ({v.get('retraso_final', 0)} min)" for v in ahora))
        l.append("")
    return l


def informe(registros):
    viajes = list(registros.get("viajes", {}).values())
    terminados = [v for v in viajes if v.get("estado") == "llegado" and "retraso_final" in v]
    en_ruta = [v for v in viajes if v.get("estado") == "en_ruta"]
    sentidos = sorted({v["sentido"] for v in viajes})

    l = ["# 🚄 Puntualidad Valencia J. Sorolla ⇄ Madrid Chamartín", ""]
    l.append(f"Última actualización: **{registros.get('ultima_actualizacion', '–')}** (hora de Madrid). "
             "Datos en tiempo real de Renfe (AVE, AVLO, Alvia…). Iryo y Ouigo solo aparecen si se apuntan a mano en anotaciones.csv.")
    l.append("")
    l.append("El retraso de cada tren es el último que publica Renfe antes de llegar a la estación de destino.")
    l.append("")
    l += seccion_mi_viaje(registros, terminados, en_ruta)

    if not terminados:
        l += ["Todavía no hay trenes terminados registrados. Vuelve en unas horas.", ""]

    l += ["## Resumen general", ""]
    l.append("| Sentido | Trenes | " + " | ".join(CATEGORIAS) + " | Retraso medio | Máximo |")
    l.append("|---|---|" + "---|" * len(CATEGORIAS) + "---|---|")
    for s in sentidos + ["Total"]:
        grupo = terminados if s == "Total" else [v for v in terminados if v["sentido"] == s]
        total, cats, medio, maximo = resumen(grupo)
        fila = [f"**{s}**" if s == "Total" else s, str(total)] + [pct(c, total) for c in cats]
        fila += [f"{medio:.1f} min" if total else "–", f"{maximo} min" if total else "–"]
        l.append("| " + " | ".join(fila) + " |")
    l.append("")

    l += ["## Día a día", ""]
    l.append("| Fecha | Trenes | Puntuales | Retraso medio | Peor tren |")
    l.append("|---|---|---|---|---|")
    for fecha in sorted({v["fecha"] for v in terminados}, reverse=True):
        grupo = [v for v in terminados if v["fecha"] == fecha]
        total, cats, medio, _ = resumen(grupo)
        peor = max(grupo, key=lambda v: v["retraso_final"])
        l.append(f"| {fecha} | {total} | {pct(cats[0], total)} | {medio:.1f} min | "
                 f"{peor['tipo']} {peor['tren']} ({peor['retraso_final']} min) |")
    l.append("")

    l += ["## Por tren (busca aquí el tuyo)", "",
          "El número de tren se repite cada día, así que puedes ver cómo suele ir el que vas a coger.", ""]
    for s in sentidos:
        l += [f"### {s}", ""]
        l.append("| Salida | Llegada | Tren | Días | Puntual | Retraso medio | Máximo |")
        l.append("|---|---|---|---|---|---|---|")
        por_tren = {}
        for v in terminados:
            if v["sentido"] == s:
                por_tren.setdefault(v["tren"], []).append(v)
        for cod, grupo in sorted(por_tren.items(), key=lambda kv: kv[1][-1].get("salida_prevista", "")):
            total, cats, medio, maximo = resumen(grupo)
            ref = grupo[-1]
            l.append(f"| {ref.get('salida_prevista', '')} | {ref.get('llegada_prevista', '')} | "
                     f"{ref['tipo']} {cod} | {total} | {pct(cats[0], total)} | {medio:.1f} min | {maximo} min |")
        l.append("")

    if en_ruta:
        l += ["## Ahora mismo en ruta", ""]
        l.append("| Tren | Sentido | Salida | Retraso actual |")
        l.append("|---|---|---|---|")
        for v in sorted(en_ruta, key=lambda v: v.get("salida_prevista", "")):
            l.append(f"| {v['tipo']} {v['tren']} | {v['sentido']} | {v.get('salida_prevista', '')} | "
                     f"{v.get('retraso_final', 0)} min |")
        l.append("")

    return "\n".join(l)


ANOTACIONES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "anotaciones.csv")
SENTIDOS = {
    "VLC-MAD": f"{NOMBRES[VALENCIA]} → {NOMBRES[CHAMARTIN]}",
    "MAD-VLC": f"{NOMBRES[CHAMARTIN]} → {NOMBRES[VALENCIA]}",
}


def anotaciones(registros, ruta=ANOTACIONES):
    """Añade los trenes apuntados a mano (Iryo, Ouigo...) desde anotaciones.csv.

    Formato de cada línea: fecha,operador,tren,sentido,salida,llegada,retraso
    p. ej. 2026-11-13,Iryo,06157,VLC-MAD,13:57,15:52,4
    """
    import csv
    viajes = registros.setdefault("viajes", {})
    nuevas = {}
    try:
        with open(ruta, encoding="utf-8") as f:
            filas = [l for l in f if l.strip() and not l.lstrip().startswith("#")]
    except OSError:
        filas = []
    for n, fila in enumerate(csv.reader(filas), 1):
        fila = [c.strip() for c in fila]
        if fila and fila[0].lower() == "fecha":
            continue
        try:
            fecha, operador, tren, sentido, salida, llegada, retraso = fila[:7]
            datetime.strptime(fecha, "%Y-%m-%d")
            retraso = int(retraso)
            sentido = SENTIDOS[sentido.upper().replace(" ", "")]
        except (ValueError, KeyError) as e:
            print(f"Aviso: anotación {n} ignorada ({fila}): {e}")
            continue
        operador = operador.strip().capitalize() if operador.lower() != "ouigo" else "Ouigo"
        nuevas[f"{fecha}_{operador}_{tren}"] = {
            "fecha": fecha, "tren": tren, "tipo": operador, "sentido": sentido,
            "salida_prevista": salida, "llegada_prevista": llegada,
            "retraso_final": retraso, "retraso_max": retraso,
            "observaciones": 1, "estado": "llegado", "fuente": "manual",
        }
    # Las anotaciones borradas o corregidas en el CSV se reflejan tal cual.
    for clave in [c for c, v in viajes.items() if v.get("fuente") == "manual"]:
        del viajes[clave]
    viajes.update(nuevas)
    if nuevas:
        print(f"Anotaciones manuales: {len(nuevas)}")


def main():
    carpeta = sys.argv[1] if len(sys.argv) > 1 else "."
    ruta_registros = os.path.join(carpeta, "registros.json")
    registros = cargar(ruta_registros, {"version": 1, "viajes": {}})
    ahora = datetime.now(TZ)

    if ahora.date().isoformat() <= FIN_SEGUIMIENTO:
        flota = descargar(FLOTA_URL)
        try:
            rutas = descargar(RUTAS_URL)
        except RuntimeError as e:
            print(f"Aviso: sin datos de paradas ({e}); se usan origen y destino.")
            rutas = None
        actualizar(registros, flota, rutas, ahora)
    else:
        print("Seguimiento terminado; solo se regenera el informe.")

    anotaciones(registros)
    with open(ruta_registros, "w", encoding="utf-8") as f:
        json.dump(registros, f, ensure_ascii=False, indent=1, sort_keys=True)
    texto = informe(registros)
    with open(os.path.join(carpeta, "INFORME.md"), "w", encoding="utf-8") as f:
        f.write(texto + "\n")

    resumen_gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen_gh:
        with open(resumen_gh, "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    print(texto)


if __name__ == "__main__":
    main()
