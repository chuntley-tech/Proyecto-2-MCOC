# Integración de Proyecto-2-MCOC.zip

Fecha: 20 de octubre de 2026. Fuente: archivo aportado por el usuario.
Se revisaron e integraron fuentes, configuraciones, pruebas y preparación de
laboratorio. Los resultados se regeneraron localmente. El ZIP original se
conserva fuera del repositorio y se guardó un respaldo local previo a la integración.

## Mejoras incorporadas

- Solver explícito con bordes Dirichlet, Neumann y Robin, ambiente constante o
  sinusoidal, fuente volumétrica uniforme y guardado selectivo del historial.
- Balance sobre medias celdas en los extremos y control del límite de estabilidad
  de Robin. Verificación de energía, flujos y soluciones estacionarias.
- Casos JSON con condiciones iniciales uniforme, lineal, seno o perfil de puntos.
  `--set` permite cambiar entradas sin modificar archivos.
- Referencias exactas y semidiscretas, estudio de convergencia espacial y temporal
  con figuras, tablas y prueba automatizada de los órdenes esperados.
- Comparación de inspecciones IFC para detectar modificaciones guardadas. Se
  ajustó la identificación por GUID para soportar nombres modificados y se
  conservó la clave `footings` de los informes anteriores.
- Guías de preparación E02/E03 adaptadas al modelo principal y al entorno actual.

## Qué se conservó del proyecto actual

- `models/g8_base.ifc`: fundación principal de tres componentes, altura total
  3,30 m, zócalo octagonal, transición aproximada y cilindro Ø7 m × 1,10 m.
- La imagen acotada, el generador, la vista y las pruebas de esa geometría.
- Las coordenadas docentes G8: -41.222539, -73.295603.
- El caso de verificación de 14 días y sus propiedades sintéticas. Su formato
  JSON se amplió con bordes y condición inicial explícitos.
- Las dependencias fijadas, que son las mismas requeridas por las mejoras.
- `AGENTS.md`, especialmente la exigencia de solicitud explícita para publicar.

## Geometría única

Por instrucción del usuario se conserva únicamente models/g8_base.ifc, con
altura total de 3,30 m y tres componentes. Se eliminó la geometría incorrecta
del ZIP junto con sus archivos, generador, configuración, pruebas y resultados.
Las mejoras térmicas, la comparación IFC y la preparación E02/E03 se conservan.

## Ajustes respecto del ZIP

- Se endureció la validación de entradas: perfiles finitos y completos, ambiente
  sinusoidal finito, bandera de estabilidad booleana y funciones temporales finitas.
- Se corrigió el redondeo del número de pasos para no alargar el último paso
  más allá del Δt solicitado.
- Se añadió una regresión que modifica, renombra y guarda un objeto del modelo
  principal para comprobar que Python identifica ambos cambios por GUID.
- Se reemplazó la instrucción de descartar cambios con Git por una práctica
  sobre una copia IFC. No se copiaron instrucciones del ZIP a `AGENTS.md`.
- Se eliminaron afirmaciones de rúbrica no respaldadas por el enunciado recibido.

## Procedencia y límites

Las guías G00–G08 y la guía extensa de difusión fueron entregadas posteriormente
en `guias.zip` y se conservan en [guias](guias/README.md). Las referencias fueron
revisadas: se confirmó el fundamento de BIM/IFC, balance, bordes, estabilidad y
propiedades térmicas. Los ejemplos se identifican como casos coincidentes o
adaptaciones según [la revisión de referencias](REFERENCIAS_GUIAS.md).

No se importaron `.git`, el ambiente virtual, cachés, binarios de terceros,
capturas como evidencia de una revisión propia, ni resultados precalculados
como prueba de ejecución local. El modelo de 3,30 m se valida y los resultados
térmicos y de convergencia se volvieron a generar.

La edición manual en Bonsai del modelo actual sigue pendiente. Las pruebas
de cambios guardados usan IfcOpenShell, no una interacción manual con Bonsai.
La fuente uniforme no constituye un modelo de hidratación calibrado y el clima
sinusoidal no representa mediciones ni pronósticos del punto G8.

Los cambios permanecen locales hasta una solicitud explícita de publicación.
