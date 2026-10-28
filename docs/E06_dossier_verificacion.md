# E06: evidencias de verificación y avance geométrico

Este dossier utiliza resultados recalculados localmente después de adaptar el
segundo ZIP. **Todos los datos térmicos son sintéticos**; los volúmenes proceden
de la geometría docente IFC, no de mediciones de una fundación construida.

## Evidencias y reproducción

| Comando `python -m ...` | Resultados |
|---|---|
| `scripts.verify_3d` | [Batería base](../results/verification_3d/resumen.json), convergencia espacial y figura |
| `scripts.verify` | [Matriz adicional](../results/verification/matriz.md) y [métricas](../results/verification/resultados.json) |
| `scripts.convergence_nd` | [Estudio temporal](../results/convergence_nd/resumen.json), CSV y PNG |
| `scripts.voxelize_foundation` | [Volúmenes](../results/voxel/volumen.csv), [procedencia IFC](../results/voxel/resumen.json) y NPZ |
| `scripts.foundation_3d_demo` | [Demostración térmica](../results/voxel/demo_termica_fundacion.json) y corte PNG |

Usar Python de `.venv`. Las opciones y ejemplos están en [E05](E05_guia_laboratorio.md).

## Solver y resultados calculados

El balance centrado usa caras de media celda, resistencias Robin en serie,
fuentes evaluadas en el inicio del paso y conductancias precalculadas. Con
materiales distintos, la media armónica garantiza un único flujo de interfaz.
El registro energético comprueba `E−E0−Q_borde−Q_fuente` en estados guardados.
Las celdas inactivas permanecen intactas. No se sustituye la API 1D existente.

| Prueba | Resultado de los JSON enlazados |
|---|---|
| Orden espacial 2D | 1.972885; 1.993250 |
| Orden espacial 3D | 1.960988; 1.990289 |
| Robin transitorio frente a 1D fino | órdenes 1.875635; 1.951416 |
| Orden temporal 2D | 1.004047; 1.002018; 1.001008 |
| Orden temporal 3D | 1.005559; 1.002769; 1.001382 |
| Dos materiales, estacionario por tramos | error máximo 0 °C; conductancia de interfaz ≈16 W/K |
| Energía con capacidades variables | error relativo 5.115679e-16 |
| Fuente y capacidad propia por celda | error relativo máximo 2.220446e-16 |
| Superficies expuestas, fuente y balance | residuo relativo 2.934969e-16; cambio inactivo 0 °C |

Para medir el orden temporal se compara con la solución **semidiscreta**.
El error contra el continuo puede aumentar al reducir Δt debido a compensación
entre errores espaciales y temporales: eso no es el criterio de este ensayo.
Las tolerancias estrictas se justifican con los errores medidos junto a los tests.

## IFC y voxelización

Se conserva el caso nominal de **3.30 m** y sus tres componentes. IfcOpenShell
lee los triángulos del archivo guardado, en coordenadas globales SI. La regla
de clasificación es centro dentro/fuera; la superficie queda escalonada.
El origen y los espaciamientos efectivos `Δ=L/n` acompañan la máscara.

La referencia volumétrica es la triangulación del IFC: **487.350199 m³**.
Los errores relativos para Δx solicitado de 0.5, 0.25, 0.125 y 0.0625 m son
**0.004617205; 0.006027895; 0.001316191; 0.000313881**. No disminuyen
monótonamente. La resolución más fina alcanza aproximadamente **0.0314 %**.
No se atribuye este error al solver térmico.

La demo usa **28184** celdas activas, parte de **30 °C**, toma aire constante
de **10 °C** y h de **10 W/(m²·K)**. Después de **604800 s**, la sonda central
activa llega a **27.462812 °C**. El residuo energético relativo es
**7.291569e-16**. No hay hidratación, clima real ni suelo; el resultado solo
demuestra el funcionamiento del pipeline y de los bordes sobre una máscara.

## Límites y pendientes

- La convergencia térmica sobre la fundación requiere comparar temperaturas y
  flujos entre resoluciones; el estudio de volumen no la reemplaza.
- Los tres componentes geométricos no son automáticamente vertidas. Falta
  activación temporal y una planificación constructiva justificada.
- Las pruebas heterogéneas no calibran un modelo de suelo ni una mezcla real.
- `effective_h` permite resistencias de ensayo, pero faltan espesores,
  propiedades y secuencias reales de moldaje/aislación.
- El clasificador exige mallas cerradas y rechaza solapamientos detectados en
  centros; no certifica ausencia global de autointersecciones o solapamientos.
- La demo mantiene el enlace de material común y la geometría vertical del
  caso G8; no es una interfaz general para cualquier edificio IFC.
- Faltan hidratación real, clima, Monte Carlo/HPC y análisis de confiabilidad.
- No se dispone del Anexo 4 original del ICH en el ZIP; la lectura individual
  solicitada no se reemplaza por esta documentación.
