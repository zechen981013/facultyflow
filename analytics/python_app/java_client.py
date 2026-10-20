# -*- coding: utf-8 -*-
"""
java_client.py —— Python 后台的 dao/api 层
================================================
封装对Java 考勤服务的所有 HTTP 调用。
作用等价于传统三层架构里的"dao 层"，但访问的不是数据库，
而是Java REST 接口（考勤服务负责读写 MySQL）。

调用链：Python 后台 ──HTTP+Token──▶ Java 后端(:8080) ──▶ MySQL
"""
import requests


class JavaClient:
    """Java 考勤服务的 HTTP 客户端"""

    def __init__(self, base="http://localhost:8080"):
        self.base = base.rstrip("/")
        self.token = None

    # ---------------- 认证 ----------------
    def login(self, username, password):
        """登录考勤服务，保存 token，返回用户信息"""
        r = requests.post(f"{self.base}/api/auth/login",
                          json={"username": username, "password": password},
                          timeout=15)
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(data.get("message", "登录失败"))
        self.token = data["data"]["token"]
        return data["data"]

    def _headers(self):
        if not self.token:
            raise RuntimeError("尚未登录考勤服务")
        return {"Authorization": f"Bearer {self.token}"}

    def _call(self, method, path, **kwargs):
        fn = getattr(requests, method)
        r = fn(f"{self.base}{path}", headers=self._headers(), timeout=20, **kwargs)
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(data.get("message", "接口调用失败"))
        return data.get("data")

    # ---------------- 业务接口 ----------------
    def get_month_attendance(self, year, month):
        """① 拿全员考勤数据（第 2 步）"""
        return self._call("get", "/api/attendance/month",
                          params={"year": year, "month": month})

    def calculate_salary(self, year, month):
        """让考勤服务计算工资并入库"""
        return self._call("post", "/api/salary/calculate",
                          params={"year": year, "month": month})

    def get_salary_list(self, year, month):
        """考勤服务里的工资单列表（带 id 和发放状态，发薪靠它）"""
        return self._call("get", "/api/salary/list",
                          params={"year": year, "month": month})

    def pay(self, ids):
        """发工资：单个或批量，投递到 RabbitMQ 队列异步处理"""
        return self._call("post", "/api/salary/pay", json={"ids": ids})

    def simulate_pay(self, count):
        """模拟高并发发薪（削峰填谷演示）"""
        return self._call("post", "/api/salary/pay/simulate",
                          params={"count": count})
