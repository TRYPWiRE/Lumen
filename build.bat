@echo off
setlocal
cd /d "%~dp0"

echo === 1/5  Installing requirements ===
python -m pip install -r requirements.txt pyinstaller || goto :error

echo === 2/5  Running tests ===
python -m unittest discover tests || goto :error

for /f "delims=" %%v in ('python -c "import lumen; print(lumen.__version__)"') do set VER=%%v
echo Building Lumen %VER%

echo === 3/5  Building the app (PyInstaller) ===
python -m PyInstaller --noconfirm --clean --windowed --name Lumen --icon assets\lumen.ico --add-data "assets;assets" --add-data "extensions;extensions" main.py || goto :error

echo === 4/5  Building the installer (Inno Setup) ===
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    echo.
    echo Inno Setup 6 was not found, so no installer was made.
    echo Install it from https://jrsoftware.org/isdl.php and run build.bat again.
    echo The portable app is ready in dist\Lumen\Lumen.exe
    goto :done
)
"%ISCC%" /Qp /DMyAppVersion=%VER% installer\lumen.iss || goto :error

echo === 5/5  Updating updates\manifest.json ===
python tools\release.py release\LumenSetup-%VER%.exe || goto :error
python tools\build_extensions.py || goto :error

echo.
echo Installer: release\LumenSetup-%VER%.exe
echo Run publish.bat to put this version on GitHub.
:done
pause
exit /b 0
:error
echo.
echo Build failed - see the messages above.
pause
exit /b 1
