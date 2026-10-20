# 员工考勤系统 · 工资计算与 RabbitMQ 总结文档

> 系统：Spring Boot 3.5 + Vue3 + MySQL 8.4 + RabbitMQ
> 本文总结两件事：① 工资是怎么算出来的（数据来源 → 处理 → 结果）；② RabbitMQ 从安装到收发消息的完整说明。

---

# 一、工资是怎么计算的

## 1.1 涉及的表与数据来源

工资计算一共用到 **4 张表**：

| 表 | 取什么数据 | 用途 |
| --- | --- | --- |
| `employee`（员工表） | `salary_type`（薪资类型）、`base_salary`（底薪） | 判断固定薪水还是销售，取底薪 |
| `attendance_record`（考勤记录表） | 每天 `status`（正常/迟到/早退/迟到早退/请假/缺勤/休息）、`check_in_time`、`check_out_time` | 计算固定薪水的考勤扣款 |
| `sales_record`（销售业绩表） | `amount`（当月销售额） | 计算销售提成 |
| `salary_record`（工资记录表） | — | **最终计算结果写入这张表** |

计算入口：后端 `SalaryService.calculate(year, month)`，一次算出全公司 21 人的工资。

## 1.2 计算流程（以 2026 年 7 月为例）

```
employee.base_salary
   │
   ├── 薪资类型 = FIXED（固定薪水，如技术部/财务部）
   │      │
   │      ├─ 日薪 = 底薪 ÷ 21.75            （21.75 = 月计薪天数）
   │      ├─ 时薪 = 日薪 ÷ 8                （每天 8 小时）
   │      │
   │      ├─ 逐天遍历 attendance_record：
   │      │    · 正常       → 不扣款
   │      │    · 迟到       → 扣 时薪 × 迟到分钟/60
   │      │    · 早退       → 扣 时薪 × 早退分钟/60
   │      │    · 迟到早退   → 两项都扣
   │      │    · 请假       → 扣 1 天（8 小时）的日薪
   │      │    · 缺勤(旷工) → 扣 3 倍日薪
   │      │
   │      └─ 应发 gross = 底薪 − 考勤扣款（最低为 0）
   │
   └── 薪资类型 = SALES（销售，如销售部）
          │
          ├─ 销售额 < 10 万  → 提成 = 销售额 × 3%
          ├─ 销售额 ≥ 10 万  → 提成 = 销售额 × 5%
          │
          └─ 应发 gross = 底薪 + 提成

        （销售只按"底薪+提成"，不再做考勤扣款，规则见需求要求）

gross（应发工资）
   │
   ├─ 五险一金 social = gross × 20%（个人承担比例，可配置）
   ├─ 应纳税所得额 = gross − 个税起征点 5000 − 五险一金
   ├─ 个人所得税 tax = 应纳税所得额 × 税率 − 速算扣除数（月度超额累进，3%~45%）
   │
   └─ 实发 net = gross − 五险一金 − 个税

→ 写入 salary_record 表（状态默认"待发放"）
```

## 1.3 个税税率表（月度预扣，深圳/全国统一）

| 级数 | 应纳税所得额（元） | 税率 | 速算扣除数 |
| --- | --- | ---: | ---: |
| 1 | ≤ 3,000 | 3% | 0 |
| 2 | 3,000 ~ 12,000 | 10% | 210 |
| 3 | 12,000 ~ 25,000 | 20% | 1,410 |
| 4 | 25,000 ~ 35,000 | 25% | 2,660 |
| 5 | 35,000 ~ 55,000 | 30% | 4,410 |
| 6 | 55,000 ~ 80,000 | 35% | 7,160 |
| 7 | > 80,000 | 45% | 15,160 |

## 1.4 示例：王芳（财务部，固定薪水，底薪 15000）

- 7 月考勤：7/1 请假 1 天、7/13 迟到 14 分钟、7/16 迟到 9 分钟
- 日薪 = 15000 / 21.75 ≈ 689.66；时薪 ≈ 86.21
- 考勤扣款 = 689.66（请假1天）+ 86.21×14/60（迟到）+ 86.21×9/60（迟到）≈ **722.70**
- 应发 = 15000 − 722.70 = **14,277.30**
- 五险一金 = 14,277.30 × 20% = **2,855.46**
- 应纳税所得额 = 14,277.30 − 5000 − 2,855.46 = 6,421.84 → 个税 = 6,421.84×10% − 210 = **432.18**
- **实发 = 14,277.30 − 2,855.46 − 432.18 = 10,989.66**

> 例：冯雪（销售经理，底薪 8000，7 月销售额 36 万）→ 提成 = 36万×5% = 18,000，应发 = 8,000+18,000 = 26,000。

## 1.5 结果存哪

计算完成后写入 **`salary_record`** 表，一条记录一人一月，字段包括：底薪、考勤扣款、提成、应发、五险一金、个税、实发、**状态**（待发放→发放中→已发放）、发放时间。

- 相关代码：`backend/.../service/SalaryService.java`（计算）、`service/TaxCalculator.java`（个税）、`controller/SalaryController.java`（接口）
- 交叉验证版（Python）：`analytics/salary_calc.py`，与 Java 计算结果完全一致

---

# 二、RabbitMQ 总结

## 2.1 RabbitMQ 是什么

RabbitMQ 是一个**消息队列（Message Queue）中间件**，基于 AMQP 协议（Erlang 编写）。核心作用：

- **异步解耦**：生产者只管发消息，不用等消费者处理完
- **削峰填谷**：突发流量（如 20000 人同时发工资）先全部进队列，消费者按自己能力慢慢消费，防止把数据库/系统打垮
- **可靠投递**：消息持久化到磁盘，消费者没确认前不会丢

## 2.2 核心概念（架构）

```
生产者 Producer
   │  发送消息(convertAndSend)
   ▼
交换机 Exchange（pt.salary.exchange，direct 直连型）
   │  按路由键(RoutingKey)分发
   ▼
队列 Queue（pt.salary.pay.queue，持久化）
   │  消费者按自身能力拉取/订阅
   ▼
消费者 Consumer（@RabbitListener）
```

| 概念 | 本系统中的配置 |
| --- | --- |
| **Producer 生产者** | 后端 `PayService`，发工资时把请求发给交换机 |
| **Exchange 交换机** | `pt.salary.exchange`（direct 直连型，按 RoutingKey 精确匹配） |
| **RoutingKey 路由键** | `pt.salary.pay` |
| **Queue 队列** | `pt.salary.pay.queue`（durable 持久化，重启不丢） |
| **Consumer 消费者** | `SalaryPayConsumer`，`@RabbitListener` 监听队列 |
| **Binding 绑定** | 把 队列 绑定到 交换机（queue → exchange with routingKey） |
| **Message 消息** | `PayMessage`（工资单ID、员工、金额等），JSON 序列化 |

> 交换机本身不存消息，它只负责"路由"；真正存消息的是**队列**。一条消息 = 一次发薪请求。

## 2.3 安装（Docker 一键启动）

镜像 `rabbitmq:3-management`（自带 Web 管理台）：

```bash
# 单独启动
docker run -d --name pt-rabbitmq \
  -p 5672:5672 -p 15672:15672 \
  -e RABBITMQ_DEFAULT_USER=admin \
  -e RABBITMQ_DEFAULT_PASS=123456 \
  rabbitmq:3-management

# 或随项目 docker compose up -d（docker-compose.yml 已包含 rabbitmq 服务）
```

- `5672`：业务端口（程序收发消息用）
- `15672`：Web 管理台 → 浏览器访问 http://localhost:15672（admin / 123456）

> 国内拉镜像慢时可用镜像源：`docker pull docker.m.daocloud.io/rabbitmq:3-management` 后 `docker tag` 回原名。

## 2.4 怎么发数据（生产者）

后端 `PayService.pay(ids)`：

```java
// 1. 把消息对象放到交换机，路由键指定，消息自动进入队列
rabbitTemplate.convertAndSend(
    RabbitConfig.SALARY_EXCHANGE,     // pt.salary.exchange
    RabbitConfig.SALARY_ROUTING_KEY,  // pt.salary.pay
    new PayMessage(rec.getId(), rec.getEmployeeId(), ...) // 消息体
);
```

要点：
- 发之前先把工资单状态置为"发放中"（防止重复提交）
- 消息体 `PayMessage` 通过 `Jackson2JsonMessageConverter` 自动转成 JSON
- 批量发放 = 循环调用一次发一条；"模拟 20000 人" = 循环发 20000 条，瞬间全部进队列（**这就是削峰，请求不会压垮数据库**）

配置（application.yml）：

```yaml
spring:
  rabbitmq:
    host: rabbitmq      # 地址（本地跑填 localhost）
    port: 5672
    username: admin
    password: "123456"
```

## 2.5 怎么拿数据（消费者）

后端 `SalaryPayConsumer`：

```java
@RabbitListener(queues = RabbitConfig.SALARY_QUEUE, concurrency = "1")
public void onMessage(PayMessage message) {
    Thread.sleep(30);                    // 模拟银行打款耗时
    // 按工资单ID 查库 → 状态改为"已发放" → 记录发放时间
    rec.setStatus("已发放");
    rec.setPayDate(LocalDateTime.now());
    salaryRecordRepository.save(rec);
}
```

要点：
- `concurrency = "1"` + `prefetch = 1`：**每次只取 1 条、单线程消费**，消费者"按自己的能力"慢慢处理 → 这就是**填谷**
- 消息处理成功（方法正常返回）→ RabbitMQ 自动 ack，消息从队列删除
- 处理异常 → 记录"发放失败"，防止消息丢失

## 2.6 削峰填谷演示（20000 人同时发工资）

| 时间 | 队列状态 |
| --- | --- |
| 0 秒 | 20000 条消息瞬间入队，队列积压 20000（**峰**） |
| 持续 | 消费者约 46ms/条 匀速处理，队列逐渐减少（**谷**） |
| ~15 分钟 | 全部消费完毕，队列归零，21 张真实工资单全部"已发放" |

后台日志实时可见：`[模拟发放] 模拟员工-xxx 处理完成`。

## 2.7 管理台怎么看

http://localhost:15672（admin/123456）：

- **Overview**：整体消息速率、连接数
- **Queues**：找到 `pt.salary.pay.queue`，可看到 **Ready（待消费）/ Unacked（处理中）** 数量 —— 模拟 20000 时这里能看到积压暴涨再缓慢下降
- **Exchanges / Bindings**：查看交换机与绑定关系
- **Connections / Channels**：查看后端生产者/消费者的连接

## 2.8 关键代码位置

| 文件 | 作用 |
| --- | --- |
| `backend/.../config/RabbitConfig.java` | 声明交换机、队列、绑定、JSON 消息转换器 |
| `backend/.../service/PayService.java` | 生产者：发工资（单个/批量/模拟20000） |
| `backend/.../service/PayMessage.java` | 消息体 |
| `backend/.../mq/SalaryPayConsumer.java` | 消费者：监听队列，落库改状态 |
| `backend/.../controller/SalaryController.java` | 发薪/模拟并发接口 |

---

*本文基于项目实际代码与运行结果整理，数据与线上一致。*
