@echo off
rem ============================================================
rem  _python.cmd - resolve a Python launcher into %PYQ%
rem  Used by the other .cmd files so they work on ANY machine
rem  (no hard-coded python path).  Call it, then use %PYQ%.
rem
rem  Search order:
rem    1) WorkBuddy managed venv under %USERPROFILE%\.workbuddy
rem    2) python.exe found on PATH
rem    3) Windows "py" launcher  (py -3)
rem ============================================================
set "PYQ="
set "_M=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if exist "%_M%" (
  set "PYQ="%_M%""
  goto :eof
)
for /f "delims=" %%i in ('where python 2^>nul') do if not defined PYQ set "PYQ="%%i""
if defined PYQ goto :eof
for /f "delims=" %%i in ('where py 2^>nul') do if not defined PYQ set "PYQ=%%i -3"
goto :eof
