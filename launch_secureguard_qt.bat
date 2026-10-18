@echo off
REM SG-LAUNCHER-V2
REM ===========================================================================
REM  SecureGuard Governance Model - PySide6 launcher (developer / operator tool)
REM
REM  Usage:  launch_secureguard_qt.bat [probe|0-5]
REM
REM    probe  report the selected interpreter and exit
REM    1      Dashboard + Quick Profile login    [DEV]  SECUREGUARD_TEST_MODE=1
REM    2      Dashboard, production mode                SECUREGUARD_TEST_MODE=0
REM    3      Dashboard + API server            [DEV]  both on test mode 1
REM    4      API server only                           SECUREGUARD_TEST_MODE=0
REM    5      Create the desktop shortcut
REM    0      Quit
REM
REM  Env: SG_HOST (default 127.0.0.1), SG_API_PORT (default 8000),
REM       SG_TEST_MODE=1 to run mode 4 with demo tokens instead of mode 0.
REM
REM  Interpreter: .venv\Scripts\python.exe is used ONLY if it can really
REM  "import PySide6" - existing is not enough, because this machine's .venv
REM  contains PyQt6 and no PySide6, so it cannot run this app. If the probe
REM  fails the launcher falls back to python from PATH, and if that fails too
REM  it stops with a pip instruction instead of launching into a traceback.
REM  Nothing here requires .venv to exist.
REM
REM  main_qt.py and dashboard_qt.py default SECUREGUARD_TEST_MODE to "0" on
REM  purpose: test mode mints a supervisor token whose MFA is already verified,
REM  which bypasses the auth and dual-control gates. Modes 1 and 3 therefore set
REM  it explicitly and loudly; it is never silently inherited.
REM ===========================================================================

setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

set "SG_ARG=%~1"
set "SG_CHOICE="
set "SG_RC=0"
set "SG_MODE="
set "SG_API=0"
set "SG_API_ONLY=0"
set "SG_APIRC=0"
set "SG_PY="
set "SG_WHY="
set "SG_VENV=%~dp0.venv\Scripts\python.exe"
if not defined SG_HOST set "SG_HOST=127.0.0.1"
if not defined SG_API_PORT set "SG_API_PORT=8000"

call :sg_can "%SG_VENV%"
if "%SG_OK%"=="1" goto :sg_use_venv
set "SG_VENV_SAY=%SG_SAY%"
call :sg_can "python"
if "%SG_OK%"=="1" goto :sg_use_path
set "SG_PATH_SAY=%SG_SAY%"

echo.
echo ERROR: no usable interpreter - neither candidate can "import PySide6".
echo   %SG_VENV%
echo     %SG_VENV_SAY%
echo   python on PATH
echo     %SG_PATH_SAY%
echo.
echo   Fix:  pip install -r requirements.txt
echo.
pause
exit /b 1

:sg_use_venv
set "SG_PY=%SG_VENV%"
set "SG_WHY=project .venv"
goto :sg_ready

:sg_use_path
set "SG_PY=python"
set "SG_WHY=system PATH"
goto :sg_ready

:sg_ready
REM Resolve the real interpreter. The venv path is already absolute. For the
REM bare "python" on PATH, "for /f" is used because it waits for the process to
REM release the pipe; a temp file plus "set /p" races against the PyManager
REM shim, which can still hold the write handle, and loses the line.
set "SG_REAL=%SG_PY%"
if /i not "%SG_PY%"=="python" goto :sg_show
set "SG_REAL="
for /f "delims=" %%I in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "SG_REAL=%%I"

:sg_show
echo.
echo Interpreter : %SG_PY%  [%SG_WHY%]
if defined SG_REAL echo Resolved    : %SG_REAL%
if /i "%SG_ARG%"=="probe" goto :sg_probed

if not "%SG_ARG%"=="" goto :sg_dispatch
echo.
echo   1  Dashboard + Quick Profile login   [DEV]  test mode 1
echo   2  Dashboard, production mode                test mode 0, manual token
echo   3  Dashboard + API server            [DEV]  %SG_HOST%:%SG_API_PORT%
echo   4  API server only                           %SG_HOST%:%SG_API_PORT%
echo   5  Create the desktop shortcut
echo   0  Quit
echo.
set /p SG_CHOICE=Choice [1]:

:sg_dispatch
if not defined SG_CHOICE set "SG_CHOICE=%SG_ARG%"
if not defined SG_CHOICE set "SG_CHOICE=1"
if "%SG_CHOICE%"=="0" goto :sg_end
if "%SG_CHOICE%"=="1" goto :sg_dev
if "%SG_CHOICE%"=="2" goto :sg_prod
if "%SG_CHOICE%"=="3" goto :sg_dev_api
if "%SG_CHOICE%"=="4" goto :sg_api_only
if "%SG_CHOICE%"=="5" goto :sg_shortcut
echo.
echo Unknown choice "%SG_CHOICE%" - expected probe or 0-5.
set "SG_RC=2"
goto :sg_end

:sg_probed
echo PySide6    : import OK
goto :sg_end

:sg_dev
set "SG_MODE=1"
goto :sg_run

:sg_prod
set "SG_MODE=0"
goto :sg_run

:sg_dev_api
set "SG_MODE=1"
set "SG_API=1"
goto :sg_run

:sg_api_only
set "SG_API=1"
set "SG_API_ONLY=1"
if /i "%SG_TEST_MODE%"=="1" set "SG_MODE=1"
goto :sg_run

:sg_run
if "%SG_MODE%"=="" set "SG_MODE=0"
REM Set explicitly, never inherited: the app defaults to "0", and an inherited
REM 1 would silently re-enable demo tokens. Set before the API start so the
REM "start"ed uvicorn window gets the same mode.
set "SECUREGUARD_TEST_MODE=%SG_MODE%"
if "%SG_API%"=="1" call :sg_api_start
if not "%SG_APIRC%"=="0" goto :sg_end
if "%SG_API_ONLY%"=="1" goto :sg_end
call :sg_banner
echo Launching: "%SG_PY%" main_qt.py
"%SG_PY%" main_qt.py
set "SG_RC=%ERRORLEVEL%"
goto :sg_end

:sg_api_start
set "SG_APIRC=0"
echo.
echo Checking "from main import app" with "%SG_PY%" - errors shown if it fails.
"%SG_PY%" -c "from main import app"
if errorlevel 1 goto :sg_api_bad
echo Starting the "SecureGuard API" window on %SG_HOST%:%SG_API_PORT%, test mode %SG_MODE%.
start "SecureGuard API" /D "%~dp0" "%SG_PY%" -m uvicorn main:app --host %SG_HOST% --port %SG_API_PORT%
REM 3 s settle. "ping" instead of "timeout" because "timeout" fails when
REM stdin is redirected, which is exactly the scripted case.
ping -n 4 127.0.0.1 >nul 2>&1
echo Stop the API server with Ctrl+C in the "SecureGuard API" window.
echo.
exit /b 0

:sg_api_bad
echo.
echo ERROR: main:app does not import - the API server was NOT started.
echo        Fix that import error above, then re-run.
set "SG_APIRC=1"
exit /b 1

:sg_banner
echo.
echo ---------------------------------------------------------------
if "%SG_MODE%"=="1" goto :sg_banner_dev
echo  PRODUCTION MODE - SECUREGUARD_TEST_MODE=0
echo  No auto-login. Paste a real token in the Manual Token tab.
echo ---------------------------------------------------------------
exit /b 0

:sg_banner_dev
echo  DEV MODE - SECUREGUARD_TEST_MODE=1
echo  Quick Profile signs in with a locally minted DEMO token whose MFA is
echo  already verified. This is NOT a real authentication.
echo ---------------------------------------------------------------
exit /b 0

:sg_shortcut
echo.
echo NOTE: create_shortcut_qt.py also overwrites launch_secureguard_qt.bat with
echo       a minimal fallback launcher. Restore it after running this.
echo.
set "SG_GO="
set /p SG_GO=Create the desktop shortcut now? (y/N): 
if /i not "%SG_GO%"=="y" goto :sg_end
"%SG_PY%" create_shortcut_qt.py
set "SG_RC=%ERRORLEVEL%"
findstr /b /c:"REM SG-LAUNCHER-V2" "%~dp0launch_secureguard_qt.bat" >nul 2>&1
if errorlevel 1 echo WARNING: launch_secureguard_qt.bat was overwritten - restore it from git.
goto :sg_end

:sg_end
if not "%SG_ARG%"=="" exit /b %SG_RC%
echo.
pause
exit /b %SG_RC%

:sg_can
REM %1 = candidate interpreter. Sets SG_OK=1 only on a real PySide6 import,
REM and always sets SG_SAY to a one-line reason either way.
set "SG_OK=0"
set "SG_SAY=empty candidate"
if "%~1"=="" exit /b 0
set "SG_SAY=not found on disk or not executable"
"%~1" -c "import PySide6" >nul 2>&1
REM 9009 is cmd's "not recognized as a command" code; anything else nonzero
REM means the interpreter ran and PySide6 was genuinely missing from it.
if errorlevel 9009 exit /b 0
if not errorlevel 1 goto :sg_can_yes
set "SG_SAY=found, but PySide6 import FAILED"
exit /b 0
:sg_can_yes
set "SG_OK=1"
set "SG_SAY=PySide6 import OK"
exit /b 0
