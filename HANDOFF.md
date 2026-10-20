# HANDOFF — Actualizar Kardex (para continuar en otra sesión)

Fecha: 20/10/2026. Repositorio: **https://github.com/Camilopr09/actualizar-kardex** (rama `main`).
Último `.exe` compilado: https://github.com/Camilopr09/actualizar-kardex/actions/runs/39495296628 (artefacto `Actualizar-Kardex-Windows`).

> Este documento no contiene datos de pacientes. No pegar nombres, cédulas ni capturas sin tapar en el chat.

---

## 1. Qué es y para qué

App de escritorio para Windows que ayuda a un médico (Clínica Reina Catalina) a mantener al día el Google Doc
**«KARDEX MIS PX»** (entrega de turno). Compara lo que hay en el sistema de historia clínica
**Hospital Office / eHC** con lo que hay en el kardex y propone cambios de **DX, EVOLUCIÓN y TRATAMIENTO**.
La persona revisa y aprueba; solo entonces escribe en el documento.

- Kardex: `https://docs.google.com/document/d/1Zd2RCwl-KifgPpmm8DiGRJKSxzjDYFlo74NifzHWFA0/edit` (tiene pestañas; `tab=t.0`).
- Hospital Office: `https://appclinicareinacatalina.com.co:8090/ehc2013/historiasclinicas/Agenda.aspx`.
- Laboratorio (`http://190.131.215.70:8089/cgi/Usuario.cgi`) e imágenes (ActualPACS) **sin empezar**.
- Especialistas cuyas notas se usan: Carlos Daza, Fabián, Alberto Emiliani (configurable en Ajustes).

Historia: nació en el repo `Camilopr09/motoflash` (carpeta `actualizar-kardex/`) y se movió a su propio repo;
en motoflash quedó borrada (rama `claude/new-session-0uoyz9` sin diferencias con `master`). Ramas viejas
`wip-hospital-real` y `wip-navegacion` del repo nuevo ya no se usan (GitHub no dejó borrarlas desde la sesión).

Diseño de la interfaz: artifact https://claude.ai/artifact/NZWk4X4bYLNsM9RPkn2PUS (prototipo; Chrome/Brave en Ajustes).

## 2. Forma de trabajo pedida por el usuario

- Supervisión/revisión por el modelo principal; el trabajo de código lo hacen subagentes Sonnet
  (`Agent` con `model: "sonnet"`), con especificaciones precisas; el supervisor revisa, corre pruebas, hace commit/push.
- Todo en español. Pruebas **solo con datos inventados**.
- Tras cada push a `main`, GitHub Actions compila el `.exe` (≈2 min); avisar al usuario con el enlace del run.

## 3. Arquitectura

Python (stdlib + Playwright + google-api-python-client). La UI es una página web local que se abre como ventana
(`--app=`) en el navegador preferido (**Chrome o Brave**; Edge no).

| Archivo | Qué hace |
|---|---|
| `app.py` | Lanzador: instancia única (`instancia.json`), arranca el servidor, abre la UI, se apaga a los 180 s sin peticiones y sin tarea. Flags `--demo`, `--no-abrir`, `--puerto`. |
| `servidor.py` | `ThreadingHTTPServer` en 127.0.0.1 con token (`?t=` → cabecera `X-Token`) y chequeo de `Host`. API JSON (abajo). Una tarea a la vez (sesion/analizar/escribir). Datos de pacientes solo en memoria. |
| `ui/index.html` | Interfaz completa (vanilla JS): principal, primer uso, analizando, resultado, confirmar, escritura terminada, errores, ajustes. Tema claro/oscuro. Todo texto con `textContent`. |
| `navegador.py` | Detecta Chrome/Brave (registro de Windows + rutas), abre URLs, registra el navegador en `webbrowser` para el OAuth. `KARDEX_CHROME` fuerza ruta (pruebas). |
| `navegador_vivo.py` | **Navegador de automatización persistente** en un hilo dedicado (Playwright sync); `ejecutar(func, *args)`; reabre si la persona cierra la ventana; se cierra al apagar la app. |
| `sistema.py` | Automatización de Hospital Office: login, menú, modo, búsqueda por paciente, abrir historia, leer formatos por pestañas, diagnóstico (HTML+PNG). |
| `flujo.py` | Orquesta: config, carpeta de datos, `iniciar_sesion`, `analizar`, `aplicar`; credenciales de Hospital Office. |
| `kardex_doc.py` | Lee el kardex (export HTML con la sesión del navegador, con `&tab=`), parser de tablas; escribe con la API de Google Docs (`aplicar`). |
| `comparar.py` | Modelos (`PacienteSistema`, `FilaKardex`, `Accion`), interpretar celda DATOS, `emparejar` difuso, `buscar_paciente`, `misma_habitacion`, `comparar()`. |
| `notas.py` | Texto clínico: `extraer_dx`, `construir_evolucion`, `construir_tratamiento` (IGUAL MANEJO), `interpretar_ordenes`, `en_renglones`. |
| `secreto.py` | Usuario/clave de Hospital Office cifrados con **DPAPI** (Windows) en `hospital.bin`. |
| `demo.py` | Modo demostración con datos ficticios. |
| `errores.py` | `ErrorApp(codigo, mensaje)` (`sesion`, `kardex`, `agenda`, `navegador`, `credenciales`, `otro`) y `Cancelado`. |
| `tests/` | 120 pruebas. `tests/simulador/servidor.py` imita Hospital Office (login eHC, acordeón, grilla DevExpress paginada, historia con pestañas). |
| `.github/workflows/build-windows.yml` | windows-latest: pytest, PyInstaller (`--add-data "ui;ui" --collect-all playwright --collect-data googleapiclient`), prueba el .exe en demo, sube artefacto. |

Carpeta de datos: `%LOCALAPPDATA%\ActualizarKardex\` (`KARDEX_DATOS` la redirige en pruebas): `config.json`,
`perfil-chrome/` o `perfil-brave/` (perfil del navegador de automatización), `credentials.json` + `token.json`
(Google), `hospital.bin`, `diagnostico/` (HTML + PNG cuando algo falla; contiene datos de pacientes),
`registro-app.txt`.

API: `GET /api/estado`; `POST /api/config`, `/api/sesion`, `/api/sesion/terminar`, `/api/analizar`,
`/api/cancelar`, `/api/escribir {ids}`, `/api/abrir {que}`, `/api/credenciales {contenido}`,
`/api/credenciales/quitar`, `/api/hospital {usuario,clave}`, `/api/hospital/quitar`, `/api/salir`.

Pruebas: `KARDEX_CHROME=/opt/pw-browsers/chromium KARDEX_HEADLESS=1 python3 -m pytest -q tests`
(≈35 min completa). Rápidas: `python3 -m pytest -q tests --ignore=tests/test_integracion_sistema.py --ignore=tests/test_e2e_ui.py` (≈7 s).

## 4. Lo que se sabe del Hospital Office REAL (por capturas del usuario)

- **Login (eHC «Historias Clínicas.Net»)**: dos campos; el de usuario muestra el texto guía «Usuario»; la clave
  probablemente no es `type=password` al cargar; botón **ENTRAR es una imagen**; pie «Software Asistencial eHC -
  Desarrollado por el Departamento de Sistemas Clínica Reina Catalina». La URL de login no contiene «login».
- **Sesión NO persistente**: se pierde al cerrar la ventana/navegador (cookie de sesión). Por eso existe `navegador_vivo.py`.
- Tras entrar: «DashBoard del Usuario», arriba «NOMBRE(Salir)». Menú lateral **acordeón**: «Menu Principal»
  (se despliega → «Inicio», «Atencion de Pacientes»), «Consultas», «Historia Externa», «Parametros», «Unidades Funcionales», «Pacientes», «Ayuda».
- **Atencion De Pacientes**: radios Urgencias/Hospitalización, casilla «Últimas 24 horas.», botón **Actualizar**
  (necesario tras cambiar). Grilla «Pacientes Por Atender» con columnas Paciente | Identificacion («CC - 123…») |
  Admision | Convenio | Habitacion («6PISO-607», «HOS82-09», «H4CAM-09», «PEDIA-07») | Estado | Acción («Atender»).
  Es la lista de **todo el hospital**, paginada. **No hay lista de atendidos** → la app no propone AGREGAR.
- **Historia → «Ver» formato**: panel «Detalle del Formato», título «Formato: N - HOJA DE EVOLUCION MEDICO ESPECIALISTA»,
  **pestañas verticales**: DIAGNOSTICO:, UNIDAD EN DONDE SE ENCUENTRA EL PACIENTE, HIPOTESIS DIAGNOSTICA:, SINTOMAS DESCRITOS:,
  -EXAMEN FISICO-, ANALISIS:, PLAN-, SOLICITUD MATERIAL ESPECIAL. En DIAGNOSTICO hay un textarea «DX:» y combos
  (sospecha dengue/covid, ventilación…). «Su nivel de permisos no le permite modificar el formato».
- Nunca se vieron: el HTML real, las pestañas ANALISIS y PLAN por dentro, la grilla de formatos de la historia ni las órdenes médicas.

## 5. Reglas de negocio acordadas

- **DX** (`notas.extraer_dx`, sobre el textarea DX de la pestaña DIAGNOSTICO): si hay un renglón que es solo
  DIAGNOSTICO/DX/IDX (con o sin «:»), o empieza por «DX:»/«IDX:», el DX es lo que va **debajo** hasta la siguiente
  sección; lo de arriba (p. ej. «EVOLUCION UCI/ AM» + lista) se descarta. Si hay varios, el último. Sin encabezado:
  se quita un título de otra cosa (EVOLUCION…, NOTA…) y se usa el resto; sin títulos: todo el texto.
  Un ítem por renglón; continuaciones unidas; MAYÚSCULAS. Ejemplo validado por el usuario (foto 3).
- **EVOLUCIÓN** = «DD/MM/AAAA - DR. NOMBRE (ESPECIALIDAD)» (en negrita) + texto de la pestaña **ANALISIS**
  (si vacía: SINTOMAS DESCRITOS + EXAMEN FISICO). **Pendiente que el usuario confirme** que es ANALISIS.
- **TRATAMIENTO** = «PLAN» + líneas de la pestaña **PLAN** (pendiente de confirmar). Si dice IGUAL MANEJO:
  «IGUAL MANEJO (DR. NOMBRE DD/MM/AAAA)» + tratamiento actual del kardex (sin su encabezado) + órdenes nuevas del día.
- Hoja usada: la más reciente de un especialista de la lista; si la más reciente es de otra persona → aviso REVISAR.
- Acciones: **ACTUALIZAR** (automática, marcada), **RETIRAR** (en kardex y no en el sistema; manual),
  **REVISAR** (habitación distinta, sin hoja, error al buscar), **AGREGAR** (solo si existiera lista de atendidos).
- Emparejar paciente kardex↔sistema: primero por **cédula** (columna Identificacion); si no, nombre difuso
  (tolera errores, orden apellidos/nombres; empate → no empareja). Documento distinto descarta coincidencia por nombre.
- Habitación: «6PISO-607» ≡ «607»; PASILLO u otras sin número → no se marca REVISAR.

## 6. Formato del KARDEX (Google Doc)

- Una tabla por servicio. Fila 0: título combinado «URGENCIAS 47 ( 5 PACIENTES)», «PISO 4A ( 4 PACIENTES) 422 - 430»
  (la app lo limpia a «URGENCIAS 47», «PISO 4A»). Fila 1: encabezados DATOS | DX | EVOLUCIÓN | TRATAMIENTO |
  LABORATORIOS | IMÁGENES / NOTAS | PENDIENTES. **UCI 1 no tiene TRATAMIENTO** → columnas por nombre.
- Celda DATOS: habitación (CUB 12, 332A, 601, PASILLO, ASL, EX TORAX 327A…) o nada, nombre en 1-4 renglones,
  edad («59 AÑOS»), «CC …», «FI/FIP fecha», «STT», notas. Muchas filas vacías (se saltan).
- Todo en MAYÚSCULAS; estilo heredado de la celda (fuente, tamaño, resaltado); solo la 1.ª línea de EVOLUCIÓN en negrita.
- DX a veces con prefijo «DX:» (se respeta si la celda ya lo tiene); TRATAMIENTO con «PLAN»/«PLAN:».

## 7. Estado actual y pendientes (en orden)

1. **Último reporte del usuario (antes del .exe actual)**: «sigue saliendo error al iniciar sesión» y las ventanas se
   cerraban (se perdía la sesión). El .exe del run 39495296628 trae: login eHC corregido (botón imagen, clave sin
   type=password, detección por el pie) + navegador persistente + mensajes de error con el paso que falló.
   **Falta**: que el usuario lo pruebe y mande foto del recuadro «Detalle» del error y la PNG de `diagnostico`
   (tapando datos). Captura previa mostró el login SIN rellenar (la versión anterior no detectaba el login).
2. Confirmar con el usuario: EVOLUCIÓN = pestaña ANALISIS; TRATAMIENTO = pestaña PLAN. Pedir captura de esas pestañas.
3. Probar el tramo «Atender» → historia → grilla de formatos («HOJA DE EVOLUCION», «ORDEN M») → «Ver» → pestañas;
   nunca visto en real. Ajustar con capturas/HTML de `diagnostico`.
4. Escritura en Google Docs: el usuario creó/está creando `credentials.json` (OAuth «App de escritorio», usuario de
   prueba agregado). Le pasó que la ventana de consentimiento se cerró; ya hay timeout de 5 min con mensaje. Verificar
   la escritura real (columnas por encabezado, `&tab=`, negrita, estilo) sobre una copia del doc si es posible.
5. Botón opcional «Borrar sesión guardada» en Ajustes (ofrecido, no pedido aún).
6. LABORATORIOS (sistema de laboratorio) e IMÁGENES (ActualPACS): sin empezar.
7. Riesgos conocidos: la exportación por pestaña (`&tab=`) no verificada; emparejar tabla HTML↔API por posición;
   contraseña mala → la app borra la guardada (evita bloqueo); inactividad 180 s cierra la app y el navegador.

## 8. Cómo retomar

```bash
git clone https://github.com/Camilopr09/actualizar-kardex && cd actualizar-kardex
pip install -r requirements.txt pytest
python3 -m pytest -q tests --ignore=tests/test_integracion_sistema.py --ignore=tests/test_e2e_ui.py
python3 app.py --demo          # UI con datos ficticios
```
Pedir al usuario el resultado de la prueba del último `.exe` (punto 7.1) antes de cambiar código.
Advertencias recordadas al usuario: protección de datos (Ley 1581); `credentials.json`, `token.json`, `hospital.bin`,
`perfil-*` y `diagnostico/` son sensibles.
