#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install.py — AgentScreen 副屏（K230D）一键安装器。

做什么:
  1. 自检: Python 版本 / pyserial / Pillow / 串口(可选)
  2. 备份并写入 WorkBuddy 配置:
       ~/.workbuddy/mcp.json       -> 注册 AgentScreen 连接器(MCP)
       ~/.workbuddy/settings.json  -> 注册 6 个钩子(状态推送 + 高危审批)
     已存在的同名条目会先删除再写入(便于换目录后重装)
  3. --startup: 在 Windows 启动文件夹写入开机自启(10 分钟刷新行情+要闻)
  4. --deploy : 把板端服务上传到 K230D(等价于 redeploy_agentscreen.py)
  5. --test   : 往副屏推一条测试状态行, 验证链路

用法:
  python install.py                 # 只装 WorkBuddy 配置(推荐先跑这个)
  python install.py --pip           # 缺依赖时自动 pip install
  python install.py --startup       # 同时装开机自启
  python install.py --deploy --test # 装配置 + 上板 + 自测
  python install.py --dry-run       # 只显示将要做什么, 不写文件
"""
import sys, os, json, time, shutil, subprocess, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
HOME = os.path.expanduser("~")
WB_DIR = os.path.join(HOME, ".workbuddy")
MCP = os.path.join(WB_DIR, "mcp.json")
SETTINGS = os.path.join(WB_DIR, "settings.json")
STARTUP = os.path.join(os.environ.get("APPDATA", ""),
                       "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
STARTUP_FILE = os.path.join(STARTUP, "startup_digest.cmd")
ICON_DIR = os.path.join(HERE, "icons")
NEWS_FILE = os.path.join(HERE, "_news.txt")

STATUS_HOOK = "wb_status_hook.py"
CONFIRM_HOOK = "wb_confirm_hook.py"
MATCHER = "Bash|Write|Edit|MultiEdit|WebFetch|WebSearch"

# 钩子注册表: 事件 -> (脚本, 超时秒, 是否需要 matcher)
HOOKS = [
    ("PreToolUse",     CONFIRM_HOOK, 90, True),
    ("PostToolUse",    STATUS_HOOK,  10, True),
    ("SessionStart",   STATUS_HOOK,  10, False),
    ("UserPromptSubmit", STATUS_HOOK, 10, False),
    ("Stop",           STATUS_HOOK,  10, False),
    ("Notification",   STATUS_HOOK,  10, False),
]

ok = lambda s: print("  [v] " + s)
info = lambda s: print("  [i] " + s)
warn = lambda s: print("  [!] " + s)
step = lambda s: print("\n=== " + s + " ===")


def cmd_for(script):
    """WorkBuddy 钩子/命令里使用的可执行串(统一用正斜杠, 双引号包路径)"""
    return '"%s" "%s"' % (PY.replace("\\", "/"), os.path.join(HERE, script).replace("\\", "/"))


# ----------------------------- 1. 自检 -----------------------------
def check_deps(do_pip=False):
    step("1/5 环境自检")
    info("Python: %s" % sys.version.split()[0])
    info("解释器: %s" % PY)
    if sys.version_info < (3, 9):
        warn("建议 Python 3.9+（当前 %d.%d）" % sys.version_info[:2])
    else:
        ok("Python 版本可用")

    missing = []
    for mod, pkg in (("serial", "pyserial"), ("PIL", "pillow")):
        try:
            __import__(mod)
            ok("%s 已安装" % pkg)
        except ImportError:
            missing.append(pkg)
            warn("%s 缺失" % pkg)
    if missing:
        hint = "  %s -m pip install %s" % (PY, " ".join(missing))
        if do_pip:
            info("正在安装: %s" % " ".join(missing))
            r = subprocess.run([PY, "-m", "pip", "install"] + missing)
            if r.returncode == 0:
                ok("依赖安装完成")
            else:
                warn("安装失败，请手动执行:\n" + hint)
        else:
            warn("请先安装依赖:\n" + hint + "\n      （或加 --pip 让本脚本自动装）")
    return not missing


def check_board():
    step("串口自检（自动探测板子接在哪个口）")
    try:
        sys.path.insert(0, HERE)
        from k230_push import detect_canmv_port, port_report
        port = detect_canmv_port()
        if port:
            ok("已识别 K230D: %s" % port)
            return port
        print("  [错误] 未检测到 K230D（CanMV）串口 —— 设备可能没有连接。")
        print("  本机串口清单:")
        print("\n".join("  " + l for l in port_report().splitlines()))
        print("  请检查: 1) USB 线/口  2) 设备管理器是否有 'CanMV (Interface 0) (COMx)'")
        print("          3) 串口是否被 CanMV IDE/串口助手占用  4) 板子是否卡死(重插/断电重启)")
        print("          5) 也可显式指定: set AGENTSCREEN_PORT=COM14")
        return None
    except Exception as e:
        warn("串口自检失败: %r" % e)
        return None


# ----------------------------- 2. 配置文件 -----------------------------
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        warn("读取 %s 失败(%r)，将视为空配置" % (path, e))
        return default


def backup(path, dry=False):
    if dry or not os.path.exists(path):
        return None
    bak = "%s.bak-%s" % (path, time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(path, bak)
    info("已备份 -> %s" % os.path.basename(bak))
    return bak


def save_json(path, data, dry):
    if dry:
        info("[dry-run] 将写入 %s" % path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    ok("已写入 %s" % path)


def install_mcp(dry):
    step("2/5 注册 AgentScreen 连接器 (MCP)")
    d = load_json(MCP, {})
    servers = d.setdefault("mcpServers", {})
    servers["AgentScreen"] = {"command": PY, "args": [os.path.join(HERE, "agent_screen_mcp.py")],
                              "disabled": False}
    ok("AgentScreen -> %s" % os.path.join(HERE, "agent_screen_mcp.py"))
    backup(MCP, dry)
    save_json(MCP, d, dry)
    info("装好后需在「连接器管理 → 右上角自定义连接器」里对 AgentScreen 点 Trust 才会生效")


def install_hooks(dry):
    step("3/5 注册状态推送 / 审批 钩子")
    d = load_json(SETTINGS, {})
    hooks = d.setdefault("hooks", {})
    mine = (STATUS_HOOK, CONFIRM_HOOK)
    for event, script, timeout, need_matcher in HOOKS:
        entry = {"type": "command", "command": cmd_for(script), "timeout": timeout}
        groups = hooks.setdefault(event, [])
        # 先删掉旧的同名条目(便于换目录后重装)
        for g in list(groups):
            g["hooks"] = [h for h in g.get("hooks", [])
                          if not any(m in str(h.get("command", "")) for m in mine)]
        groups[:] = [g for g in groups if g.get("hooks")]
        # 尽量复用已有的同 matcher 分组
        target = None
        for g in groups:
            if (g.get("matcher", "") == MATCHER) == need_matcher:
                target = g
                break
        if target is None:
            target = {"hooks": []}
            if need_matcher:
                target["matcher"] = MATCHER
            groups.append(target)
        target["hooks"].append(entry)
        ok("%s -> %s" % (event, script))
    backup(SETTINGS, dry)
    save_json(SETTINGS, d, dry)
    info("钩子会在下一次事件时生效（不必重启 WorkBuddy）")


def install_startup(dry):
    step("4/5 开机自启（10 分钟刷新行情+要闻）")
    content = (
        "@echo off\r\n"
        "rem Auto-generated by install.py - AgentScreen digest refresher\r\n"
        "cd /d \"%s\"\r\n"
        "start \"AgentScreenDigest\" /min \"%s\" \"%s\" --interval 600\r\n"
        % (HERE, PY, os.path.join(HERE, "digest_loop.py"))
    )
    if dry:
        info("[dry-run] 将写入 %s" % STARTUP_FILE)
        return
    if not os.path.isdir(STARTUP):
        warn("找不到启动文件夹: %s" % STARTUP)
        return
    with open(STARTUP_FILE, "w", encoding="gbk", errors="replace", newline="") as f:
        f.write(content)
    ok("已写入 %s" % STARTUP_FILE)
    info("停止: 关掉任务栏里的 AgentScreenDigest 窗口；卸载: 运行 uninstall.py")


# ----------------------------- 5. 上板 / 自测 -----------------------------
def deploy_board():
    step("上板: 上传板端服务")
    r = subprocess.run([PY, os.path.join(HERE, "redeploy_agentscreen.py")], cwd=HERE)
    return r.returncode == 0


def self_test(do_test):
    step("5/5 链路自检")
    if not do_test:
        info("跳过推送测试（加 --test 可实测往副屏推一条）")
        return
    code = ("import sys\nsys.path.insert(0, %r)\n"
            "import agentscreen_client as C\n"
            "print(C.call({'op':'stage','text':'安装完成','color':[60,220,110],"
            "'task':'AgentScreen 安装自检'}))\n" % HERE)
    r = subprocess.run([PY, "-u", "-c", code], cwd=HERE)
    if r.returncode == 0:
        ok("已往副屏推送测试状态行；看屏幕是否显示 绿色任务段 + 绿色'安装完成'")
    else:
        warn("推送失败，请检查 USB / 串口占用")


def main():
    ap = argparse.ArgumentParser(description="AgentScreen 副屏一键安装器")
    ap.add_argument("--pip", action="store_true", help="缺依赖时自动 pip 安装")
    ap.add_argument("--startup", action="store_true", help="同时写开机自启")
    ap.add_argument("--deploy", action="store_true", help="上传板端服务到 K230D")
    ap.add_argument("--test", action="store_true", help="往副屏推一条测试状态行")
    ap.add_argument("--dry-run", action="store_true", help="只显示将要做什么，不写文件")
    a = ap.parse_args()

    print("=" * 62)
    print(" AgentScreen 副屏（K230D）安装器")
    print(" 安装目录: %s" % HERE)
    if a.dry_run:
        print(" 模式: DRY-RUN（不写任何文件）")
    print("=" * 62)

    check_deps(a.pip)
    ensure_files()
    install_mcp(a.dry_run)
    install_hooks(a.dry_run)
    if a.startup:
        install_startup(a.dry_run)
    else:
        step("4/5 开机自启")
        info("未启用（需要的话加 --startup）")

    if a.deploy and not a.dry_run:
        deploy_board()
    else:
        step("上板")
        info("未执行上传（需要的话加 --deploy，或双击 redeploy_agentscreen.cmd）")

    if not a.dry_run:
        port = check_board()
        self_test(a.test)
        if not port and (a.deploy or a.test):
            print("\n[错误] 板子未连接（或串口未识别），--deploy / --test 未能完成。")
            return 2
    else:
        step("5/5 链路自检")
        info("[dry-run] 跳过")

    print("\n" + "=" * 62)
    print(" 下一步")
    print("=" * 62)
    print(" 1) 到 WorkBuddy「连接器管理 → 右上角自定义连接器」对 AgentScreen 点 Trust")
    print(" 2) 首装/换机后执行一次上板: 双击 redeploy_agentscreen.cmd（或 --deploy）")
    print(" 3) 想每 10 分钟自动刷新行情+要闻: 双击 digest_10min.cmd（或 --startup 开机自启）")
    print(" 4) 常用命令:")
    print("      python push_digest.py        # 立刻推一次 行情+要闻")
    print("      python send_text.py \"要显示的话\"   # 推文字到信息栏")
    print("      python push_digest.py --status     # 看要闻是否该更新")
    print(" 详见同目录 README.md")
    return 0


def ensure_files():
    os.makedirs(ICON_DIR, exist_ok=True)
    if not os.path.exists(NEWS_FILE):
        try:
            with open(NEWS_FILE, "w", encoding="utf-8") as f:
                f.write("（要闻占位：由 WorkBuddy 的定时任务用 WebSearch 更新此文件）\n")
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
