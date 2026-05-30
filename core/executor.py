"""任务执行器 — 工具调用管道"""

from __future__ import annotations

import json
import re
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import AsyncOpenAI
from structlog import get_logger

from config import config
from core.memory import EvolutionMemory, Task, CreatedTool

logger = get_logger(__name__)


@dataclass
class ExecutionResult:
    success: bool
    output: str = ""
    error: str = ""
    trace: str = ""
    tool_called: str = ""


class Executor:
    """任务执行器 — 从记忆库检索工具并执行"""

    def __init__(self, memory: EvolutionMemory) -> None:
        self.memory = memory
        self._llm = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self._model = config.model

    @staticmethod
    def _requires_side_effects(task_desc: str) -> bool:
        """检测任务是否需要副作用（非纯文本推理可完成）"""
        side_effect_keywords = [
            "写文件", "创建", "下载", "执行代码", "编程", "编码",
            "生成代码", "定价算法",
            "部署", "安装", "修改文件", "生成报告文件",
            "write file", "create file", "download", "execute code",
            "generate code", "pricing algorithm",
            "搜索", "查询网络", "hermes_search", "hermes_terminal",
        ]
        desc_lower = task_desc.lower()
        return any(kw in desc_lower for kw in side_effect_keywords)

    async def execute(self, task: Task) -> ExecutionResult:
        """执行单个任务"""
        logger.info("execute.start", task_id=task.id, desc=task.description[:60])

        try:
            tools = self.memory.get_tool_schemas()

            if not tools:
                # 检查是否需要副作用
                if self._requires_side_effects(task.description):
                    return ExecutionResult(
                        success=False,
                        error="工具库为空，无法完成需要副作用的任务。需要创造新工具。",
                        tool_called="no_tools_available",
                    )
                # 纯文本推理
                response = await self._llm.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": "你是任务执行助手，直接完成用户的任务并返回结果。"},
                        {"role": "user", "content": task.description},
                    ],
                    temperature=0.5,
                )
                output = response.choices[0].message.content or ""
                return ExecutionResult(success=True, output=output, tool_called="llm_direct")

            # 智能过滤：根据任务关键词推荐最佳工具
            tools = self._filter_tools_by_keyword(task.description, tools)

            system_prompt = (
                "你是任务执行助手。\n"
                "你有以下工具可用。请分析用户任务并调用最合适的工具。\n"
                "如果任务说'调价'/'调整售价'/'定价'，你必须调用 adjust_price 工具。\n"
                "如果任务说'推进时间'/'下一天'，你必须调用 advance_day 工具。\n"
                "如果任务说'补货'/'采购'，你必须调用 restock_inventory 工具。\n"
                "如果任务说'广告'/'投放'，你必须调用 run_ad_campaign 工具。\n"
                "不要返回纯文本分析结果——你必须调用工具。\n"
                "只读查询（市场状态/日报/竞品）才用 get_ 开头的工具。\n"
            )
            # 直接调用hermes_search（绕过LLM，DeepSeek调工具有问题）
            if "hermes_search" in task.description:
                import re as _r
                qm = _r.search(r'搜索(.+?)(?:，|。|$|趋势|数据|信息)', task.description)
                q = qm.group(1).strip() if qm else "市场趋势"
                t = self.memory.find_tool("hermes_search")
                if t:
                    return await self._run_tool(t, "hermes_search", {"query": q}, task)

            response = await self._llm.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": task.description},
                ],
                tools=tools,
                temperature=0.1,
                tool_choice="auto",
            )

            msg = response.choices[0].message
            content = msg.content or ""
            tool_calls = msg.tool_calls

            # 没有调用任何工具 → 判断是真空还是幻觉
            if not tool_calls:
                # 先检查是否真的不需要工具（纯文本推理）
                if not self._requires_side_effects(task.description):
                    return ExecutionResult(success=True, output=content, tool_called="llm_direct")

                # 需要工具但没调用 → 幻觉
                return ExecutionResult(
                    success=False,
                    error=f"任务需要副作用操作，但LLM未调用任何工具。幻觉输出: {content[:200]}",
                    trace="tool_calls为空。LLM返回了纯文本但任务要求生成/执行/创建。归因: tool_vacuum",
                    tool_called="llm_hallucination",
                )

            # LLM返回纯文本但内容空洞 → 极小置信度
            if len(content.strip()) < 20 and not tools:
                return ExecutionResult(
                    success=False,
                    error=f"LLM返回结果为空或过短，可能不具备该能力。输出: {content[:100]}",
                    tool_called="llm_empty",
                )

            # 任务描述明确提到某个工具名，但LLM没调 → 幻觉
            import re as _re
            mentioned_tools = _re.findall(r'\b(hermes_search|hermes_terminal|adjust_price|get_competitor_price|get_supplier_price|restock_inventory|run_ad_campaign|advance_day|get_daily_report|get_products_list|product_pricing|get_competitors_info|calculate)\b', task.description)
            if mentioned_tools and not tool_calls:
                tool_names = set(mentioned_tools)
                return ExecutionResult(
                    success=False,
                    error=f"任务明确要求调用工具 {tool_names}，但LLM未调用任何工具(纯文本回复)。幻觉输出: {content[:200]}",
                    trace="tool_calls为空但任务指定了工具名",
                    tool_called="llm_hallucination",
                )

            # 执行工具调用
            for tc in tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                logger.info("execute.tool", name=name, args=args)

                # 查找工具
                tool = self.memory.find_tool(name)
                if not tool:
                    return ExecutionResult(
                        success=False,
                        error=f"工具未找到: {name}",
                        tool_called=name,
                    )

                # 如果是 self_created 工具，可能需要先创建
                result = await self._run_tool(tool, name, args, task)
                if not result.success:
                    return result

            return ExecutionResult(success=True, output="工具调用完成", tool_called=",".join(tc.function.name for tc in tool_calls))

        except Exception as e:
            return ExecutionResult(
                success=False,
                error=str(e),
                trace=traceback.format_exc(),
            )

    async def _run_tool(self, tool: CreatedTool, name: str, args: dict, task: Task) -> ExecutionResult:
        """执行单个工具 — 动态加载"""
        try:
            # 动态加载并执行工具代码
            namespace: dict[str, Any] = {}
            exec(tool.code, namespace)
            func = namespace.get(tool.name) or namespace.get(name)

            if not func:
                return ExecutionResult(success=False, error=f"工具执行错误: {name} - 函数未在代码中定义", tool_called=name)

            # 定价安全护栏 + 智能补全
            if name == "adjust_price":
                price = args.get("price", 0)
                try:
                    import urllib.request
                    import json as _j
                    with urllib.request.urlopen("http://127.0.0.1:5800/supplier-price", timeout=3) as r:
                        sp_data = _j.loads(r.read())
                        sp = sp_data["price"] if isinstance(sp_data, dict) and "price" in sp_data else 50.0
                    with urllib.request.urlopen("http://127.0.0.1:5800/competitor-price", timeout=3) as r:
                        cp_data = _j.loads(r.read())
                        cp_price = cp_data.get("avg_price", cp_data.get("price", sp*1.5)) if isinstance(cp_data, dict) else sp*1.5
                    if price <= 0 or price < round(sp*1.15, 2):
                        suggested = round(max(sp*1.3, cp_price*0.95), 2)
                        args["price"] = suggested
                        logger.info("price.auto_fix", old=price, new=suggested, sp=sp, cp=cp_price)
                        price = suggested
                except Exception:
                    pass  # 网络异常时放行

            # 补货上限护栏：防止LLM传超大数值导致成本爆炸
            if name == "restock_inventory":
                units = args.get("units", 0)
                if units <= 0 or units > 500:
                    args["units"] = 100
                    logger.info("restock.cap", old=units, new=100)

            result = func(**args)
            return ExecutionResult(success=True, output=str(result), tool_called=name)

        except TypeError as e:
            error_msg = f"工具执行错误: {name} - 参数不匹配: {e}"
            return ExecutionResult(
                success=False,
                error=error_msg,
                trace=traceback.format_exc(),
                tool_called=name,
            )
        except Exception as e:
            error_msg = f"工具执行错误: {name} - {e}"
            return ExecutionResult(
                success=False,
                error=error_msg,
                trace=traceback.format_exc(),
                tool_called=name,
            )

    @staticmethod
    def _filter_tools_by_keyword(task_desc: str, tools: list[dict]) -> list[dict]:
        """根据任务关键词智能过滤工具列表"""
        keywords = {
            "adjust_price": ["调价", "售价", "定价", "价格"],
            "get_competitor_price": ["竞品", "competitor"],
            "get_supplier_price": ["供应商", "supplier", "成本"],
            "restock_inventory": ["补货", "采购", "库存", "restock"],
            "run_ad_campaign": ["广告", "投放", "ad", "曝光"],
            "advance_day": ["推进", "下一天", "时间", "advance", "tick"],
            "get_daily_report": ["日报", "报告", "销售", "report"],
        }
        desc_lower = task_desc.lower()

        # 如果任务明确提到某个工具的关键词，只返回那个工具
        for tool_name, kws in keywords.items():
            if any(kw in desc_lower for kw in kws):
                return [t for t in tools if t["function"]["name"] == tool_name]

        # 没匹配到关键词：返回所有只读工具 + calculate
        return tools

    async def create_tool(self, tool_spec: dict, task: Task) -> CreatedTool | None:
        """触发工具创造管线创建新工具"""
        from core.tool_creator import ToolCreationPipeline

        pipeline = ToolCreationPipeline(memory=self.memory)
        result = await pipeline.create(tool_spec, task)
        return result
