#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""uninstall.py — 卸载 AgentScreen 在 WorkBuddy 里的注册（不动程序文件本身）。

会做三件事（都会先备份）:
  1. 从 ~/.workbuddy/mcp.json      移除 AgentScreen 连接器
  2. 从 ~/.workbuddy/settings.json 移除本程序注册的 6 个钩子
  3. 删除启动文件夹里的 startup_digest.cmd（开机自启）

用法:
  python uninstall.py          # 交互确认
  python uninstall.py --yes    # 不确认，直接执行
"""
import sys, os, json, time, shutil, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
MCP = os.path.join(HOME, ".workbuddy", "mcp.json")
SETTINGS = os.path.join(HOME, ".workbuddy", "settings.json")
STARTUP_FILE = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                            "Start Menu", "Programs", "Startup", "startup_digest.cmd")
MINE = ("wb_status_hook.py", "wb_confirm_hook.py")
ok = lambda s: print("  [v] " + s)
info = lambda s: print("  [i] " + s)
warn = lambda s: print("  [!] " + s)


def backup(path):
    if os.path.exists(path):
        bak = "%s.bak-%s" % (path, time.strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(path, bak)
        info("已备份 -> %s" % os.path.basename(bak))


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="不交互确认")
    a = ap.parse_args()

    print("将移除以下注册（程序文件保留）:")
    print("  - mcp.json 里的 AgentScreen 连接器")
    print("  - settings.json 里由本程序注册的钩子")
    print("  - 启动文件夹的开机自启: %s" % STARTUP_FILE)
    if not a.yes:
        try:
            if input("继续? [y/N] ").strip().lower() != "y":
                print("已取消"); return 0
        except Exception:
            return 0

    # 1) MCP
    d = load(MCP, None)
    if isinstance(d, dict) and "AgentScreen" in d.get("mcpServers", {}):
        backup(MCP)
        d["mcpServers"].pop("AgentScreen", None)
        save(MCP, d)
        ok("已移除 AgentScreen 连接器")
    else:
        info("mcp.json 里没有 AgentScreen，跳过")

    # 2) hooks
    s = load(SETTINGS, None)
    if isinstance(s, dict) and isinstance(s.get("hooks"), dict):
        changed = 0
        for event, groups in list(s["hooks"].items()):
            for g in groups:
                before = len(g.get("hooks", []))
                g["hooks"] = [h for h in g.get("hooks", [])
                              if not any(m in str(h.get("command", "")) for m in MINE)]
                changed += before - len(g["hooks"])
            s["hooks"][event] = [g for g in groups if g.get("hooks")]
            if not s["hooks"][event]:
                s["hooks"].pop(event, None)
        if changed:
            backup(SETTINGS)
            save(SETTINGS, s)
            ok("已移除 %d 个钩子" % changed)
        else:
            info("settings.json 里没有本程序的钩子，跳过")
    else:
        info("settings.json 不存在或无 hooks，跳过")

    # 3) startup
    if os.path.exists(STARTUP_FILE):
        with open(STARTUP_FILE, encoding="gbk", errors="replace") as f:
            body = f.read()
        if "AgentScreenDigest" in body or "digest_loop.py" in body:
            os.remove(STARTUP_FILE)
            ok("已删除开机自启: %s" % STARTUP_FILE)
        else:
            warn("启动文件夹里的同名文件不是本程序生成的，未删除: %s" % STARTUP_FILE)
    else:
        info("没有开机自启文件，跳过")

    print("\n完成。程序文件仍在: %s" % HERE)
    print("（如需彻底删除，直接删掉那个文件夹即可）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
