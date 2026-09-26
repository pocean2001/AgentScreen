# 用法: python send_text.py "第一行" "第二行" ...
#   多条 -> 作为一个多行信息块显示（超过 4 行会自动上下滚屏）; 不带参数 -> 清空
#   走 agentscreen_client (优先连接器 broker, 统一端口)
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agentscreen_client as C

msgs = sys.argv[1:]
obj = {"op": "info", "lines": msgs} if msgs else {"op": "info", "text": ""}
r = C.call(obj)
if r:
    print(r)
else:
    print("[错误] 推送失败 —— " + C.explain())
    sys.exit(2)
