# Seguimiento de trenes Valencia J. Sorolla ⇄ Madrid Chamartín

Cada 15 minutos (de 5:00 a 23:59, hora de Madrid) un proceso de GitHub Actions lee los datos
abiertos de tiempo real de Renfe y guarda el retraso de los trenes entre Valencia Joaquín Sorolla
y Madrid Chamartín.

**📊 Informe:** [INFORME.md en la rama `datos-trenes`](https://github.com/fsvsgjmrsf-prog/seguimiento-trenes/blob/datos-trenes/INFORME.md)

- Solo incluye trenes de Renfe (AVE, AVLO, Alvia…). Iryo y Ouigo no publican datos abiertos;
  como usan las mismas vías, los retrasos de Renfe sirven de referencia del estado de la línea.
- El script está en `seguimiento-trenes/seguimiento.py` y el proceso en
  `.github/workflows/trenes-valencia-madrid.yml`.
- Deja de recoger datos el 22/11/2026.
