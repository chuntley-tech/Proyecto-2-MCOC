# Instrucciones del proyecto

## Propósito

El equipo deberá **diseñar, justificar y defender un plan de construcción por vertidas** para una fundación de hormigón masivo.

## Reglas de trabajo

- No inventar mediciones. Identificar la fuente y las unidades de los datos utilizados. Distinguir explícitamente las mediciones reales, los supuestos y los resultados calculados o simulados. Si faltan datos, indicarlo.
- No ejecutar comandos destructivos de Git, como `git reset --hard`, `git clean -fd`, `git checkout -- .` o `git push --force`.
- No publicar cambios ni actualizar GitHub (incluidos `git push`, pull requests o ediciones remotas) hasta que el usuario lo solicite explícitamente. Mantener los cambios locales mientras no exista esa solicitud.
- No subir credenciales, contraseñas, tokens, claves privadas ni datos personales o confidenciales al repositorio. Usar variables de entorno o archivos locales excluidos por `.gitignore`. Los archivos de ejemplo deben contener únicamente valores ficticios.
- Revisar los archivos y los cambios antes de cada commit: `.gitignore` no detecta secretos dentro del código ni protege archivos que Git ya está siguiendo.
- Ejecutar las pruebas pertinentes después de modificar código. Informar qué pruebas se ejecutaron y sus resultados. Si no existen pruebas o no pueden ejecutarse, indicarlo explícitamente; no afirmar que pasaron.
- Mantener `requirements.txt` actualizado al agregar, cambiar o eliminar dependencias de Python, fijando las versiones utilizadas para facilitar la recreación del entorno.
