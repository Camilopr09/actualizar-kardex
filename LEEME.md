# Actualizar Kardex

App de escritorio (Windows) con tres pestañas: **qué hay que actualizar**, **qué encontré en el sistema** y
**qué encontré en el kardex**. Compara Hospital Office con el Google Doc «KARDEX MIS PX» y propone los cambios
de DX / EVOLUCIÓN / TRATAMIENTO con tus reglas (nota más reciente del especialista; «IGUAL MANEJO» conserva
el tratamiento y suma lo nuevo de las órdenes).

## Qué necesita el computador
- Windows 10/11 con **Google Chrome o Microsoft Edge** (Edge ya viene con Windows). No hay que instalar nada más si usas el `.exe`.
- Obtener el `.exe`: en GitHub → pestaña **Actions** → «Actualizar Kardex (.exe para Windows)» → *Run workflow* → descargar el artefacto `Actualizar-Kardex-Windows`. (O ejecutar `construir.bat` en un Windows con Python.)

## Uso
1. **Iniciar sesión** (solo la primera vez): se abre un navegador con dos pestañas; entra a Hospital Office y a tu cuenta de Google; cierra el navegador. Queda guardado en `%LOCALAPPDATA%\ActualizarKardex\perfil`.
2. **Analizar**: la app lee el kardex y la Agenda, abre la historia de cada paciente del kardex y arma la lista. Se abre el navegador; no lo cierres.
3. Revisa las pestañas. En «Qué hay que actualizar» selecciona una fila para ver *Ahora* vs *Nuevo*; desmarca con ☐ lo que no quieras. **Copiar texto nuevo** sirve para pegar a mano.
4. **Escribir en el kardex** (opcional, ver abajo). Deshacer: Archivo → Historial de versiones.

## Para escribir en el documento (opcional)
Leer y comparar NO requiere nada de Google Cloud. Para que la app escriba sola:
Google Cloud → crear proyecto → activar *Google Docs API* → Credenciales → *ID de cliente OAuth* tipo «App de escritorio» →
descargar y guardar como `credentials.json` en `%LOCALAPPDATA%\ActualizarKardex\`. La primera vez pide autorizar.

## Límites conocidos
- Solo escribe celdas DX/EVOLUCIÓN/TRATAMIENTO de filas existentes. **Agregar, retirar, mover de servicio y cambiar habitación se muestran como avisos** para hacerlos a mano.
- Las lecturas de Hospital Office (nombres de columnas, botón «Ver», cambio de modo Urgencias/Hospitalización) se escribieron según lo aprendido en la sesión anterior y **no se han probado contra el sistema real**. Si algo falla, la app guarda HTML y captura en `%LOCALAPPDATA%\ActualizarKardex\diagnostico` para ajustarlo.
- Si la Agenda pagina los resultados, solo se leen las filas visibles.
- Confirma con la clínica (Ley 1581) que la lectura automatizada esté permitida. `credentials.json`, `token.json`, `perfil\` y `diagnostico\` contienen datos sensibles.
