"""Add Hermes bridge tools to seed tools in main.py"""
content = open('/home/suoyi/cognitive-embryo/main.py').read()

# Hermes bridge tools to inject
hermes_tools = '''
        ("hermes_search", "搜索网络获取实时信息(通过Tavily)",
'''import json, urllib.request
TAVILY_KEY = "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"
def hermes_search(query: str):
    data = json.dumps({"api_key": TAVILY_KEY, "query": query, "search_depth": "basic", "max_results": 3}).encode()
    req = urllib.request.Request("https://api.tavily.com/search", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        results = json.loads(r.read()).get("results", [])
    if not results:
        return json.dumps({"query": query, "results": []})
    return json.dumps({"query": query, "results": [{"title": r["title"], "content": r["content"][:300]} for r in results[:3]]}, ensure_ascii=False)''',
         {"name": "hermes_search", "description": "搜索网络获取实时信息，如市场趋势、新闻、竞品动态等",
          "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}}, "required": ["query"]}}),

        ("hermes_terminal", "在服务器执行命令(通过Hermes桥接)",
'''import subprocess
def hermes_terminal(command: str):
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
    out = result.stdout.strip()[:500]
    err = result.stderr.strip()[:200]
    if err: out += "\\nstderr: " + err
    return out or "(空输出)"''',
         {"name": "hermes_terminal", "description": "在服务器执行shell命令",
          "parameters": {"type": "object", "properties": {"command": {"type": "string", "description": "要执行的命令"}}, "required": ["command"]}}),
'''

# Inject before calculate tool
marker = '        ("calculate", "执行数学计算",'
if marker in content:
    content = content.replace(marker, hermes_tools + marker)
    open('/home/suoyi/cognitive-embryo/main.py', 'w').write(content)
    print("OK: hermes bridge tools injected")
else:
    print("FAIL: marker not found")
