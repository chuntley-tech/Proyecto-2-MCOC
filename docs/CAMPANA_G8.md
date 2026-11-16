# Campaña térmica y decisión constructiva del G8

## Definición

`config/final_g8.json` declara el origen común del jueves 19 de noviembre de
2026, la capacidad por bomba, el número de bombas, la espera mínima, la
temperatura de colocación y las protecciones. Son variables de escenario
del curso. El ejemplo comienza a las 08:00 en Santiago (11:00 UTC), usa una
bomba de 40 m³/h, seis horas de espera mínima y colocación a 20 °C.

El volumen de referencia proviene del mismo IFC voxelizado a 0,25 m para
todos los planes y refinamientos. Las vertidas son secuenciales. Cada
duración se calcula como volumen dividido por caudal total disponible.
**D es el instante en que termina la última vertida, medido desde t₀.**
Incluye una postergación inicial, las esperas y la colocación. El enfriamiento
posterior se reporta en el horizonte térmico. Para aproximar el llenado,
cada nivel de la grilla se activa en el instante en que se alcanza el
punto medio de su volumen, de abajo hacia arriba. El modelo supone
colocación horizontal uniforme en cada nivel.

Sea $u$ un plan de partición, secuencia, inicios, temperatura de colocación,
protecciones y retiros. Con un caudal de colocación $r_j$ para el volumen $V_j$,
se compara el tiempo hasta terminar la última vertida.

$$
d_j = V_j/r_j,\qquad D(u)=\max_j(t_{j,\mathrm{inicio}}+d_j)-t_0,
\qquad \min_{u\in\mathcal U:\,P_f(u)\le0.05} D(u).
$$

## Insumos e indicadores

- **Hidratación.** El archivo original `data/hydration/source_terms.txt` da
  ocho fuentes invertidas de probetas. El β de 2,5 W/(m²·K) pertenece a esa
  inversión de laboratorio. Se interpolan los registros en W/m³ sobre la
  edad cronológica de cada celda. De la colocación al primer dato se usa
  una rampa de 2 h desde cero. La cola decae exponencialmente desde el último
  dato con escala supuesta de 24 h. Una fuente terminal cero da cola cero.
  Las integrales de cada registro y del modelo añadido se informan por
  separado. El caso base usa Ea = 0 porque el archivo describe tiempo de
  ensayo. Cambiar Ea aplica una hipótesis adicional de edad equivalente.
  La cabecera describe cilindros de radio 37,5 mm y altura 150 mm, densidad
  de 2476 kg/m³, calor específico de 1023 J/(kg·K) y 350,77 kg/m³ de cemento
  en el diseño Arrieta. La fuente se obtuvo por inversión térmica axisimétrica
  de volúmenes finitos, con base spline cúbica y regularización de Tikhonov.
  Se conserva la señal tabulada y se interpola linealmente entre registros.
  Las propiedades nominales de la fundación proceden del caso docente
  ($k=2{,}2$ W/(m·K), $\rho=2400$ kg/m³, $c_p=900$ J/(kg·K)).
  Se mantiene la potencia por volumen del ensayo al trasladarla al modelo.
  El archivo no confirma que todas las probetas correspondan a una sola receta.
- **Clima.** Se congeló el ensamble GFS 0,25° descargado de Open-Meteo para
  las coordenadas docentes. Se escogen tres miembros completos cerca de
  los rangos 10, 50 y 90 por temperatura media durante la parte pronosticada.
  Cada uno conserva juntos su aire, viento y radiación. La cola se completa
  con el ciclo horario medio de sus últimas 72 h y se etiqueta como
  persistencia. Primero se recortan las horas terminales sin algún dato.
  La interpolación se reserva para huecos internos entre observaciones del
  modelo. Los tres pesos iguales son una hipótesis docente.
  En la campaña ampliada se comparan dos miembros omitidos y un cambio
  aislado de cola. El caso frío y ventoso combina el rango del percentil 10
  de aire del miembro y el de viento medio durante su cuartil más frío.
  El cálido y soleado combina los rangos de las medias de aire y radiación.
  El miembro central se repite con las últimas 72 horas consecutivas
  del pronóstico, conservando el orden de las variables del bloque.
  Los tres ensayos se cruzan con las cuatro curvas SS y se reportan como
  sensibilidad sin peso probabilístico.
- **Pesos.** El cálculo principal pondera las cuatro curvas SS como casos
  equiprobables. Las cuatro 22A se evalúan y se incluyen en una sensibilidad
  con las ocho curvas equiprobables, por su menor confianza declarada en
  el archivo. Ambas comparaciones son escenarios de sensibilidad, con
  independencia supuesta entre clima y curva. La equivalencia de las
  probetas con la mezcla de obra requiere validación externa.
- **Temperaturas.** En cada paso se busca la máxima del hormigón colocado.
  Se reconstruye la temperatura a 25 mm bajo cada cara en contacto con
  aire sobre un perfil lineal entre la cara y el centro, coherente con la
  resistencia conductiva de media celda y el flujo de borde del solver.
  Al agregar hormigón, la cara que pasa a tener vecino activo se convierte
  en interfaz interna. El diferencial usa la máxima y la mínima a 25 mm
  del mismo estado. La aproximación se contrasta con malla refinada.
- **Horizonte.** Se registra el máximo en 336 h y, cuando corresponde, en
  hasta 504 h. Se amplía cuando la última vertida o el último retiro deja
  menos de 72 h, el pico cae en el último día, o la envolvente horaria de
  máximos de un día al siguiente sube más de 0,05 °C. Se comprueban también
  los máximos de cada vertida en esta última condición. Si el criterio sigue activado al
  final de la ampliación, el caso se marca abierto. Un caso abierto de
  peso positivo y sin excedencia observada impide declarar factible el plan.
- **Selección.** La unión cuenta una sola vez un escenario que excede
  ambos límites. El comparador ordena por duración y selecciona el primero
  con riesgo conjunto ≤ 5 % y clasificación cerrada. Si no existe, registra
  selección vacía. El resultado aplica al conjunto discreto evaluado.

Para cada escenario $s$, el dominio $\Omega_c(t)$ contiene el hormigón colocado
y $S_{25}(t)$ representa la reconstrucción a 25 mm bajo sus caras expuestas.

$$
M_T(u,s)=\max_{t,\,x\in\Omega_c(t)}T(x,t),\qquad
M_\Delta(u,s)=\max_t\left[\max_{x\in\Omega_c(t)}T(x,t)-\min_{x\in S_{25}(t)}T(x,t)\right].
$$

$$
F(u,s)=\{M_T(u,s)>70\,{}^\circ\mathrm C\}\cup\{M_\Delta(u,s)>20\,{}^\circ\mathrm C\},\qquad
P_f(u)=\sum_s w_s\,\mathbf{1}_{F(u,s)}.
$$

## Comparación de referencia

Los cuatro planes colocan 484,41 m³. Los escenarios principales cruzan las
cuatro curvas SS con tres historias meteorológicas. Se ejecutaron 96 casos
incluyendo la sensibilidad con las curvas 22A.

| Plan | D [h] | P(T > 70 °C) | P(ΔT > 20 °C) | Unión a 14 días | Unión final | ΔT máximo entre escenarios SS [°C] |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A · Continua | 12,11 | 0 % | 100 % | 100 % | 100 % | 50,28 |
| C · Tres vertidas con espera mínima | 24,11 | 0 % | 100 % | 100 % | 100 % | 40,20 |
| B · Tres vertidas de referencia | 49,06 | 0 % | 100 % | 100 % | 100 % | 50,79 |
| D · Tres vertidas espaciadas y aisladas | 84,11 | 0 % | 100 % | 100 % | 100 % | 41,95 |

Ninguna alternativa cumple el 5 %. C obtiene el menor diferencial máximo
de los cuatro planes. En C el mínimo superficial crítico está en un lateral
en ocho escenarios SS y en la cara superior en cuatro. La siguiente
comparación puede mantener su cronograma y variar el espesor de la
protección lateral y el momento de retiro de la manta superior.

Cada historia tiene 165 horas de pronóstico desde t₀. Para los horizontes
de 336 y 504 h se agregan 171 y 339 horas por persistencia, respectivamente.
Ocho casos SS y dos de sensibilidad se extendieron a 504 h. Todos cerraron
según los criterios de la campaña. Con las ocho curvas, el riesgo conjunto
también fue 100 % en los cuatro planes.

En el caso A con M4_SS y clima central, reducir la malla de
0,50 × 0,50 × 0,55 m a 0,25 × 0,25 × 0,275 m cambió el máximo térmico en
0,076 °C y el diferencial en 0,011 °C. Reducir el paso máximo de 600 a 300 s
en la grilla base cambió esos resultados en 0,003 °C y 0,00044 °C. Las tres
corridas exceden el límite de diferencial. La comprobación de sensibilidad
corresponde a ese escenario. Los resultados están en
[`comparison.csv`](../results/final/g8_20261119/comparison.csv) y
[`verification.json`](../results/final/g8_20261119/verification.json).

## Familia ampliada

La familia mantiene el IFC, volumen, caudal, espera mínima y mezcla fija
en cada escenario. A, B, C y D son las cuatro referencias. C1 conserva
el cronograma de C e incrementa la manta lateral de 25 a 50 mm tras
desmoldar. C2 conserva la manta lateral y mueve el retiro superior de
336 a 408 h desde $t_0$. C3 combina ambas medidas. Los espesores y fechas
son hipótesis constructivas. La realización de material y clima es común
a todas las vertidas de una corrida. Cada plan se evalúa en 24 combinaciones
de las ocho curvas y los tres miembros principales, más 12 sensibilidades
de clima con SS. La comparación cubre esta familia discreta de siete
planes y 252 corridas.

| Plan | Fin de colocación [h] | Mayor ΔT a 14 días [°C] | Mayor ΔT a 21 días [°C] | Riesgo conjunto principal |
| --- | ---: | ---: | ---: | ---: |
| A | 12,11 | 50,28 | 50,28 | 100 % |
| C | 24,11 | 37,58 | 41,93 | 100 % |
| C1 | 24,11 | 35,50 | 41,19 | 100 % |
| C2 | 24,11 | 37,58 | 39,08 | 100 % |
| C3 | 24,11 | 35,50 | 38,54 | 100 % |
| B | 49,06 | 50,79 | 50,79 | 100 % |
| D | 84,11 | 39,85 | 43,59 | 100 % |

Las 252 corridas superaron el diferencial de 20 °C. La mayor temperatura
de todo el lote fue 65,13 °C, por debajo de 70 °C. Para cada plan, la
probabilidad marginal de temperatura fue 0 % y la de diferencial fue
100 % bajo los pesos declarados. La inclusión de las curvas 22A y las
84 corridas de sensibilidad climática conservan la conclusión.
La sensibilidad usó los miembros 14 (frío y ventoso), 08 (cálido y
soleado) y 29 (central con bloque de 72 h).

C3 redujo el mayor diferencial principal de C en 3,39 °C y conservó su
duración de colocación. Su pico ocurrió a las 428 h, 20 h después del
retiro superior. Todas las corridas alcanzaron 504 h y cerraron según
el criterio de envolvente. En la familia ampliada se simuló hasta ese
horizonte en todos los casos para observar el comportamiento tras el
último retiro. Cada simulación gruesa tardó 11,9 s de mediana y 14,0 s
como máximo en el lote local. El residuo energético relativo máximo
fue 3,93 × 10⁻¹⁵.

La campaña queda identificada por su
[`manifest.json`](../results/final/g8_20261119_ampliada/manifest.json),
con hashes del código, IFC, fuente y clima. Se reprodujo la combinación
de vertida única del índice 0 desde una copia aislada de los insumos
y código local, con los mismos máximos, tiempos y coordenadas.
El [resumen completo](../results/final/g8_20261119_ampliada/comparison.json)
incluye las métricas de ambos horizontes y las pruebas climáticas.

### Sensibilidad cerca de la cara crítica

Se verificó el escenario principal de máximo diferencial de C, D y C3.
En los tres, el escenario fue M4_SS con clima central y la cara crítica
fue la superior.

| Plan | ΔT con malla base [°C] | ΔT con malla fina y paso de 300 s [°C] | Hora del pico refinado [h] |
| --- | ---: | ---: | ---: |
| C | 41,93 | 39,86 | 357,5 |
| D | 43,59 | 41,74 | 356,0 |
| C3 | 38,54 | 36,15 | 428,0 |

En C, refinar sólo la malla dio 39,87 °C. Reducir sólo el paso dio
41,93 °C. En estos ensayos el refinamiento espacial tiene un efecto
mayor en el diferencial y las tres clasificaciones se mantienen.
En el pico refinado de C3, el perfil normal a la superficie da
15,18 °C en la cara, 16,50 °C a 25 mm y 22,44 °C en el primer centro
a 137,5 mm. La tabla del visor muestra también el mínimo superficial
antes y después del retiro. Su ubicación puede cambiar entre instantes.
[`verification.json`](../results/final/g8_20261119_ampliada/verification.json)

## Ejecutar

Editar una copia de `config/final_g8.json` y usar un directorio de campaña
nuevo. Desde la raíz, con el entorno del proyecto activo:

```sh
python -m scripts.final_campaign prepare results/final/alternativa --config config/final_g8.json --mesh 2
python -m scripts.final_campaign local results/final/alternativa --workers 4
python -m scripts.final_campaign aggregate results/final/alternativa
python -m scripts.final_campaign verify results/final/alternativa
```

`prepare --mesh 2` permite usar una malla de 0,50 m en la campaña local.
En ese caso `verify` refina el escenario examinado a la malla de
0,25 m y prueba por separado la mitad del paso temporal para C. Se prueba
el refinamiento combinado para C, D y la mejor variante encontrada por
riesgo conjunto y diferencial máximo, o el plan factible seleccionado.
El cronograma y los volúmenes de obra se conservan en estos cálculos.

Para ejecutar en Slurm, sustituir el comando `local` por un job array.
Usar la cantidad de tareas que imprime `prepare`, con índices desde cero.

```sh
LOT=results/final/alternativa
COUNT=252
JOB=$(sbatch --parsable --array="0-$((COUNT-1))%8" scripts/final_campaign.slurm "$LOT")
sbatch --dependency="afterok:${JOB%%;*}" --wrap="python -m scripts.final_campaign aggregate '$LOT'"
```

La campaña guarda el manifiesto, un resultado por combinación, las tablas
`scenarios.csv` y `comparison.csv`, y `comparison.json` para **Decisión G8**
en el visor. `verify` añade sensibilidad espacial y temporal, figuras y
campos VTK en los instantes críticos de C, un perfil normal a la cara en el
instante del diferencial y muestras antes y después de retirar la manta. El campo en
el instante del diferencial muestra las temperaturas de las celdas. La
temperatura reconstruida a 25 mm y su coordenada están en la tabla por
escenario.

## Guion de defensa

- Abrir el IFC y mostrar las tres piezas. El volumen triangulado es
  487,35 m³ y el de referencia voxelizado es 484,41 m³, una diferencia de
  0,60 %. Las vertidas se definen sobre esta última geometría.
- Explicar el balance `ρ cₚ ∂T/∂t = ∇·(k∇T) + Q(a)` y su balance de celda.
  La energía cambia por conducción entre vecinos, flujos de borde,
  hidratación y energía sensible del hormigón incorporado. El paso de
  Euler se limita por la capacidad y suma de conductancias de cada celda.
  El suelo comienza a 10 °C como supuesto, el hormigón entra a su temperatura
  de colocación y cada nivel comienza con edad cero.
- Mostrar cómo una cara superior temporal pasa de intercambiar con aire
  y manta a conducir hacia la siguiente vertida. En las caras al aire
  `h = 5,7 + 3,8 v₂` y `T_sol-aire = T_aire + α f G_sw / h`.
  Moldaje y manta agregan resistencia espesor/conductividad. La base
  transmite calor a través de las celdas de suelo.
- Mostrar la solución conocida, el balance energético y la sensibilidad
  de malla y tiempo con la [matriz de verificación](../reports/report01.md).
  Las fuentes de probeta provienen de una inversión y la campaña es una
  predicción condicionada a los insumos. Queda pendiente compararla con
  observaciones independientes de temperatura de la fundación de G8.
- Consultas: correspondencia entre probetas y recetas, mantas y tiempos
  constructivamente disponibles, referencia meteorológica aceptable para
  cubrir la parte del horizonte fuera de pronóstico.

[Open-Meteo Ensemble API](https://open-meteo.com/en/docs/ensemble-api)
