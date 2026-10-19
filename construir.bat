@echo off
rem Crea "Actualizar Kardex.exe" (carpeta dist). Requiere Python 3.10+ instalado en el equipo que lo construye.
python -m venv .venv || goto :error
call .venv\Scripts\activate
pip install -r requirements.txt pyinstaller || goto :error
pyinstaller --noconfirm --onefile --windowed --name "Actualizar Kardex" --add-data "ui;ui" --collect-all playwright app.py || goto :error
echo Listo: dist\Actualizar Kardex.exe
exit /b 0
:error
echo Fallo la construccion.
exit /b 1
