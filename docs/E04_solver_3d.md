# E04: solver térmico cartesiano centrado en celdas

## Alcance y procedencia

Implementación propia en `thermal3d/`, independiente de Blender. No sustituye
`thermal1d/` ni lee directamente el IFC. Sigue G05, G04, G08 y las secciones
de difusión multidimensional y balances de voxel de la guía de difusión.
**Todos los parámetros y temperaturas de esta verificación son sintéticos**;
no son mediciones ni una predicción de la fundación G8.

Los resultados de la tabla proceden de
[`resumen.json`](../results/verification_3d/resumen.json), generado antes de
escribir este documento mediante:

```cmd
.venv\Scripts\python.exe -m scripts.verify_3d
.venv\Scripts\python.exe -m pytest -q tests/test_thermal3d.py --durations=0
```

## Balance y discretización

La ecuación es \(\rho c_p\partial_tT=k\nabla^2T+\dot q\). Cada celda cumple:

\[
C_i\frac{T_i^{n+1}-T_i^n}{\Delta t}
=\sum_jG_{ij}(T_j^n-T_i^n)+\dot q(t_n)V_i+Q_{b,i}(t_n),
\quad C_i=\rho c_pV_i,\quad G_{ij}=kA_{ij}/d_{ij}.
\]

Los arrays siguen los ejes `(x,y[,z])`. Los centros son
\(x_i=(i+1/2)\Delta x\), con \(\Delta x=L_x/n_x\), análogamente en los
demás ejes. Los espaciamientos pueden ser distintos. En dos dimensiones
se usa profundidad unitaria. El stencil contiene centro y cuatro vecinos
(cinco puntos), o centro y seis vecinos (siete puntos). Cada interfaz se
calcula una vez por slicing y aporta potencias iguales y opuestas.

`active` selecciona celdas participantes. Las interfaces activa/inactiva son
**adiabáticas por defecto**; `exposed` permite asignarles explícitamente un
borde. Las inactivas no cambian. Materiales distintos usan media armónica de
conductividad y capacidad propia por celda.

## Bordes y tiempo

Se reutilizan `Dirichlet`, `Neumann` y `Robin` de `thermal1d.solver`:

- Dirichlet: \(Q_b=G_b(T_b-T_i)\), \(G_b=kA/(\Delta/2)\).
- Robin: \(Q_b=G_b(T_\infty-T_i)\),
  \(G_b=[1/(hA)+(\Delta/2)/(kA)]^{-1}\); si h es cero, no hay intercambio.
- Neumann: \(Q_b=q_{in}A\), positivo hacia dentro.

Las condiciones se asignan por cara exterior `x-`, `x+`, `y-`, `y+`, `z-`,
`z+`; una cara omitida es adiabática. Las conductancias y máscaras se
precalculan antes del bucle temporal. La fuente y el ambiente variable se
evalúan **al inicio del paso**, en \(t_n\). El último paso se acorta hasta
la duración exacta. Se guarda inicial, cada `save_every` pasos y final,
junto con \(E=\sum_{activos}\rho c_pVT\), relativa al cero Celsius.

Se rechaza el paso si falla cualquiera de los criterios:

\[
\alpha\Delta t\sum_a\Delta a^{-2}\le1/2,
\qquad\Delta t\le\min_{activos}\frac{C_i}{\sum_jG_{ij}+G_{b,i}}.
\]

El segundo incluye las contribuciones de todas las caras Dirichlet/Robin
de una celda, incluso esquinas. Los errores muestran el límite calculado.

## Resultados verificados

Errores de temperatura en °C; errores de balance relativos salvo indicación.
El estudio espacial usa Fo por eje de 0.01 y paso proporcional al cuadrado
del espaciamiento; el chequeo externo usa 0.05.

| Ensayo | Resultado calculado |
|---|---|
| Referencias externas 2D | 8.599209e-4; 2.178354e-4; 5.463764e-5 |
| Seno 2D, error fino / órdenes | 1.201467e-4 / 1.972885; 1.993250 |
| Seno 3D, error fino / órdenes | 1.377562e-4 / 1.960988; 1.990289 |
| Energía adiabática | 1.774818e-16 |
| Fuente constante, todas las celdas | 5.350252e-14 |
| Fuente variable evaluada en inicio | 3.036981e-16 |
| Neumann, máximo entre caras ensayadas | 8.064942e-15 |
| Robin frente a referencia nodal fina | error fino 4.470141e-5; órdenes 1.875635; 1.951416 |
| Diferencia entre referencias Robin | 2.600652e-7; cada referencia guarda dos estados |
| Ambiente Robin variable | error absoluto 0 |
| Máscara con hueco y recorte en L | energía 2.190793e-16; cambio inactivo 0 |
| Anisotropía frente a modo 1D discreto | 6.661338e-16; cambio al variar x/z 5.551115e-17 |
| Ausencia de periodicidad, un paso | cambio lejano y cara opuesta 0 |
| Estabilidad general / local Robin | límites 0.0104166666667 / 0.00694448148138 s; aceptación inferior y rechazo superior |
| Guardado y último paso acortado | tiempos 0; 0.009; 0.018; 0.019 s |
| Ejecución del script / pico residente | 4.221303 s / 75.272 MB |

Las tolerancias de pytest se justifican junto a cada comprobación. La referencia
Robin se interpola en centros; su diferencia por refinamiento es menor que
el error del solver multidimensional. No se almacena su historial completo.

## Diferencias y trabajo pendiente

`thermal1d` es nodal, incluye nodos superficiales y medias celdas en extremos.
Aquí los centros están dentro del dominio, todos los volúmenes son completos
y los bordes se conectan mediante resistencias de media celda.

La ampliación de [E06](E06_dossier_verificacion.md) verifica voxelización del
IFC, materiales heterogéneos y superficies expuestas por separado.
**Pendiente:** convergencia térmica sobre la fundación, activación de vertidas,
hidratación real, clima, moldaje y suelo calibrados, y Monte Carlo/HPC. Las
pruebas sintéticas no justifican todavía decisiones constructivas.
