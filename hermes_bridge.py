"""Hermes Bridge v2 — 轻量版, 直接调API不走Hermes进程"""

import json
import subprocess
import urllib.request
from typing import Optional


class HermesBridge:
    """桥接真实世界工具"""
    
    TAVILY_KEY = "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"
    
    def search(self, query: str, max_results: int = 3) -> str:
        """用Tavily搜网络"""
        try:
            data = json.dumps({
                "api_key": self.TAVILY_KEY,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
            }).encode()
            req = urllib.request.Request(
                "https://api.tavily.com/search",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                result = json.loads(r.read())
            results = result.get("results", [])
            if not results:
                return f"(无搜索结果: {query})"
            lines = [f"--- {query} ---"]
            for i, item in enumerate(results[:max_results], 1):
                title = item.get("title", "?")
                content = item.get("content", "")[:200]
                lines.append(f"{i}. {title}: {content}")
            return "\n".join(lines)
        except Exception as e:
            return f"[搜索失败] {e}"
    
    def run_terminal(self, command: str) -> str:
        """执行命令"""
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=15
            )
            out = result.stdout.strip()[:500]
            err = result.stderr.strip()[:200]
            if err:
                out += f"\n(stderr: {err})"
            return out or "(空输出)"
        except subprocess.TimeoutExpired:
            return "[超时]"
        except Exception as e:
            return f"[错误] {e}"


if __name__ == "__main__":
    b = HermesBridge()
    r = b.search("AI Agent 2026发展趋势")
    print(r[:500])
