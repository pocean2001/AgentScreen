# 这是「PC 端安装环境」包 —— 不含板端固件

本包收纳在**电脑上**运行的全部工具：串口推送、MCP 连接器、编辑器钩子、定时刷新、安装/打包脚本，
以及要推到板子上的**素材**（图标 / 提示音 / 补字库）。

**不含** `board/` 目录 —— 那是上传到 K230D 的板端服务（`agent_screen.py`、`board_main.py`）。

> ⚠️ 本包的 `README.md` 是**完整版文档**，其中涉及 `board/`、上板部署（`--deploy`）的章节**不适用于本包**；
> 以本文件为准。

## 因此以下命令在本包内不可用

| 命令 | 原因 |
|---|---|
| `python install.py --deploy` | 需要 `board/` 里的板端脚本 |
| `redeploy_agentscreen.cmd` | 同上 |
| `python install.py --test` | 需要板端服务已在板上运行 |

## 仍然可用（PC 端）

- `python install.py` —— 写入 MCP 连接器配置 + 编辑器钩子（会先备份原文件）
- `python push_digest.py` / `push_market.py` / `push_weather.py` —— 把行情/要闻/天气推到副屏（需板子在跑服务）
- `python glyphcheck.py "东莞"` —— 查板端字库有没有某个字的字形
- `make_icon.py` / `make_sfx.py` / `send_text.py` / `as_check.py`
- `python uninstall.py` —— 卸载 PC 端配置

## 需要上板时

改用完整包（含 `board/`），或自行把板端脚本放进 `board/` 后再执行 `--deploy`。
