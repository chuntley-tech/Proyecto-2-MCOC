# E10 — Entorno, moldaje y clima (G8)

Objetivo: mostrar cómo el ambiente real entra a la física y cómo se obtienen
pronósticos trazables.

## Qué hay en el repositorio

| Pedido E10 | Dónde | Qué hace |
|---|---|---|
| Módulo de condiciones de borde | `environment/surface.py`, `thermal3d/solver.py` | `SurfaceExposure`: aire, viento, sol y capas en serie para cada cara. `SurfaceMap` asigna condiciones distintas a la cara superior, el costado y el suelo. El solver acepta estos bordes sin saber de clima. |
| Tratamiento de suelo | `environment/ground.py` | `SoilModel` + `add_soil_layer`: voxeles de suelo bajo el hormigón y a un costado, con temperatura profunda fija en la base. |
| Moldaje/aislación | `environment/surface.py` | `Layer` (R = e/k) y `LayerSchedule`: moldaje que se retira a las 72 h y manta aislante en la cara superior. |
| Cliente/loader meteorológico | `weather/open_meteo.py`, `weather/series.py`, `scripts/fetch_weather.py` | Arma la consulta a Open-Meteo (forecast, ensemble, archive, historical forecast y previous runs), la descarga y la convierte en funciones f(t) para los bordes. |
| Esquema de snapshots | `weather/snapshots.py` | `data/weather/<fecha>Z_<tipo>/` con la respuesta original y `metadata.json` (fuente, modelo, fecha de descarga, URL, coordenadas, unidades y sha256). Las carpetas no se sobrescriben. |
| Demo | `scripts/environment_demo.py`, `config/environment_g8.json` | Sección 2D con suelo, manta, moldaje y sol. Compara el desmolde a las 72 h con el moldaje permanente. |
| Pruebas | `tests/test_environment.py`, `tests/test_weather.py` | Solución analítica en serie, balance de energía con clima variable, estabilidad, desmolde, sol-aire, suelo, snapshots y cobertura. |

### Comandos

```powershell
python -m pytest tests/test_environment.py tests/test_weather.py -q
python -m scripts.fetch_weather                  # requiere internet: crea data/weather/<fecha>Z_forecast/
python -m scripts.fetch_weather --kind archive --start 2025-11-27 --end 2025-12-11   # reanálisis para climatología
python -m scripts.environment_demo --decision 2026-11-20T12:00Z  # último pronóstico del G8 disponible al corte
python -m scripts.environment_demo --synthetic                  # usa una serie sintética, sin internet
```

Resultados en `results/environment/`: `environment_demo.png`, `environment_demo.json`
(con la carpeta y el sha256 del snapshot usado) y `weather_used.csv` (hora a
hora, con la columna `origin`).

Si falta un pronóstico para el corte, el demo etiqueta la serie como sintética.
Para completar la cola con reanálisis, `auto` busca una descarga del mismo
sitio disponible al corte y registra su huella. El archivo histórico debe
corresponder al período estacional que se quiere representar.

## Física: cómo entra el ambiente

Cada cara expuesta tiene esta cadena de resistencias, de la superficie al aire:

```
T_celda ──[Δ/2k]── cara del hormigón ──[R_capas(t) = Σ e/k]── cara exterior ──[1/h(t)]── T_sol-aire(t)
```

El flujo que entra por m² es

    q = (T_sa − T_s) / (1/h + R_capas),     T_sa = T_aire + a·f·G / h

En el solver, la conductancia de cada cara se calcula en cada paso como
`A / (R_ext(t) + Δ/2k)`. La temperatura equivalente se evalúa en t_n, igual que
la fuente (Euler explícito).

### Respuestas a las preguntas posibles

**¿Qué término usa la temperatura ambiente?**
El término de borde Robin, en el balance de la celda de la cara:
`G·(T_eq − T_celda)`, con `G = A/(1/h + R_capas + Δ/2k)`. T_eq es la
temperatura sol-aire: el aire a 2 m (`temperature_2m`) más el aporte del sol. No
es una condición Dirichlet. La superficie no queda a la temperatura del aire;
la película 1/h y las capas limitan cuánto calor pasa.

**¿Cómo entra el viento?**
A través del coeficiente de película: h = 5,7 + 3,8·v (Jürges/McAdams). La
velocidad se baja de 10 m (`wind_speed_10m`) a 2 m con un perfil potencial
(exponente 0,14). Más viento significa más h, menos resistencia y más
enfriamiento. El viento también cambia el Δt estable: se usa el viento máximo
de la serie para calcular la resistencia mínima.

**¿Cómo modelar una resistencia térmica de moldaje?**
Como una capa sin masa en serie: R = e/k. Para el terciado de 18 mm,
R = 0,018/0,13 ≈ 0,14 m²K/W. La manta de 25 mm tiene R = 0,025/0,04 ≈ 0,63 m²K/W.
Se suma a 1/h. Se ignora su capacidad térmica, que es pequeña frente al
hormigón. Si se quisiera incluirla, el moldaje se representaría con voxeles
propios.

**¿Qué cambia al desmoldar?**
La resistencia del costado pasa de 1/h + 0,14 a solo 1/h. En el
`LayerSchedule` es un cambio de etapa a las 72 h, supuesto del demo para
`RetiroMoldaje_h` (propiedad propuesta en G02). Al desmoldar, la superficie se enfría más rápido y crece la diferencia
entre núcleo y superficie, que es el riesgo de fisuración térmica. En el demo
sintético, el costado a 96 h queda unos 4–5 °C más frío con desmolde que con
moldaje permanente, y el ΔT interno máximo sube de ~36 a ~40 °C. Este ΔT
mide la diferencia entre las celdas más caliente y más fría del hormigón
en un mismo instante. Son resultados del escenario sintético. El cálculo de
estabilidad considera la condición sin moldaje.

**¿Qué es un flujo solar?**
Es la radiación de onda corta que llega por unidad de área [W/m²].
Open-Meteo entrega `shortwave_radiation` (global horizontal, GHI) como media de
la hora anterior; el valor de las 13:00 corresponde a 12:00–13:00. Por eso en
el código se ubica en el centro de esa hora. La cara solo absorbe la fracción
a (absortancia ≈ 0,65 en hormigón gris). En caras verticales se usa un factor
f (0,35, supuesto docente) porque reciben menos radiación que una horizontal.
[Documentación de las variables horarias de Open-Meteo](https://open-meteo.com/en/docs#hourly_parameter_definition).

**¿Cómo evitar doble-contar radiación y convección?**
Se usa la temperatura sol-aire. El sol se convierte en un aumento equivalente
de la temperatura exterior, a·f·G/h, y entra por la misma resistencia que la
convección. Hay un solo término de borde por cara. No se agrega un flujo solar
aparte encima de un h que ya incluye radiación. Si una manta tapa la cara, el
sol calienta la manta y no el hormigón directamente; por eso su aporte también
pasa por R_capas. La prueba `test_sol_air_adds_sun_once_through_the_same_film`
lo comprueba. La onda larga (enfriamiento nocturno al cielo) no está incluida;
si se agrega, se linealiza como h_rad y se suma dentro del mismo h.

**¿Diferencia entre forecast, reanalysis y observación?**
- **Observación**: lo que midió un instrumento en un lugar y momento
  (estación, sensor en obra). Es el único dato medido.
- **Reanálisis** (`archive`, ERA5): reconstrucción del pasado con un modelo que
  asimila observaciones. Es coherente en espacio y tiempo, pero es un modelo en
  una grilla de ~10–25 km, no una medición en el sitio.
- **Pronóstico** (`forecast`): predicción del futuro hecha en una fecha de
  emisión. Pierde precisión a mayor antelación y cambia con cada corrida.
  El `ensemble` entrega varios miembros para estimar la incertidumbre.

En `metadata.json` cada snapshot guarda su tipo en `kind` y `status`, y cada
hora de la serie lleva su `origin`.

**¿Qué ocurre si el forecast no cubre aún los 14 días posteriores al 27?**
Por ejemplo, una serie de 16 días que comienza a las 00:00 UTC del 11 de
noviembre termina antes del 27. `coverage()` informa cuántas
horas del período cubre el pronóstico y cuántas faltan al final.
`fill_tail()` completa el resto con un método declarado:
- `climatologia`: ciclo diario medio del reanálisis de las mismas fechas del
  año anterior (snapshot `archive`). Un solo año representa un escenario
  histórico de referencia.
- `persistencia`: repite el ciclo de las últimas 72 h pronosticadas.
- `conservador`: caso frío (aire mínimo − 2 °C, viento máximo, sin sol). Sirve
  para acotar el enfriamiento; no es conservador para el máximo térmico.

Cada hora rellenada queda marcada en `origin` y en la figura (franja gris), y
el JSON registra el método. A medida que se acerque el 27, nuevos snapshots
cubrirán más horas. El pronóstico nunca se extrapola en silencio:
`boundary_functions()` lanza un error si se pide una hora fuera de la serie.

**¿Por qué conservar forecasts antiguos?**
- Trazabilidad: una decisión, por ejemplo "vertemos el 27", se tomó con el
  pronóstico disponible ese día. `latest_before(decisión)` recupera exactamente
  ese snapshot, y su sha256 prueba que no se modificó.
- Evaluar el pronóstico: comparando snapshots de distintas fechas con lo que
  ocurrió se mide el error según la antelación.
- Reproducibilidad: si se reemplazara el archivo, no se podría reproducir una
  figura antigua. Por eso `save_snapshot` falla si la carpeta ya existe.

## Supuestos y estado de los datos

| Dato | Valor | Estado |
|---|---|---|
| Sitio | −41,222539; −73,295603 | punto docente (case_g8.json) |
| Inicio | 27-nov-2026 04:00 local = 07:00 UTC | ejemplo de la guía G08; se supone UTC−3 |
| h(v) | 5,7 + 3,8 v | correlación de literatura |
| Moldaje | terciado 18 mm, k = 0,13 | valor típico; retiro a las 72 h como supuesto E10 |
| Manta | 25 mm, k = 0,04 | supuesto de diseño |
| Suelo | k = 1,39, ρ = 1800, cp = 1273 | Ju y Lei (2019), guía de difusión §31 |
| T profunda del suelo | 10 °C | **supuesto**, no medido |
| Absortancia / factor lateral | 0,65 / 0,35 | supuestos docentes |
| Hidratación | pulso coseno, qmax 1300 W/m³ | **sintético**, no calibrado |
| Clima del demo | snapshot si existe; si no, serie **sintética** | lo indica el título de la figura y `weather_source` en el JSON |

## Límites conocidos

- La sección 2D es rectangular. La geometría octogonal completa está en el
  modelo 3D, y los mismos bordes funcionan en 3D (`SurfaceMap` usa las
  direcciones `x±`, `y±` y `z±`).
- No hay sombreado ni geometría solar: la fracción de radiación en caras
  verticales es un factor fijo.
- No se incluye radiación de onda larga al cielo nocturno.
- La hidratación del demo no depende de la temperatura. La versión con
  Arrhenius está en `thermal3d/construction.py`.
- El visor aplica los bordes E10 a la fundación voxelizada, también por etapas.
  Usa un ciclo meteorológico sintético diario y ofrece un borde de suelo
  equivalente en la base (`R″ = profundidad/k` hacia la temperatura profunda).
  El demo de Python incluye suelo explícito y permite usar pronósticos guardados.
  La hora de desmolde del visor se mide desde el inicio de la simulación y se
  aplica a los laterales en la evaluación del siguiente paso. El paso máximo
  ambiental de 600 s proviene de la configuración del demo E10.
