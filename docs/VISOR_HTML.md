# Visor térmico portátil

## Abrir y compartir

Copiar **`visor_termico.html`** al otro computador y abrirlo con doble clic
en un navegador moderno con JavaScript habilitado. El archivo incluye estilos,
gráficos, cálculo térmico y geometría voxelizada: no requiere Python, Blender,
Node, un servidor ni conexión a Internet. No depende de una ruta de este equipo.

El cálculo se ejecuta en un Web Worker del navegador. La vista 3D usa WebGL2;
si no está disponible, utiliza una representación con Canvas. Se necesita un
navegador que permita JavaScript y workers locales; políticas de seguridad de
equipos administrados pueden restringirlos. No se ha ensayado cada sistema
operativo ni cada versión de navegador.

## Usar el visor

1. Elegir fundación G8, caja 2D, caja 3D o perfil 1D.
   En **Cubo / bloque 3D**, elegir **Cubo · lados iguales** para cambiar un
   único lado, o **Bloque · dimensiones independientes** para editar Lx, Ly
   y Lz por separado. La sección de geometría está visible sobre los controles
   térmicos. Las dimensiones admitidas son de 0.1 a 20 m.
2. Modificar temperatura inicial, duración y condiciones de borde. En las
   opciones desplegables aparecen material, fuente y resolución.
   Todos estos controles funcionan también con el bloque editable: Dirichlet,
   Neumann, Robin, condición independiente en la base, aislación en el borde
   principal Robin, perfil inicial, fuente, malla y paso temporal. Las celdas
   por eje se mantienen iguales en cantidad; sus tamaños cambian como Lx/n,
   Ly/n y Lz/n. El paso automático se adapta al límite de estabilidad.
3. Pulsar **Calcular temperaturas**. Cambiar un control deja pendiente el
   recálculo hasta pulsar el botón.
4. Arrastrar el modelo para girarlo, usar la rueda para acercar y abrir cortes
   verticales u horizontales para ver el interior.
5. Recorrer los estados guardados con la barra temporal o reproducirlos.
   Los gráficos muestran las temperaturas calculadas de cada estado.
   La curva temperatura–tiempo incluye líneas discontinuas con las temperaturas
   Dirichlet impuestas en el borde principal y la base, cuando corresponda.
   Son horizontales porque estos controles imponen temperaturas constantes.
   Los puntos de las curvas y el cursor vertical avanzan con el modelo.
   Pulsar el gráfico selecciona el estado guardado más cercano a ese tiempo.
   **Temperatura según la altura** compara cinco perfiles de la columna
   central: inicio, aproximadamente un cuarto, mitad, tres cuartos y final
   del cálculo. Se añade el instante seleccionado si es distinto; su curva
   aparece más gruesa y cambia durante la reproducción. Los tiempos rotulados
   corresponden a estados realmente guardados. Los extremos Dirichlet se
   dibujan en las caras físicas, además de los centros de las celdas.
6. **Exportar resultados** descarga los parámetros, tiempos, campos e historias
   en JSON. **Guardar HTML** guarda otra copia autónoma del visor.

Los controles describen ensayos **sintéticos**, no mediciones del proyecto.
Dirichlet impone la temperatura en la cara; en 2D/3D la celda vecina está a
media separación de ella y su temperatura puede ser distinta. Neumann usa
flujo entrante positivo; flujo cero es adiabático. Robin incluye resistencia
de conducción hasta la cara y convección. La base tiene controles propios.

## Fuente temporal de la pizarra

El modo cubo/bloque 3D inicia ahora con el pulso activo, inicio uniforme a
20 °C, base adiabática y observación de cuatro días. Después de seleccionar
el modo, pulsar **Calcular temperaturas** para actualizar los resultados.
Qmax queda fijo en **1300 W/m³** en el visor. La duración del pulso continúa
editable. Para cambiar el tipo de fuente, usar su selector y después calcular.
Una fuente constante cero produce correctamente una línea horizontal: el
gráfico lo señala explícitamente como **Sin generación de calor**.

En **Generación de calor Q(t)** se puede elegir una fuente constante o el pulso
temporal de la fotografía entregada por el usuario:

```text
Q(t) = Qmax/2 · [1 − cos(2πt/τ)]   si 0 ≤ t < τ
Q(t) = 0                          si t ≥ τ
```

Q se interpreta como potencia volumétrica en W/m³ porque aparece como término
fuente en `ρ cp ∂T/∂t − k ∇²T = Q(t)`. Qmax no es temperatura ni calor
acumulado. El pulso alcanza Qmax en τ/2; para τ = 2 días, al día 1. Su integral
completa es Qmax·τ/2 J/m³, usando τ en segundos. El valor fijo del visor,
Qmax = 1300 W/m³, es un **supuesto sintético elegido por el usuario**, sin
calibración experimental.

El cubo inicia con Dirichlet principal a 20 °C, base Neumann adiabática y
pulso de 2 días. La altura y las otras dimensiones siguen siendo editables;
no se deduce una tercera dimensión de la foto 2D. Se utiliza únicamente
**Calcular temperaturas**, sin botones adicionales para aplicar el ensayo.

El gráfico Q(t) representa la función impuesta; los perfiles y la historia
central representan la temperatura resuelta. La fuente se evalúa al comienzo
de cada paso `t_n`. El paso automático respeta la estabilidad y se limita
además a τ/100 para resolver el pulso. Un paso manual excesivamente grande
respecto de τ puede representar mal la fuente aunque sea estable.

El máximo central mostrado es el mayor de los estados guardados. No se fuerza
que alcance 70 °C ni se considera Qmax = 70: alcanzar ese valor requeriría
elegir o calibrar Qmax para una geometría, material y bordes específicos.

## Geometría incluida y actualización

El HTML contiene una captura del IFC guardado al construirlo, con máscaras en
tres resoluciones. El identificador SHA mostrado permite reconocer esa versión.
El archivo portátil no lee automáticamente un IFC que se edite después.
Para incorporar cambios guardados en Bonsai, ejecutar desde la raíz del proyecto:

```cmd
.venv\Scripts\python.exe -m scripts.build_dashboard
```

Esto regenera `visor_termico.html`, que debe volver a compartirse. Las cajas
2D/3D son dominios sintéticos; el modo fundación usa la máscara exportada del IFC.

## Versión conectada al Python del proyecto

Es opcional y utiliza los solvers originales con el IFC local guardado:

```cmd
.venv\Scripts\python.exe -m scripts.serve_dashboard --open
```

El servidor escucha solo en `127.0.0.1`. Esa dirección sirve únicamente en el
computador que ejecuta Python. Para compartir sin instalar nada, enviar el HTML
portátil en vez de la dirección del servidor.

## Verificación

La suite completa ejecutada el 29 de octubre de 2026 terminó con **185 pruebas
aprobadas en 106.18 s**, sin pruebas omitidas. Incluye el contraste Python y
JavaScript del pulso temporal en 1D/2D/3D y su integral discreta adiabática,
comprobando la evaluación en el inicio del paso y el último paso acortado.

`tests/test_dashboard_offline.py` contrasta el núcleo JavaScript con Python en
1D, 2D, 3D y la fundación, con fuentes y los tres tipos de borde. Node se usa
solo para automatizar ese contraste durante el desarrollo; el usuario del HTML
no lo necesita. También se verifica que el archivo incorpore todos sus recursos
y prohíba conexiones de red mediante su política de contenido.

Se comprobó en el navegador el recálculo del archivo autónomo servido inicialmente
por HTTP y después con el servidor apagado. La apertura automatizada mediante
`file:` quedó restringida por la herramienta de navegación; no se presenta como
una prueba realizada. La apertura directa debe hacerse desde el explorador de
archivos del computador destinatario.
