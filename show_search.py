"""展示hermes_search的搜索结果"""
import sqlite3
import json

conn = sqlite3.connect("/home/suoyi/cognitive-embryo/data/memory.db")

# 找任务节点
cur = conn.execute("SELECT id, data FROM nodes WHERE type='task' ORDER BY rowid")
for row in cur:
    d = json.loads(row[0])
    desc = d.get("description", "")
    if "hermes_search" in desc or "搜索" in desc:
        result = d.get("result")
        if result:
            print(f"任务: {desc[:80]}")
            print(f"结果: {str(result)[:600]}")
            print()

# 找工具调用记录
cur2 = conn.execute("SELECT data FROM edges WHERE relation='SOLVED_BY' ORDER BY rowid DESC LIMIT 5")
for row in cur2:
    d = json.loads(row[0])
    print(f"因果边: {d.get('description', '')[:80]}")

conn.close()
