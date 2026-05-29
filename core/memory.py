"""长期演进记忆库 — 认知图谱 + 进化事件存储"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from config import config


def _uid(prefix: str = "") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ── 数据模型 ──

class Goal(BaseModel):
    id: str = Field(default_factory=lambda: _uid("goal"))
    description: str
    status: str = "active"  # active | paused | completed | revised
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Task(BaseModel):
    id: str = Field(default_factory=lambda: _uid("task"))
    goal_id: str = ""
    type: str = ""
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    status: str = "ready"  # ready | running | complete | failed | blocked
    retry_count: int = 0
    tools_used: list[str] = Field(default_factory=list)
    last_error: str = ""
    result: Optional[Any] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CreatedTool(BaseModel):
    id: str = Field(default_factory=lambda: _uid("tool"))
    name: str
    code: str
    schema: dict = Field(default_factory=dict)  # OpenAI function-call schema
    source: str = "self_created"  # human | self_created
    version: str = "v1"
    test_results: list[dict] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EvolutionEvent(BaseModel):
    id: str = Field(default_factory=lambda: _uid("evo"))
    type: str  # failure | tool_created | path_melted | success
    task_id: str = ""
    description: str = ""
    detail: dict = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())



class CausalLink(BaseModel):
    """因果边 — 记录"什么失败"→"什么工具解决"的父子关系"""
    id: str = Field(default_factory=lambda: _uid("link"))
    from_type: str = ""              # failure | goal | task
    from_id: str = ""                # 源节点ID
    to_type: str = ""                # tool | task | goal
    to_id: str = ""                  # 目标节点ID
    relation: str = ""               # SOLVED_BY | CAUSED | MELTED | CREATED_FROM
    description: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())



# ── 记忆库 ──

class EvolutionMemory:
    """长期演进记忆库 — 文件持久化"""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or config.memory_path
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self.goals: dict[str, Goal] = {}
        self.tasks: dict[str, Task] = {}
        self.tools: dict[str, CreatedTool] = {}
        self.events: list[EvolutionEvent] = []
        self.causal_links: list[CausalLink] = []  # 因果边

        self._load()

    # ── 持久化 ──

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
            self.goals = {k: Goal(**v) for k, v in data.get("goals", {}).items()}
            self.tasks = {k: Task(**v) for k, v in data.get("tasks", {}).items()}
            self.tools = {k: CreatedTool(**v) for k, v in data.get("tools", {}).items()}
            self.events = [EvolutionEvent(**e) for e in data.get("events", [])]
            self.causal_links = [CausalLink(**c) for c in data.get("causal_links", [])]
        except Exception:
            pass

    def save(self) -> None:
        self.path.write_text(json.dumps({
            "goals": {k: v.model_dump() for k, v in self.goals.items()},
            "tasks": {k: v.model_dump() for k, v in self.tasks.items()},
            "tools": {k: v.model_dump() for k, v in self.tools.items()},
            "events": [e.model_dump() for e in self.events],
            "causal_links": [c.model_dump() for c in self.causal_links],
        }, ensure_ascii=False, indent=2, default=str))

    # ── 因果边 ──

    def add_causal_link(
        self,
        from_id: str,
        to_id: str,
        relation: str,
        from_type: str = "task",
        to_type: str = "tool",
        description: str = "",
    ) -> CausalLink:
        """添加因果边并持久化"""
        link = CausalLink(
            from_id=from_id,
            to_id=to_id,
            relation=relation,
            from_type=from_type,
            to_type=to_type,
            description=description[:200],
        )
        self.causal_links.append(link)
        self.save()
        return link

    def query_causal_chain(self, from_id: str) -> list[CausalLink]:
        """从某个节点出发，查询所有因它而产生的后续节点"""
        results = [c for c in self.causal_links if c.from_id == from_id]
        # 递归查询子节点
        for link in results:
            results.extend(self.query_causal_chain(link.to_id))
        return results

    def query_solved_by(self, pattern: str) -> list[dict]:
        """查询'什么失败→什么工具解决'的因果链"""
        results = []
        for c in self.causal_links:
            if c.relation == "SOLVED_BY":
                task = self.tasks.get(c.from_id)
                tool = self.tools.get(c.to_id)
                if task and tool and pattern.lower() in task.description.lower():
                    results.append({
                        "problem": task.description[:100],
                        "error": task.last_error[:100],
                        "solution_tool": tool.name,
                        "tool_id": tool.id,
                    })
        return results

    def query_melted_paths(self) -> list[str]:
        """查询所有已被熔断的路径描述"""
        descriptions = []
        for c in self.causal_links:
            if c.relation == "MELTED":
                descriptions.append(c.description)
        return descriptions

    # ── Goal ──

    def save_goal(self, goal: Goal) -> None:
        self.goals[goal.id] = goal
        self.save()

    # ── Task ──

    def save_task(self, task: Task) -> None:
        self.tasks[task.id] = task
        self.save()

    def record_success(self, task: Task, result: Any) -> None:
        task.status = "complete"
        task.result = result
        self.tasks[task.id] = task
        self.events.append(EvolutionEvent(
            type="success", task_id=task.id,
            description=f"任务成功: {task.description[:80]}",
        ))
        self.save()

    def record_failure(self, task: Task, error: str, root_cause: str = "") -> None:
        task.status = "failed"
        task.last_error = error
        task.retry_count += 1
        self.tasks[task.id] = task
        self.events.append(EvolutionEvent(
            type="failure", task_id=task.id,
            description=f"失败 [{root_cause}]: {error[:100]}",
            detail={"root_cause": root_cause, "error": error},
        ))
        self.save()

    # ── Tool ──

    def register_tool(self, tool: CreatedTool, source_task_id: str = "") -> None:
        # 同名工具替换: 移除旧版
        old_ids = [k for k, v in self.tools.items() if v.name == tool.name and k != tool.id]
        for oid in old_ids:
            del self.tools[oid]
        self.tools[tool.id] = tool
        self.events.append(EvolutionEvent(
            type="tool_created", task_id=source_task_id,
            description=f"新工具: {tool.name}",
            detail={"tool_id": tool.id, "tool_name": tool.name},
        ))
        if source_task_id:
            self.add_causal_link(
                from_id=source_task_id,
                to_id=tool.id,
                relation="SOLVED_BY",
                from_type="task",
                to_type="tool",
                description=f"工具真空 → {tool.name}",
            )
        self.save()

    def list_active_tools(self) -> list[CreatedTool]:
        return list(self.tools.values())

    def get_tool_schemas(self) -> list[dict]:
        return [
            {"type": "function", "function": t.schema}
            for t in self.tools.values()
        ]

    # ── 决策熔断 ──

    def melt_path(self, task_id: str) -> None:
        self.events.append(EvolutionEvent(
            type="path_melted", task_id=task_id,
            description="策略路径熔断",
        ))
        # 记录熔断因果边
        self.add_causal_link(
            from_id=task_id, to_id=task_id,
            relation="MELTED",
            from_type="task", to_type="task",
            description=f"策略路径熔断: {task_id}",
        )
        self.save()

    # ── 查询 ──

    def query_similar_goals(self, goal_desc: str, top_k: int = 3) -> list[dict]:
        """查询相似历史目标"""
        results = []
        for g in self.goals.values():
            if g.status == "complete":
                tasks = [t for t in self.tasks.values() if t.goal_id == g.id and t.status == "complete"]
                results.append({
                    "goal": g.description,
                    "success_path": [t.description for t in tasks[:5]],
                    "task_count": len(tasks),
                })
        return results[:top_k]

    def query_similar_failures(self, task_desc: str, error_msg: str) -> list[dict]:
        """查询相似失败案例"""
        results = []
        for e in self.events:
            if e.type == "failure":
                results.append({
                    "task_id": e.task_id,
                    "description": e.description,
                    "root_cause": e.detail.get("root_cause", ""),
                    "error": e.detail.get("error", ""),
                })
        return results[-10:]  # 最近 10 条

    def generate_report(self) -> dict:
        """生成执行报告"""
        total = len(self.tasks)
        if total == 0:
            return {"total_tasks": 0, "success_rate": 0, "tools_created": 0, "evolution_events": 0}
        success_count = sum(1 for t in self.tasks.values() if t.status == "complete")
        return {
            "total_tasks": total,
            "success_rate": round(success_count / total, 2),
            "tools_created": len(self.tools),
            "evolution_events": len(self.events),
        }
