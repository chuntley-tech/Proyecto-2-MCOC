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
2. Modificar temperatura inicial, duración y condiciones de borde. En las
   opciones desplegables aparecen material, fuente y resolución.
3. Pulsar **Calcular temperaturas**. Cambiar un control deja pendiente el
   recálculo hasta pulsar el botón.
4. Arrastrar el modelo para girarlo, usar la rueda para acercar y abrir cortes
   verticales u horizontales para ver el interior.
5. Recorrer los estados guardados con la barra temporal o reproducirlos.
   Los gráficos muestran las temperaturas calculadas de cada estado.
6. **Exportar resultados** descarga los parámetros, tiempos, campos e historias
   en JSON. **Guardar HTML** guarda otra copia autónoma del visor.

Los controles describen ensayos **sintéticos**, no mediciones del proyecto.
Dirichlet impone la temperatura en la cara; en 2D/3D la celda vecina está a
media separación de ella y su temperatura puede ser distinta. Neumann usa
flujo entrante positivo; flujo cero es adiabático. Robin incluye resistencia
de conducción hasta la cara y convección. La base tiene controles propios.

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

La suite completa ejecutada el 28 de octubre de 2026 terminó con **175 pruebas
aprobadas en 115.05 s**, sin pruebas omitidas.

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
