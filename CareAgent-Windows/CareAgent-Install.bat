@echo off
SETLOCAL ENABLEDELAYEDEXPANSION
color 0A
echo.
echo  =============================================
echo    Care Agent v4.0 - Windows Installer
echo    Warm AI Caregiver Companion for Families
echo  =============================================
echo.

REM ── Check Python ──────────────────────────────
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Python not found!
    echo         Please install from https://www.python.org/downloads/
    echo         Make sure to check "Add Python to PATH"
    pause & exit /b 1
)
FOR /F "tokens=*" %%i IN ('python --version 2^>^&1') DO SET PYVER=%%i
echo [OK] Found %PYVER%
echo.

SET INSTALL_DIR=%~dp0
echo [INFO] Installing in: %INSTALL_DIR%
echo.

REM ── Virtual environment ───────────────────────
echo [1/3] Creating virtual environment...
python -m venv "%INSTALL_DIR%venv"
IF ERRORLEVEL 1 ( echo [ERROR] venv failed! & pause & exit /b 1 )
echo [OK] Virtual environment ready!
echo.

REM ── Install deps ──────────────────────────────
echo [2/3] Installing AI libraries (3-5 min)...
echo       flask, httpx, anthropic, edge-tts,
echo       faster-whisper, chromadb, instructor...
echo.
"%INSTALL_DIR%venv\Scripts\pip.exe" install --upgrade pip --quiet --no-warn-script-location
"%INSTALL_DIR%venv\Scripts\pip.exe" install flask httpx edge-tts anthropic pydantic instructor faster-whisper chromadb tenacity diskcache openai --quiet --no-warn-script-location

IF ERRORLEVEL 1 (
    echo [WARNING] Some optional packages failed - core app still works!
) ELSE (
    echo [OK] All libraries installed!
)
echo.

REM ── Create launcher ───────────────────────────
echo [3/3] Creating launcher...
(
echo @echo off
echo color 0A
echo echo.
echo echo  ===================================
echo echo    Care Agent v4.0 - Starting...
echo echo  ===================================
echo echo.
echo echo  Opening browser to http://localhost:5000
echo echo  Press Ctrl+C to stop Care Agent
echo echo.
echo cd /d "%%~dp0"
echo start http://localhost:5000
echo "%%~dp0venv\Scripts\python.exe" care_agent_web.py
echo pause
) > "%INSTALL_DIR%Launch-CareAgent.bat"

REM ── Desktop shortcut ──────────────────────────
powershell -Command "$ws=$env:INSTALL_DIR; $WS=New-Object -ComObject WScript.Shell; $SC=$WS.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Care Agent.lnk'); $SC.TargetPath='%INSTALL_DIR%Launch-CareAgent.bat'; $SC.WorkingDirectory='%INSTALL_DIR%'; $SC.Description='Care Agent v4.0'; $SC.Save()" 2>nul

echo.
echo  =============================================
echo    [SUCCESS] Care Agent v4.0 is Ready!
echo  =============================================
echo.
echo   Launch:  Double-click Launch-CareAgent.bat
echo            OR use Care Agent on your Desktop
echo.
echo   API Key: Set in the app Settings panel
echo            Get one at https://console.anthropic.com
echo            Or free tier: https://openrouter.ai
echo.
pause
