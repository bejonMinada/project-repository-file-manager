@echo off
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "REPO_DIR=%ROOT%repository"
set "SNAPSHOTS_DIR=%ROOT%snapshots"
set "RECYCLE_BIN_DIR=%ROOT%recycle_bin"

:: Ensure required runtime folders exist for first-time launch on new devices
if not exist "%REPO_DIR%" (
    mkdir "%REPO_DIR%"
)
if not exist "%SNAPSHOTS_DIR%" (
    mkdir "%SNAPSHOTS_DIR%"
)
if not exist "%RECYCLE_BIN_DIR%" (
    mkdir "%RECYCLE_BIN_DIR%"
)

:: 1. Use existing venv python if available
if exist "%VENV_PY%" (
    "%VENV_PY%" "%ROOT%launch_app.py"
    exit /b %ERRORLEVEL%
)

:: 2. Check py launcher on PATH
where py >nul 2>&1
if %ERRORLEVEL% == 0 (
    py -3 "%ROOT%launch_app.py"
    exit /b %ERRORLEVEL%
)

:: 3. Check python on PATH
where python >nul 2>&1
if %ERRORLEVEL% == 0 (
    python "%ROOT%launch_app.py"
    exit /b %ERRORLEVEL%
)

:: 4. Python not on PATH — search common install locations automatically
echo Python not found on PATH. Searching common install locations...
set "FOUND_PY="

for %%D in (
    "%LOCALAPPDATA%\Programs\Python"
    "%ProgramFiles%"
    "%ProgramFiles(x86)%"
    "C:\"
) do (
    if not defined FOUND_PY (
        for /d %%P in ("%%~D\Python3*") do (
            if exist "%%P\python.exe" (
                if not defined FOUND_PY set "FOUND_PY=%%P\python.exe"
            )
        )
    )
)

if defined FOUND_PY (
    echo Found Python at: %FOUND_PY%
    for %%F in ("%FOUND_PY%") do set "PY_DIR=%%~dpF"
    set "PATH=!PY_DIR!;%PATH%"
    echo Adding to PATH for this session and launching...
    "%FOUND_PY%" "%ROOT%launch_app.py"
    exit /b %ERRORLEVEL%
)

:: 5. Truly not found anywhere
echo.
echo ============================================================
echo  Python 3.10+ was not found on this device.
echo.
echo  Please install Python from:
echo    https://www.python.org/downloads/
echo.
echo  During installation, check:
echo    "Add Python to PATH"
echo.
echo  Then run this file again.
echo ============================================================
echo.
pause
