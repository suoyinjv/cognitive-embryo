"""认知胚胎 — 主循环入口

使用方式:
    python main.py "30天内使虚拟电商业净利润最大化"

三个核心闭环:
    失败蒸馏 → 工具创造 → 重试
    路径熔断 → 重规划
    目标审视 → 转向
"""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config import config
from core.mcc import MetaCognitionController, FailureDecision
from core.executor import Executor, ExecutionResult
from core.memory import EvolutionMemory, Goal, Task
from core.goal_examiner import GoalExaminer, GoalRevision
from core.tool_creator import ToolCreationPipeline
from safety.shell import SafetyShell

console = Console()


class CognitiveEmbryo:
    """认知胚胎 — 闭环进化型智能体"""

    def __init__(self) -> None:
        self.memory = EvolutionMemory()
        self.executor = Executor(self.memory)
        self.mcc = MetaCognitionController(self.memory, self.executor)
        self.goal_examiner = GoalExaminer(self.memory)
        self.safety = SafetyShell()
        self._original_goal: str = ""  # 保存原始目标，修复后自动恢复

    async def run(self, goal_desc: str, max_iterations: Optional[int] = None) -> dict:
        max_iter = max_iterations or config.max_iterations
        iteration = 0
        current_goal = goal_desc
        self._original_goal = goal_desc

        # 记录目标
        goal = Goal(description=current_goal)
        self.memory.save_goal(goal)

        # 1. 初始规划
        console.print(Panel.fit(
            f"[bold cyan]{current_goal}[/bold cyan]",
            title="🎯 认知胚胎启动",
        ))
        task_dag = await self.mcc.plan(current_goal)

        while iteration < max_iter:
            iteration += 1

            # 2. 目标审视 (每 N 轮)
            if iteration % config.introspection_interval == 0:
                revision = await self.goal_examiner.examine(current_goal, task_dag)
                if revision.should_redirect and revision.new_goal:
                    console.print(Panel(
                        f"[yellow]原目标:[/yellow] {current_goal}\n[yellow]新目标:[/yellow] {revision.new_goal}",
                        title=f"🔄 目标转向 (健康度: {revision.health_score:.2f})",
                    ))
                    # 保存前一个目标
                    current_goal = revision.new_goal
                    goal = Goal(description=current_goal)
                    self.memory.save_goal(goal)
                    task_dag = await self.mcc.plan(current_goal)
                    continue

                # 健康度恢复且当前是修复子目标 → 自动切回原始目标
                if (revision.health_score >= 0.7
                    and revision.recommendation == "continue"
                    and current_goal != self._original_goal
                    and not any(s == "failed" for s in task_dag.status.values())):
                    console.print(Panel(
                        f"[green]修复完成，恢复原始目标:[/green] {self._original_goal}",
                        title="↩️ 目标恢复",
                    ))
                    current_goal = self._original_goal
                    goal = Goal(description=current_goal)
                    self.memory.save_goal(goal)
                    task_dag = await self.mcc.plan(current_goal)
                    continue

            # 3. 取下一个就绪任务
            task = task_dag.get_next_ready()
            if task is None:
                if task_dag.all_done:
                    # 连续运营模式: DAG完成 → 继续下一轮
                    if iteration < max_iter - 1:
                        console.print(f"  🔄 [dim]阶段[{iteration}]完成, 进入下一轮规划...[/dim]")
                        task_dag = await self.mcc.plan(current_goal)
                        continue
                    break
                # 有任务但都不就绪 (阻塞/等待)
                await asyncio.sleep(0.1)
                continue

            # 4. 安全检查
            if not self.safety.approve(task):
                task_dag.mark_blocked(task.id, "safety_rejection")
                console.print(f"  🛡  [red]安全拦截:[/red] {task.description[:50]}")
                continue

            # 5. 执行
            console.print(f"  ⚡ [{iteration}] {task.description[:60]}...", end=" ")
            result = await self.executor.execute(task)

            # 6. 反馈处理
            if result.success:
                task_dag.mark_complete(task.id, result)
                self.memory.record_success(task, result.output)
                console.print("[green]✓[/green]")
            else:
                task_dag.mark_failed(task.id)
                self.memory.record_failure(task, result.error, "unknown")
                console.print(f"[red]✗[/red] {result.error[:60]}")

                # 核心：失败蒸馏 → 决策
                decision = await self.mcc.handle_failure(task, result.error, task_dag)

                if decision.action == "create_tool":
                    console.print(f"    🔧 [cyan]触发工具创造:[/cyan] {decision.tool_spec.get('name', '?')}")
                    new_tool = await self.executor.create_tool(
                        decision.tool_spec or {}, task
                    )
                    if new_tool:
                        self.memory.register_tool(new_tool, source_task_id=task.id)
                        task_dag.retry_task(task.id)
                        console.print(f"    ✅ 新工具注册: {new_tool.name}")
                    else:
                        task_dag.mark_blocked(task.id, "tool_creation_failed")
                        console.print(f"    ❌ 工具创造失败")

                elif decision.action == "replan":
                    console.print(f"    🔄 [yellow]重规划[/yellow]")
                    # 记录熔断因果边
                    self.memory.add_causal_link(
                        from_id=task.id, to_id=task.id,
                        relation="MELTED",
                        from_type="task", to_type="task",
                        description=f"路径熔断: {task.description[:60]} - {decision.reason[:100]}"
                    )
                    task_dag = await self.mcc.plan(current_goal)

                elif decision.action == "skip":
                    # 未达重试阈值 → 放回队列等待重试
                    task_dag.retry_task(task.id)
                    console.print(f"    🔁 [dim]重试 {task.retry_count}/{config.max_retries_per_task}[/dim]")

            # 小延迟避免 API 限流
            await asyncio.sleep(0.5)

        # 7. 生成报告
        report = self.memory.generate_report()

        table = Table(title="📊 执行报告")
        table.add_column("指标", style="cyan")
        table.add_column("数值", style="green")
        table.add_row("总迭代", str(iteration))
        table.add_row("总任务", str(report["total_tasks"]))
        table.add_row("成功率", f"{report['success_rate']:.0%}")
        table.add_row("自创工具", str(report["tools_created"]))
        table.add_row("进化事件", str(report["evolution_events"]))
        console.print(table)

        return report


# ── CLI 入口 ──

async def main() -> None:
    if len(sys.argv) < 2:
        console.print("[yellow]用法: python main.py \"目标描述\"[/yellow]")
        console.print("[dim]示例: python main.py \"分析竞品定价策略\"[/dim]")
        console.print("[dim]示例: python main.py \"30天内最大化虚拟电商利润\"[/dim]")
        return

    goal = " ".join(sys.argv[1:])
    embryo = CognitiveEmbryo()

    # 播种初始工具
    _seed_tools(embryo.memory)

    await embryo.run(goal)


def _seed_tools(memory: EvolutionMemory) -> None:
    """播种初始工具集"""
    from core.memory import CreatedTool

    seeds = [
        ("calculate", "执行数学计算", "calculate = lambda expression: str(eval(expression))", {
            "name": "calculate", "description": "执行数学计算",
            "parameters": {"type": "object", "properties": {"expression": {"type": "string", "description": "数学表达式"}}, "required": ["expression"]},
        }),
        # ── 电商模拟器工具 (删除了 get_market_status 和 get_daily_report 以迫使TCP触发) ──
        ("get_competitor_price", "查询竞品价格",
'''import urllib.request, json
def get_competitor_price():
    with urllib.request.urlopen("http://127.0.0.1:5800/competitor-price") as r:
        return json.dumps(json.loads(r.read()), ensure_ascii=False)''',
         {"name": "get_competitor_price", "description": "查询竞品均价和竞品数量",
          "parameters": {"type": "object", "properties": {}, "required": []}}),

        ("get_supplier_price", "查询供应商采购价格",
'''import urllib.request, json
def get_supplier_price():
    with urllib.request.urlopen("http://127.0.0.1:5800/supplier-price") as r:
        return json.dumps(json.loads(r.read()), ensure_ascii=False)''',
         {"name": "get_supplier_price", "description": "查询供应商当前采购价格和趋势",
          "parameters": {"type": "object", "properties": {}, "required": []}}),

        ("adjust_price", "调整我的售价", 
'''import urllib.request, json
def adjust_price(price: float):
    data = json.dumps({"price": price}).encode()
    req = urllib.request.Request("http://127.0.0.1:5800/pricing", data=data, headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.dumps(json.loads(r.read()), ensure_ascii=False)''',
         {"name": "adjust_price", "description": "调整商品售价",
          "parameters": {"type": "object", "properties": {"price": {"type": "number", "description": "新售价"}}, "required": ["price"]}}),

        ("run_ad_campaign", "投放广告", 
'''import urllib.request, json
def run_ad_campaign(budget: float):
    data = json.dumps({"budget": budget}).encode()
    req = urllib.request.Request("http://127.0.0.1:5800/ad-spend", data=data, headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.dumps(json.loads(r.read()), ensure_ascii=False)''',
         {"name": "run_ad_campaign", "description": "投放广告，返回曝光/点击/转化数据",
          "parameters": {"type": "object", "properties": {"budget": {"type": "number", "description": "广告预算(元)"}}, "required": ["budget"]}}),

        ("restock_inventory", "采购补货",
'''import urllib.request, json
def restock_inventory(units: int):
    data = json.dumps({"units": units}).encode()
    req = urllib.request.Request("http://127.0.0.1:5800/inventory", data=data, headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.dumps(json.loads(r.read()), ensure_ascii=False)''',
         {"name": "restock_inventory", "description": "采购补货，增加库存",
          "parameters": {"type": "object", "properties": {"units": {"type": "integer", "description": "采购数量"}}, "required": ["units"]}}),

        ("advance_day", "推进到下一天（触发市场波动和销售结算）",
'''import urllib.request, json
def advance_day():
    req = urllib.request.Request("http://127.0.0.1:5800/tick", data=b"{}", headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.dumps(json.loads(r.read()), ensure_ascii=False)''',
         {"name": "advance_day", "description": "推进到下一天，触发市场波动和当日销售结算",
          "parameters": {"type": "object", "properties": {}, "required": []}}),

        ("get_daily_report", "获取当日销售报告",
'''import urllib.request, json
def get_daily_report():
    with urllib.request.urlopen("http://127.0.0.1:5800/daily-sales") as r:
        return json.dumps(json.loads(r.read()), ensure_ascii=False)''',
         {"name": "get_daily_report", "description": "获取累计销售报告：总收入/总成本/总利润/销量",
          "parameters": {"type": "object", "properties": {}, "required": []}}),
    ]
    for name, desc, code, schema in seeds:
        if not any(t.name == name for t in memory.tools.values()):
            tool = CreatedTool(name=name, code=code, schema=schema, source="human")
            memory.register_tool(tool)
            console.print(f"  🌱 播种工具: {name}")


if __name__ == "__main__":
    asyncio.run(main())
