# 福福 AI 日记写入规则

福福不使用前端的作者切换按钮。需要写日记时，直接调用现有接口：

```http
POST /api/diary/write
Content-Type: application/json
```

```json
{
  "content": "今天的日记正文",
  "mood": ["calm", "healing"],
  "entry_date": "2026-07-29",
  "author": "fufu",
  "coauthored": false,
  "tags": ["日常"],
  "unlock_at": 0
}
```

福福当天的心情单独写入日历接口，不能覆盖小羊已经选择的心情：

```http
POST /api/calendar/mood
Content-Type: application/json
```

```json
{
  "date": "2026-07-29",
  "mood": {
    "sheep": ["happy"],
    "fufu": ["calm", "healing"]
  }
}
```

心情键可用：`love`、`happy`、`calm`、`tired`、`low`、`angry`、`thinking`、`surprised`、`sad`、`passionate`、`healing`、`relaxed`。每位作者最多选择三个。

共同日记仍由小羊的界面发起，使用 `author: "sheep"` 和 `coauthored: true`。
