# -*- coding: utf-8 -*-
"""
salary.py —— 工资计算业务逻辑（Python 后台的 service 层）
==========================================================
按工资规则计算 2026 年 7 月工资：
  固定薪水：日薪=底薪/21.75，时薪=日薪/8；迟到/早退按分钟扣款、请假扣1天、旷工扣3倍
  销售：底薪+提成（<10万 3%，>=10万 5%）
  个税：月度超额累进，起征点 5000，五险一金个人 20%
"""
from collections import defaultdict

# ---------------- 配置常量（与考勤服务保持一致） ----------------
DAILY_DAYS = 21.75            # 月计薪天数
HOURS_PER_DAY = 8             # 每日标准工时
WORK_START = "08:30:00"       # 默认上班时间
WORK_END = "18:00:00"         # 默认下班时间
TAX_THRESHOLD = 5000          # 个税起征点
SOCIAL_RATE = 0.2             # 五险一金个人承担比例
# 月度超额累进税率表：(应纳税所得额上限, 税率, 速算扣除数)
TAX_BRACKETS = [
    (3000, 0.03, 0),
    (12000, 0.10, 210),
    (25000, 0.20, 1410),
    (35000, 0.25, 2660),
    (55000, 0.30, 4410),
    (80000, 0.35, 7160),
    (float('inf'), 0.45, 15160),
]


def to_minutes(t):
    """'HH:MM:SS' -> 当天分钟数"""
    if not t:
        return None
    parts = t.split(':')
    return int(parts[0]) * 60 + int(parts[1])


def day_deduction(rec, daily, hourly):
    """单天考勤扣款"""
    status = rec.get('status')
    if status == '迟到':
        late = max(to_minutes(rec.get('checkInTime')) - to_minutes(WORK_START), 0)
        return round(hourly * late / 60, 2)
    if status == '早退':
        early = max(to_minutes(WORK_END) - to_minutes(rec.get('checkOutTime')), 0)
        return round(hourly * early / 60, 2)
    if status == '迟到早退':
        late = max(to_minutes(rec.get('checkInTime')) - to_minutes(WORK_START), 0)
        early = max(to_minutes(WORK_END) - to_minutes(rec.get('checkOutTime')), 0)
        return round(hourly * (late + early) / 60, 2)
    if status == '请假':
        return daily
    if status == '缺勤':
        return daily * 3
    return 0.0


def calc_tax(taxable):
    """月度个人所得税：应纳税所得额 × 税率 − 速算扣除数"""
    if taxable <= 0:
        return 0.0
    for ceiling, rate, quick in TAX_BRACKETS:
        if taxable <= ceiling:
            return round(max(taxable * rate - quick, 0), 2)
    return 0.0


def compute_employee(emp):
    """按规则计算一名员工的工资，返回结果 dict"""
    base = float(emp.get('baseSalary') or 0)
    records = emp.get('records') or []
    salary_type = emp.get('salaryType')

    if salary_type == 'SALES':
        sales = float(emp.get('monthlySales') or 0)
        commission = round(sales * 0.05 if sales >= 100000 else sales * 0.03, 2)
        gross = round(base + commission, 2)
        deduction = 0.0
        daily_map = {}
        workdays = [r for r in records if r.get('status') != '休息']
        per_day = round(gross / len(workdays), 2) if workdays else 0.0
        for r in records:
            daily_map[r['date']] = per_day if r.get('status') != '休息' else 0.0
    else:
        daily = base / DAILY_DAYS
        hourly = daily / HOURS_PER_DAY
        commission = 0.0
        deduction = 0.0
        daily_map = {}
        for r in records:
            if r.get('status') == '休息':
                daily_map[r['date']] = 0.0
                continue
            d = day_deduction(r, daily, hourly)
            deduction += d
            daily_map[r['date']] = round(daily - d, 2)
        deduction = round(deduction, 2)
        gross = round(max(base - deduction, 0), 2)

    social = round(gross * SOCIAL_RATE, 2)
    taxable = max(gross - TAX_THRESHOLD - social, 0)
    tax = calc_tax(taxable)
    net = round(gross - social - tax, 2)
    net_ratio = (net / gross) if gross > 0 else 0.0

    return {
        'employeeId': emp.get('employeeId'),
        'name': emp.get('name'),
        'department': emp.get('departmentName'),
        'position': emp.get('position'),
        'salaryType': salary_type,
        'base': base,
        'deduction': deduction,
        'commission': commission,
        'gross': gross,
        'social': social,
        'tax': tax,
        'net': net,
        'daily_net': {d: round(v * net_ratio, 2) for d, v in daily_map.items()},
    }


def compute_all(attendance_data):
    """计算全员工资，返回结果列表"""
    return [compute_employee(e) for e in attendance_data['employees']]


def summary(results):
    """本月发薪汇总（交付物 1）"""
    return {
        'employeeCount': len(results),
        'totalGross': round(sum(r['gross'] for r in results), 2),
        'totalNet': round(sum(r['net'] for r in results), 2),
        'totalTax': round(sum(r['tax'] for r in results), 2),
        'totalSocial': round(sum(r['social'] for r in results), 2),
    }


def dept_stats(results):
    """按部门统计平均薪水（交付物 2）"""
    dept = defaultdict(list)
    for r in results:
        dept[r['department']].append(r)
    stats = []
    for name, items in dept.items():
        stats.append({
            'department': name,
            'count': len(items),
            'avgGross': round(sum(i['gross'] for i in items) / len(items), 2),
            'avgNet': round(sum(i['net'] for i in items) / len(items), 2),
            'totalNet': round(sum(i['net'] for i in items), 2),
        })
    return stats


def line_data(results):
    """折线图数据（交付物 3）：各部门累计实发工资随日期增长"""
    dept = defaultdict(list)
    for r in results:
        dept[r['department']].append(r)
    dates = sorted({d for r in results for d in r['daily_net']})
    series = []
    for name, items in dept.items():
        cum = 0.0
        values = []
        for day in dates:
            cum += sum(it['daily_net'].get(day, 0.0) for it in items)
            values.append(round(cum, 2))
        series.append({'name': name, 'values': values})
    return {'dates': dates, 'series': series}


def pie_data(results):
    """饼图数据（交付物 4）：分部门实发工资占比"""
    dept = defaultdict(float)
    for r in results:
        dept[r['department']] += r['net']
    return [{'name': k, 'value': round(v, 2)} for k, v in dept.items()]
