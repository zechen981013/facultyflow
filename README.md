# FacultyFlow

员工考勤与工资发放系统：Spring Boot 3.5 + Vue 3 + MySQL 8.4 + RabbitMQ 高并发发薪，配套 Python 数据分析端。

## 模块

| 模块 | 说明 |
|---|---|
| `backend/` | Spring Boot 3.5 考勤与发薪服务 |
| `frontend/` | Vue 3 管理台 |
| `analytics/` | Python 数据分析与交叉校验脚本 |
| `pt.sql` | 初始化数据库 |

## 快速开始

1. 导入 `pt.sql` 初始化 MySQL 8.4。
2. 启动 `backend/` 与 `frontend/`。
3. 进入 `analytics/` 运行分析脚本查看统计结果。
