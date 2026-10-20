# -*- coding: utf-8 -*-
"""
conftest.py —— 自动化测试公共配置
测试对象：
  Python 后台 http://localhost:5001（财务登录/看图表/发薪入口）
  Java 考勤服务 http://localhost:8080（最终数据源）

前置条件：Java 后端、Python 后端均已启动。
"""
import time

import pytest
import requests

PY_BASE = "http://localhost:5001"    # Python 后台（本项目自己的）
JAVA_BASE = "http://localhost:8080"  # Java 考勤服务
USERNAME = "wangfang"                # 财务部唯一员工
PASSWORD = "123456"
YEAR, MONTH = 2026, 7
EXPECTED_TOTAL_NET = 215797.59       # 与 Java 统计一致的实发总额


def py_request(method, path, token=None, **kwargs):
    """调用 Python 后台接口"""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.request(method, f"{PY_BASE}{path}", headers=headers, timeout=15, **kwargs)


def java_request(method, path, token=None, **kwargs):
    """直接调用Java 接口（用于核对状态）"""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return requests.request(method, f"{JAVA_BASE}{path}", headers=headers, timeout=15, **kwargs)


@pytest.fixture(scope="session", autouse=True)
def purge_queue():
    """清空 RabbitMQ 发薪队列：避免之前模拟压测的积压消息阻塞真实发薪"""
    try:
        requests.delete(
            "http://localhost:15672/api/queues/%2F/pt.salary.pay.queue/contents",
            auth=("admin", "123456"), timeout=10)
    except Exception:
        pass


@pytest.fixture(scope="session")
def java_token():
    """先登录 Java 拿一个 token（供校准/重置数据用）"""
    r = requests.post(f"{JAVA_BASE}/api/auth/login",
                      json={"username": USERNAME, "password": PASSWORD}, timeout=15)
    assert r.json()["code"] == 0, "登录 Java 失败"
    return r.json()["data"]["token"]


@pytest.fixture(scope="session")
def reset_salary(java_token):
    """重置 2026年7月 工资单为「待发放」，保证发薪用例可重复执行"""
    r = java_request("POST", f"/api/salary/calculate?year={YEAR}&month={MONTH}",
                     token=java_token)
    assert r.json()["code"] == 0
    return True


@pytest.fixture(scope="module")
def finance_session():
    """财务（王芳）在 Python 后台登录，拿到 Python 侧会话 token"""
    r = py_request("POST", "/api/login",
                   json={"username": USERNAME, "password": PASSWORD})
    assert r.status_code == 200, f"登录失败: {r.text}"
    body = r.json()
    assert body["code"] == 0, f"登录失败: {body}"
    return {"token": body["data"]["token"], "user": body["data"]}


def wait_until_paid(record_id, timeout=8):
    """轮询 Java 工资单，等待状态变为「已发放」"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        # 用 java_token 需要重新登录，这里通过 finance 的 token 不便跨 fixture；
        # 直接重新登录 Java 拿 token 查询
        r = requests.post(f"{JAVA_BASE}/api/auth/login",
                          json={"username": USERNAME, "password": PASSWORD}, timeout=15)
        tok = r.json()["data"]["token"]
        resp = java_request("GET", f"/api/salary/list?year={YEAR}&month={MONTH}", token=tok)
        for rec in resp.json()["data"]:
            if rec["id"] == record_id:
                if rec["status"] == "已发放":
                    return rec
                break
        time.sleep(0.5)
    raise AssertionError(f"工资单 #{record_id} 在 {timeout}s 内未变为「已发放」")
