# Conexión automática entre IFC y solver 1D

El caso principal importa la altura y las propiedades comunes de material desde
el IFC guardado. El modelo nominal sigue teniendo 3,30 m. El lector funciona en
Python externo y no necesita que Blender esté abierto.

## Qué se importa

| Entrada del solver | Fuente en IFC |
|---|---|
| Longitud vertical L | Máximo z menos mínimo z de la geometría de los tres GUID configurados |
| Conductividad k | `MCOC_Thermal1D.Conductivity_W_mK` |
| Densidad ρ | `MCOC_Thermal1D.Density_kg_m3` |
| Calor específico cp | `MCOC_Thermal1D.SpecificHeat_J_kgK` |

El conjunto `MCOC_Thermal1D` está **solo en el cilindro G8-BASE-03**. Actúa como
entrada común para todo el material homogéneo del modelo 1D, no solo para el
cilindro. Los valores iniciales 2,2 W/(m·K), 2400 kg/m³ y 900 J/(kg·K) son los
valores sintéticos del caso de verificación; no son mediciones G8.

Se elige una sola fuente de propiedades para evitar promediar o resolver
silenciosamente contradicciones entre piezas. El modelo aún no resuelve
materiales distintos por capa.

## Cómo ensayar desde Bonsai y CMD

1. Abrir nuevamente el IFC actualizado para cargar el conjunto de propiedades.
2. Trabajar sobre una copia, guardada como `results/lab/edited.ifc`.
3. Seleccionar el cilindro superior y entrar a **Object Information → Property
   Sets → MCOC_Thermal1D**.
4. Cambiar, por ejemplo, `Conductivity_W_mK` de 2,2 a 1,1 y confirmar la edición.
5. Guardar con **Save IFC Project**. El lector necesita el archivo en disco.
6. Desde la raíz del proyecto, ejecutar:

```cmd
.venv\Scripts\python.exe -m scripts.run_case --ifc results/lab/edited.ifc --output results/lab_ifc_editado
```

La consola muestra el IFC, la altura y las propiedades utilizadas. Para este
ejemplo, reducir la conductividad reduce la difusividad y hace más lento el
enfriamiento, manteniendo las demás condiciones. Los resultados y el hash del
archivo de entrada quedan guardados en `summary.json`.

Si cambias la altura real del cilindro, conservando su base en contacto con la
transición, el solver reconstruye su malla y perfil inicial con la nueva altura
total. Cambiar únicamente el texto `MCOC_InitialModel.Height_m` no modifica la
geometría y no cambia L. No se ha automatizado la edición dentro de Bonsai:
las pruebas realizan cambios equivalentes sobre copias IFC y las guardan.

### Cambiar la altura del cilindro en Bonsai

1. Seleccionar `G8-BASE-03` y abrir **Geometry and Materials → Representations
   → Representation Utilities → Get Representation IFC Parameters**.
2. En la fila de `IfcExtrudedAreaSolid`, cambiar la profundidad de extrusión de
   1,10 a 1,30 m y pulsar Enter. Mantener el radio de `IfcCircleProfileDef` en
   3,50 m para conservar el diámetro de 7 m.
3. Aplicar con las flechas circulares **de la misma fila del valor editado**.
   Las flechas superiores de la fila `Model / Body` recargan la representación;
   no aplican el valor pendiente y pueden devolverlo al anterior.
4. Comprobar visualmente desde una vista frontal que sube la cara superior y
   que la inferior permanece en contacto con la transición.
5. Guardar con **Save IFC Project** y ejecutar el comando anterior indicando
   la copia guardada. Con un cilindro de 1,30 m, la altura total será 3,50 m.

Este cambio es un ensayo; el IFC nominal del repositorio conserva 3,30 m.

## Qué permanece en JSON

Las condiciones de borde, temperatura/perfil inicial, fuente, cantidad de nodos,
paso temporal y duración continúan en el caso JSON. Tampoco se deduce una
conductividad a partir del nombre comercial del material. Solo se leen los
campos explícitos de la tabla, con unidades SI en sus nombres.

La sección `ifc` de `config/case_g8.json` define el archivo y los GUID de interés.
Su ruta es relativa a la carpeta del JSON; `--ifc` permite usar una copia y su
ruta se interpreta desde el directorio actual. La identificación por GUID
permite renombrar objetos; si se reemplazan y cambian sus GUID, hay que revisar
la selección del dominio.

El IFC tiene prioridad para los cuatro campos importados. `--no-ifc` desactiva
esa conexión para una ejecución. Los ejemplos JSON sin sección `ifc` mantienen
su comportamiento anterior.

## Límites y comprobaciones

- El solver sigue usando una sección constante equivalente. Cambiar solo el
  ancho o el diámetro se registra en la geometría y el hash, pero no altera
  automáticamente las temperaturas. No se ha implementado un solver 3D.
- Se comprueba que los intervalos verticales de las piezas estén en contacto y
  que sus envolventes tengan una zona XY común. No es un análisis general de
  intersecciones de sólidos ni certifica la validez de cualquier geometría 3D.
- Si falta una propiedad o es inválida, se interrumpe la lectura. No se suponen
  datos ni se vuelve silenciosamente al valor del JSON.
- Los vértices IFC se leen en metros, incluso si el archivo usa milímetros.
- Los cambios de L o α pueden exigir un Δt menor. El control de estabilidad
  sigue activo y da el límite admisible. Se puede ajustar desde CMD con
  `--set thermal.dt_s=150`, sin editar el JSON.
- El lector y el solver no guardan ni regeneran el IFC. `scripts.create_ifc`
  sí lo regenera desde los datos nominales: no usarlo para ejecutar una edición.

Las pruebas verifican cambios guardados de altura y conductividad, identidad
por GUID, conversión de unidades, conservación del JSON, casos inválidos y
trazabilidad del resumen. Esta automatización no valida físicamente la mezcla
ni convierte el caso sintético en una predicción real de la fundación.
