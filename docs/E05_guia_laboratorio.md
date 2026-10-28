# E05: laboratorio con comandos adaptados

Ejecutar desde la raíz del proyecto. Los experimentos térmicos usan datos
sintéticos; las cifras válidas son las que genere cada ejecución.

## Baterías y convergencia

```cmd
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m scripts.verify_3d
.venv\Scripts\python.exe -m scripts.verify
.venv\Scripts\python.exe -m scripts.convergence_nd
```

- `verify_3d`: batería base, órdenes espaciales y comparación Robin/1D.
- `verify`: matriz adicional de dos materiales, capacidades variables,
  superficies expuestas, energía y orden temporal.
- `convergence_nd`: CSV, PNG y JSON de error temporal frente al seno semidiscreto.

Seleccionar una prueba y modificar condiciones sin tocar el código:

```cmd
.venv\Scripts\python.exe -m scripts.verify --only exposed --set exposed.h_w_m2k=20 --output results/lab_exposed
```

La matriz registra los valores calculados. Un criterio incumplido detiene la
ejecución; no se copian filas «OK» de resultados anteriores.

## Del IFC a los voxeles y al solver

```cmd
.venv\Scripts\python.exe -m scripts.voxelize_foundation
.venv\Scripts\python.exe -m scripts.foundation_3d_demo
```

El primer comando usa cuatro resoluciones, compara volúmenes contra la
triangulación IFC y guarda la grilla, origen, espaciamientos, GUID y hash del
archivo. El segundo lee el mismo IFC y sus propiedades térmicas comunes,
aplica convección a superficies expuestas y deja la base adiabática.

Para una copia editada en Bonsai:

```cmd
.venv\Scripts\python.exe -m scripts.voxelize_foundation --ifc results/lab/edited.ifc --output results/lab_voxel
.venv\Scripts\python.exe -m scripts.foundation_3d_demo --ifc results/lab/edited.ifc --output results/lab_termica
```

Mantener los GUID configurados y guardar **Save IFC Project**. El JSON no
define la geometría voxelizada. Si el sólido desaparece entre centros con una
grilla gruesa, refinar antes de interpretar sus temperaturas.

Modificar aire, convección, aislación o resolución de la demo:

```cmd
.venv\Scripts\python.exe -m scripts.foundation_3d_demo --set h_w_m2k=20 --set air_c=0 --output results/lab_frio
.venv\Scripts\python.exe -m scripts.foundation_3d_demo --set insulation_resistance_m2k_w=0.5 --output results/lab_aislado
.venv\Scripts\python.exe -m scripts.foundation_3d_demo --set dx_m=0.125 --set dz_m=0.1375 --output results/lab_fino
```

Más aislación reduce el intercambio con el aire; un aire más frío tiende a
acelerar el enfriamiento superficial. No asumir magnitudes sin correr el caso.
El paso de la demo se elige bajo ambos límites de estabilidad. Para ensayar
rechazos y `save_every`, usar los tests y la API `thermal3d.Parameters`.

## Qué explicar

Fuente volumétrica y flujo superficial tienen unidades y áreas de actuación
distintas. Refinar exige reducir el paso explícito. La convergencia del volumen
no garantiza convergencia térmica. Un campo bonito no sustituye un balance
energético ni una comparación con solución exacta.
