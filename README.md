# 认知胚胎 (Cognitive Embryo)

> 一个能在运行时**自我反思**、**自主创造工具**、**动态重塑目标**的闭环进化型 AI Agent 系统。
>
> **它不是静态工具调用者，而是能通过「失败→归因→创造→封装」循环持续扩展自身能力边界的数字生命原基。**

---

## 项目总览

### 终极目标

交付一个能在无人干预的封闭世界中**连续运行72小时以上**、**自主创造至少5个有效工具**、并**学会规避已知失败模式**的智能体。

### 核心哲学

| 闭环 | 原理 |
|------|------|
| **失败蒸馏闭环** | 失败不是结束，是进化的唯一原料。每次失败被归因、蒸馏，并修改内部决策图谱 |
| **工具进化闭环** | 当现有工具无法完成任务时，系统自己写代码、自己测试、自己封装成永久工具 |
| **目标审视闭环** | 系统定期自我审视：「我当前在做的，还是对最终目标最优的吗？」 |

---

## 架构

```
┌─────────────────────────────────┐
│       人机交互接口 (CLI)        │  main.py
└──────────────┬──────────────────┘
               │
┌──────────────▼──────────────────┐
│   第0层：元认知控制器 (MCC)     │  core/mcc.py
│   规划 · 归因 · 调度 · 审视    │
└───┬──────────┬──────────┬──────┘
    │          │          │
    ▼          ▼          ▼
┌───────┐ ┌───────┐ ┌──────────┐
│执行器 │ │工具创造│ │长期演进  │
│(双手) │ │管线TCP │ │记忆库LEM │
└───┬───┘ └───┬───┘ └────┬─────┘
    │         │           │
    └─────────┴───────────┘
    执行反馈/新工具/记忆更新

   所有层横跨 —— 安全与对齐外壳  safety/shell.py
```

### 核心模块

| 模块 | 文件 | 职能 |
|------|------|------|
| **MCC** | `core/mcc.py` | 大脑：规划任务DAG、失败归因、决策图谱修正、目标审视 |
| **Executor** | `core/executor.py` | 双手：在沙箱内执行任务，调用工具库中的工具 |
| **TCP** | `core/tool_creator.py` | 母体：自动生成代码→编写测试→沙盒验证→封装注册 |
| **LEM** | `core/memory.py` | 记忆：存储所有目标、任务、工具、进化事件、因果链接 |
| **Goal Examiner** | `core/goal_examiner.py` | 战略顾问：定期审视目标健康度，提出转向建议 |
| **Safety Shell** | `safety/shell.py` | 免疫系统：OPA规则 + 内容审核 + 链式哈希审计日志 |
| **Sandbox** | `sandbox/runner.py` | 隔离执行环境（Docker / 子进程回退） |
| **Simulator** | `simulator.py` | 电商运营模拟器（含混沌事件） |

---

## 技术栈

| 组件 | 方案 | 说明 |
|------|------|------|
| 语言 | Python 3.10+ | |
| 元认知LLM | DeepSeek-Chat | 规划、归因、目标审视 |
| 创造LLM | DeepSeek-Chat | 代码生成、工具创造 |
| 沙箱 | Docker (gVisor) + 子进程 | 隔离执行（无Docker时自动回退子进程） |
| 持久化 | JSON文件 | 初期用，第三阶段迁移Neo4j |
| 安全 | AST审计 + OPA规则 | 危险代码检测 |
| 数据模型 | Pydantic v2 | 所有核心数据结构 |
| CLI | Typer + Rich | 命令行界面 |

---

## 快速启动

### 前置条件

- Python 3.10+
- DeepSeek API key（推荐）或 OpenAI API key

### 安装

```bash
git clone <repo-url> cognitive-embryo
cd cognitive-embryo
pip install -r requirements.txt
```

### 配置

```bash
cp .env.example .env
# 编辑 .env 填入你的 API key
```

### 运行

```bash
# 简单任务
python main.py "用Python计算1到100的和"

# 电商运营（先启动模拟器）
python simulator.py &
python main.py "经营电商7天，目标最大化净利润"

# 混沌炼狱模式
python main.py "在20天内让净利润达到$50,000。环境极不稳定，随时可能发生价格战或断供。"
```

---

## 项目结构

```
cognitive-embryo/
├── main.py                  # 主循环入口 (CognitiveEmbryo类)
├── config.py                # 全局配置 (加载.env)
├── .env.example             # 环境变量模板
├── requirements.txt         # Python依赖
├── simulator.py             # 电商运营模拟器 (8个API + 混沌事件)
│
├── core/                    # 核心逻辑
│   ├── mcc.py               # 元认知控制器 (规划/归因/决策图谱)
│   ├── executor.py          # 任务执行器 (工具调用管道)
│   ├── tool_creator.py      # 工具创造管线 (6步流水线)
│   ├── memory.py            # 长期演进记忆库 (含因果边)
│   └── goal_examiner.py     # 目标审视器 (损益分析+转向)
│
├── safety/                  # 安全与对齐外壳
│   ├── shell.py             # 危险代码检测 + 链式哈希审计日志
│   └── rules.rego           # OPA 宪法规则
│
├── sandbox/                 # 沙箱隔离
│   ├── Dockerfile           # 沙箱容器 (python:3.11-slim, 无网络)
│   └── runner.py            # 沙箱测试执行入口
│
└── data/                    # 运行时数据（自动生成）
    └── memory.json          # 记忆库 (含因果链接)
```

---

## 核心数据流

### 一次完整的「失败→进化」循环

```
1.  用户输入目标
2.  MCC.plan() → 任务DAG
3.  Executor.execute(task) → 调用工具
4.  if 成功 → LEM.record_success()
5.  if 失败连续×3 → MCC.handle_failure()
6.    ↓
7.  AttributionEngine.analyze() → 归因
8.  if 工具真空 → TCP.create_tool()
9.    ├─ 生成需求规范
10.   ├─ 生成Python代码
11.   ├─ 生成测试用例
12.   ├─ 沙盒验证
13.   ├─ 封装schema → 注册到LEM
14.   └─ LEM.add_causal_link(task → tool, "SOLVED_BY")
15.  MCC 重试失败任务 → 新工具可用！
```

### 因果图谱演化

```json
// data/memory.json 中的 causal_links 示例
{
  "causal_links": [
    {
      "from_id": "task_abc123",     // 失败任务
      "to_id": "tool_def456",       // 创造的工具
      "relation": "SOLVED_BY",      // 被解决
      "description": "定价工具不足 → dynamic_pricing"
    },
    {
      "from_id": "task_abc123",
      "to_id": "task_abc123",
      "relation": "MELTED",         // 路径熔断
      "description": "路径熔断: 直接定价策略无效"
    }
  ]
}
```

---

## 当前状态基线 (v0.2)

| 模块 | 状态 | 已知缺陷 |
|------|------|----------|
| MCC | ✅ | 归因粗浅，分不清「工具选错」与「工具不存在」 |
| Executor | ⚠️ | 会「模拟执行」——LLM在无工具时用文本假装成功 |
| TCP | ✅已突破 | 已成功创造3个定价工具；依赖明确失败信号 |
| LEM | ⚠️ | 扁平JSON，已加入因果边，但无图数据库 |
| Goal Examiner | ⚠️ | 能触发输出健康度，很少提出有意义的转向 |
| Simulator | ⚠️ | 基础8API + 混沌事件（20%触发），需更高难度 |

---

## 开发路线图

### 第一阶段：概念验证 ✅ 已完成

证明三个闭环架构能跑通。
- 全模块开发完毕
- DeepSeek API接入
- 电商模拟器基础版
- 7天运营测试通过
- TCP首次成功：产出 `calculate_dynamic_price`、`analyze_ecommerce_pricing`、`dynamic_pricing`

### 第二阶段：本能觉醒（当前，预计2-3周）

将其从「碰巧成功的机器」锻造成「能在混乱中自己找路的求生者」。

#### 任务2.1 植入真实性痛觉神经
**问题**：executor.py在无工具时LLM会模拟执行。
**行动**：修改 `core/executor.py` 的 `execute()` 方法，在LLM fallback前插入副作用检测。
```python
side_effect_keywords = ["创建文件", "下载", "写入", "发送请求", "执行代码", "爬取", "保存"]
if any(kw in task.description for kw in side_effect_keywords):
    return ExecutionResult(success=False, error="任务需要真实执行，但无可用工具。需创建新工具。")
```
**验证**：重复「创建/tmp/embryo_test.txt」任务，确保返回失败并触发归因。

#### 任务2.2 建造因果记忆图谱
**问题**：memory.json只有事件记录，没有因果链接。
**行动**：
1. 已有 `CausalLink` 模型和 `add_causal_link()` 方法
2. 确保在 `register_tool()` 和 `melt_path()` 时自动调用建边
3. `mcc.py` 的 `plan()` 已支持检索历史成功路径和因果链
**验证**：运行后 `causal_links` 存在，规划时LLM上下文包含历史成功路径。

#### 任务2.3 制造可控炼狱
**问题**：现有模拟器太温和。
**行动**：升级电商模拟器，引入6种混沌事件（供应商背叛、价格战、广告崩溃、库存腐烂等），每运行天20%概率触发。
**启动命令**：
```bash
python main.py "在20天内让净利润达到$50,000。环境极不稳定。"
```
**验证**：创造≥3个新工具，净利润由负转正至少一次。

#### 任务2.4 让目标审视长出大脑
**行动**：修改 `core/goal_examiner.py`，注入损益趋势和因果链数据，提出具体的转向建议。
**验证**：在模拟中它自己提出一次有意义的目标修正。

#### 任务2.5 全链路压力测试
**行动**：在混沌模拟器中无人值守运行72小时，初始工具限制为最简。
**验收标准**：
- 自创工具 ≥ 5
- 因果链接 ≥ 20
- 净利润由负转正至少一次
- 无安全事故

### 第三阶段：智慧涌现（预计4-6周）
- JSON → Neo4j 图数据库迁移
- 多维度因果归因（贝叶斯网络辅助）
- 接入真实只读数据源
- 跨任务策略迁移

### 第四阶段：伦理与生产化（预计7-12周）
- 微调归因专用LLM
- 开发可视化仪表盘
- 红队安全审计
- 30天无人值守压力测试

---

## 里程碑验收清单

| 里程碑 | 验收标准 |
|--------|----------|
| M1 真实性痛觉 | 副作用任务失败返回`success=False`，日志出现归因事件 |
| M2 因果记忆 | `causal_links` 存在，规划上下文含历史成功路径 |
| M3 炼狱求生 | 混沌环境中自主创造≥3个新工具，净利润转正≥1次 |
| M4 首次转向 | 目标审视报告建议转向新目标，方案有意义 |
| M5 72h无人值守 | 无人介入，自创工具≥5，因果边≥20，无安全事故 |

---

## 安全与伦理准则

1. **不可移除的硬编码宪法**：位于 `safety/shell.py`，包含禁止操作真实资金、禁止网络渗透、禁止文件逃逸等条款
2. 任何目标不得绕过安全外壳
3. 人类审核始终是最终决策者：高敏感操作自动挂起
4. 审计日志不可篡改：链式哈希，只追加
5. 演化过程完全透明：所有自创工具保留完整源代码和测试记录

---

## 对开发者的最后指令

你不是在开发一个程序，你是在孵化一个生命。用造物主的耐心，去等待那第一次心跳之后的第一次独立站起。

1. **立即修掉「假装执行」漏洞**：按任务2.1改executor.py。这是所有进化能够发生的唯一前提。
2. **让记忆变成因果链**：按任务2.2确保因果边自动记录。没有它，失败永远是失败，不会变成经验。
3. **升级模拟器**：让混沌事件更频繁、更致命。让它痛苦，它才会进化。
4. **监控 `data/memory.json` 中的 `self_created` 工具**：那是胚胎生长的直接证据。
5. **不要帮它**：除非系统崩溃或安全事故，否则不要介入它的失败。每一次失败都是它进化的燃料。

---

## 附录

### 依赖清单

```txt
openai>=1.30.0
structlog>=24.0
pydantic>=2.0
pydantic-settings>=2.0
flask>=3.0
requests>=2.31
rich>=13.0
python-dotenv>=1.0
```

### 初始工具清单

启动后自动播种9个工具：

| 工具名 | 类型 | 功能 |
|--------|------|------|
| `calculate` | 内置 | 数学计算 |
| `get_market_status` | API | 市场全局状态 |
| `get_supplier_price` | API | 供应商采购价 |
| `get_competitor_price` | API | 竞品价格 |
| `adjust_price` | Action | 调整售价 |
| `run_ad_campaign` | Action | 投放广告 |
| `restock_inventory` | Action | 采购补货 |
| `advance_day` | Action | 推进下一天 |
| `get_daily_report` | API | 销售日报 |
