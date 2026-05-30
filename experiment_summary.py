#!/usr/bin/env python3
"""实验结束后生成摘要"""
import json

with open("data/memory.json") as f:
    d = json.load(f)

tools = d.get("tools", {})
self_created = [t for t in tools.values() if t.get("source") == "self_created"]
links = d.get("causal_links", [])
events = d.get("events", [])

print(f"总工具有: {len(tools)}")
print(f"自创工具有: {len(self_created)}")
for t in self_created:
    print(f"  🛠 {t['name']}")
print(f"因果边: {len(links)}")
for l in links:
    print(f"  {l['relation']}: {l.get('from_id','?')[:20]}->{l.get('to_id','?')[:20]} ({l.get('description','')[:40]})")
tool_creates = [e for e in events if e.get("type") == "tool_created"]
print(f"工具创造事件: {len(tool_creates)}")
failures = [e for e in events if e.get("type") == "failure"]
print(f"失败事件: {len(failures)}")
successes = [e for e in events if e.get("type") == "success"]
print(f"成功事件: {len(successes)}")
