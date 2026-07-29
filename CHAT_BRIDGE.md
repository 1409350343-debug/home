# 小窝聊天与 CC/TG 联动约定

## 保持不变的主通道

现有 Monitor 继续监听：

`/var/www/home/data/reading/chat.json`

网页继续通过 `/api/read/chat` 追加消息。消息仍保留 `id`、`sender`、
`text`、`page`、`book_id` 和 `ts` 字段，所以旧 Monitor 可以继续工作。
新增的 `delivery`、`route`、`client_id` 字段可以忽略。

## 共享时间上下文

`/var/www/home/api/time_state.json` 每 5 分钟在本地刷新一次，包含当地时刻、自然光、
天气、季节和最近的作息信号。网页新消息会额外带上
`temporal_context`，旧 Monitor 忽略它也不会受影响。

Monitor 处理一条消息时优先读取该消息的 `temporal_context.summary`；
如果消息里没有，可直接执行：

```bash
python3 /var/www/home/api/time_sense.py --context --no-weather-refresh
```

这份上下文只用于调整语气、回复时机和提醒强度。作息状态不确定时不得
把推测说成事实。TG 的收发地址、chat.json 路径和消息主字段均未改变。

## CC 心跳（可选）

Monitor 每 15～30 秒执行一次：

```bash
python3 /var/www/home/api/chat_bridge.py heartbeat --state idle
```

收到消息后可以依次写：

```bash
python3 /var/www/home/api/chat_bridge.py heartbeat --state reading --message-id 消息ID
python3 /var/www/home/api/chat_bridge.py heartbeat --state thinking --message-id 消息ID
python3 /var/www/home/api/chat_bridge.py heartbeat --state replying --message-id 消息ID
```

超过 45 秒没有心跳时，小窝只会提示“CC 心跳已中断”，不会自动调用
其他模型，也不会切断 TG。

## 备胎规则

`standby_config.json` 目前只保存备胎配置。默认不得自动接管，避免 CC/TG
和备胎同时回复。将来增加真正的备胎进程时，必须满足：

1. CC 心跳失联；
2. 用户消息等待超过设定时间；
3. 重新确认同一 `client_id` 尚未被回复；
4. 备胎回复仍写回 `chat.json`，并标记 `route: "standby"`；
5. 同步通知 TG，保证两边上下文一致。

## 数据安全

- API 使用原子替换写 `chat.json`，避免写到一半留下坏文件。
- 主文件只保留最近 500 条，溢出的旧消息进入 `chat-archive.jsonl`。
- 重试使用 `client_id` 去重，网络断开后重试不会重复发送。
- 图片限制为 8 MB，只接受 JPEG、PNG、GIF 和 WebP。
