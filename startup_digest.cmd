@echo off
rem ============================================================
rem  AgentScreen digest refresher - minimized launcher
rem  Same as digest_10min.cmd but starts the loop in a MINIMIZED
rem  window (used for the Startup folder / boot auto-start).
rem
rem  Stop : close the "AgentScreenDigest" window in the taskbar
rem ============================================================
setlocal
cd /d "%~dp0"
call "%~dp0_python.cmd"
if not defined PYQ exit /b 1
start "AgentScreenDigest" /min %PYQ% "%~dp0digest_loop.py" --interval 600
