# -*- coding: utf-8 -*-
"""
app.py —— Python 项目后台（FastAPI，端口 5000）
================================================
分层对应：
  controller 层 = 本文件的路由（/api/...）
  service  层   = salary.py（工资计算业务）
  dao/api  层   = java_client.py（HTTP 调用Java 考勤服务）

登录走考勤服务的用户表（Java /api/auth/login），仅财务部可登录，
所有业务接口都需要先登录。

启动：cd student/python_app && uvicorn app:app --host 0.0.0.0 --port 5000
"""
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import salary
from java_client import JavaClient

YEAR, MONTH = 2026, 7
FINANCE_DEPT = "财务部"

app = FastAPI(title="Python 工资管理系统", description="Python 后台，调用Java 考勤服务")

# Python 侧会话：python_token -> {user, java}
SESSIONS = {}


# ---------------- 请求体模型 ----------------
class LoginBody(BaseModel):
    username: str
    password: str


class PayBody(BaseModel):
    ids: list[int]


class SimulateBody(BaseModel):
    count: int = 20000


# ---------------- 认证 ----------------
def require_session(authorization: str = Header(default="")):
    """校验 Python 侧 token，返回会话；无效则 401"""
    token = authorization.removeprefix("Bearer ").strip()
    sess = SESSIONS.get(token)
    if not sess:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    return sess


@app.post("/api/login")
def login(body: LoginBody):
    """登录：复用考勤服务的用户表（Java 系统），仅财务部可登录"""
    java = JavaClient()
    try:
        user = java.login(body.username, body.password)
    except RuntimeError as e:
        raise HTTPException(status_code=401, detail=str(e))
    if user.get("departmentName") != FINANCE_DEPT:
        raise HTTPException(status_code=403, detail=f"仅{FINANCE_DEPT}可登录本系统（当前部门：{user.get('departmentName')}）")
    token = uuid.uuid4().hex
    SESSIONS[token] = {"user": user, "java": java}
    return {"code": 0, "data": {"token": token, "name": user.get("name"),
                                "position": user.get("position"),
                                "departmentName": user.get("departmentName")}}


@app.post("/api/logout")
def logout(authorization: str = Header(default="")):
    token = authorization.removeprefix("Bearer ").strip()
    SESSIONS.pop(token, None)
    return {"code": 0, "data": None}


# ---------------- 业务接口 ----------------
@app.get("/api/overview")
def overview(year: int = YEAR, month: int = MONTH, authorization: str = Header(default="")):
    """首页总览：汇总 + 分部门平均 + 折线图数据 + 饼图数据"""
    sess = require_session(authorization)
    data = sess["java"].get_month_attendance(year, month)
    results = salary.compute_all(data)
    return {"code": 0, "data": {
        "year": year, "month": month,
        "summary": salary.summary(results),
        "deptStats": salary.dept_stats(results),
        "line": salary.line_data(results),
        "pie": salary.pie_data(results),
    }}


@app.get("/api/salary/list")
def salary_list(year: int = YEAR, month: int = MONTH, authorization: str = Header(default="")):
    """考勤服务里的工资单列表（带 id 和发放状态，供发薪勾选）"""
    sess = require_session(authorization)
    return {"code": 0, "data": sess["java"].get_salary_list(year, month)}


@app.post("/api/salary/pay")
def pay(body: PayBody, authorization: str = Header(default="")):
    """发工资：单个或批量，投递到服务端的 RabbitMQ 队列异步发放"""
    sess = require_session(authorization)
    return {"code": 0, "data": sess["java"].pay(body.ids)}


@app.post("/api/salary/simulate")
def simulate(body: SimulateBody, authorization: str = Header(default="")):
    """模拟高并发发薪（削峰填谷）"""
    sess = require_session(authorization)
    return {"code": 0, "data": sess["java"].simulate_pay(body.count)}


# ---------------- 静态前端 ----------------
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")
