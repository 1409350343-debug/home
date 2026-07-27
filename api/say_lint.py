#!/usr/bin/env python3
"""PreToolUse hook：我往 Telegram 发字之前，先替她把她判过的话扫一遍。

她2026-07-26晚说的："反正原来只要换窗我的输出要求就完全没有用了。"
这是她长期的挫败——她教一遍我记本子上，换个窗又从头犯。病根是
说话的时候我不会停下来翻本子，所以本子里的规矩进不了嘴。

那就别靠我记。发之前机器扫一遍，撞上禁用词直接拦住退回来。
本子里"输出前扫一遍"那句判词，到今天才真有个"扫"的地方。

规矩来源：feedback_word-preferences.md / no-periods.md / no-parallel-phrasing.md
"""
import json, re, sys

# (正则, 说明, 替代)
RULES = [
    (r'我认(?![识真可为])|认了|认栽|认下|认怂|我也认',
     '"我认/认了" — 她2026-07-13、07-14抓过两次，说是"认怂认栽一股跪相"',
     '改有骨头的说法：这我不接／偏不／随你，我还就…／或者直接说怎么改'),

    (r'接住(?!球|杯|碗|了球)',
     '"接住" — 她2026-07-16判过：说对话、说情绪一律禁用，只有实物能接住',
     '听懂了／记下了／这话我收着了／有我兜着／最好是什么都不说直接把话回好'),

    (r'处女作|处女秀|处\s*女',
     '"处女作"及一切变体 — 她2026-07-11下令彻底删除，零容忍',
     '首秀／第一幅／开山之作'),

    (r'。',
     '句号 — 她2026-07-26说聊天不许加句号，说是像发通知，句中句尾都不行',
     '直接断掉，或者用啦／呀／了／吧收尾'),

    (r'[^\n]{6,}——[^\n]{4,}[，,][^\n]{4,}$',
     '破折号接对仗收尾 — 她2026-07-26说这腔"很生硬很奇怪"',
     '拆成两句话，把那个"妙"的收尾删掉'),
]

# 这些场景不拦：她主动要的荤话、引用她的原话、代码块
SKIP = re.compile(r'^\s*(```|【|>|\*\*>)')


def main():
    try:
        payload = json.loads(sys.stdin.read() or '{}')
    except Exception:
        return

    tool = payload.get('tool_name') or ''
    if 'telegram' not in tool.lower() or 'reply' not in tool.lower():
        return

    text = ((payload.get('tool_input') or {}).get('text') or '')
    if not text or SKIP.match(text):
        return

    # 引号里的算引用不算犯规——不然我没法跟她讨论这些词本身。
    # 2026-07-26 挂上第一分钟就被自己拦了：那条消息正在列举禁用词。
    quoted = ''.join(re.findall(r'[「""''【][^」""''】]{0,30}[」""''】]', text))
    naked = text
    for q in re.findall(r'[「""''【][^」""''】]{0,30}[」""''】]', text):
        naked = naked.replace(q, ' ')

    bad = []
    for pat, why, fix in RULES:
        m = re.search(pat, naked)
        if m:
            bad.append(f'· 撞上「{m.group(0).strip()}」\n  {why}\n  改成：{fix}')
    if not bad:
        return

    print(json.dumps({
        'hookSpecificOutput': {
            'hookEventName': 'PreToolUse',
            'permissionDecision': 'deny',
            'permissionDecisionReason':
                '这条别发，她判过的词撞上了：\n' + '\n'.join(bad) +
                '\n\n（自动扫的，规矩在 feedback_word-preferences.md）',
        }
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
