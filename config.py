"""认知胚胎 — 全局配置"""

import os
from dataclasses import dataclass
from pathlib import Path

# 自动加载 .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class Config:
    # ── LLM (通过 OpenCode Zen 代理访问 DeepSeek) ──
    api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    base_url: str = os.getenv("CE_BASE_URL", "https://api.deepseek.com")
    model: str = os.getenv("CE_MODEL", "deepseek-chat")

    # OpenAI (备用)
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    # ── 兼容属性 (代码内统一用 config.api_key/base_url/model) ──
    llm_provider: str = os.getenv("CE_LLM_PROVIDER", "deepseek")

    # ── 执行 ──
    max_iterations: int = int(os.getenv("CE_MAX_ITERATIONS", "200"))
    max_retries_per_task: int = int(os.getenv("CE_MAX_RETRIES", "3"))
    introspection_interval: int = int(os.getenv("CE_INTROSPECTION_INTERVAL", "10"))
    sandbox_timeout: int = int(os.getenv("CE_SANDBOX_TIMEOUT", "30"))

    # ── 存储 ──
    memory_path: Path = Path(os.getenv("CE_MEMORY_PATH", "./data/memory.json"))
    audit_path: Path = Path(os.getenv("CE_AUDIT_PATH", "./data/audit.jsonl"))

    # ── 沙箱 ──
    sandbox_type: str = os.getenv("CE_SANDBOX_TYPE", "subprocess")  # subprocess | docker
    sandbox_image: str = os.getenv("CE_SANDBOX_IMAGE", "cognitive-embryo-sandbox:latest")

    # ── 安全 ──
    safety_enabled: bool = os.getenv("CE_SAFETY_ENABLED", "true").lower() == "true"
    auto_approve_tools: bool = os.getenv("CE_AUTO_APPROVE_TOOLS", "false").lower() == "true"

    # ── 目标审视 ──
    auto_revise_goals: bool = os.getenv("CE_AUTO_REVISE_GOALS", "false").lower() == "true"


config = Config()
