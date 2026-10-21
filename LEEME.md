# Actualizar Kardex

App para Windows con tres pestañas: **qué hay que actualizar**, **qué encontré en el sistema** y
**qué encontré en el kardex**. Compara Hospital Office con el Google Doc «KARDEX MIS PX» y propone los cambios
de DX / EVOLUCIÓN / TRATAMIENTO con tus reglas (nota más reciente del especialista; «IGUAL MANEJO» conserva
el tratamiento y suma lo nuevo de las órdenes), los estudios nuevos de la columna **IMÁGENES / NOTAS**, el cambio de
habitación o de piso, y las **filas nuevas** de los pacientes que los documentos de entregas mandan a cirugía general.
Todo pasa por la pantalla de revisión: **nada se escribe sin que lo apruebes**.

La interfaz es una página local que se abre **en tu navegador (Chrome o Brave)** como una ventana de aplicación.
Todo lo que la app abre (su pantalla, Hospital Office, el Google Doc, el permiso de Google, «Abrir el kardex»)
usa el navegador que elijas en Ajustes. Edge ya no se usa.

## Qué necesita el computador
- Windows 10/11 con **Google Chrome o Brave**. No hay que instalar nada más si usas el `.exe`.
- Obtener el `.exe`: en GitHub → pestaña **Actions** → «Actualizar Kardex (.exe para Windows)» → *Run workflow* → descargar el artefacto `Actualizar-Kardex-Windows`. (O ejecutar `construir.bat` en un Windows con Python.)

## Uso
1. **Primer uso** (solo Google): la app abre el navegador con dos pestañas; entra a tu cuenta de Google (la que puede abrir el kardex). La app lo detecta (verás «✓ dentro») y guarda la sesión sola; también puedes pulsar «Guardar sesión ahora». La ventana no hace falta cerrarla. Queda en `%LOCALAPPDATA%\ActualizarKardex\perfil-chrome` (o `perfil-brave`). Hospital Office guarda la sesión solo mientras la ventana está abierta (su cookie se pierde al cerrar el navegador); por eso la app mantiene la ventana abierta mientras corre y no hace falta entrar ahí en el primer uso.
   - **Usuario de Hospital Office (opcional, recomendado)**: en **Ajustes → Hospital Office** guarda tu usuario y contraseña. En cada análisis la app entra sola: va a la Agenda, escribe usuario y contraseña (clic + teclado, para que funcione el texto guía «Usuario» de eHC), pulsa el botón ENTRAR (aunque sea una imagen) y, en el menú lateral tipo acordeón, pulsa «Menu Principal» (solo si no está ya desplegado) y «Atencion de Pacientes» hasta ver la grilla «Pacientes Por Atender». Si la sesión vence a mitad del análisis, vuelve a entrar sola.
   - Sin usuario guardado: la app abre Hospital Office, te avisa («Esperando inicio de sesión…») y espera hasta 5 minutos a que entres tú en esa ventana; luego sigue sola.
   - Si el usuario o la contraseña no sirven, el análisis termina con «Usuario o contraseña de Hospital Office no válidos».
2. **Analizar**: la app lee el kardex y los **documentos de entregas** (ver abajo) y, **paciente por paciente**, lo busca en «Atencion de Pacientes» (no lee la lista de todo el hospital): elige Urgencias u Hospitalización según el servicio del kardex (si no está, prueba el otro), quita «Últimas 24 horas», pulsa «Actualizar», filtra la columna Identificacion por el número de documento del kardex (o, si no lo trae, la columna Paciente por la primera palabra del nombre), abre su historia y arma la lista. El documento manda sobre el nombre: si coincide, es el mismo paciente aunque el nombre esté mal escrito. Después busca igual a los pacientes de las entregas con valoración por cirugía general que **no** están en el kardex (Urgencias primero si el documento de entregas es de Urgencias). El avance cuenta los pacientes del kardex más esos pacientes de las entregas. Usa el navegador de automatización, que **sigue abierto al terminar** (también si hay un error) para no perder la sesión de Hospital Office: puedes minimizarlo. Si lo cierras, la app lo vuelve a abrir y entra de nuevo en el siguiente análisis. Reutiliza siempre la misma pestaña de Hospital Office. Puedes cancelar.
3. Revisa las pestañas. En «Qué hay que actualizar» selecciona una fila para ver *Ahora* vs *Nuevo*; desmarca lo que no quieras. **Copiar texto nuevo** sirve para pegar a mano (en IMÁGENES / NOTAS copia solo el texto que se agrega; en una fila nueva, la fila completa).
   Tipos de acción: **ACTUALIZAR** (↻, verde), **AGREGAR** (+, azul), **MOVER** (→, violeta), **RETIRAR** (−, rojo) y **REVISAR** (!, ámbar). ACTUALIZAR, AGREGAR y MOVER vienen marcados y se escriben al aprobar; RETIRAR, REVISAR y los AGREGAR sin tabla destino se hacen a mano.
4. **Escribir en el kardex** (opcional, ver abajo). Deshacer: Archivo → Historial de versiones del Google Doc. Tras agregar filas o mover pacientes conviene volver a analizar para refrescar la lista.

La app se cierra sola tras 3 minutos sin usarse. Solo hay una a la vez: abrirla otra vez muestra la que ya está corriendo.

## Probar la interfaz sin nada (modo demostración)
`python app.py --demo` (o `"Actualizar Kardex.exe" --demo`): usa pacientes inventados, sin navegador de automatización ni red.
Otras opciones: `--no-abrir` (solo imprime la dirección) y `--puerto N`.

## Documentos de entregas (solo lectura)
La fuente de los pacientes nuevos son los documentos **«ENTREGAS CRC»** (un Google Doc por servicio). Vienen de fábrica los 11
(PISO 3 GINECO, PISO 4C, PISO 4A, PISO 4B, PISO 5, PISO 6, PISOS 10 Y 11, URGENCIAS CARRERA 47, URGENCIAS CALLE 82, UCI 1 y UCI 7) y se editan en
**Ajustes → Documentos de entregas** (lista de nombre + enlace, hasta 30; el enlace debe ser de un Google Doc). Se leen con la
misma sesión de Google del navegador y **la app nunca escribe en ellos**.
- **Qué paciente se toma**: el que tiene en su fila valoración o seguimiento por **cirugía general**: «CIRUGIA GENERAL», «CX GENERAL»,
  «CX GRAL», o una palabra de aviso (VALORACION, VAL, SS, S/S, IC, INTERCONSULTA, SGTO, SEGUIMIENTO, A CARGO DE, POR, X…) seguida de «CIRUGIA» o «CX»
  («VALORACION POR CIRUGIA», «VAL X CX», «SS CX», «IC CIRUGIA GRAL»…). **No cuenta** cirugía de otra especialidad (plástica, vascular, cardiovascular,
  tórax, pediátrica, mano, maxilofacial, neurocirugía…), «QX» (pre quirúrgico) ni el «CX POR …» de los antecedentes quirúrgicos.
- **Qué se hace con él**: si ya está en el kardex se actualiza como siempre (más IMÁGENES / NOTAS); si **no** está, se busca en Hospital Office y se propone
  **AGREGAR** una fila nueva en la tabla de su piso. Si no aparece en el sistema solo queda en el registro de actividad.
- Los pacientes que ya están en el kardex se siguen actualizando **todos**, estén o no en las entregas.
- **Formato esperado**: igual al del kardex (tablas con título «PISO 6 ( 5 PACIENTES)» y encabezado DATOS | DX | …); si una tabla no trae encabezado DATOS
  se usa la 1.ª columna cuando de ella sale un nombre. Es una suposición: **no está verificada contra los documentos reales**.
- Un documento que no se puede leer no detiene el análisis: sale un aviso **REVISAR** «No pude leer el documento de entregas X: motivo». Si Google pide iniciar sesión, el análisis se corta.

## Qué escribe la app (tras aprobar)
Cada fila marcada se verifica antes de escribir (que la fila siga siendo ese paciente; si no, se omite con su motivo) y se vuelve a leer el documento entre pasos.
- **ACTUALIZAR DX / EVOLUCIÓN / TRATAMIENTO**: reemplaza la celda y conserva su formato (como siempre).
- **ACTUALIZAR IMÁGENES / NOTAS**: de cada «INFORME DE IMAGENOLOGIA» de la historia (pestaña EXAMEN) se agrega un bloque —título en **negrita con resaltado verde**
  (tipo de estudio + estudio + fecha, p. ej. «ECOGRAFÍA TEJIDOS BLANDOS … 19/10/26») y debajo el informe tal cual— **arriba de la celda** (o justo debajo del subtítulo «IMÁGENES…»
  si la celda lo tiene), el más reciente primero y **sin borrar nada**. Un estudio que ya está en la celda (mismo título, mismo informe, o la misma fecha y estudio) no se repite.
  En la pantalla de revisión se ve la celda completa (*Ahora* / *Nuevo*) con lo que se agrega subrayado.
- **ACTUALIZAR HABITACIÓN**: mismo servicio pero otra habitación: cambia solo el renglón de la habitación en DATOS.
- **MOVER**: la habitación del sistema indica otro piso. Se copia la **fila completa con su formato** a la tabla correcta, se pone la habitación nueva, se verifica la copia, se borra
  la fila original y se ajusta el «( N PACIENTES)» de los dos títulos. La tabla sale del piso de la habitación («6PISO-607» → 607 → PISO 6); con PISO 4A / 4B / 4C decide el rango del título
  («422 - 430», «430 EN ADELANTE», «401 - 421»); si la habitación no dice el piso, el documento de entregas donde aparece el paciente.
- **AGREGAR**: fila nueva (DATOS, DX, EVOLUCIÓN, TRATAMIENTO e IMÁGENES / NOTAS) en la tabla destino, cada columna por su encabezado: usa la primera fila vacía tras el encabezado o agrega una
  debajo de la última, con el estilo de la fila con paciente más cercana, y sube el «( N PACIENTES)». DATOS lleva habitación, nombre (como está en las entregas), edad y «CC 123».
- **Se omite** (con el motivo en «Escritura terminada»): la fila ya no es ese paciente o hay dos filas del mismo; AGREGAR de alguien que ya está en el kardex; MOVER a una tabla donde el paciente ya está,
  a una tabla sin una columna que la fila trae con contenido, o de una fila con tablas/imágenes dentro; HABITACIÓN sin renglón de habitación en DATOS.
- **Siempre a mano**: RETIRAR, REVISAR y los AGREGAR sin tabla destino («No sé en qué tabla va: agrégalo a mano»).

## Para escribir en el documento (opcional)
Leer y comparar NO requiere nada de Google Cloud. Para que la app escriba sola:
Google Cloud → crear proyecto → activar *Google Docs API* → Credenciales → *ID de cliente OAuth* tipo «App de escritorio» →
descargar el `credentials.json` y cargarlo en **Ajustes → Escribir en Google Docs**. La primera vez pide autorizar
(se abre en tu navegador elegido). El texto escrito conserva el formato de la celda.

## Límites conocidos
- **RETIRAR** = paciente del kardex que no aparece en ninguno de los dos modos; se hace a mano. Ya no hay lista de «atendidos»: los pacientes nuevos salen **solo** de los documentos de entregas (con valoración por cirugía general); la grilla «Pacientes Por Atender» es de todo el hospital y nunca se usa para proponer pacientes.
- **Habitación**: se compara el código del kardex («607», «332A», «CUB 12») con el final de la del sistema («6PISO-607», «3PISO-332A», «HOS82-12»). Si es de piso («PISO» en el código, o número de 3-4 dígitos con letra opcional) y otra tabla corresponde → **MOVER**; si la tabla es la misma → ACTUALIZAR «HABITACIÓN»; si no se sabe la tabla, o el código no es de piso («HOS82-09», «UCI5-09», «PEDIA-07») y la habitación difiere claramente → REVISAR a mano. «PASILLO» u otra palabra sin número no genera aviso. **Se desconocen los códigos de habitación de UCI y Urgencias del sistema real**: para ellos no se propone MOVER (solo el documento de entregas decide la tabla de un AGREGAR).
- **IMÁGENES / NOTAS** solo se propone si la tabla del servicio tiene esa columna y la historia trae informes de imagenología (pestaña EXAMEN; «DESCRIPCIÓN DEL EXAMEN» viene vacía y se ignora). Se leen como máximo los 20 más recientes por paciente.
- **MOVER, AGREGAR, IMÁGENES / NOTAS y HABITACIÓN se probaron contra un documento falso de la API de Google Docs y contra el simulador, no contra el Google Doc ni el Hospital Office reales.** Revisa el resultado en el documento (y deshaz con el historial de versiones si algo no quedó bien) las primeras veces.
- Las lecturas de Hospital Office (login con texto guía y botón ENTRAR como imagen, acordeón del menú, radios Urgencias/Hospitalización, «Actualizar», filtro por columna, botón «Ver») se escribieron según capturas y descripciones y **no se han probado contra el sistema real**, solo contra el simulador. Si algo falla, la app guarda HTML y captura en `%LOCALAPPDATA%\ActualizarKardex\diagnostico` para ajustarlo.
- Si el filtro por columna (`AutoFilterByColumn`) no funciona, la app escribe en la fila de filtros de la grilla y pulsa Enter. Si el filtro por número no devuelve filas, prueba «TIPO - número».
- Los datos de pacientes solo viven en memoria mientras la app está abierta (no se guardan en disco, salvo `diagnostico\` si algo falla). El registro técnico `registro-app.txt` no incluye datos de pacientes.
- Las credenciales de Hospital Office se guardan en `hospital.bin` cifradas con **Windows DPAPI** (solo tu usuario de Windows en este computador puede descifrarlas); nunca se muestran de nuevo, ni van al registro ni a `diagnostico\` (antes de guardar un diagnóstico de login se vacía el campo de contraseña). Fuera de Windows (solo desarrollo) se usa base64, que NO protege.
- El inicio de sesión automático y la ruta «Menu Principal» → «Atencion de Pacientes» se escribieron según lo que se describió y **no se han probado contra el Hospital Office real** (cómo se llaman los campos del login, qué hay tras entrar, etc.). Si falla, revisa `diagnostico\` (`*-login.html`, `*-agenda.html`).
- Confirma con la clínica (Ley 1581) que la lectura automatizada esté permitida. `credentials.json`, `token.json`, `hospital.bin`, `perfil-*\` y `diagnostico\` contienen datos sensibles.

**Cerrar la app cierra ese navegador** (con «Salir», o cuando se apaga sola tras 180 s sin uso y sin ninguna tarea en curso: nunca se apaga mientras una tarea corre). Al volver a abrir la app habrá que entrar de nuevo a Hospital Office (la app lo hace sola si guardaste el usuario en Ajustes). Cambiar el navegador en Ajustes hace que la ventana se reabra con el nuevo en la siguiente tarea. En modo demo no se abre ningún navegador. El código está en `navegador_vivo.py` (un hilo dedicado donde vive Playwright).

## Pruebas (desarrollo)
`python -m pytest -q tests`. Sin navegador: lógica, entregas, imágenes, escritura sobre un Google Doc falso en memoria (`docs_falso.py`), servidor y `test_flujo.py` (`flujo._analizar` con objetos falsos: kardex + entregas + pacientes nuevos).
Las pruebas con navegador (`test_e2e_ui.py`: recorrido de la interfaz en modo demo, con AGREGAR, MOVER, HABITACIÓN, IMÁGENES / NOTAS y Ajustes de entregas; `test_integracion_sistema.py`:
`flujo.analizar` contra un simulador de Hospital Office en `tests/simulador/`: login con texto guía «Usuario» y botón ENTRAR como imagen, cookie de sesión, acordeón «Menu Principal» → «Atencion de Pacientes», radios + casilla + «Actualizar» (necesario), grilla de 7 columnas con filtros y paginación de 10 filas, y sesión que vence) usan Playwright con un Chromium; si no hay, se saltan.
Variables solo para pruebas: `KARDEX_CHROME` (ruta del Chromium), `KARDEX_HEADLESS=1` (abre el navegador de automatización sin ventana),
`KARDEX_CAPTURAS=<carpeta>` (guarda capturas del recorrido).
