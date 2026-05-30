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
            filtered_tools = self._filter_tools(tools, task.description)

            # 有工具：让 LLM 选择工具并调用
            system_prompt = (
                "你是执行器。你必须调用工具来完成任务。"
                "如果任务说'调价'/'调整售价'/'定价'，你必须调用 adjust_price 工具。"
                "如果任务说'推进时间'/'下一天'，你必须调用 advance_day 工具。"
                "如果任务说'补货'/'采购'，你必须调用 restock_inventory 工具。"
                "如果任务说'广告'/'投放'，你必须调用 run_ad_campaign 工具。"
                "不要返回纯文本分析结果——你必须调用工具。"
                "只读查询（市场状态/日报/竞品）才用 get_ 开头的工具。"
            )
            response = await self._llm.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": task.description},
                ],
                tools=filtered_tools,
                temperature=0.1,
            )

            msg = response.choices[0].message

            # 检查 tool_calls
            if msg.tool_calls:
                tool_call = msg.tool_calls[0]
                tool_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)
                return await self._run_tool(tool_name, args, task)

            # 回退：从文本解析
            content = msg.content or ""
            parsed = self._parse_tool_call(content)
            if parsed:
                return await self._run_tool(parsed["tool"], parsed["args"], task)

            # LLM没有调用工具 → 检测是否需要副作用
            if self._requires_side_effects(task.description):
                return ExecutionResult(
                    success=False,
                    error=f"任务需要副作用操作，但LLM未调用任何工具。幻觉输出: {content[:200]}",
                    trace=f"tool_calls为空。LLM返回了纯文本但任务要求生成/执行/创建。归因: tool_vacuum",
                    tool_called="llm_hallucination",
                )

            # LLM返回纯文本但内容空洞 → 极小置信度
            if len(content.strip()) < 20 and not tools:
                return ExecutionResult(
                    success=False,
                    error=f"LLM返回结果为空或过短，可能不具备该能力。输出: {content[:100]}",
                    tool_called="llm_empty",
                )

            return ExecutionResult(success=True, output=content, tool_called="llm_direct")

        except Exception as e:
            return ExecutionResult(
                success=False,
                error=str(e),
                trace=traceback.format_exc(),
            )

    async def _run_tool(self, name: str, args: dict, task: Task) -> ExecutionResult:
        """在内存中执行已注册的工具函数"""
        tool = self._find_tool(name)
        if not tool:
            return ExecutionResult(success=False, error=f"工具未找到: {name}")

        logger.info("execute.tool", name=name, args=args)
        if task:
            task.tools_used = [name]

        try:
            # 动态加载并执行工具代码
            namespace: dict[str, Any] = {}
            exec(tool.code, namespace)
            func = namespace.get(tool.name) or namespace.get(name)

            if not func:
                return ExecutionResult(success=False, error=f"工具执行错误: {name} - 函数未在代码中定义", tool_called=name)

            # 定价安全护栏：售价低于成本+10%毛利 → 拒绝
            if name == "adjust_price":
                price = args.get("price", 0)
                try:
                    import urllib.request, json as _j
                    with urllib.request.urlopen("http://127.0.0.1:5800/supplier-price", timeout=3) as r:
                        sp = _j.loads(r.read())["price"]
                    min_price = round(sp * 1.15, 2)
                    if price < min_price:
                        return ExecutionResult(
                            success=False,
                            error=f"定价错误: ${price} 低于最低合理售价 ${min_price} (供应商价${sp}×1.15)。请使用更高价格。",
                            tool_called=name,
                        )
                except Exception:
                    pass  # 网络异常时放行

            result = func(**args)
            return ExecutionResult(success=True, output=str(result), tool_called=name)

        except TypeError as e:
            # 工具存在但调用参数不匹配 → 标记为工具修复需求，不是路径熔断
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
    def _filter_tools(tools: list[dict], task_desc: str) -> list[dict]:
        """根据任务关键词智能过滤工具列表"""
        desc_lower = task_desc.lower()
        keywords = {
            "adjust_price": ["调价", "adjust", "定价", "售价", "价格调整"],
            "restock_inventory": ["补货", "采购", "restock", "库存", "进货"],
            "run_ad_campaign": ["广告", "ad", "投放", "campaign", "推广"],
            "advance_day": ["推进", "下一天", "advance", "next day", "过一天", "天数"],
            "get_competitor_price": ["竞品", "competitor", "对手"],
            "get_supplier_price": ["供应商", "supplier", "采购价"],
            "get_daily_report": ["日报", "daily", "报告", "report"],
            "get_market_status": ["市场状态", "market status", "全局", "概览"],
            "calculate": ["计算", "calculate", "公式", "求和"],
        }
        # 如果任务明确提到某个工具的关键词，只返回那个工具
        for tool_name, kws in keywords.items():
            if any(kw in desc_lower for kw in kws):
                # 找到匹配的工具 schema
                matched = [t for t in tools if t.get("function", {}).get("name") == tool_name]
                if matched:
                    return matched
        # 没匹配到关键词：返回所有只读工具 + calculate
        return [t for t in tools if t.get("function", {}).get("name", "").startswith("get_") or t.get("function", {}).get("name") == "calculate"]

    def _find_tool(self, name: str) -> Optional[CreatedTool]:
        for t in self.memory.tools.values():
            if t.name == name or t.schema.get("name") == name:
                return t
        return None

    @staticmethod
    def _parse_tool_call(text: str) -> Optional[dict]:
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                if "tool" in data:
                    return data
        except json.JSONDecodeError:
            pass
        return None

    async def create_tool(self, tool_spec: dict, failed_task: Task) -> Optional[CreatedTool]:
        """触发工具创造管线（委托给 ToolCreationPipeline）"""
        from core.tool_creator import ToolCreationPipeline
        pipeline = ToolCreationPipeline(memory=self.memory)
        return await pipeline.create(tool_spec, failed_task)
