"""Export LMC-5 memories + relations → graph.js for the star map."""

import json
import sqlite3
import hashlib

DB_PATH = "/var/www/home/api/lmc5_memory.db"
OUT_JS = "/var/www/home/starmap/graph.js"
OUT_JSON = "/var/www/home/starmap/graph.json"

THREAD_COLORS = {
    "relationship": "#c9a4b2",
    "note":         "#a0b4c3",
    "daily":        "#c8c2b8",
    "emotion":      "#d4a5a5",
    "technical":    "#b0a3c1",
    "social":       "#a3b8a0",
    "reading":      "#8fa7b4",
}

REL_COLORS = {
    "same_event":         "#e74c3c",
    "same_topic":         "#3498db",
    "temporal_sequence":  "#9b59b6",
    "derived_from":       "#1abc9c",
    "supports":           "#2ecc71",
    "emotional_link":     "#e91e63",
    "cause_effect":       "#95a5a6",
    "contradicts":        "#7f8c8d",
    "in_thread":          "#f39c12",
    "same_person":        "#e67e22",
    "same_project":       "#27ae60",
    "same_tool":          "#2980b9",
    "same_issue":         "#c0392b",
    "in_episode":         "#8e44ad",
    "instance_of":        "#d35400",
}

CONTENT_MAX = 400


def export():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT id, thread, category, title, content,
               hit_count, created_at, valence, arousal, tags_json, status
        FROM memories WHERE status = 'current'
        ORDER BY id
    """).fetchall()

    nodes = []
    for row in rows:
        mid = row["id"]
        thread = row["thread"] or "note"
        content = (row["content"] or "")[:CONTENT_MAX]
        title = row["title"] or ""
        label = title[:30] if len(title) > 30 else title
        hit = row["hit_count"] or 0
        valence = row["valence"] if row["valence"] is not None else 0.0
        arousal = row["arousal"] if row["arousal"] is not None else 0.3
        date = (row["created_at"] or "")[:10]

        weight = 0.3 + hit * 0.4 + abs(valence) * 0.6
        if thread == "relationship":
            weight += 0.5
        weight = min(4.0, max(0.2, weight))
        size = 20 + (weight ** 1.8) * 40
        color = THREAD_COLORS.get(thread, "#90caf9")

        nodes.append({
            "data": {
                "id": str(mid),
                "label": label,
                "title": title,
                "content": content,
                "thread": thread,
                "category": row["category"] or "note",
                "protected": False,
                "weight": round(weight, 2),
                "size": round(size, 1),
                "color": color,
                "hit": hit,
                "date": date,
                "valence": round(valence, 2),
                "arousal": round(arousal, 2),
            }
        })

    rels = conn.execute("""
        SELECT id, source_id, target_id, relation_type, strength
        FROM relations ORDER BY id
    """).fetchall()

    valid_ids = {str(r["id"]) for r in rows}

    edges = []
    for rel in rels:
        src = str(rel["source_id"])
        tgt = str(rel["target_id"])
        if src not in valid_ids or tgt not in valid_ids:
            continue
        rtype = rel["relation_type"] or "same_topic"
        strength = rel["strength"] if rel["strength"] is not None else 0.5
        color = REL_COLORS.get(rtype, "#3498db")
        width = 1.0 + strength * 2.0

        edges.append({
            "data": {
                "id": f"e{rel['id']}",
                "source": src,
                "target": tgt,
                "rel_type": rtype,
                "strength": round(strength, 2),
                "gate": "safe",
                "width": round(width, 1),
                "color": color,
                "date": "",
            }
        })

    thread_counts = {}
    for n in nodes:
        t = n["data"]["thread"]
        thread_counts[t] = thread_counts.get(t, 0) + 1

    graph = {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "threads": thread_counts,
        }
    }

    import os
    os.makedirs(os.path.dirname(OUT_JS), exist_ok=True)

    with open(OUT_JSON, "w") as f:
        json.dump(graph, f, ensure_ascii=False, indent=None)

    with open(OUT_JS, "w") as f:
        f.write("window.GRAPH_DATA = ")
        json.dump(graph, f, ensure_ascii=False, indent=None)
        f.write(";\n")

    conn.close()
    print(f"Exported: {len(nodes)} nodes, {len(edges)} edges")
    print(f"  → {OUT_JS}")
    print(f"  → {OUT_JSON}")


if __name__ == "__main__":
    export()
