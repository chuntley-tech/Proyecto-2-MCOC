# Integración adaptada de Proyecto-2-MCOC (2).zip

Fuente: ZIP entregado por el usuario, revisado el 27 de octubre de 2026.
No se importaron su entorno virtual, metadatos Git, cachés ni resultados como
si fueran mediciones o verificaciones propias.

## Qué se aprovechó

| Propuesta del ZIP | Adaptación local |
|---|---|
| `thermal3d/reference.py` | Referencias continuas, semidiscretas y perfil exacto de dos capas sobre nuestra API `Parameters` |
| Estudio `convergence_nd.py` | Convergencia temporal 2D/3D contra semidiscreta, sin mallas nodales nuevas |
| Materiales por voxel | Campos k, ρ y cp compatibles con escalares; media armónica y estabilidad local |
| Caras expuestas | Opción `exposed`; el comportamiento adiabático anterior sigue siendo el predeterminado |
| Registro de energía | Aportes acumulados de fuente y bordes solo en instantes solicitados; conserva `save_every` |
| Resistencia de moldaje/aislación | `effective_h` con validación y ensayo sintético; no representa material calibrado |
| Voxelización desde JSON | Sustituida por triangulación del IFC guardado con IfcOpenShell; GUID y SHA-256 trazables |
| Demo de fundación | Consume la máscara IFC y material común del enlace existente; mantiene base adiabática explícita |
| Matriz de verificación y CLI | `scripts.verify` añade selección y cambios de parámetros; la batería base sigue en `verify_3d` |
| Guías E04/E05/E06 | Reescritas para los comandos actuales y resultados regenerados, sin copiar cifras antiguas |

## Compatibilidad y decisiones

No se reemplazó `thermal1d`, el IFC nominal de 3.30 m, el JSON del caso ni las
guías originales del curso. Tampoco se adoptaron `Grid/Problem`, `max_saved`,
la redistribución de todos los pasos temporales o el reemplazo de temperaturas
inactivas por NaN del solver alternativo. Se amplió la API existente.

Las condiciones sobre interfaces activa/inactiva son optativas: activar Robin
es una decisión física explícita. Las propiedades variables no se infieren de
nombres de materiales IFC; la demo G8 conserva propiedades homogéneas comunes.

La voxelización ajusta el número de celdas al tamaño real de la caja, registra
el Δ efectivo y valida cierre de las mallas. Su referencia es el volumen de los
triángulos IFC, no el volumen analítico de un cilindro ideal. La prueba de
modificación guarda una copia IFC editada y demuestra que cambia la grilla sin
editar el JSON. También se ensayan unidades milimétricas y traslaciones.

Todos los nuevos resultados térmicos son sintéticos. La convergencia del volumen
no se fuerza a ser monótona ni se presenta como convergencia de temperaturas.
Las limitaciones y evidencias están en [E06](E06_dossier_verificacion.md).

La publicación en GitHub requiere una solicitud explícita del usuario,
conforme a `AGENTS.md`.
