"""记忆系统的集中路径配置。

默认值根据本仓库所在位置计算；部署时可用环境变量覆盖，不再要求代码
必须位于 /var/www/home。这里仅定义结构，不预设任何记忆分类内容。
"""
import os
from pathlib import Path


APP_ROOT = Path(
    os.environ.get("HOME_APP_ROOT", Path(__file__).resolve().parent.parent)
).expanduser()
API_DIR = APP_ROOT / "api"

LMC5_DB = Path(
    os.environ.get("HOME_MEMORY_DB", API_DIR / "lmc5_memory.db")
).expanduser()
LMC5_SRC = Path(
    os.environ.get("LMC5_SRC", "/root/lmc-5/src")
).expanduser()
LMC5_TOOL = API_DIR / "lmc5_tool.py"

BRAIN_DATA = Path(
    os.environ.get("HOME_BRAIN_DATA", APP_ROOT / "brain-data.json")
).expanduser()
RECALL_LOG = Path(
    os.environ.get("HOME_RECALL_LOG", APP_ROOT / "data" / "recall_hook.log")
).expanduser()
RECALL_EXPLORE_STATE = Path(
    os.environ.get(
        "HOME_RECALL_EXPLORE_STATE",
        APP_ROOT / "data" / "recall_explore.json",
    )
).expanduser()
MEMORY_API_TOKEN = os.environ.get("HOME_MEMORY_API_TOKEN", "").strip()

_default_memory_dirs = (
    "/root/.claude/projects/-var-www-home-api/memory:"
    "/root/.claude/projects/-root/memory"
)
MEMORY_NOTE_DIRS = [
    Path(item).expanduser()
    for item in os.environ.get("HOME_MEMORY_NOTE_DIRS", _default_memory_dirs).split(":")
    if item
]

_default_lifelines = (
    "/root/.claude/projects/-var-www-home-api/memory/lifeline.md:"
    "/root/.claude/projects/-root/memory/lifeline.md"
)
CANONICAL_LIFELINE = Path(
    os.environ.get(
        "HOME_LIFELINE_FILE",
        "/root/.claude/projects/-var-www-home-api/memory/lifeline.md",
    )
).expanduser()
_lifeline_candidates = [
    CANONICAL_LIFELINE,
    *[
    Path(item).expanduser()
    for item in os.environ.get("HOME_LIFELINE_FILES", _default_lifelines).split(":")
    if item
    ],
]
LIFELINE_CANDIDATES = list(dict.fromkeys(_lifeline_candidates))
