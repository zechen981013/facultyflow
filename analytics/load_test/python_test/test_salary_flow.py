# -*- coding: utf-8 -*-
"""
test_salary_flow.py —— 模拟财务「登录 → 看数据 → 发薪」全流程自动化测试

覆盖：
  1. 财务登录成功 / 非财务被拒 / 密码错误被拒
  2. 无 token 访问被拒
  3. 工资汇总（本月共计发薪）正确
  4. 分部门统计正确
  5. 工资单列表字段完整
  6. 发薪：单个发放 → 状态流转为「已发放」
  7. 发薪：幂等（已发放的不能重复发）
  8. 模拟高并发发薪入队
"""
import requests
import pytest

from conftest import (PY_BASE, JAVA_BASE, USERNAME, PASSWORD,
                      YEAR, MONTH, EXPECTED_TOTAL_NET,
                      py_request, java_request, wait_until_paid)


# ================= 1. 登录与权限 =================

def test_finance_login_success(finance_session):
    """财务部（王芳）登录成功，返回 Python 会话 token"""
    user = finance_session["user"]
    assert user["name"] == "王芳"
    assert user["departmentName"] == "财务部"
    assert finance_session["token"]


def test_non_finance_login_rejected():
    """非财务（技术部张伟）登录被拒"""
    r = py_request("POST", "/api/login",
                   json={"username": "zhangwei", "password": PASSWORD})
    assert r.status_code == 403
    assert "仅财务部" in r.json()["detail"]


def test_wrong_password_rejected():
    """密码错误被拒"""
    r = py_request("POST", "/api/login",
                   json={"username": USERNAME, "password": "wrong"})
    assert r.status_code == 401


def test_no_token_rejected():
    """不带 token 访问业务接口 → 401"""
    r = py_request("GET", "/api/overview")
    assert r.status_code == 401


# ================= 2. 数据统计（图表数据源） =================

def test_overview_total_net(reset_salary, finance_session):
    """本月共计发薪（实发总额）与 Java 统计一致"""
    data = py_request("GET", "/api/overview", token=finance_session["token"]).json()["data"]
    assert data["summary"]["totalNet"] == EXPECTED_TOTAL_NET
    assert data["summary"]["employeeCount"] == 21


def test_overview_dept_stats(finance_session):
    """分部门统计：技术部与销售部平均薪水正确"""
    data = py_request("GET", "/api/overview", token=finance_session["token"]).json()["data"]
    stats = {s["department"]: s for s in data["deptStats"]}
    assert stats["技术部"]["count"] == 10
    assert stats["销售部"]["count"] == 10
    assert stats["财务部"]["count"] == 1
    # 折线图/饼图数据非空
    assert len(data["line"]["dates"]) == 31
    assert sum(item["value"] for item in data["pie"]) == pytest.approx(EXPECTED_TOTAL_NET, abs=0.5)


# ================= 3. 工资单列表 =================

def test_salary_list_fields(finance_session):
    """工资单列表：21 条且关键字段齐全"""
    r = py_request("GET", "/api/salary/list", token=finance_session["token"])
    data = r.json()["data"]
    assert len(data) == 21
    for rec in data:
        assert "id" in rec and "name" in rec and "departmentName" in rec
        assert "grossSalary" in rec and "netSalary" in rec and "status" in rec


# ================= 4. 发薪流程 =================

def test_pay_single_and_status_change(reset_salary, finance_session):
    """单个发薪：投递后轮询 Java，状态最终变为「已发放」"""
    records = py_request("GET", "/api/salary/list", token=finance_session["token"]).json()["data"]
    pending = [r for r in records if r["status"] == "待发放"]
    assert pending, "重置后应存在待发放工资单"
    target = pending[0]

    r = py_request("POST", "/api/salary/pay", token=finance_session["token"],
                   json={"ids": [target["id"]]})
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["sent"] == 1

    paid = wait_until_paid(target["id"])
    assert paid["status"] == "已发放"
    assert paid["payDate"]  # 发放时间已记录


def test_pay_idempotent(reset_salary, finance_session):
    """幂等：同一工资单重复发，第二次不再重复投递"""
    records = py_request("GET", "/api/salary/list", token=finance_session["token"]).json()["data"]
    target = next(r for r in records if r["status"] == "待发放")

    first = py_request("POST", "/api/salary/pay", token=finance_session["token"],
                       json={"ids": [target["id"]]}).json()
    assert first["data"]["sent"] == 1

    # 立即再次发放（此时状态已是「发放中」或「已发放」）
    second = py_request("POST", "/api/salary/pay", token=finance_session["token"],
                        json={"ids": [target["id"]]}).json()
    assert second["data"]["sent"] == 0   # 已被跳过，未重复投递


def test_simulate_high_concurrency(finance_session):
    """模拟高并发发薪：投递指定条数到 RabbitMQ"""
    r = py_request("POST", "/api/salary/simulate", token=finance_session["token"],
                   json={"count": 100})
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["sent"] == 100
