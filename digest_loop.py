#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""digest_loop.py — 常驻刷新器: 每 N 秒把「美股行情 + 要闻」推到 K230D 副屏。

用法:
  python digest_loop.py                # 每 600s(10分钟) 推一次, 常驻
  python digest_loop.py --interval 60  # 改间隔
  python digest_loop.py --count 3      # 只跑 3 次就退出(测试用)
  python digest_loop.py --dry          # 只打印本次合成内容, 不推送

纯脚本、不走 Agent, 所以开销极小; 新闻内容由 WorkBuddy 的定时任务用 WebSearch 更新到 _news.txt。
日志: _digest.log (追加)。停止: Ctrl-C 或关掉窗口。
"""
import sys, os, time, socket, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "_digest.log")
PUSH = os.path.join(HERE, "push_digest.py")
SINGLETON_PORT = int(os.environ.get("DIGEST_SINGLETON_PORT", "8721"))   # 占住这个本地端口=单实例锁
LOG_MAX = 256 * 1024                                                    # 日志超过 256KB 就清空重来


def arg(name, default=None, cast=str):
    a = sys.argv
    if name in a and a.index(name) + 1 < len(a):
        try:
            return cast(a[a.index(name) + 1])
        except Exception:
            return default
    return default


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > LOG_MAX:
            os.remove(LOG)                     # 简单轮转: 太大就重来
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def acquire_singleton():
    """占住一个本地端口当单实例锁(进程退出即自动释放, 不会有残留锁文件)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Windows: SO_EXCLUSIVEADDRUSE 与 SO_REUSEADDR 互斥, 同时设会让 bind 失败 -> 只能二选一
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", SINGLETON_PORT))
        s.listen(1)
    except OSError:
        s.close()
        return None
    return s


def check_device(interval):
    """启动时探测板子在哪个串口; 未连接则打印可操作的报错(之后每轮仍会重试)"""
    try:
        sys.path.insert(0, HERE)
        from k230_push import detect_canmv_port, port_report
    except Exception as e:
        log("ERROR 加载 k230_push 失败: %r" % e)
        return False
    p = detect_canmv_port()
    if p:
        log("device ok: K230D @ %s" % p)
        return True
    log("=" * 58)
    log("错误: 未检测到 K230D（CanMV）串口 —— 设备可能没有连接。")
    for ln in port_report().splitlines():
        log(ln)
    log("请检查: 1) USB 线/口是否插好  2) 设备管理器是否有 'CanMV (Interface 0) (COMx)'")
    log("        3) 串口是否被 CanMV IDE / 串口助手占用  4) 板子是否卡死(重插 USB 或断电重启)")
    log("本循环仍会每 %d 秒重试一次（插上板子后自动恢复）" % interval)
    log("=" * 58)
    return False


def one_pass(extra=None):
    cmd = [sys.executable, PUSH] + (extra or [])
    try:
        p = subprocess.run(cmd, cwd=HERE, capture_output=True, timeout=180)
        out = p.stdout.decode("utf-8", "replace").strip()
        err = p.stderr.decode("utf-8", "replace").strip()
        tail = " | ".join(out.splitlines()[-2:]) if out else ""
        if p.returncode == 0:
            log("push ok  %s" % tail)
        else:
            log("push FAIL rc=%d  %s  %s" % (p.returncode, tail, err[:200]))
        return p.returncode == 0
    except Exception as e:
        log("push ERR %r" % e)
        return False


def main():
    if "--dry" in sys.argv:
        subprocess.run([sys.executable, PUSH], cwd=HERE)
        return 0
    interval = arg("--interval", 600, int)
    count = arg("--count", 0, int)
    lock = acquire_singleton()
    if lock is None:
        log("another digest_loop is already running (port %d busy) -> exit" % SINGLETON_PORT)
        return 0
    log("digest_loop start interval=%ds count=%s pid=%d" % (interval, count or "inf", os.getpid()))
    check_device(interval)          # 启动即探测: 板子接在哪个串口 / 未连接则报错
    try:
        while True:
            one_pass()
            if count:
                count -= 1
                if count <= 0:
                    break
            time.sleep(interval)
    except KeyboardInterrupt:
        log("digest_loop stopped by user")
    log("digest_loop exit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
