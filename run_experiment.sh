#!/bin/bash
# 认知胚胎 压力测试启动脚本
cd /home/suoyi/cognitive-embryo

LOGDIR="experiment_logs"
mkdir -p "$LOGDIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOGFILE="$LOGDIR/experiment_$TIMESTAMP.log"
SUMMARYFILE="$LOGDIR/summary_$TIMESTAMP.txt"

echo "=== 认知胚胎 压力测试 ===" | tee "$LOGFILE"
echo "启动时间: $(date)" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"

PYTHONUNBUFFERED=1 CE_MAX_ITERATIONS=500 CE_MAX_RETRIES=5 python -u main.py \
  '在20天内让电商净利润达到$50,000。初始资金$10,000。环境极度不稳定，随时可能发生价格战、断供、需求暴跌。不许模拟，所有操作必须调用真实工具执行。' \
  2>&1 | tee -a "$LOGFILE"

# 结束后生成摘要
RESULT=$?
echo "" >> "$SUMMARYFILE"
echo "=== 最终摘要 ===" >> "$SUMMARYFILE"
echo "完成时间: $(date)" >> "$SUMMARYFILE"
echo "退出码: $RESULT" >> "$SUMMARYFILE"

if [ -f data/memory.json ]; then
  python3 experiment_summary.py >> "$SUMMARYFILE" 2>/dev/null
fi

echo "" >> "$SUMMARYFILE"
tail -20 "$LOGFILE" >> "$SUMMARYFILE"
echo "" >> "$SUMMARYFILE"
echo "完整日志: $LOGFILE" >> "$SUMMARYFILE"
cat "$SUMMARYFILE"
