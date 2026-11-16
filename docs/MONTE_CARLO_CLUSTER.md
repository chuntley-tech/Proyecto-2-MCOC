# Monte Carlo de E12 en el clúster

El lote usa la geometría IFC, el pronóstico y el plan de tres vertidas de E12.
Por muestra cambia la temperatura de colocación común a las tres capas y los
parámetros de la curva de hidratación `theta_inf_c` y `tau_h`. Los rangos
uniformes e independientes de `config/monte_carlo_g8.json` son supuestos
docentes, sin ajuste a datos de obra. Cada lote usa un pronóstico fijo, de
modo que sus frecuencias dependen de ese pronóstico y de los rangos elegidos.

## Prueba local

Desde la raíz, con el entorno Python del proyecto activo:

```bash
python -m scripts.monte_carlo sample results/monte_carlo/prueba --count 4 --seed 2026 --coarsen 2 --snapshot data/weather/2026-11-13T1522Z_forecast
python -m scripts.monte_carlo local results/monte_carlo/prueba --workers 2
python -m scripts.monte_carlo aggregate results/monte_carlo/prueba
```

`--coarsen 2` reduce la resolución para comprobar el flujo. La duración
predeterminada es 336 h, y omitir `--coarsen` usa la resolución de E12.
`--synthetic` habilita una prueba explícitamente sintética sin snapshot.
Cada lote requiere un directorio nuevo para el muestreo. El comando
`run <lote> <índice>` permite repetir una tarea faltante.

## Slurm

Ejecuta desde la raíz del proyecto, con el entorno Python activo y el
directorio del lote accesible para todos los nodos. Ajusta tiempo, memoria y
concurrencia a los recursos del clúster.

```bash
LOT=results/monte_carlo/g8
COUNT=32
python -m scripts.monte_carlo sample "$LOT" --count "$COUNT" --seed 2026 --snapshot data/weather/2026-11-13T1522Z_forecast
JOB=$(sbatch --parsable --array="0-$((COUNT-1))%4" scripts/monte_carlo.slurm "$LOT")
sbatch --dependency="afterok:${JOB%%;*}" --wrap="python -m scripts.monte_carlo aggregate '$LOT'"
```

El manifiesto congela las muestras y registra la semilla, el paso, la malla y
las huellas del código, IFC y pronóstico. Cada tarea escribe un JSON en
`runs/` con sus parámetros, métricas y residuo energético. El agregador exige
que estén todos los resultados del mismo manifiesto y escribe
`aggregate.json` con p05, p50, p95 y la fracción de muestras que superan
70 °C, 20 °C o cualquiera de los dos límites.

Monte Carlo evalúa los extremos en cada paso aceptado, incluidas las caras
temporales de hormigón al aire durante las vertidas. El diferencial es la
temperatura máxima del hormigón colocado menos la mínima de sus celdas
expuestas en ese instante. Las métricas del informe E12 original usan los
cuadros guardados y su clasificación superficial de referencia.

[Documentación de arreglos de tareas Slurm](https://slurm.schedmd.com/job_array.html)
