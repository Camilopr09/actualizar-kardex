# Actualizar Kardex

App para Windows con tres pestañas: **qué hay que actualizar**, **qué encontré en el sistema** y
**qué encontré en el kardex**. Compara Hospital Office con el Google Doc «KARDEX MIS PX» y propone los cambios
de DX / EVOLUCIÓN / TRATAMIENTO con tus reglas (nota más reciente del especialista; «IGUAL MANEJO» conserva
el tratamiento y suma lo nuevo de las órdenes).

La interfaz es una página local que se abre **en tu navegador (Chrome o Brave)** como una ventana de aplicación.
Todo lo que la app abre (su pantalla, Hospital Office, el Google Doc, el permiso de Google, «Abrir el kardex»)
usa el navegador que elijas en Ajustes. Edge ya no se usa.

## Qué necesita el computador
- Windows 10/11 con **Google Chrome o Brave**. No hay que instalar nada más si usas el `.exe`.
- Obtener el `.exe`: en GitHub → pestaña **Actions** → «Actualizar Kardex (.exe para Windows)» → *Run workflow* → descargar el artefacto `Actualizar-Kardex-Windows`. (O ejecutar `construir.bat` en un Windows con Python.)

## Uso
1. **Primer uso** (solo Google): la app abre el navegador con dos pestañas; entra a tu cuenta de Google (la que puede abrir el kardex). La app lo detecta (verás «✓ dentro») y guarda la sesión sola; también puedes pulsar «Guardar sesión ahora» o cerrar el navegador. Queda en `%LOCALAPPDATA%\ActualizarKardex\perfil-chrome` (o `perfil-brave`). **Hospital Office no guarda la sesión** (su cookie se pierde al cerrar el navegador), así que no hace falta entrar ahí en el primer uso.
   - **Usuario de Hospital Office (opcional, recomendado)**: en **Ajustes → Hospital Office** guarda tu usuario y contraseña. En cada análisis la app entra sola: va a la Agenda, escribe el usuario, envía, y si hace falta pulsa «Menu Principal» y «Atención de pacientes» hasta ver las grillas. Si la sesión vence a mitad del análisis, vuelve a entrar sola.
   - Sin usuario guardado: la app abre Hospital Office, te avisa («Esperando inicio de sesión…») y espera hasta 5 minutos a que entres tú en esa ventana; luego sigue sola.
   - Si el usuario o la contraseña no sirven, el análisis termina con «Usuario o contraseña de Hospital Office no válidos».
2. **Analizar**: la app lee el kardex y la Agenda, abre la historia de cada paciente del kardex y arma la lista. Se abre el navegador de automatización; no lo cierres. Puedes cancelar.
3. Revisa las pestañas. En «Qué hay que actualizar» selecciona una fila para ver *Ahora* vs *Nuevo*; desmarca lo que no quieras. **Copiar texto nuevo** sirve para pegar a mano.
4. **Escribir en el kardex** (opcional, ver abajo). Deshacer: Archivo → Historial de versiones del Google Doc.

La app se cierra sola tras 3 minutos sin usarse. Solo hay una a la vez: abrirla otra vez muestra la que ya está corriendo.

## Probar la interfaz sin nada (modo demostración)
`python app.py --demo` (o `"Actualizar Kardex.exe" --demo`): usa pacientes inventados, sin navegador de automatización ni red.
Otras opciones: `--no-abrir` (solo imprime la dirección) y `--puerto N`.

## Para escribir en el documento (opcional)
Leer y comparar NO requiere nada de Google Cloud. Para que la app escriba sola:
Google Cloud → crear proyecto → activar *Google Docs API* → Credenciales → *ID de cliente OAuth* tipo «App de escritorio» →
descargar el `credentials.json` y cargarlo en **Ajustes → Escribir en Google Docs**. La primera vez pide autorizar
(se abre en tu navegador elegido). El texto escrito conserva el formato de la celda.

## Límites conocidos
- Solo escribe celdas DX/EVOLUCIÓN/TRATAMIENTO de filas existentes. **Agregar, retirar, mover de servicio y cambiar habitación se muestran como avisos** para hacerlos a mano.
- Las lecturas de Hospital Office (nombres de columnas, botón «Ver», cambio de modo Urgencias/Hospitalización) se escribieron según lo aprendido en la sesión anterior y **no se han probado contra el sistema real**. Si algo falla, la app guarda HTML y captura en `%LOCALAPPDATA%\ActualizarKardex\diagnostico` para ajustarlo.
- Si la Agenda pagina los resultados, solo se leen las filas visibles.
- Los datos de pacientes solo viven en memoria mientras la app está abierta (no se guardan en disco, salvo `diagnostico\` si algo falla). El registro técnico `registro-app.txt` no incluye datos de pacientes.
- Las credenciales de Hospital Office se guardan en `hospital.bin` cifradas con **Windows DPAPI** (solo tu usuario de Windows en este computador puede descifrarlas); nunca se muestran de nuevo, ni van al registro ni a `diagnostico\` (antes de guardar un diagnóstico de login se vacía el campo de contraseña). Fuera de Windows (solo desarrollo) se usa base64, que NO protege.
- El inicio de sesión automático y la ruta «Menu Principal» → «Atención de pacientes» se escribieron según lo que se describió y **no se han probado contra el Hospital Office real** (cómo se llaman los campos del login, qué hay tras entrar, etc.). Si falla, revisa `diagnostico\` (`*-login.html`, `*-agenda.html`).
- Confirma con la clínica (Ley 1581) que la lectura automatizada esté permitida. `credentials.json`, `token.json`, `hospital.bin`, `perfil-*\` y `diagnostico\` contienen datos sensibles.

## Pruebas (desarrollo)
`python -m pytest -q tests`. Las pruebas con navegador (`test_e2e_ui.py`: recorrido de la interfaz en modo demo; `test_integracion_sistema.py`:
`flujo.analizar` contra un simulador de Hospital Office en `tests/simulador/`, que incluye login con cookie de sesión, Menu Principal → Atención de Pacientes y sesión que vence) usan Playwright con un Chromium; si no hay, se saltan.
Variables solo para pruebas: `KARDEX_CHROME` (ruta del Chromium), `KARDEX_HEADLESS=1` (abre el navegador de automatización sin ventana),
`KARDEX_CAPTURAS=<carpeta>` (guarda capturas del recorrido).
