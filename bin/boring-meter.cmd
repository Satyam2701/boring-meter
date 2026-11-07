@echo off
rem Boring Meter launcher for Windows (CMD and PowerShell).
rem Finds a working Python 3.9+ and runs scripts\run_boring_meter.py.
setlocal
set "BM_ROOT=%~dp0.."
set "BM_PY="
set "BM_CHECK=import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"
py -3 -c "%BM_CHECK%" >nul 2>nul && set "BM_PY=py -3"
if not defined BM_PY (python -c "%BM_CHECK%" >nul 2>nul && set "BM_PY=python")
if not defined BM_PY (python3 -c "%BM_CHECK%" >nul 2>nul && set "BM_PY=python3")
if not defined BM_PY goto nopython
%BM_PY% "%BM_ROOT%\scripts\run_boring_meter.py" %*
exit /b %ERRORLEVEL%

:nopython
rem Hooks must never fail Claude Code: without Python the hook simply does nothing.
if "%~1"=="--run-hook" exit /b 0
echo Boring Meter error [RUNTIME_MISSING]: Python 3.9 or newer is required but was not found. 1>&2
echo Hint: install Python 3 from python.org (it includes the "py" launcher), then run the command again. 1>&2
exit /b 3
