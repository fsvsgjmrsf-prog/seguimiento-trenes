# Dashboard de Grafana

`trenes-valencia-chamartin.json` es una plantilla de dashboard con:

- **Mapa en directo** con el trazado de la línea, las estaciones y cada tren en su posición GPS, coloreado por retraso.
- **Trenes en circulación y sus paradas**: retraso actual, hora prevista y estimada de cada parada y minutos que faltan; solo las paradas que faltan, con la próxima resaltada. Filtra por tren con el embudo de la columna Tren.
- **Tu viaje** (sábado 21/11, 13:57): puntualidad de los trenes de Renfe que salen de Valencia entre las 12:27 y las 15:27.
- **Historial**: resumen, retraso de cada tren, puntualidad por día y tablas por tren y por día.

## Importarlo

1. Instala el plugin **Infinity** (`yesoreyeram-infinity-datasource`) y crea una fuente de datos Infinity.
   Si tu Grafana limita los dominios, permite `tiempo-real.renfe.com` y `raw.githubusercontent.com`.
2. En Grafana: **Dashboards → New → Import**, sube este JSON (o pega su contenido) y elige tu fuente Infinity.

## De dónde salen los datos

- Estado, mapa y tiempos de paso: datos abiertos en tiempo real de Renfe (`flotaLD.json` y `trenesConEstacionesLD.json`).
- Historial: `registros.json` de la rama `datos-trenes` de este repo, que actualiza el proceso de GitHub Actions.

Solo incluye trenes de Renfe; Iryo y Ouigo no publican datos abiertos. El mapa en directo muestra los trenes con origen y destino en
Valencia J. Sorolla y Madrid Chamartín.
