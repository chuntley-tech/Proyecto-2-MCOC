# Referencias contrastadas con las guías

Revisión del 20 de octubre de 2026. Se contrastaron las referencias del ZIP
`Proyecto-2-MCOC.zip` con las guías G00–G08 y la guía extensa de difusión
entregadas posteriormente en `guias.zip`. Los originales están en [guias](guias/README.md).

## Correspondencia de conceptos e implementación

| Tema del proyecto | Referencia comprobada | Aplicación |
|---|---|---|
| Separación BIM, solver y visualizador | [G00](guias/G00_MAPA_CONCEPTUAL.md) y [G08](guias/G08_ARQUITECTURA_DEL_PROYECTO.md) | El solver usa Python externo y entradas JSON |
| IFC abierto e interoperabilidad | [G01](guias/G01_BIM_IFC_REVIT_OPENBIM.md) | Archivo IFC4 y validación de unidades, clases y propiedades |
| Blender, Bonsai y tres objetos | [G02](guias/G02_BLENDER_BONSAI.md) | Tres componentes identificables y procedimiento de edición/guardado |
| Geometría y GUID desde Python | [G03](guias/G03_IFCOPENSHELL_PYTHON.md) | Inspección con IfcOpenShell y comparación por GUID |
| Balance y difusividad | [G05](guias/G05_DIFUSION_TERMICA_FD.md); [Difusión](guias/DIFUSION_DE_CALOR_1D_2D_3D.md), §§1–3 y 26 | `ρ cp ∂T/∂t = k ∂²T/∂z² + q̇` |
| FTCS, estabilidad y solución exacta | G05; Difusión, §§5–8 y 30 | Solver 1D y estudios de convergencia |
| Neumann y Robin, medias celdas | Difusión, §§9–12 y 22 | Flujos en los extremos y conservación de energía |
| Fuente uniforme y energía adiabática | G05, tests recomendados; Difusión, §§21–22 y 33 | Pruebas de aumento lineal y conservación |
| Propiedades térmicas de referencia | Difusión, §31 | Plantilla ilustrativa: k≈2,22 W/(m·K), ρ=2400 kg/m³, cp=970 J/(kg·K) |
| Verificación frente a validación | Difusión, §32 | Los casos exactos verifican el código; no validan sensores del G8 |

G02 permite nombres distintos si se documenta un esquema equivalente. El modelo
actual identifica sus componentes mediante `G8-BASE-01`…`G8-BASE-03` y
`MCOC_InitialModel`; todavía no define un plan constructivo ni todos los campos
de planificación sugeridos por la guía.

## Ejemplos del ZIP anterior

Se corrigieron las atribuciones que presentaban las adaptaciones como si fueran
copias literales de los ejemplos del curso. Los nombres de archivo se mantienen
para no romper los comandos y pruebas existentes.

| Configuración | Referencia y relación real |
|---|---|
| `case_g8.json` | Adaptación de la solución seno de Difusión §7 y convergencia §8: longitud, amplitud, propiedades y duración propios del caso sintético G8 |
| `01_dirichlet_video.json` | Caso ilustrativo del ZIP con extremos distintos, basado en Dirichlet de §9.1. No coincide con §7, que usa un seno y extremos iguales |
| `03_neumann_video.json` | Adaptación del problema de §10: mismo mecanismo, pero el ZIP usa 18000 s y la guía 6000 s; también difiere la imposición de Dirichlet al instante inicial |
| `04_robin_video.json` | Extensión con aire sinusoidal de los bordes Robin de §§11–12. La guía §12 utiliza aire constante |
| `05_fuente_video.json` | Caso con fuente uniforme y extremos fríos, relacionado con §§5 y 21. No es el ejemplo adiabático de §21 |
| `06_losa_robin_guia.json` | Coincide con los parámetros y condiciones de la losa convectiva de §12: 1 m, 81 nodos, 70 °C inicial, aire 20 °C, h=12, k=2, ρ=2400, cp=900 y 48 h |
| `plantilla_hormigon.json` | Las propiedades coinciden con §31, que las atribuye a Ju y Lei (2019). Bordes, temperaturas y duración son decisiones ilustrativas de la plantilla |

La coincidencia de §31 se comprobó contra la guía recibida; no constituye una
verificación independiente de la tabla del paper ni de la mezcla del proyecto.
El caso principal conserva k=2,2 y cp=900 como parámetros sintéticos de prueba.

## Convención de signo y formulación de borde

G05 y Difusión §9 expresan el flujo **saliente** como `-k ∇T·n`.
La API del proyecto recibe el flujo **entrante**, de signo opuesto:

```text
flux_in_w_m2 = -q_saliente
Robin: flujo entrante = h (T_ambiente - T_superficie)
```

Es una convención equivalente. La prueba de flujo impuesto comprueba que el
aumento de energía es `q_entrante × tiempo` por unidad de área.
El límite implementado para Robin se deriva del balance explícito sobre media
celda: `Fo (1 + Bi) ≤ 1/2`. No se presenta como una transcripción literal del
paso conservador elegido en el ejemplo de la guía.

La referencia correcta para ese tratamiento nodal son §§10, 12 y 22. La sección
28 describe otra disposición: centros de celda separados de la superficie por
media celda y resistencias térmicas en serie. No se confunden ambas formulaciones.

## Alcance geométrico y siguientes etapas

Estas guías no establecen las cotas que justificarían el modelo eliminado del
ZIP anterior. Se mantiene exclusivamente el IFC de **3,30 m totales**, según la
imagen aportada por el usuario. La interpolación de la transición sigue siendo
un supuesto documentado, no una dimensión confirmada por G00–G08.

G04, G06 y G07 orientan etapas posteriores: voxelización, visualización de campos
3D y clima. No se implementan solo por incorporar las referencias. Las pruebas
2D/3D que recomienda G05 también quedan para la ampliación del solver.

Las guías sí están disponibles y fueron revisadas para esta correspondencia.
La demostración manual actual en Bonsai y la lectura individual de cada
integrante conservan su estado propio; no se dan por realizadas al citar fuentes.
