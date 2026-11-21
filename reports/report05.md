# Reporte 05 — Riesgo térmico y decisión provisional del Grupo 8

**Fecha:** 20 de noviembre de 2026. **Repositorio:** [Proyecto-2-MCOC](https://github.com/chuntley-tech/Proyecto-2-MCOC). **Commit evaluado:** [`9ea542f`](https://github.com/chuntley-tech/Proyecto-2-MCOC/commit/9ea542f29cf08d1e5774c654566bf743f1574995).

## 1. Criterio y simulaciones

Se busca terminar la última vertida lo antes posible, contando las esperas desde el **19 de noviembre de 2026 a las 08:00 de Santiago**, inicio común del escenario simulado. Se cuenta una falla cuando **la temperatura máxima supera 70 °C o el diferencial máximo supera 20 °C**, incluso si se superan ambos límites en la misma corrida. El diferencial toma, en un mismo instante, la temperatura máxima del hormigón colocado y la mínima reconstruida a 25 mm bajo las caras expuestas. Para aceptar probabilísticamente un plan se exige cerrar los horizontes y obtener una cota superior del IC bilateral del 95 % para la unión inferior al 5 %.

- **S8 de referencia:** 200 simulaciones Monte Carlo, 100 por lote, con semillas `20261119` y `20261219`. Malla de 500 × 500 × 550 mm, paso máximo de 600 s y horizonte de 157 días. El pronóstico aporta 373 h y las restantes 3395 h se completan por persistencia. [Resumen de los lotes](../results/final/s8_mc/summary.json).
- **Diez planes del visor:** 30 simulaciones deterministas, tres mallas por plan, durante 157 días con paso máximo de 600 s. Comparten el miembro 23 del ensamble y los demás insumos del escenario elegido. Las tres mallas de un plan son un ensayo de discretización del mismo escenario. [Manifiesto](../results/final/s8_pour_comparison/manifest.json) · [Resultados](../results/final/s8_pour_comparison/summary.json).
- **Referencias históricas de la tabla:** 200 corridas Monte Carlo para S7 y 100 para el plan de tres capas a 12 °C. Se conservan sus configuraciones de campaña y sus horizontes propios. [S7, lote base](../results/final/g8_20261119_mc/s7_base/comparison.json) · [S7, confirmación](../results/final/g8_20261119_mc/s7_confirm/comparison.json) · [Plan de tres capas](../results/final/g8_20261119_mc/base31/comparison.json).

## 2. Incertidumbres

| Variable | Tratamiento en el Monte Carlo de S8 | Dato que falta |
| --- | --- | --- |
| Fuente de hidratación | Selección uniforme de las curvas M1–M4_SS, con multiplicador uniforme entre 0,84 y 1,20. | Ensayo de la mezcla de obra y contraste de la cinética con registros independientes. |
| Clima | Selección uniforme entre 31 miembros GFS de Open-Meteo. Temperatura, viento y radiación horarios. Persistencia tras 373 h. | Pronóstico actualizado al inicio efectivo y escenarios posteriores para comprobar los picos tardíos. |
| Temperatura de colocación | Nominal de 16 °C en S8 de referencia, con variación uniforme de ±2 °C. S8‑V01 usa 14 °C fijos en el ensayo determinista. | Capacidad de enfriamiento y tolerancia de temperatura a pie de bomba. |
| Suelo y propiedades del hormigón | Temperatura inicial y profunda uniforme entre 8 y 12 °C. Conductividad, densidad y calor específico fijos. | Medición del suelo y ensayos térmicos representativos de la mezcla. |
| Protección y ejecución | Mantas, subbase, fechas de retiro y bombeo fijos. Una bomba a 40 m³/h como supuesto constructivo. | Fichas y disponibilidad, resistencia efectiva instalada, aprobación de subbase y confirmación de suministro. |
| Malla y superficie | Malla fija en Monte Carlo. Tres niveles en los diez planes, con reconstrucción de temperatura a 25 mm desde la cara voxelizada. | Estabilidad espacial del diferencial de S8‑V01 y contraste de la reconstrucción con la geometría del IFC. |

El muestreo supone independencia entre las variables aleatorias. [Configuración de S8](../config/monte_carlo_s8.json) · [Distribuciones heredadas](../config/monte_carlo_final_g8.json).

## 3. Evolución de la probabilidad e intervalo de confianza

Para el S8 de referencia, la estimación P̂f(N) es el número de fallas observadas dividido por N, primero con las muestras del lote base y luego con las de confirmación. La tabla usa IC binomiales exactos de **Clopper–Pearson** al 95 % para la unión de fallas observadas hasta el día 157. [Datos por corrida](../results/final/s8_mc/samples.csv).

| N acumulado | Fallas observadas | P̂f(N) | IC 95 % | Horizontes abiertos |
| ---: | ---: | ---: | ---: | ---: |
| 25 | 0 | 0 % | [0 %; 13,72 %] | 24 |
| 50 | 0 | 0 % | [0 %; 7,11 %] | 38 |
| 100 | 0 | 0 % | [0 %; 3,62 %] | 81 |
| 150 | 0 | 0 % | [0 %; 2,43 %] | 126 |
| 200 | 0 | 0 % | [0 %; 1,83 %] | 167 |

Cada lote por separado obtuvo **0/100** e IC **[0 %; 3,62 %]**. El intervalo se estrecha al sumar muestras, pero **167 horizontes quedaron abiertos**. El conteo y el intervalo se refieren a la ventana simulada. El riesgo integral bajo el umbral del 5 % sigue pendiente de demostrar. [Resumen Monte Carlo](../results/final/s8_mc/summary.json).

## 4. Comparación de planes

**Sin estimar** indica que el plan solo se ensayó en un escenario. Los máximos indicados para los planes del visor son los de la malla fina de **187,5 × 187,5 × 137,5 mm**.

| Plan | P(Tmax>70) | P(ΔT>20) | Impacto constructivo | Recomendación |
| --- | --- | --- | --- | --- |
| **S8‑V01** | Sin estimar | Sin estimar | Una vertida a 14 °C, 12,11 h. Exige colocación continua y control de la temperatura. | Priorizar para el siguiente lote. T máxima 57,48 °C y ΔT 16,65 °C. |
| S8‑V02 | Sin estimar | Sin estimar | Una vertida a 16 °C, 12,11 h. Alternativa si el suministro a 14 °C resulta inviable. | Mantener como alternativa de una vertida. T máxima 59,42 °C y ΔT 16,85 °C. |
| S8‑V07 | Sin estimar | Sin estimar | Dos vertidas a 15 °C, con inicios separados 24 h. Termina en 25,06 h y requiere gestionar la junta. | Mantener como alternativa de dos vertidas. T máxima 58,24 °C y ΔT 17,42 °C. |
| S8‑V08 | Sin estimar | Sin estimar | Tres vertidas a 14 °C, con inicios separados 24 h. Termina en 49,06 h y requiere dos juntas. | Descartar en el escenario ensayado: ΔT de 28,03 °C. |
| S8 de referencia | 0 % observado en ambos lotes | 0 % observado en ambos lotes | Una vertida a 16 °C nominal, 12,11 h y retiro final de protección al día 150. | Usar como referencia probabilística de su propia configuración. Falta cerrar los horizontes. |
| S7 | 0 % observado en ambos lotes | 0 % observado en ambos lotes | Una vertida a 16 °C nominal, 12,11 h y retiro final al día 105. | No priorizar. Una verificación fina alcanzó ΔT de 20,78 °C. |
| Tres capas a 12 °C, manta de 25 mm | 0 % (0/100) | 100 % (100/100) | Tres vertidas en 24,11 h, con retiro de manta a las 504 h. | Descartar en su campaña. IC 95 % de la unión [96,38 %; 100 %]. |

[Comparación de los diez planes](../results/final/s8_pour_comparison/comparison.csv) · [Verificación fina de S7](../results/final/s7_convergence/summary.json).

## 5. Recomendación provisional y evidencia que puede cambiarla

**Priorizar S8‑V01 para verificación.** Empata en duración con V02 y presenta menor diferencial en las tres mallas. Su ΔT pasa de **15,89 a 15,47 y 16,65 °C**, por lo que la convergencia espacial de ese indicador queda pendiente. V07 cumple el objetivo exploratorio de convergencia en el escenario comparado y queda como alternativa si la colocación continua resulta inviable. [Convergencia por plan](../results/final/s8_pour_comparison/summary.json).

**¿Qué información que llegue entre hoy y la fecha final (TBD) podría cambiar su decisión?** Una confirmación del proveedor sobre descarga a 14 °C y bombeo continuo a 40 m³/h determinaría si V01 es ejecutable. Si solo se garantizan 16 °C, V02 gana prioridad. Si se necesita dividir el suministro, se vuelve a evaluar V07 y su junta. La dosificación real, las fichas de mantas, la aprobación estructural y geotécnica de la subbase o un pronóstico más frío también pueden modificar los máximos. La confirmación final requiere un Monte Carlo propio del plan elegido, horizontes cerrados y una verificación espacial del diferencial en realizaciones críticas. [Evidencias pendientes](../docs/S8_VALIDACION_Y_ACEPTACION.md).
