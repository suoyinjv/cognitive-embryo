"""目标审视器 — 定期战略反思"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from openai import AsyncOpenAI
from structlog import get_logger

from config import config
from core.memory import EvolutionMemory

logger = get_logger(__name__)


@dataclass
class GoalRevision:
    should_redirect: bool
    new_goal: str = ""
    health_score: float = 1.0
    anomalies: list[str] = None
    recommendation: str = "continue"  # continue | pause | pivot

    def __post_init__(self):
        if self.anomalies is None:
            self.anomalies = []


INTROSPECT_SYSTEM = """你是战略审视顾问。评估当前目标是否仍然合理。

请分析:
1. 目标健康度 (0~1)，越低越差
2. 发现的新洞察或异常
3. 识别关键问题：是工具缺失、策略错误还是环境恶化
4. 如果当前利润持续亏损，必须提出转向建议

输出 JSON:
{
  "health_score": 0.8,
  "anomalies": ["发现1"],
  "new_insights": ["洞察1"],
  "recommendation": "continue|pause|pivot",
  "revised_goal": "如果 pivot，新目标是什么"
}"""


class GoalExaminer:
    """目标审视器 — 守护进程式战略反思"""

    def __init__(self, memory: EvolutionMemory) -> None:
        self.memory = memory
        self._llm = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self._model = config.model

    async def examine(self, goal: str, task_dag) -> GoalRevision:
        """审视当前目标 — 含损益表和因果链"""
        # 统计数据
        counts = {"complete": 0, "failed": 0, "total": len(task_dag.tasks)}
        for s in task_dag.status.values():
            if s == "complete":
                counts["complete"] += 1
            elif s == "failed":
                counts["failed"] += 1

        recent_events = self.memory.events[-5:]
        events_text = "\n".join(
            f"- [{e.type}] {e.description[:100]}" for e in recent_events
        )

        # 损益数据 (从 memory 中的任务获取)
        tools = self.memory.list_active_tools()
        causal_count = len(self.memory.causal_links)
        melted = len(self.memory.query_melted_paths())

        prompt = f"""当前目标: {goal}
进度: {counts['complete']}/{counts['total']} 完成, {counts['failed']} 失败

工具库: {len(tools)}个工具 (含{sum(1 for t in self.memory.tools.values() if t.source=='self_created')}个自创)
因果链接: {causal_count}条
已熔断路径: {melted}条

最近事件:
{events_text}

审视当前目标是否合理。如果利润持续亏损或关键指标恶化，建议pivot并给出新目标。"""
        resp = await self._llm.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": INTROSPECT_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
        )

        parsed = self._parse(resp.choices[0].message.content or "")
        health = parsed.get("health_score", 0.7)
        rec = parsed.get("recommendation", "continue")
        new_goal = parsed.get("revised_goal", "")

        should_redirect = rec in ("pause", "pivot") and bool(new_goal)

        logger.info("examiner.check", health=health, rec=rec, redirect=should_redirect)

        return GoalRevision(
            should_redirect=should_redirect and config.auto_revise_goals,
            new_goal=new_goal,
            health_score=health,
            anomalies=parsed.get("anomalies", []),
            recommendation=rec,
        )

    @staticmethod
    def _parse(text: str) -> dict:
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
        return {"health_score": 0.5, "recommendation": "continue"}
