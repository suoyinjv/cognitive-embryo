"""元认知控制器 — 规划/归因/调度"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from openai import AsyncOpenAI
from structlog import get_logger

from config import config
from core.memory import EvolutionMemory, Task

logger = get_logger(__name__)


# ── 枚举 ──

class FailureRootCause(str, Enum):
    TOOL_INADEQUATE = "tool_inadequate"    # 工具能力真空
    STRATEGY_FLAWED = "strategy_flawed"    # 策略路径错误
    ENVIRONMENT_SHIFT = "environment_shift"  # 环境突变


@dataclass
class FailureDecision:
    action: str  # create_tool | skip | replan
    tool_spec: Optional[dict] = None
    reason: str = ""


# ── 任务 DAG ──

class TaskDAG:
    """有向无环图 — 任务依赖管理"""

    def __init__(self, tasks: list[Task], edges: list[tuple[str, str]]) -> None:
        self.tasks: dict[str, Task] = {t.id: t for t in tasks}
        self.edges = edges  # (from_id, to_id)
        self.status: dict[str, str] = {t.id: "ready" for t in tasks}

        # 计算入度、出度
        self.in_degree: dict[str, int] = defaultdict(int)
        self.dependents: dict[str, list[str]] = defaultdict(list)
        for src, dst in edges:
            self.in_degree[dst] += 1
            self.dependents[src].append(dst)

        # 初始状态：有依赖的任务标记为 waiting
        for tid, deg in self.in_degree.items():
            if deg > 0 and tid in self.status:
                self.status[tid] = "waiting"

    def get_next_ready(self) -> Optional[Task]:
        for tid, st in self.status.items():
            if st == "ready":
                deps_met = all(
                    self.status.get(e[0]) == "complete"
                    for e in self.edges if e[1] == tid
                )
                if deps_met:
                    self.status[tid] = "running"
                    return self.tasks[tid]
        return None

    def mark_complete(self, task_id: str, result: object) -> None:
        self.status[task_id] = "complete"
        # 解锁依赖此任务的后续任务
        for dep in self.dependents.get(task_id, []):
            if self.status.get(dep) == "waiting":
                deps_met = all(
                    self.status.get(e[0]) == "complete"
                    for e in self.edges if e[1] == dep
                )
                if deps_met:
                    self.status[dep] = "ready"

    def mark_blocked(self, task_id: str, reason: str = "") -> None:
        self.status[task_id] = "blocked"

    def mark_skip(self, task_id: str, reason: str = "") -> None:
        self.status[task_id] = "skipped"

    def mark_failed(self, task_id: str) -> None:
        self.status[task_id] = "failed"

    def retry_task(self, task_id: str) -> None:
        self.status[task_id] = "ready"

    @property
    def all_done(self) -> bool:
        return all(s in ("complete", "blocked", "skipped") for s in self.status.values())

    def summary(self) -> str:
        counts = defaultdict(int)
        for s in self.status.values():
            counts[s] += 1
        return ", ".join(f"{k}={v}" for k, v in counts.items())


# ── 规划 Prompt ──

PLAN_SYSTEM = """你是任务规划器。将目标分解为子任务 DAG。

规则:
1. 每个子任务单一职责、可验证
2. 明确依赖关系
3. 运行的模拟器中时间需要推进

可用工具列表:

【定价策略铁律】
1. 售价必须接近竞品均价（competitor_price），不得高于竞品价50%以上
2. 合理售价 = max(供应商价×1.15, 竞品价×0.9) ~ 竞品价×1.1
3. 如果当前售价远高于竞品均价，必须立即降价到竞品附近
4. 如果售价太低（低于供应商价×1.15），必须上调到至少供应商价×1.15
- get_supplier_price: 查询供应商价格
- get_competitor_price: 查询竞品价格
- adjust_price: 调整售价
- run_ad_campaign: 投放广告
- restock_inventory: 采购补货
- advance_day: 推进到下一天（每天结束时必须调用！）
- get_daily_report: 获取累计销售报告
- calculate: 执行数学计算

【强制执行规则】
- 每轮规划必须包含至少一个「动作型」任务：adjust_price / restock_inventory / run_ad_campaign
- 纯分析/计算/评估任务不调任何工具 = 空转！禁止单独的分析类任务
- advance_day 每日规划必须包含1次
- 每个任务都必须明确指定 tools_needed 字段列明需要调用的工具名
- 定价策略铁律: 售价必须接近竞品均价，如果当前售价远高于竞品价必须立即降价。合理售价区间 = 供应商价×1.15 ~ 竞品价×1.1
- 输出 JSON:
{
  "tasks": [
    {
      "id": "task_<desc>",
      "type": "execute",
      "description": "具体任务描述（必须包含调用的工具名）",
      "depends_on": [],
      "tools_needed": ["工具名"]
    }
  ]
}"""

ATTRIBUTION_SYSTEM = """你是失败归因引擎。分析失败根因。

判定标准:
- tool_inadequate: 工具无法完成任务 → 创造新工具
- strategy_flawed: 策略/参数错误 → 熔断路径
- environment_shift: 外部环境变化 → 等待

只返回分类: tool_inadequate / strategy_flawed / environment_shift"""

# ── 元认知控制器 ──

class MetaCognitionController:
    """元认知控制器 — 规划 + 归因"""

    def __init__(self, memory: EvolutionMemory, executor=None) -> None:
        self.memory = memory
        self.executor = executor
        self._llm = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self._model = config.model
        self.failure_counts: dict[str, int] = defaultdict(int)

    async def plan(self, goal: str) -> TaskDAG:
        """目标 → 任务 DAG"""
        # 查询历史成功路径 + 因果链
        similar = self.memory.query_similar_goals(goal, top_k=3)
        solved = self.memory.query_solved_by(goal)
        melted = self.memory.query_melted_paths()
        context = ""
        if similar:
            paths = "\n".join(
                f"- {s['goal'][:60]}: {' → '.join(s['success_path'][:3])}"
                for s in similar
            )
            context += f"\n历史成功路径:\n{paths}\n"
        if solved:
            context += "\n历史解决方案(因果链):\n" + "\n".join(
                f"- 问题: {s['problem']} → 工具: {s['solution_tool']}"
                for s in solved[:3]
            ) + "\n"
        if melted:
            context += "\n已失效路径(规避以下方式):\n" + "\n".join(
                f"- {m}" for m in melted[:3]
            ) + "\n"

        prompt = f"目标: {goal}{context}"
        resp = await self._llm.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": PLAN_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
        )

        tasks, edges = self._parse_plan(resp.choices[0].message.content or "", goal)
        logger.info("mcc.plan", goal=goal[:60], tasks=len(tasks))

        return TaskDAG(tasks, edges)

    async def handle_failure(
        self, task: Task, error: str, dag: TaskDAG
    ) -> FailureDecision:
        """失败处理: 归因 → 决策"""
        self.failure_counts[task.id] += 1
        retry_count = self.failure_counts[task.id]

        # 查询相似失败
        similar = self.memory.query_similar_failures(task.description, error)

        # 快速路径：错误信息明确指示工具执行错误 → 触发工具修复
        if "工具执行错误:" in error:
            # 提取工具名 → 触发TCP修复（不是新建，是修复已有工具的bug）
            # 从 memory 中获取该工具的详细信息传给 TCP
            tool_name = error.split("工具执行错误:")[1].split(" -")[0].strip()
            tool_spec = {
                "name": tool_name,
                "description": f"修复工具 {tool_name} 的参数签名错误",
                "fix_existing": True,
                "error": error,
            }
            return FailureDecision(
                action="create_tool",
                tool_spec=tool_spec,
                reason=f"工具执行错误: {error[:100]}",
            )

        # 快速路径：错误信息明确指示工具真空
        tool_vacuum_signals = [
            "需要创造新工具", "无可用工具", "未能调用任何工具",
            "工具库为空", "幻觉输出", "tool_calls为空",
            "需要副作用操作", "未调用任何工具",
            "工具未找到",
        ]
        if any(sig in error for sig in tool_vacuum_signals):
            root_cause = FailureRootCause.TOOL_INADEQUATE
        else:
            # 因果归因
            root_cause = await self._diagnose(task, error, similar)

        if root_cause == FailureRootCause.TOOL_INADEQUATE:
            if retry_count >= config.max_retries_per_task:
                # 防重: 缺失工具已存在 → 不创建，而是重规划
                missing_match = re.search(r'工具未找到:\s*(\S+)', error)
                missing_tool = missing_match.group(1) if missing_match else None
                if missing_tool and self.memory.find_tool(missing_tool):
                    return FailureDecision(
                        action="replan",
                        reason=f"工具{missing_tool}已存在但没被正确调用，重规划",
                    )
                tool_spec = await self._generate_tool_spec(task, error, missing_tool)
                return FailureDecision(
                    action="create_tool",
                    tool_spec=tool_spec,
                    reason=f"工具真空: {error[:100]}",
                )
            return FailureDecision(action="skip", reason="等待重试阈值")

        elif root_cause == FailureRootCause.STRATEGY_FLAWED:
            self.memory.melt_path(task.id, reason=task.description[:80])
            return FailureDecision(action="replan", reason="路径熔断")

        else:
            return FailureDecision(action="skip", reason="环境异常")

    # ── 归因 ──

    async def _diagnose(
        self, task: Task, error: str, similar: list[dict]
    ) -> FailureRootCause:
        history = "\n".join(
            f"- [{s.get('root_cause', '?')}] {s.get('description', '')[:100]}"
            for s in similar[:3]
        )
        prompt = f"""任务: {task.description}
失败: {error}
历史相似失败:
{history}

判断根因分类:"""
        resp = await self._llm.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": ATTRIBUTION_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        raw = resp.choices[0].message.content or ""
        raw = raw.strip().lower()

        if "tool_inadequate" in raw:
            return FailureRootCause.TOOL_INADEQUATE
        elif "strategy" in raw:
            return FailureRootCause.STRATEGY_FLAWED
        return FailureRootCause.ENVIRONMENT_SHIFT

    # ── 工具需求 ──

    # 已知 API 端点工具的正确签名（跨 LLM 幻觉）
    KNOWN_API_TOOLS: dict = {
        "get_market_status": {
            "name": "get_market_status",
            "description": "获取市场全局状态：竞品均价/供应商价/库存/广告/当日利润/天",
            "parameters": [],
            "return_type": "str",
        },
        "get_daily_report": {
            "name": "get_daily_report",
            "description": "获取累计销售报告：总收入/总成本/总利润/销量",
            "parameters": [],
            "return_type": "str",
        },
        "advance_day": {
            "name": "advance_day",
            "description": "推进到下一天，触发市场波动和销售结算",
            "parameters": [],
            "return_type": "str",
        },
    }

    async def _generate_tool_spec(self, task: Task, error: str, missing_tool: str | None = None) -> dict:
        # 已知 API 端点 → 直接返回规范签名，无需 LLM
        if missing_tool and missing_tool in self.KNOWN_API_TOOLS:
            logger.info("tcp.known_api", tool=missing_tool)
            return dict(self.KNOWN_API_TOOLS[missing_tool])

        explicit = ""
        if missing_tool:
            explicit = (
                f"错误明确指示缺失工具名为「{missing_tool}」，"
                f"请创建该工具。名称必须为「{missing_tool}」。\n"
            )
        prompt = (
            f"任务失败，需要新工具:\n"
            f"任务: {task.description}\n"
            f"错误: {error}\n"
            f"已有工具: {task.tools_used}\n"
            f"{explicit}生成新工具规格（JSON）:\n"
            '{\n'
            '  "name": "snake_case函数名",\n'
            '  "description": "功能描述",\n'
            '  "parameters": [{"name": "x", "type": "str", "description": "...", "required": true}],\n'
            '  "return_type": "str"\n'
            '}'
        )
        resp = await self._llm.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        text = resp.choices[0].message.content or ""
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
        return {"name": f"tool_for_{task.id[:8]}", "description": task.description, "parameters": []}

    # ── 解析 ──

    def _parse_plan(self, response: str, goal_id: str) -> tuple[list[Task], list[tuple[str, str]]]:
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                tasks_raw = data.get("tasks", [])
            else:
                tasks_raw = self._fallback_parse(response)
        except (json.JSONDecodeError, KeyError):
            tasks_raw = self._fallback_parse(response)

        tasks = []
        edges = []
        for t in tasks_raw:
            if isinstance(t, str):
                tasks.append(Task(goal_id=goal_id, type="general", description=t))
            else:
                tid = t.get("id", f"task_{len(tasks)}")
                task = Task(
                    id=tid,
                    goal_id=goal_id,
                    type=t.get("type", "general"),
                    description=t.get("description", t.get("desc", "")),
                    depends_on=t.get("depends_on", []),
                )
                tasks.append(task)
                for dep in task.depends_on:
                    edges.append((dep, tid))

        if not tasks:
            tasks.append(Task(goal_id=goal_id, type="general", description=response[:200]))

        return tasks, edges

    @staticmethod
    def _fallback_parse(response: str) -> list[dict]:
        tasks = []
        for line in response.split("\n"):
            line = line.strip()
            if re.match(r'^\d+[\.\)、]', line):
                desc = re.sub(r'^\d+[\.\)、]\s*', '', line)
                tasks.append({"description": desc, "depends_on": []})
        if not tasks:
            tasks.append({"description": response.strip()[:200], "depends_on": []})
        return tasks
