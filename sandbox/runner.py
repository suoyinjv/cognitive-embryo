"""沙盒执行入口 — Docker 容器内运行的测试 runner"""

import json
import sys
import traceback


def run_tests(code: str) -> list[dict]:
    """在隔离环境中执行代码和测试"""
    namespace: dict = {}
    try:
        exec(code, namespace)
    except Exception as e:
        return [{"test": "compile", "status": "fail", "error": str(e)}]

    # 收集 test_ 开头的函数
    test_funcs = [
        (name, func)
        for name, func in namespace.items()
        if name.startswith("test_") and callable(func)
    ]

    if not test_funcs:
        return [{"test": "all", "status": "fail", "error": "No test functions found"}]

    results = []
    for name, func in test_funcs:
        try:
            func()
            results.append({"test": name, "status": "pass"})
        except Exception as e:
            results.append({
                "test": name,
                "status": "fail",
                "error": f"{type(e).__name__}: {e}",
            })

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--code", type=str, required=True, help="Code to test (base64 or file path)")
    args = parser.parse_args()

    # Read code from file or stdin
    try:
        code = sys.stdin.read() if args.code == "-" else open(args.code).read()
    except FileNotFoundError:
        # Try base64 decode
        import base64
        try:
            code = base64.b64decode(args.code).decode()
        except Exception:
            print(json.dumps([{"test": "input", "status": "fail", "error": "Cannot read code"}]))
            sys.exit(1)

    results = run_tests(code)
    print(json.dumps(results, ensure_ascii=False))
    sys.exit(0 if all(r["status"] == "pass" for r in results) else 1)
