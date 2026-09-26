@echo off
rem ============================================================
rem  AgentScreen digest refresher - portable launcher
rem  Pushes "US market quotes + news" to the K230D screen every
rem  10 minutes. Pure local script - no agent/LLM cost.
rem
rem  Start : double-click this file
rem  Stop  : close the console window (or Ctrl-C)
rem  Tune  : change INTERVAL below (seconds)
rem  Log   : <this folder>\_digest.log
rem  News  : refreshed by the WorkBuddy automation into _news.txt
rem ============================================================
setlocal
cd /d "%~dp0"
call "%~dp0_python.cmd"
if not defined PYQ (
  echo [!] Python not found. Install Python 3.9+ (or WorkBuddy) and retry.
  pause
  exit /b 1
)
set INTERVAL=600
%PYQ% "%~dp0digest_loop.py" --interval %INTERVAL%
