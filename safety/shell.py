"""安全与对齐外壳 — 跨层审计"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

from structlog import get_logger

from config import config

logger = get_logger(__name__)

# ── 宪法规则 ──

DANGEROUS_PATTERNS = [
    r'eval\s*\(',
    r'exec\s*\(',
    r'__import__\s*\(',
    r'os\.system\s*\(',
    r'subprocess\.',
    r'socket\.',
    r'requests\.delete',
    r'requests\.put',
    r'os\.remove\s*\(',
    r'shutil\.rmtree',
    r'/etc/passwd',
    r'/proc/',
]


class SafetyShell:
    """安全审计中间件 — OPA 规则 + 链式审计日志"""

    def __init__(self, audit_path: Optional[Path] = None) -> None:
        self.audit_path = audit_path or config.audit_path
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_hash = self._read_last_hash()
        self.enabled = config.safety_enabled

    # ── 任务审查 ──

    def approve(self, task) -> bool:
        """审查任务是否安全"""
        if not self.enabled:
            return True

        desc = task.description if hasattr(task, "description") else str(task)
        # 检查是否有高危关键词
        dangerous = ["hack", "exploit", "crack", "bypass firewall", "sql injection"]
        for kw in dangerous:
            if kw in desc.lower():
                self._audit("task_reject", str(task.id)[:20], "block", f"危险关键词: {kw}")
                return False

        self._audit("task_approve", str(task.id)[:20], "allow")
        return True

    # ── 代码审查 ──

    def approve_code(self, code: str) -> tuple[bool, list[str]]:
        """审查生成代码"""
        if not self.enabled:
            return True, []

        violations = []
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                violations.append(f"危险模式: {pattern}")

        if violations:
            self._audit("code_reject", f"code_{hash(code) % 10000}", "block", "; ".join(violations))
            return False, violations

        self._audit("code_approve", f"code_{hash(code) % 10000}", "allow")
        return True, []

    # ── 工具审查 ──

    def approve_tool(self, tool_name: str) -> bool:
        """审查工具名称"""
        dangerous_names = {"hack", "exploit", "steal", "bypass", "crack", "inject", "backdoor"}
        if tool_name.lower() in dangerous_names:
            self._audit("tool_reject", tool_name, "block", "危险工具名")
            return False
        return True

    # ── 审计日志 ──

    def _audit(self, action: str, target: str, verdict: str, detail: str = "") -> None:
        entry = {
            "action": action,
            "target": target,
            "verdict": verdict,
            "detail": detail,
        }
        entry_json = json.dumps(entry, ensure_ascii=False)
        entry["signature"] = hashlib.sha256(
            (self._last_hash + entry_json).encode()
        ).hexdigest()
        self._last_hash = entry["signature"]

        with open(self.audit_path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        if verdict == "block":
            logger.warning("safety.block", action=action, target=target, detail=detail)
        else:
            logger.debug("safety.allow", action=action, target=target)

    def _read_last_hash(self) -> str:
        if not self.audit_path.exists():
            return ""
        with open(self.audit_path) as f:
            last = ""
            for line in f:
                last = line
            if last:
                try:
                    return json.loads(last).get("signature", "")
                except Exception:
                    pass
        return ""
