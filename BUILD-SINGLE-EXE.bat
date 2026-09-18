@echo off
setlocal
cd /d "%~dp0"
title WayFinder - Build Single EXE

echo ============================================================
echo   WayFinder v1.0.0 - SINGLE APP BUILDER
echo ============================================================
echo.
echo Builds release\WayFinder.exe with the WayFinder GUI,
echo native tracker/logic engine and native Archipelago runtime adapter.
echo Archipelago core/game source is imported by the user at runtime.
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: py.exe was not found. Install Python 3.13 and rerun.
  pause
  exit /b 1
)
py -3.13 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3,13) else 1)" >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python 3.13 was not found.
  py -0p
  pause
  exit /b 1
)
set "PY=py -3.13"

%PY% -m pip --version >nul 2>nul
if errorlevel 1 (
  echo ERROR: pip is unavailable.
  pause
  exit /b 1
)

echo [1/4] Installing build/runtime dependencies...
%PY% -m pip install --upgrade pyinstaller pillow packaging colorama==0.4.6 websockets==13.1 PyYAML==6.0.3 jellyfish==1.2.1 jinja2==3.1.6 schema==0.7.8 bsdiff4==1.2.6 platformdirs==4.9.4 certifi cython cymem orjson typing_extensions pyshortcuts pathspec Pymem requests
if errorlevel 1 goto :fail

echo Checking bundled Python 3.13 native dependency wheels...
%PY% tools\verify_native_wheels.py
if errorlevel 1 goto :fail

echo [2/4] Cleaning old build output...
if exist build rmdir /s /q build
if exist release rmdir /s /q release
if exist WayFinder.spec del /q WayFinder.spec

if exist integration_assets (
  echo ERROR: obsolete integration_assets folder exists. Native-only releases must not contain it.
  goto :fail
)
if exist embedded_ut_runtime.py (
  echo ERROR: obsolete embedded runtime builder exists.
  goto :fail
)

echo [3/4] Building WayFinder.exe with live debug console...
%PY% -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --console ^
  --name WayFinder ^
  --icon "assets\wayfinder.ico" ^
  --distpath release ^
  --workpath build ^
  --collect-submodules wayfinder ^
  --collect-all yaml ^
  --collect-all websockets ^
  --collect-all jellyfish ^
  --collect-all jinja2 ^
  --collect-all schema ^
  --collect-all bsdiff4 ^
  --collect-all platformdirs ^
  --collect-all certifi ^
  --collect-all orjson ^
  --collect-all typing_extensions ^
  --collect-all pathspec ^
  --collect-all requests ^
  --collect-all packaging ^
  --collect-all colorama ^
  --exclude-module pip ^
  --exclude-module uv ^
  --add-data "native_wheels;native_wheels" ^
  --add-data "assets\wayfinder.ico;assets" ^
  --add-data "assets\wayfinder_icon_master.png;assets" ^
  --hidden-import pkgutil ^
  --hidden-import importlib.metadata ^
  run_wayfinder.py
if errorlevel 1 goto :fail

echo [4/4] Cleaning temporary PyInstaller output...
if exist build rmdir /s /q build
if exist WayFinder.spec del /q WayFinder.spec

echo.
echo BUILD COMPLETE: %CD%\release\WayFinder.exe
explorer "%CD%\release"
pause
exit /b 0

:fail
echo.
echo BUILD FAILED
pause
exit /b 1
