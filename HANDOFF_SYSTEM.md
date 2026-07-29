# 小窝无缝换窗

小窝现在只保留一套交接线路：`api/handoff.py`。它同时服务 CC
窗口切换、模型换班、生活线恢复和 TG 聊天进度续接。

## 一次换窗的顺序

1. `session_swap.py` 读取旧窗口，生成精简的新 transcript。
2. `handoff.py` 写入私有交接包，其中包含生活线位置与校验值、最近对话、
   未完成工具调用和 TG 消息游标。
3. 新窗口启动。此时旧 transcript 仍留在原处，可随时回退。
4. 新窗口读完生活线与交接包后发送 ready：

   ```bash
   python3 /var/www/home/api/handoff.py ready --session-id 新会话ID
   ```

5. ready 校验通过后，旧 transcript 才移入 `archived_sessions/`。
6. 如果启动失败，执行：

   ```bash
   python3 /var/www/home/api/handoff.py rollback --error "失败原因"
   ```

   新 transcript 会移入 `failed_handoffs/`，旧窗口保持不动。

## 外部程序的两个接入点

仓库里没有 VPS 上的 `start-bot.sh` 和 TG monitor 源码，因此部署时需要它们
遵守下面两个约定。

- CC/TG 启动器：启动新会话前读取 `handoff-current.json`；恢复完成后调用
  `handoff.py ready`。模型换班会由 `statusline.sh` 在检测到目标模型心跳时
  自动确认。
- TG monitor：当 `handoff_state.json` 的状态为 `preparing`、
  `transcript_ready`、`starting` 或 `awaiting_ready` 时暂停派发新消息，
  但继续收取并落盘；状态变为 `ready` 或 `rolled_back` 后，从
  `chat_cursor` 继续，避免重发或漏回。

设置页只读取脱敏后的 `/data/handoff_state.json`，不会把最近对话或内部文件
路径暴露给前端。

## 统一路径

可通过环境变量覆盖：

- `HOME_CLAUDE_PROJECT_DIR`：CC 会话目录。
- `HOME_LIFELINE_FILE`：唯一生活线文件。
- `HOME_CHAT_FILE`：TG/网页共用聊天记录。
- `HOME_HANDOFF_STATE`：私有状态。
- `HOME_HANDOFF_PACKAGE`：私有交接包。
- `HOME_HANDOFF_PUBLIC_STATE`：设置页读取的脱敏状态。

推荐部署值：

```text
HOME_CLAUDE_PROJECT_DIR=/root/.claude/projects/-var-www-home-api
HOME_LIFELINE_FILE=/root/.claude/projects/-var-www-home-api/memory/lifeline.md
HOME_CHAT_FILE=/var/www/home/data/reading/chat.json
HOME_HANDOFF_PUBLIC_STATE=/var/www/home/data/handoff_state.json
```
