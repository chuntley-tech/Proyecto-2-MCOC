# Diez alternativas de vertida para S8

Los 30 cálculos mantienen el IFC, una bomba de 40 m³/h, 484,41 m³ de volumen
de referencia, una espera mínima de 6 h entre vertidas y los materiales
y retiros de S8. Los cortes de las vertidas se ubican a 1,10 o 2,20 m y
la cubierta central se define mediante una sección física del IFC a 2 m.
La fecha común es el 19 de noviembre de 2026 a las 08:00 de Santiago.
La duración incluye cualquier espera desde esa hora. Se simula hasta el
día 157, siete días después del retiro de las mantas.

| Caso | Inicios desde t₀ [h] | Aire pronosticado al inicio [°C] | Hormigón al colocar [°C] | Duración [h] |
|---|---|---|---:|---:|
| S8-V01 | 0 | 10,5 | 14 | 12,11 |
| S8-V02 | 0 | 10,5 | 16 | 12,11 |
| S8-V03 | 4 | 13,9 | 16 | 16,11 |
| S8-V04 | 0, 24 | 10,5 / 8,0 | 14 | 28,79 |
| S8-V05 | 0, 28 | 10,5 / 17,2 | 16 | 32,79 |
| S8-V06 | 4, 48 | 13,9 / 10,4 | 15 | 52,79 |
| S8-V07 | 0, 24 | 10,5 / 8,0 | 15 | 25,06 |
| S8-V08 | 0, 24, 48 | 10,5 / 8,0 / 10,4 | 14 | 49,06 |
| S8-V09 | 4, 28, 52 | 13,9 / 17,2 / 17,6 | 16 | 53,06 |
| S8-V10 | 0, 36, 60 | 10,5 / 13,8 / 14,1 | 15 | 61,06 |

Las temperaturas de colocación son hipótesis de suministro y se mantienen
durante las vertidas del plan correspondiente. El aire, viento y radiación
provienen del miembro 23 del ensamble GFS de Open-Meteo del 17 de noviembre,
consultado para el punto docente de Llanquihue. Se mantienen la curva M3_SS,
el factor de calor y la temperatura inicial del suelo de la muestra crítica
46. Después de 373 horas de pronóstico se usa persistencia, incluyendo
la etapa de retiro de las mantas.
[Metadata del pronóstico](../data/weather/2026-11-17T1622Z_ensemble/metadata.json).

Se comparan tres mallas alineadas de 750 × 750 × 550, 375 × 375 × 275 y
187,5 × 187,5 × 137,5 mm. El paso temporal máximo es 600 s. El ajuste
de Richardson se informa solo para secuencias con cambios monótonos y
decrecientes. Es un orden aparente de los máximos globales y no sustituye
una verificación temporal para cada alternativa. El criterio de cribado
térmico es T máxima ≤ 70 °C y diferencial máximo ≤ 20 °C, con horizonte
cerrado. Cada plan se evalúa para un único escenario climático.

Las vertidas se activan progresivamente por niveles. Mientras una capa queda
expuesta, usa las condiciones de protección del modelo S8. La preparación
de juntas, las resistencias entre capas y la posibilidad de alcanzar la
temperatura de descarga requieren validación constructiva.

```powershell
python -m scripts.compare_s8_pours --workers 12
python -m scripts.compare_s8_pours --aggregate
```

La corrida usa 12 procesos y un hilo de biblioteca numérica por proceso.
Al volver a ejecutar, reutiliza resultados correspondientes al manifiesto.
El agregador acepta resultados parciales y registra su conteo.
[Manifiesto de la campaña](../results/final/s8_pour_comparison/manifest.json).

En el visor, abre **Decisión G8 → ¿Cuántas vertidas convienen?**.
Los gráficos comparan duración de obra, diferencial máximo y temperatura
máxima. Los gráficos térmicos muestran las tres mallas y el límite del curso.
El filtro por número de vertidas se aplica también a la tabla. El selector de
detalle muestra las horas locales, el aire pronosticado y dos gráficos de
convergencia espacial del plan seleccionado. Cada gráfico compara uno de
los máximos entre las tres mallas a paso temporal máximo fijo y muestra
el cambio al último refinamiento y el orden aparente cuando se puede calcular.
Se destaca el menor plazo entre los
planes dentro de ambos límites y con picos capturados en todas sus corridas
disponibles. El desempate usa el diferencial de la malla más fina común.
El visor conectado puede actualizar la tabla desde Python. El HTML portátil
incluye los resultados disponibles al momento de exportarlo.
