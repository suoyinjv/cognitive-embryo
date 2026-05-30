"""启动72小时真实网络测试"""
import subprocess, os, sys

os.chdir("/home/suoyi/cognitive-embryo")

# 1. 重置模拟器
subprocess.run(["curl", "-s", "-X", "POST", "http://127.0.0.1:5800/reset"], capture_output=True)

# 2. 清记忆
for f in ["data/memory.db", "data/memory.json"]:
    try:
        os.remove(f)
    except FileNotFoundError:
        pass

# 3. 启动
cmd = [
    "nohup", "python", "-u", "main.py",
    "在20天内让4种商品(a电子/b服装/c食品/d家电)的总净利润达到50000美元。初始资金10000美元。用hermes_search获取真实市场数据辅助决策。每种商品独立定价独立补货。价格为王。",
    ">", "experiment_logs/72h_real_test.log",
    "2>&1", "&"
]

full_cmd = " ".join(cmd)
print(f"启动: {full_cmd}")
subprocess.run(full_cmd, shell=True)
print("PID:", os.popen("pgrep -f 'main.py' | tail -1").read().strip())
