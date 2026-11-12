# E11 — Weather pipeline y visualización 3D (G8)

E11 conecta un pronóstico guardado con las condiciones de borde y genera
campos térmicos 3D inspeccionables.

## Antes del laboratorio (una vez, con internet)

```powershell
python -m scripts.fetch_weather          # pronóstico → data/weather/<fecha>Z_forecast/
python -m scripts.weather_3d             # 48 h con ese snapshot → results/weather_3d/<snapshot>/
python -m scripts.view_3d "results/weather_3d/NOMBRE_DEL_SNAPSHOT"
```

Opcional, para tener también un histórico: `python -m scripts.fetch_weather --kind archive --start 2025-11-27 --end 2025-12-11`.

La respuesta original y su metadata quedan en `data/weather/<snapshot>/`.
Los cuadros de la serie (`vtk/temperature_XXXX.vti`) se regeneran con
`scripts.weather_3d`. ParaView puede abrir `final.vti` por separado.

## Visor HTML

Abre **Clima 3D · E11** y selecciona `visor_e11.json` de la carpeta de resultados.
Puedes cambiar el instante, el plano y su posición, ocultar el suelo o
saltar al corte por el punto caliente. El gráfico compara núcleo geométrico,
sondas superficiales, temperatura máxima y aire. Los gráficos de viento y
radiación muestran los insumos del cálculo. El encabezado identifica el
pronóstico o la serie sintética y, cuando corresponde, el hash del snapshot.

## Guion: lo que pedirá el ayudante

| Pedido | Qué mostrar |
|---|---|
| 1. Archivo meteorológico | `data/weather/<fecha>Z_forecast/forecast.json`: la respuesta de Open-Meteo **sin modificar** (`hourly.time`, `temperature_2m`, `wind_speed_10m`, `shortwave_radiation`). |
| 2. Metadata | `metadata.json` del mismo snapshot: fuente, tipo (`kind`/`status`), modelo, `retrieved_at`, URL exacta de la consulta, coordenadas pedidas y de la celda del modelo, zona horaria GMT, unidades, primera/última hora y `sha256`. `load_snapshot` vuelve a calcular el hash y falla si el archivo fue editado. |
| 3. Gráfico de temperatura ambiente | `results/weather_3d/<snapshot>/clima_snapshot.png`: aire, viento y onda corta con la carpeta, fecha de descarga y hash en el título; franja roja = período simulado. |
| 4. Alimentar una BC con la serie | `scripts/weather_3d.py` → `build_model`: `series.boundary_functions(t0)` entrega `air_c(t)`, `wind_10m_m_s(t)`, `shortwave_w_m2(t)` que se pasan a tres `SurfaceExposure` (costados con moldaje, caras superiores con manta, terreno). En `resumen.json` → `boundaries_at_t0` se ve el aire, h, capas y T sol-aire de cada cara en t = 0; la prueba `test_snapshot_feeds_boundaries_and_exports_vtk` comprueba que el aire del borde es exactamente el valor del snapshot. |
| 5. Simulación corta | `python -m scripts.weather_3d --hours 48`. Voxeliza el IFC vigente, añade suelo y registra la malla, el paso de tiempo, su límite de estabilidad y el balance de energía. |
| 6. Abrir resultados 3D | ParaView: *File > Open* → `temperature.pvd` (serie) o `final.vti` → *Apply* → colorear por `temperature`. PyVista: `python -m scripts.view_3d <carpeta> --show`. |
| 7. Slice o clipping | ParaView: *Threshold* `material` entre 1 y 1 (solo hormigón) → *Slice* (normal Z o Y por el núcleo) o *Clip* (plano Y). Python: `scripts.view_3d` genera `slices_*.png` (XZ, YZ, XY por el núcleo). `--show` abre la vista de PyVista si está instalado. |
| 8. Núcleo y superficie | Campo `zone`: 3 = núcleo, 2 = superficie expuesta al aire, 4 = contacto con suelo, 1 = interior. `resumen.json` → `core` (celda y coordenadas) y `surface_probes`; `nucleo_superficie.png` grafica sus temperaturas. `depth_to_boundary_m` da la distancia de cada celda al borde más cercano. |

### Núcleo geométrico vs. núcleo térmico

* **Núcleo geométrico**: la celda de hormigón más alejada de todo borde (aire y
  suelo). Se calcula con `surface_depth` y queda en `zone = 3`.
* **Punto caliente**: celda con la temperatura máxima de cada cuadro
  (`tmax_by_frame`). Su ubicación puede cambiar con la hidratación y los
  intercambios de calor en los bordes.

## Dónde entran el viento y la radiación (ecuaciones exactas)

Balance de la celda de borde (Euler explícito, `thermal3d/solver.py` l. 273–276):

```
P_cara = G(t) · (T_eq(t) − T_celda),     G(t) = A / (R_ext(t) + Δ/(2k))
```

| Término | Ecuación | Código |
|---|---|---|
| Viento a 2 m | v₂ = v₁₀ · (2/10)^0,14 | `environment/surface.py` l. 58 (`wind_at_height`) |
| Convección | h = 5,7 + 3,8 · v₂  [W/(m²K)] | `environment/surface.py` l. 51 (`convection_h`) |
| Resistencia exterior | R_ext = 1/h + Σ eᵢ/kᵢ (moldaje 0,018/0,13; manta 0,025/0,04) | `environment/surface.py` l. 186 |
| Radiación (sol-aire) | T_eq = T_sa = T_aire + a · f · G_sw / h | `environment/surface.py` l. 202–203 |
| Ubicación horaria del sol | `shortwave_radiation` es media de la hora anterior → se ubica en t − 30 min | `weather/series.py` l. 85 |
| Uso en el solver | `conductance = area/(outer_resistance + g)`; `face_power = conductance·(equivalent_ambient − T)` | `thermal3d/solver.py` l. 275–276 |

* El **viento** solo entra por h. Cambia la resistencia de la película 1/h; no
  cambia la temperatura de referencia.
* La **radiación** solo entra por T_sa, dividida por el mismo h. Por eso no se
  cuenta dos veces junto con la convección. Bajo una capa, el sol absorbido
  afuera también tiene que atravesar R_capas.
* a = absortancia (0,65 hormigón, 0,6 moldaje) y f = fracción sobre la cara
  (1 en caras horizontales, 0,35 en verticales). Ambos son supuestos
  declarados en `config/environment_g8.json`.

## Trazabilidad del resultado

`resumen.json` registra el snapshot usado (`folder`, `retrieved_at`, `sha256`,
`request_url`), el inicio UTC, Δt y su límite, el balance de energía, el hash
del IFC de los voxeles y el estado de cada dato. En el título de cada figura
aparece la carpeta del snapshot. Si se ejecuta con `--synthetic`, el resultado
queda rotulado como **SINTÉTICO** en todas partes. Esa opción es solo para
probar sin internet y no reemplaza al snapshot real.

## Supuestos y límites

* La simulación es corta y todo el volumen se coloca en t = 0. Sirve para
  mostrar el pipeline; no es el plan de vertidas.
* La hidratación es un pulso coseno sintético (qmax 1300 W/m³) y no está
  calibrada.
* El inicio del período es la primera hora completa después de la descarga.
  El script no extrapola: si la serie no cubre las horas pedidas, se detiene.
* La temperatura profunda del suelo (10 °C) es un supuesto.
* No hay sombreado ni onda larga nocturna.
* `--coarsen 2` (voxeles de 0,5 m) se usa solo en vistas rápidas y en las
  pruebas.

[Variables horarias de Open-Meteo](https://open-meteo.com/en/docs#hourly_parameter_definition)
· [Formato VTK XML ImageData](https://docs.vtk.org/en/latest/vtk_file_formats/vtkxml_file_format.html)
