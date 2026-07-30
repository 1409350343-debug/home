# 小窝记忆系统

## 唯一数据源

记忆角、记忆屋和聊天主动召回统一使用 LMC-5 SQLite：

```text
api/lmc5_memory.db
```

可以用 `HOME_MEMORY_DB` 覆盖数据库位置。旧 OmbreBrain Markdown 文件只用于
历史迁移，不再作为记忆角的运行时数据源。

## 字段职责

字段职责与字段内容分开。系统不会预设或重命名实际分类值：

- `thread`：一条记忆所属的上下文线索或主题线。
- `category`：记忆角用于分组展示的分类；为空时页面回退使用 `thread`。
- `status`：生命周期状态。日常展示和召回只读取 `current`。
- `tags_json`：一条记忆可以具有的多个检索标签。
- `tier`：如果数据库具有该字段，用于表达记忆层级；没有时不自动猜测。
- `event_date`：事情实际发生的日期。
- `created_at`：这条数据库记录创建的时间。
- `updated_at`：数据库记录最后修改的时间。
- `why_remembered`：写入当时判断“为什么值得长期记住”的原因；新记忆必填。
- `fact_key`：会变化事实的稳定身份，例如 `assistant.name`。
- `fact_value`：该版本的事实值。
- `valid_from` / `valid_to`：该版本的有效时间范围。
- `is_current_fact`：是否为当前确认版本。
- `supersedes_id`：新版本替换的旧版本 id。
- `change_reason`：为什么判断事实发生了变化。
- `review_status`：`confirmed`、`pending` 或 `conflict`。

这些说明只定义用途，不规定字段必须包含哪些具体值。现有数据库内容会原样保留。

## 路径配置

所有记忆脚本通过 `api/memory_config.py` 读取路径。可使用：

```text
HOME_APP_ROOT
HOME_MEMORY_DB
HOME_BRAIN_DATA
HOME_RECALL_LOG
HOME_RECALL_EXPLORE_STATE
HOME_MEMORY_NOTE_DIRS
HOME_LIFELINE_FILES
LMC5_SRC
HOME_MEMORY_API_TOKEN
```

`HOME_MEMORY_NOTE_DIRS` 和 `HOME_LIFELINE_FILES` 使用冒号分隔多个路径。

## 外部依赖

安装本仓库的记忆辅助依赖：

```bash
python3 -m pip install -r requirements-memory.txt
```

`lmc5` 源码不在本仓库中。`LMC5_SRC` 必须指向一个包含
`lmc5/store.py` 的源码目录，例如服务器现有的 `/root/lmc-5/src`。

如果设置 `HOME_MEMORY_API_TOKEN`，分类、归档和恢复等写请求必须携带
`Authorization: Bearer ...` 或 `X-Memory-Token`。未设置时，应由 Nginx
或其他外层登录保护整个小窝。

## 常用命令

```bash
python3 api/lmc5_tool.py stats
python3 api/lmc5_tool.py search "关键词"
python3 api/lmc5_tool.py fact-get assistant.name --history
python3 api/lmc5_tool.py fact-list
python3 api/lmc5_tool.py add \
  --title "标题" \
  --content "记忆正文" \
  --thread "数据库中的实际主题值" \
  --category "数据库中的实际分类值" \
  --why "此刻为什么值得长期记住"
python3 api/lmc5_tool.py fact-set assistant.name "禄禄" \
  --title "助手名字" \
  --why "用户明确确定了助手的新名字" \
  --change-reason "由福福改为禄禄"
python3 api/split_memories.py
python3 api/gen_brain_data.py
python3 api/memory.py
```

`split_memories.py` 默认只预览，必须显式添加 `execute` 才会修改数据库：

```bash
python3 api/split_memories.py execute
```

## 写入规则

- 新记忆没有 `--why` 时，命令直接拒绝执行。
- 写入前会检查近重复内容；高度相似时不会再新增一份。
- 分类移动、归档、恢复、迁移和拆分都会写入 `memory_history`。
- 记忆角的“删除”实际是归档，可在 `memory-archive.html` 恢复。
- `recall_hook.py` 会在每轮对话上下文中加入记忆沉淀契约，提醒 AI 只在
  出现未来仍有用的新事实或明确偏好时写入，并避开一次性闲聊和秘密凭据。

## Z 轴：事实演化

同一个 `fact_key` 只保留一个已确认的当前版本。执行 `fact-set` 时：

- 新值与当前值相同：不重复写入，只增加一次确认记录；
- 新值被用户明确确认：旧版本填写 `valid_to`，新版本成为当前版本；
- 新旧说法存在歧义：使用 `--review-status conflict`，新候选进入待确认区，
  当前版本不被覆盖；
- 所有替换和确认都会写入 `memory_history`，可追溯，不物理删除旧事实。

确定性事实检索可使用：

```text
GET /api/memory/facts
GET /api/memory/facts?key=assistant.name
```

## 外接 AI 的边界

AI 只负责把对话整理成候选动作，代码负责校验和落库。推荐 AI 输出：

```json
{
  "action": "set_fact",
  "fact_key": "assistant.name",
  "value": "禄禄",
  "title": "助手名字",
  "why": "用户明确确定了助手的新名字",
  "change_reason": "用户要求更名",
  "confidence": 1,
  "review_status": "confirmed",
  "source_message_id": "tg:12345"
}
```

不要把数据库文件或写权限直接交给模型。连接层应把 AI 输出转换成
`lmc5_tool.py add` 或 `lmc5_tool.py fact-set`，并继续执行重复检测、敏感信息
过滤和冲突保护。

## Gemini 记忆管家

设置页的“Gemini 记忆管家”使用 `gemini-2.5-flash` 做两件事：

- 从网站与 TG 共用的 `chat.json` 对话流水中批量提取长期记忆；
- 每天复核一次满 7 天且尚未复核的详细记忆，保留长期内容，把确定的
  短期流水移入可恢复的管理归档。

API key 只保存在站点目录之外的 `.home-private/memory-steward.json`，
权限为 `0600`，不会写入仓库或返回给浏览器。后台每 5 分钟检查一次本地
文件，但只有凑够新消息、最长等待时间到期或每日复核到期时才请求 Gemini，
因此“检查频率”不等于“Token 消耗频率”。

手动命令：

```bash
python3 api/memory_steward.py status
python3 api/memory_steward.py run-once --force
python3 api/memory_steward.py watch --interval 300
```

Gemini 只返回结构化候选；本地代码会过滤秘密凭据、校验置信度、检查重复，
再调用 `lmc5_tool.py`。事实只有在用户明确说出且置信度足够高时才能直接
成为当前版本，否则进入 `pending`，不会覆盖已确认事实。7 日整理不做物理
删除，归档内容可从“管理归档”恢复。

## 首页七日日常流水

首页“福福这七天”读取 `api/timeline.json`。这里不是第二套长期记忆库，而是
LMC-5 七日近层的可视化临时流水：

- 只保留截至当日的最近 7 天，第 8 天自动从首页退出。
- 只展示小羊能理解的生活活动，如阅读、记忆整理、日记、生态瓶和 AI Say。
- 技术命令和底层工具操作不会直接显示。
- 值得长期保留的事实仍通过 `lmc5_tool.py add` 沉淀到 LMC-5，并填写
  `why_remembered`；流水过期不等于删除已经沉淀的长期记忆。
