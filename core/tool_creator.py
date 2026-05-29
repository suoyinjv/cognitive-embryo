"""工具创造管线 — 6 步流水线: 规范→编码→测试→验证→注册"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI
from structlog import get_logger

from config import config
from core.memory import CreatedTool, Task

logger = get_logger(__name__)

# ── Prompt 模板 ──

CODE_GEN_SYSTEM = """你是 Python 代码生成器。只输出代码，不要解释。
要求:
1. 完整的 type hints
2. 完整的 docstring
3. 只使用 Python 标准库 (urllib.request, json, math 等)
4. 代码放在 ```python ``` 代码块中
5. 如果需要与外部服务通信, 以下是可用的 HTTP API 端点:
   - GET http://127.0.0.1:5800/market-status → 市场全局状态(竞品/供应商/库存/广告/日/利润)
   - GET http://127.0.0.1:5800/competitor-price → 竞品均价+竞品数量
   - GET http://127.0.0.1:5800/supplier-price → 供应商采购价+趋势
   - GET http://127.0.0.1:5800/daily-sales → 销售报告(收入/成本/利润/销量)
   - POST http://127.0.0.1:5800/pricing (body: {"price": 12.5}) → 设置售价
   - POST http://127.0.0.1:5800/ad-spend (body: {"budget": 100}) → 投放广告
   - POST http://127.0.0.1:5800/inventory (body: {"units": 50}) → 补货
   - POST http://127.0.0.1:5800/tick (body: {}) → 推进一天+触发随机事件
6. 函数应使用 urllib.request 调用真实 API，不要伪造数据"""

TEST_GEN_SYSTEM = """你是测试用例生成器。为函数生成 5 个 pytest 风格的测试。
要求:
1. 函数名以 test_ 开头
2. 使用 assert 断言
3. 覆盖正常/边界/异常场景
4. 只输出代码在 ```python ``` 中
5. 不要写任何 import 语句（函数和测试代码已经在同一个文件中）
6. 不要写 from xxx import yyy
7. 直接调用被测函数，假设它已在当前作用域中"""

SCHEMA_EXTRACT_SYSTEM = """从代码提取 OpenAI function-calling schema。
输出 JSON:
{"name": "函数名", "description": "描述", "parameters": {"type": "object", "properties": {...}, "required": [...]}}"""


class ToolCreationPipeline:
    """工具创造管线"""

    def __init__(self, sandbox_image: str = "", memory=None) -> None:
        self.sandbox_image = sandbox_image or config.sandbox_image
        self.memory = memory
        # TCP 代码生成也使用同一 provider (DeepSeek)
        self._llm = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self._model = config.model

    async def create(self, tool_spec: dict, failed_task: Task) -> Optional[CreatedTool]:
        tool_id = uuid.uuid4().hex[:8]
        logger.info("tcp.start", tool_id=tool_id, name=tool_spec.get("name", "?"))

        # 修复模式: 已有工具存在 bug，直接修复它的代码
        if tool_spec.get("fix_existing"):
            tool_name = tool_spec.get("name", "")
            return await self._fix_existing_tool(tool_name, tool_spec.get("error", ""), failed_task)

        # Step 1: 生成代码
        code = await self._generate_code(tool_spec)
        if not code:
            return None

        # Step 2: 生成测试
        tests = await self._generate_tests(tool_spec, code)
        if not tests:
            return None

        # Step 3: 沙盒验证
        passed, results = await self._sandbox_verify(code, tests)
        if not passed:
            # 尝试自动修复一次
            logger.info("tcp.fix_attempt")
            code = await self._fix_code(code, results)
            tests = await self._generate_tests(tool_spec, code)
            passed, results = await self._sandbox_verify(code, tests)
            if not passed:
                logger.error("tcp.verify_failed", results=results)
                return None

        # Step 4: 提取 schema
        schema = await self._extract_schema(code)

        tool = CreatedTool(
            id=tool_id,
            name=tool_spec.get("name", f"tool_{tool_id}"),
            code=code,
            schema=schema,
            test_results=results,
        )
        logger.info("tcp.created", name=tool.name, id=tool.id)
        return tool

    async def _fix_existing_tool(self, tool_name: str, error: str, failed_task: Task) -> Optional[CreatedTool]:
        """修复模式下: 拿已有工具的代码，让 LLM 修复参数签名/运行时错误"""
        if not self.memory:
            logger.error("tcp.fix_no_memory")
            return None

        # 从 memory 中查找已有工具
        existing = None
        for t in self.memory.tools.values():
            if t.name == tool_name:
                existing = t
                break
        if not existing:
            logger.error("tcp.fix_not_found", name=tool_name)
            return None

        logger.info("tcp.fix_start", name=tool_name, error=error[:80])

        fix_prompt = f"""以下工具调用时出错，请修复代码。

工具名: {tool_name}
错误: {error}

现有代码:
```python
{existing.code}
```

要求:
1. 修复参数签名错误 — 如果是参数不匹配，请确保函数不需要多余参数或设置默认值
2. 保持原有功能不变
3. 从模拟器 API 获取真实数据 (http://127.0.0.1:5800/)
4. 输出完整修复后的代码放在 ```python ``` 中"""

        resp = await self._llm.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": fix_prompt}],
            temperature=0.2,
        )
        new_code = self._extract_code_block(resp.choices[0].message.content or "")
        if not new_code:
            return None

        # 重新生成测试并验证
        tests = await self._generate_tests({"name": tool_name, "description": f"修复 {tool_name}"}, new_code)
        if not tests:
            return None

        passed, results = await self._sandbox_verify(new_code, tests)
        if not passed:
            logger.info("tcp.fix_retry")
            new_code = await self._fix_code(new_code, results)
            tests = await self._generate_tests({"name": tool_name, "description": f"修复 {tool_name}"}, new_code)
            passed, results = await self._sandbox_verify(new_code, tests)
            if not passed:
                logger.error("tcp.fix_failed", results=results)
                return None

        # 返回修复后的工具（用新 id 但同名，注册时会覆盖旧工具）
        schema = await self._extract_schema(new_code)
        tool_id = uuid.uuid4().hex[:8]
        tool = CreatedTool(
            id=tool_id,
            name=tool_name,
            code=new_code,
            schema=schema,
            source="self_created",
            test_results=results,
        )
        logger.info("tcp.fix_done", name=tool_name, id=tool.id)
        return tool

    # ── Step 1: 生成代码 ──

    async def _generate_code(self, spec: dict) -> str:
        prompt = f"""根据需求生成 Python 函数:
{json.dumps(spec, ensure_ascii=False, indent=2)}"""
        resp = await self._llm.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": CODE_GEN_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        return self._extract_code_block(resp.choices[0].message.content or "")

    # ── Step 2: 生成测试 ──

    async def _generate_tests(self, spec: dict, code: str) -> str:
        prompt = f"""为以下函数生成测试用例:
```python
{code}
```"""
        resp = await self._llm.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": TEST_GEN_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        return self._extract_code_block(resp.choices[0].message.content or "")

    # ── Step 3: 沙盒验证 ──

    async def _sandbox_verify(self, code: str, tests: str) -> tuple[bool, list[dict]]:
        # 清理测试代码中的残留 import
        tests = self._clean_test_imports(tests)
        combined = f"""{code}

{tests}

import json, sys, traceback

results = []
test_funcs = [(n, f) for n, f in list(globals().items()) if n.startswith('test_') and callable(f)]
for name, func in test_funcs:
    try:
        func()
        results.append({{"test": name, "status": "pass"}})
    except Exception as e:
        results.append({{"test": name, "status": "fail", "error": str(e)}})

print(json.dumps(results))
"""
        if config.sandbox_type == "docker":
            return await self._docker_execute(combined)
        return await self._subprocess_execute(combined)

    async def _subprocess_execute(self, code: str) -> tuple[bool, list[dict]]:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            tmp_path = f.name

        try:
            result = subprocess.run(
                ["python3", tmp_path],
                capture_output=True, text=True, timeout=config.sandbox_timeout,
            )
            if result.returncode != 0:
                return False, [{"test": "compile", "status": "fail", "error": result.stderr[:500]}]
            try:
                results = json.loads(result.stdout.strip().split("\n")[-1])
            except json.JSONDecodeError:
                results = [{"test": "parse", "status": "fail", "error": result.stdout[:200]}]
            passed = all(r["status"] == "pass" for r in results)
            return passed, results
        except subprocess.TimeoutExpired:
            return False, [{"test": "timeout", "status": "fail", "error": f"{config.sandbox_timeout}s timeout"}]
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def _docker_execute(self, code: str) -> tuple[bool, list[dict]]:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            tmp_path = f.name

        try:
            result = subprocess.run(
                ["docker", "run", "--rm", "--network=none", "--memory=256m", "--cpus=0.5",
                 "-v", f"{tmp_path}:/code/test.py:ro", self.sandbox_image,
                 "python", "/code/test.py"],
                capture_output=True, text=True, timeout=config.sandbox_timeout + 5,
            )
            results = json.loads(result.stdout.strip().split("\n")[-1])
            passed = all(r["status"] == "pass" for r in results)
            return passed, results
        except Exception as e:
            return False, [{"test": "docker", "status": "fail", "error": str(e)}]
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    # ── Step 4: 提取 schema ──

    async def _extract_schema(self, code: str) -> dict:
        resp = await self._llm.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": SCHEMA_EXTRACT_SYSTEM},
                {"role": "user", "content": f"```python\n{code}\n```"},
            ],
            temperature=0.1,
        )
        text = resp.choices[0].message.content or ""
        try:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
        return {"name": "unknown", "description": "", "parameters": {"type": "object", "properties": {}, "required": []}}

    # ── 自动修复 ──

    async def _fix_code(self, code: str, test_results: list[dict]) -> str:
        failures = [r for r in test_results if r["status"] == "fail"]
        if not failures:
            return code

        prompt = f"""以下代码的测试用例失败，请修复代码:
```python
{code}
```

失败测试:
{json.dumps(failures, ensure_ascii=False)}

修复代码并放在 ```python ``` 中。"""
        resp = await self._llm.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        fixed = self._extract_code_block(resp.choices[0].message.content or "")
        return fixed or code

    # ── 工具方法 ──

    @staticmethod
    def _clean_test_imports(tests: str) -> str:
        """清理测试代码中的残留 import 语句"""
        lines = tests.split("\n")
        cleaned = []
        for line in lines:
            stripped = line.strip()
            # 移除 from xxx import yyy 和 import xxx
            if stripped.startswith("from ") and "import" in stripped:
                if "your_module" in stripped or "pricing_module" in stripped:
                    continue
            if stripped.startswith("import ") and not stripped.startswith("import json") and not stripped.startswith("import math"):
                if stripped.split()[1] not in ("json", "math", "statistics", "sys"):
                    continue
            cleaned.append(line)
        return "\n".join(cleaned)

    @staticmethod
    def _extract_code_block(text: str) -> str:
        m = re.search(r'```(?:python)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        return m.group(1).strip() if m else text.strip()
