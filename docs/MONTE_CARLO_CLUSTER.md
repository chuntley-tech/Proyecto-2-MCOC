# Monte Carlo final G8 (E13/E14)

El flujo de decisión usa `scripts.final_mc` para congelar muestras y
agregar resultados y `scripts.final_campaign` para resolver el balance
térmico. `config/monte_carlo_final_g8.json` documenta los rangos, las
fuentes y la semilla.

## Ejecución local

```sh
ROOT=results/final/g8_20261119_mc
python -m scripts.final_mc screen "$ROOT/screen"
python -m scripts.final_campaign local "$ROOT/screen" --workers 8
python -m scripts.final_mc aggregate "$ROOT/screen"
python -m scripts.final_mc sample "$ROOT/base31" --shortlist "$ROOT/screen/shortlist.json"
python -m scripts.final_campaign local "$ROOT/base31" --workers 8
python -m scripts.final_mc aggregate "$ROOT/base31"
```

Para las sensibilidades, repetir los tres últimos comandos en directorios
distintos con `--variant curves`, `--variant mix` o `--variant ea` en
`sample`. Cada sensibilidad usa 100 realizaciones por plan con las mismas
secuencias de clima, suelo, calor y colocación. La sensibilidad de curvas
modifica el conjunto discreto a partir de la misma semilla.

Si el lote base identifica una alternativa factible, preparar un lote
independiente con `python -m scripts.final_mc confirm "$ROOT/confirm" --shortlist "$ROOT/screen/shortlist.json" --plan ID`.
Ejecutarlo y agregarlo con los mismos comandos. El JSON fija la semilla
de confirmación.

## Job array y agregación en Slurm

Después de preparar el lote, ejecutar desde la raíz del repositorio.

```sh
LOT=results/final/g8_20261119_mc/base31
COUNT=$(python -c 'import json,sys; print(len(json.load(open(sys.argv[1],encoding="utf-8"))["jobs"]))' "$LOT/manifest.json")
JOB=$(sbatch --parsable --array="0-$((COUNT-1))%8" scripts/final_campaign.slurm "$LOT")
sbatch --dependency="afterok:${JOB%%;*}" --wrap="python -m scripts.final_mc aggregate '$LOT'"
```

Cada índice identifica un plan y una realización. El manifiesto congela
las entradas, los índices, la versión de NumPy y las huellas del código,
IFC, curvas y clima. El agregador exige un resultado compatible por índice
antes de escribir `comparison.json`.

## Tres mallas del escenario crítico

Después de agregar el lote base, usar el identificador del candidato
nuevo en la segunda variable. Cada salida conserva la realización
completa y las coordenadas del máximo diferencial.

```sh
LOT=results/final/g8_20261119_mc/base31
CANDIDATO=3h-12C-25mm-504h-direct
for PLAN in C3 "$CANDIDATO"; do
    for MALLA in 2 1 0.5; do
        python -m scripts.final_mc_refinement "$LOT" --plan "$PLAN" --mesh "$MALLA"
    done
done
python -m scripts.final_mc_refinement "$LOT"
```

Los factores 2, 1 y 0,5 corresponden a Δx de 0,50, 0,25 y 0,125 m.
El paso máximo común es 600 s frente a 1200 s en el lote. El orden
observado se informa si las diferencias decrecen monótonamente.

## Flujo histórico E12

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

## Explorar en el visor HTML

Abre `visor_termico.html` y entra en **Monte Carlo**. La pestaña muestra
automáticamente un lote de ejemplo de cuatro simulaciones. Para explorar
otro lote sin servidor, usa **Importar otro lote guardado** y selecciona
`aggregate.json` y los archivos de `runs/`. Usa **Limpiar lote** si quieres
cambiar de manifiesto después de importar.

Con el visor conectado mediante `python -m scripts.serve_dashboard`, el
formulario **Ejecutar lote con Python** permite elegir el pronóstico guardado,
la semilla, la cantidad de muestras, la malla y los procesos locales.
Al terminar, carga el resumen y las corridas automáticamente. El lote
queda en `results/visor_python/<id>/`, junto con su manifiesto. Para
ejecutar en el clúster, usa los comandos Slurm de la sección siguiente.

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
