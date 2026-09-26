@echo off
rem ============================================================
rem  codex_status.cmd - Codex 状态推送的 Windows 侧入口
rem    手动自检:  codex_status.cmd --check
rem                codex_status.cmd --test 测试文本
rem    Windows 版 Codex 的 hooks.json 可直接写:
rem        cmd /d /s /c "D:\K230D\codex_status.cmd"
rem ============================================================
setlocal
cd /d "%~dp0"
call "%~dp0_python.cmd"
if not defined PYQ (
  echo [!] Python not found 1>&2
  exit /b 0
)
%PYQ% "%~dp0codex_status_hook.py" %*
exit /b 0
