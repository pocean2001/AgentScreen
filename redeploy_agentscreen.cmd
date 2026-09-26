@echo off
rem ============================================================
rem  Deploy / re-deploy the board-side service to the K230D
rem  (uploads agent_screen.py + board_main.py, then soft reset)
rem
rem  Requires: USB connected, pyserial installed
rem  Note: soft reset clears the on-screen icon/weather/info block
rem ============================================================
setlocal
cd /d "%~dp0"
call "%~dp0_python.cmd"
if not defined PYQ (
  echo [!] Python not found. Install Python 3.9+ (or WorkBuddy) and retry.
  pause
  exit /b 1
)
%PYQ% "%~dp0redeploy_agentscreen.py"
pause
