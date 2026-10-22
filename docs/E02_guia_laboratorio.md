# E02 · Guía rápida para el laboratorio del jueves

Material de preparación contrastado con las guías
[G02](guias/G02_BLENDER_BONSAI.md), [G03](guias/G03_IFCOPENSHELL_PYTHON.md) y
[G05](guias/G05_DIFUSION_TERMICA_FD.md). El modelo es `models/g8_base.ifc`
(tres componentes, altura total de 3,30 m), único modelo del proyecto.

Lo que pedirá el ayudante (enunciado E02), en orden:
1. abrir el IFC en Bonsai e identificar los objetos;
2. modificar geometría o una propiedad, guardar y demostrar que Python detecta el cambio (**sección 1**);
3. ejecutar el solver 1D, modificar Δx o Δt y explicar el efecto (**secciones 2 y 3**);
4. preguntas individuales breves (**sección 4**).

El enunciado E02 proporcionado por el usuario asigna 3 puntos. No se asume
un desglose de rúbrica adicional.

Todos los comandos se ejecutan en PowerShell, desde la raíz del proyecto.

## 0. Antes de entrar al laboratorio

```powershell
.\.venv\Scripts\python.exe -m pytest -q        # evidencia: todas las pruebas pasan
```

Abre Blender y carga el IFC antes de empezar la actividad para comprobar el entorno.

## 1. IFC: crear, guardar y cargar

**Con una copia del modelo principal** (prueba de ida y vuelta):

```powershell
New-Item -ItemType Directory -Path results/lab -Force
Copy-Item models/g8_base.ifc results/lab/edited.ifc
.\.venv\Scripts\python.exe -m scripts.inspect_ifc results/lab/edited.ifc --output results/lab/before.json
```

1. En Blender: **File > Open IFC Project** y abrir `results/lab/edited.ifc`.
2. Seleccionar `G8-BASE-02 - Transición inclinada` y, en **Object Information > Property Sets > MCOC_InitialModel**, cambiar `GeometryStatus` por `Prueba E02`.
3. Guardar con **File > Save IFC Project**, no con Save del `.blend`.
4. Comprobar el cambio desde Python:
   ```powershell
   .\.venv\Scripts\python.exe -m scripts.inspect_ifc results/lab/edited.ifc --compare results/lab/before.json
   ```
   Debe aparecer un cambio en `MCOC_InitialModel.GeometryStatus`.
5. Para volver al original, cerrar la copia y abrir `models/g8_base.ifc`.
   La comparación con archivos guardados está probada automáticamente; la edición
   manual de esta versión en Bonsai debe demostrarse durante la práctica.

Para que el solver use también el IFC editado:

```cmd
.venv\Scripts\python.exe -m scripts.run_case --ifc results/lab/edited.ifc --output results/lab_ifc_editado
```

El caso principal toma L de la geometría y k, ρ, cp de `MCOC_Thermal1D` en el
cilindro. Una modificación de texto como `GeometryStatus` se detecta en la
comparación, pero no cambia temperaturas. Para la demo térmica puede editarse
`Conductivity_W_mK`. Véase [IFC → solver](IFC_SOLVER_1D.md).

## 2. Solver 1D: resolver lo que pida el ayudante

Parte de la plantilla y cambia los datos con `--set`, sin editar código:

```powershell
.\.venv\Scripts\python.exe -m scripts.run_case --config config/ejemplos/plantilla_hormigon.json --output results/lab `
  --set initial.temperature_c=40 `
  --set bottom.type=dirichlet --set bottom.temperature_c=12 `
  --set top.type=robin --set top.h_w_m2k=15 --set top.ambient_c=5 `
  --set thermal.duration_s=172800
```

| Lo que piden | Cómo se escribe |
|---|---|
| Temperatura fija | `{"type": "dirichlet", "temperature_c": 20}` |
| Cara aislada o simetría | `{"type": "neumann", "flux_in_w_m2": 0}` |
| Flujo que entra (por ejemplo, sol) | `{"type": "neumann", "flux_in_w_m2": 300}` |
| Aire con convección | `{"type": "robin", "h_w_m2k": 12, "ambient_c": 20}` |
| Aire que oscila día/noche | `"ambient_c": {"mean_c": 10, "amplitude_c": 5, "period_h": 24}` |
| Calor interno | `"source_w_m3": 500` |
| Perfil inicial | `{"type": "uniform", ...}`, `"linear"`, `"sine"` o `"profile"` con puntos |

En la terminal sale un resumen: Fo y su máximo estable, la T final en el centro y
la T máxima. En `results/lab` quedan los gráficos de perfiles e historia.

**Si aparece "Paso inestable":** el mensaje indica el Δt máximo. Bájalo con `--set thermal.dt_s=...`.

## 3. Modificar Δz o Δt y explicar el efecto

Se usa el caso de verificación, porque tiene solución exacta y la consola
imprime el error. Δz = L/(nodos − 1): con 67 nodos, Δz = 0,05 m.

```powershell
.\.venv\Scripts\python.exe -m scripts.run_case --output results/lab_dt --set thermal.dt_s=1200
```

| Cambio (`--set …`) | Qué se observa | Por qué |
|---|---|---|
| ninguno (67 nodos, Δt = 600 s) | Fo = 0,244; error 6,4·10⁻⁴ °C | caso base |
| `thermal.nodes=34` (Δz al doble) | error 3,5·10⁻³ °C, unas 5 veces mayor | el error espacial crece como Δz² |
| `thermal.nodes=133` (Δz a la mitad) | el solver se niega: Fo = 0,98 > 0,5 y pide Δt ≤ 307 s | el Δt estable es Δz²/(2α): Δz a la mitad obliga a Δt/4 |
| `thermal.nodes=133` y `thermal.dt_s=150` | error 1,6·10⁻⁴ °C, 4 veces menor | segundo orden en Δz, con Fo igual al base |
| `thermal.dt_s=1200` (Δt al doble) | Fo = 0,489, sigue estable; error 2,7·10⁻³ °C | Euler explícito: el error crece con Δt |
| `thermal.dt_s=1300` | el solver se niega: Fo = 0,53 > 0,5 | se pasó del límite de estabilidad |
| `thermal.dt_s=1300` más `--allow-unstable` | temperaturas absurdas, del orden de 10²⁹ °C | el modo en zigzag crece como \|1 − 4Fo\|ⁿ |

Para **ver** la inestabilidad en un gráfico (`results\lab_inestable\profiles.png`):

```powershell
.\.venv\Scripts\python.exe -m scripts.run_case --config config/ejemplos/01_dirichlet_video.json --output results/lab_inestable --set thermal.dt_s=0.55 --set thermal.duration_s=20 --allow-unstable
```

Con Fo = 0,55 aparecen dientes de sierra y temperaturas entre −38 y 64 °C,
aunque todo debería quedar entre 0 y 20 °C: se viola el principio del máximo.
Con el Δt original (0,45 s, Fo = 0,45) eso no pasa.

## 4. Lo que conviene saber explicar

- **¿Por qué el solver no depende de Blender?** Lee datos en Python normal. Así se prueba, se repite y se corre en el clúster sin interfaz.
- **¿Por qué el borde usa 2·Fo?** El nodo de borde representa media celda, Δz/2.
- **¿Por qué Robin baja el Δt estable?** El nodo de borde también pierde calor hacia el aire. La condición es Fo (1 + Bi) ≤ 1/2.
- **¿Qué demuestran las pruebas?** Que el código resuelve bien la ecuación (verificación). Todavía no dicen nada sobre la fundación real (validación).
