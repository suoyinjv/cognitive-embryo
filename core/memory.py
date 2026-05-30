"""长期演进记忆库 — 认知图谱 (networkx + SQLite)

架构:
- 所有实体(Goal/Task/Tool/Event)作为图节点
- 因果边(CausalLink)作为有向边
- SQLite + JSON混合持久化
- 保持与旧版 EvolutionMemory 完全兼容的公共API
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import networkx as nx
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
    schema: dict = Field(default_factory=dict)
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
    id: str = Field(default_factory=lambda: _uid("link"))
    from_type: str = ""
    from_id: str = ""
    to_type: str = ""
    to_id: str = ""
    relation: str = ""  # SOLVED_BY | CAUSED | MELTED | CREATED_FROM
    description: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── 图记忆库 ──

class EvolutionMemory:
    """长期演进记忆库 — 图结构 + SQLite持久化
    
    所有实体作为图节点，因果边作为有向边。
    支持图查询：最短路径、子图、中心度分析。
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or config.memory_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = self.path.with_suffix(".db")  # SQLite alongside JSON
        
        # 图引擎
        self.graph: nx.DiGraph = nx.DiGraph()
        
        # 快速索引（保持与旧版兼容的dict接口）
        self.goals: dict[str, Goal] = {}
        self.tasks: dict[str, Task] = {}
        self.tools: dict[str, CreatedTool] = {}
        self.events: list[EvolutionEvent] = []
        self.causal_links: list[CausalLink] = []

        self._init_db()
        self._load()

    # ── SQLite持久化 ──

    def _init_db(self) -> None:
        """初始化SQLite数据库"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,       -- goal | task | tool | event
                data TEXT NOT NULL,       -- JSON序列化
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS edges (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation TEXT NOT NULL,   -- SOLVED_BY | MELTED | CAUSED | CREATED_FROM
                data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES nodes(id),
                FOREIGN KEY (target_id) REFERENCES nodes(id)
            );
            CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
            CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
            CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
        """)
        conn.commit()
        conn.close()

    def _save_node(self, node_type: str, obj: BaseModel) -> None:
        """写入一个节点到SQLite"""
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT OR REPLACE INTO nodes (id, type, data, created_at) VALUES (?, ?, ?, ?)",
            (obj.id, node_type, obj.model_dump_json(), now),
        )
        conn.commit()
        conn.close()
        # 同步到图
        self.graph.add_node(obj.id, type=node_type, data=obj)

    def _save_edge(self, link: CausalLink) -> None:
        """写入一条边到SQLite"""
        now = datetime.now(timezone.utc).isoformat()
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            "INSERT OR REPLACE INTO edges (id, source_id, target_id, relation, data, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (link.id, link.from_id, link.to_id, link.relation, link.model_dump_json(), now),
        )
        conn.commit()
        conn.close()
        # 同步到图
        self.graph.add_edge(link.from_id, link.to_id, id=link.id, relation=link.relation, data=link)

    def _load(self) -> None:
        """从SQLite加载所有数据到内存"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        
        # 加载节点
        for row in conn.execute("SELECT type, data FROM nodes"):
            try:
                d = json.loads(row["data"])
                t = row["type"]
                if t == "goal":
                    obj = Goal(**d)
                    self.goals[obj.id] = obj
                elif t == "task":
                    obj = Task(**d)
                    self.tasks[obj.id] = obj
                elif t == "tool":
                    obj = CreatedTool(**d)
                    self.tools[obj.id] = obj
                elif t == "event":
                    obj = EvolutionEvent(**d)
                    self.events.append(obj)
                self.graph.add_node(obj.id, type=t, data=obj)
            except Exception:
                pass
        
        # 加载边
        for row in conn.execute("SELECT data FROM edges"):
            try:
                link = CausalLink(**json.loads(row["data"]))
                self.causal_links.append(link)
                self.graph.add_edge(link.from_id, link.to_id, id=link.id, relation=link.relation, data=link)
            except Exception:
                pass
        
        conn.close()

    def save(self) -> None:
        """全量持久化（兼容旧接口）"""
        pass  # 数据已通过 _save_node/_save_edge 实时写入

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
        link = CausalLink(
            from_id=from_id,
            to_id=to_id,
            relation=relation,
            from_type=from_type,
            to_type=to_type,
            description=description[:200],
        )
        self.causal_links.append(link)
        self._save_edge(link)
        return link

    def query_causal_chain(self, from_id: str) -> list[CausalLink]:
        """从某个节点出发，图遍历所有后续因果边"""
        results = []
        if from_id not in self.graph:
            return results
        # BFS遍历
        for _, _, edge_data in nx.bfs_edges(self.graph, from_id):
            link = edge_data.get("data")
            if link:
                results.append(link)
        return results

    def query_shortest_path(self, from_id: str, to_type: str, relation: Optional[str] = None) -> list[str]:
        """查询从节点到目标类型的最短路径"""
        if from_id not in self.graph:
            return []
        # 找所有符合条件的节点
        targets = [n for n, d in self.graph.nodes(data=True) if d.get("type") == to_type]
        if not targets:
            return []
        try:
            # 只考虑特定关系的边
            if relation:
                sub = self.graph.edge_subgraph(
                    (u, v) for u, v, d in self.graph.edges(data=True)
                    if d.get("relation") == relation
                )
                if from_id in sub:
                    path = nx.shortest_path(sub, from_id, targets[0])
                    return path
            path = nx.shortest_path(self.graph, from_id, targets[0])
            return path
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def query_solved_by(self, pattern: str) -> list[dict]:
        """查询'失败→工具'因果链"""
        results = []
        for u, v, d in self.graph.edges(data=True):
            if d.get("relation") == "SOLVED_BY":
                task_node = self.graph.nodes.get(u)
                tool_node = self.graph.nodes.get(v)
                if task_node and tool_node:
                    task = task_node.get("data")
                    tool = tool_node.get("data")
                    if task and tool and pattern.lower() in task.description.lower():
                        results.append({
                            "problem": task.description[:100],
                            "error": getattr(task, "last_error", "")[:100],
                            "solution_tool": tool.name,
                            "tool_id": tool.id,
                        })
        return results

    def query_melted_paths(self) -> list[str]:
        """查询最近5条熔断路径"""
        descriptions = []
        for link in reversed(self.causal_links):
            if link.relation == "MELTED":
                descriptions.append(link.description)
                if len(descriptions) >= 5:
                    break
        return list(reversed(descriptions))

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
        """查询最近10条失败事件"""
        results = []
        for e in self.events:
            if e.type == "failure":
                results.append({
                    "task_id": e.task_id,
                    "description": e.description,
                    "root_cause": e.detail.get("root_cause", ""),
                    "error": e.detail.get("error", ""),
                })
        return results[-10:]

    # ── Goal ──

    def save_goal(self, goal: Goal) -> None:
        self.goals[goal.id] = goal
        self._save_node("goal", goal)

    # ── Task ──

    def save_task(self, task: Task) -> None:
        self.tasks[task.id] = task
        self._save_node("task", task)

    def record_success(self, task: Task, result: Any) -> None:
        task.status = "complete"
        task.result = result
        self.tasks[task.id] = task
        self._save_node("task", task)
        evt = EvolutionEvent(type="success", task_id=task.id, description=f"任务成功: {task.description[:80]}")
        self.events.append(evt)
        self._save_node("event", evt)

    def record_failure(self, task: Task, error: str, root_cause: str = "") -> None:
        task.status = "failed"
        task.last_error = error
        task.retry_count += 1
        self.tasks[task.id] = task
        self._save_node("task", task)
        evt = EvolutionEvent(
            type="failure", task_id=task.id,
            description=f"失败 [{root_cause}]: {error[:100]}",
            detail={"root_cause": root_cause, "error": error},
        )
        self.events.append(evt)
        self._save_node("event", evt)

    # ── Tool ──

    def register_tool(self, tool: CreatedTool, source_task_id: str = "") -> None:
        old_ids = [k for k, v in self.tools.items() if v.name == tool.name and k != tool.id]
        for oid in old_ids:
            del self.tools[oid]
            if oid in self.graph:
                self.graph.remove_node(oid)
        self.tools[tool.id] = tool
        self._save_node("tool", tool)
        evt = EvolutionEvent(
            type="tool_created", task_id=source_task_id,
            description=f"新工具: {tool.name}",
            detail={"tool_id": tool.id, "tool_name": tool.name},
        )
        self.events.append(evt)
        self._save_node("event", evt)
        if source_task_id:
            self.add_causal_link(
                from_id=source_task_id, to_id=tool.id,
                relation="SOLVED_BY", from_type="task", to_type="tool",
                description=f"工具真空 → {tool.name}",
            )

    def list_active_tools(self) -> list[CreatedTool]:
        return list(self.tools.values())

    def find_tool(self, name: str) -> Optional[CreatedTool]:
        for t in self.tools.values():
            if t.name == name or t.schema.get("name") == name:
                return t
        return None

    def get_tool_schemas(self) -> list[dict]:
        return [{"type": "function", "function": t.schema} for t in self.tools.values()]

    # ── 决策熔断 ──

    def melt_path(self, task_id: str, reason: str = "") -> None:
        evt = EvolutionEvent(type="path_melted", task_id=task_id, description=f"策略路径熔断: {reason}")
        self.events.append(evt)
        self._save_node("event", evt)
        self.add_causal_link(
            from_id=task_id, to_id=task_id,
            relation="MELTED", from_type="task", to_type="task",
            description=f"路径熔断: {reason}",
        )

    # ── 图分析查询（新能力）──

    def query_tool_centrality(self, top_k: int = 5) -> list[dict]:
        """查询中心度最高的工具（最常用的工具）"""
        centrality = nx.degree_centrality(self.graph)
        tool_centrality = [
            (n, c) for n, c in centrality.items()
            if self.graph.nodes.get(n, {}).get("type") == "tool"
        ]
        tool_centrality.sort(key=lambda x: -x[1])
        results = []
        for node_id, cent in tool_centrality[:top_k]:
            tool = self.tools.get(node_id)
            if tool:
                results.append({"name": tool.name, "centrality": round(cent, 3), "source": tool.source})
        return results

    def query_subgraph(self, node_id: str, depth: int = 2) -> dict:
        """查询以某节点为中心的子图（用于可视化/分析）"""
        if node_id not in self.graph:
            return {"nodes": [], "edges": []}
        # BFS提取子图
        sub_nodes = {node_id}
        current = {node_id}
        for _ in range(depth):
            neighbors = set()
            for n in current:
                neighbors |= set(self.graph.successors(n))
                neighbors |= set(self.graph.predecessors(n))
            sub_nodes |= neighbors
            current = neighbors
        sub = self.graph.subgraph(sub_nodes)
        return {
            "nodes": [
                {"id": n, "type": d.get("type", "?"), "name": getattr(d.get("data"), "name", getattr(d.get("data"), "description", n))[:40]}
                for n, d in sub.nodes(data=True)
            ],
            "edges": [
                {"source": u, "target": v, "relation": d.get("relation", "?")}
                for u, v, d in sub.edges(data=True)
            ],
        }

    def query_pattern_frequency(self) -> list[dict]:
        """分析最常见的失败模式"""
        pattern_count: dict[str, int] = defaultdict(int)
        for link in self.causal_links:
            if link.relation == "MELTED":
                # 从描述中提取模式关键词
                desc = link.description.lower()
                for kw in ["定价", "补货", "广告", "查询", "调价", "推进", "评估"]:
                    if kw in desc:
                        pattern_count[kw] += 1
        return sorted(
            [{"pattern": k, "count": v} for k, v in pattern_count.items()],
            key=lambda x: -x["count"],
        )

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
            "graph_nodes": self.graph.number_of_nodes(),
            "graph_edges": self.graph.number_of_edges(),
            "top_tools": self.query_tool_centrality(3),
            "patterns": self.query_pattern_frequency()[:3],
        }
