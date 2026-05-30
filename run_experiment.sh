#!/bin/bash
# 认知胚胎 压力测试启动脚本
cd /home/suoyi/cognitive-embryo

LOGDIR="experiment_logs"
mkdir -p "$LOGDIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOGFILE="$LOGDIR/experiment_$TIMESTAMP.log"
SUMMARYFILE="$LOGDIR/summary_$TIMESTAMP.txt"

echo "=== 认知胚胎 压力测试 ===" | tee -a "$LOGFILE"
echo "启动时间: $(date)" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"

PYTHONUNBUFFERED=1 CE_MAX_ITERATIONS=500 CE_MAX_RETRIES=5 python -u main.py \
  '在20天内让电商净利润达到$50,000。初始资金$10,000。环境极度不稳定，随时可能发生价格战、断供、需求暴跌。不许模拟，所有操作必须调用真实工具执行。' \
  2>&1 | tee -a "$LOGFILE"

# 结束后生成摘要
echo "" >> "$SUMMARYFILE"
echo "=== 最终摘要 ===" >> "$SUMMARYFILE"
echo "完成时间: $(date)" >> "$SUMMARYFILE"

if [ -f data/memory.json ]; then
  python3 -c "
import json
with open('data/memory.json') as f:
    d = json.load(f)
tools = d.get('tools', {})
self_created = [t for t in tools.values() if t.get('source') == 'self_created']
links = d.get('causal_links', [])
print(f'总工具有: {len(tools)}')
print(f'自创工具有: {len(self_created)}')
for t in self_created:
    print(f'  🛠 {t[\"name\"]}')
print(f'因果边: {len(links)}')
for l in links:
    print(f'  {l[\"relation\"]}: {l.get(\"from_id\",\"?\")[:20]}→{l.get(\"to_id\",\"?\")[:20]} ({l.get(\"description\",\"\")[:40]})')
events = d.get('events', [])
tool_creates = [e for e in events if e.get('type')=='tool_created']
print(f'工具创造事件: {len(tool_creates)}')
failures = [e for e in events if e.get('type')=='failure']
print(f'失败事件: {len(failures)}')
successes = [e for e in events if e.get('type')=='success']
print(f'成功事件: {len(successes)}')
" 2>/dev/null >> "$SUMMARYFILE"

echo "" >> "$SUMMARYFILE"
tail -20 "$LOGFILE" >> "$SUMMARYFILE"
echo "" >> "$SUMMARYFILE"
echo "完整日志: $LOGFILE" >> "$SUMMARYFILE"
cat "$SUMMARYFILE"
