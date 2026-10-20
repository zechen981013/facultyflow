# -*- coding: utf-8 -*-
"""
mcp_server.py —— FastMCP 发工资工具
====================================
把"给某人发工资"封装成一个 MCP 工具。
工具内部：登录考勤服务（财务部）→ 查工资单 → 调 Java /api/salary/pay 发放。

启动（stdio 模式，供 MCP 客户端调用）：
    cd student/python_app && python mcp_server.py
调试（交互式调用工具）：
    fastmcp run mcp_server.py
"""
from fastmcp import FastMCP
from java_client import JavaClient

mcp = FastMCP("salary-pay")

FINANCE_USER = "wangfang"
FINANCE_PASSWORD = "123456"


@mcp.tool
def pay_salary_by_name(employee_name: str, year: int = 2026, month: int = 7) -> str:
    """给指定员工发放某月工资（通过考勤服务的 RabbitMQ 异步发放）。

    Args:
        employee_name: 员工姓名（如 王芳）
        year: 年份，默认 2026
        month: 月份，默认 7
    """
    java = JavaClient()
    user = java.login(FINANCE_USER, FINANCE_PASSWORD)   # 共用用户表，财务部登录
    if user.get("departmentName") != "财务部":
        return f"无权限：当前账号非财务部（{user.get('departmentName')}）"

    records = java.get_salary_list(year, month)
    matches = [r for r in records if r.get("name") == employee_name]
    if not matches:
        names = "、".join(r.get("name", "") for r in records)
        return f"未找到员工「{employee_name}」。当月工资单中的人员：{names}"

    record = matches[0]
    if record.get("status") != "待发放":
        return f"员工「{employee_name}」的工资单当前状态为「{record.get('status')}」，无法发放（只有待发放可发）"

    result = java.pay([record["id"]])
    return (f"已为「{employee_name}」发起发放：工资单 #{record['id']}，"
            f"应发 {record.get('grossSalary')} 元，实发 {record.get('netSalary')} 元。"
            f"请求已投递 RabbitMQ（{result.get('sent')}/{result.get('total')}），稍后刷新可见发放结果。")


@mcp.tool
def simulate_high_concurrency(count: int = 20000) -> str:
    """模拟 count 人同时发工资（默认 20000），验证 RabbitMQ 削峰填谷。

    Args:
        count: 模拟人数，默认 20000
    """
    java = JavaClient()
    user = java.login(FINANCE_USER, FINANCE_PASSWORD)
    if user.get("departmentName") != "财务部":
        return f"无权限：当前账号非财务部（{user.get('departmentName')}）"
    result = java.simulate_pay(count)
    return (f"已向 RabbitMQ 队列投递 {result.get('sent')} 条模拟发放请求，"
            f"消费者将按自身能力逐条消费（削峰填谷）。")


if __name__ == "__main__":
    mcp.run()
