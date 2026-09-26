@echo off
rem ============================================================
rem  codex_confirm.cmd - Codex 授权请求(副屏选 K0=允许/K1=拒绝)的 Windows 侧入口
rem    手动自检:  codex_confirm.cmd --check
rem                codex_confirm.cmd --test     (弹一个测试授权框)
rem    Windows 版 Codex 的 hooks.json 可直接写:
rem        cmd /d /s /c "D:\K230D\codex_confirm.cmd"
rem    注意: 本脚本会往 stdout 输出决策 JSON, 不要给其它输出(如 echo)污染。
rem ============================================================
setlocal
cd /d "%~dp0"
call "%~dp0_python.cmd"
if not defined PYQ (
  echo [!] Python not found 1>&2
  exit /b 0
)
%PYQ% "%~dp0codex_confirm_hook.py" %*
exit /b 0
