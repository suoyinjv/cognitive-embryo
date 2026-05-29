# OPA 安全策略 — 认知胚胎宪法规则
package cognitive_embryo.safety

# ── 默认拒绝 ──
default allow = false

# ── 允许安全的工具 ──
allow {
    input.action == "create_tool"
    not is_dangerous_code(input.code)
}

allow {
    input.action == "execute_task"
    not is_dangerous_task(input.task)
}

allow {
    input.action == "modify_memory"
    # 记忆修改需要人工审批
    input.approved == true
}

# ── 危险模式检测 ──

is_dangerous_code(code) {
    contains(code, "eval(")
}

is_dangerous_code(code) {
    contains(code, "exec(")
}

is_dangerous_code(code) {
    contains(code, "os.system")
}

is_dangerous_code(code) {
    contains(code, "subprocess.")
}

is_dangerous_code(code) {
    contains(code, "__import__")
}

is_dangerous_code(code) {
    contains(code, "socket.")
}

is_dangerous_task(task) {
    contains(lower(task.description), "hack")
}

is_dangerous_task(task) {
    contains(lower(task.description), "exploit")
}

is_dangerous_task(task) {
    contains(lower(task.description), "crack")
}
