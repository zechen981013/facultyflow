# -*- coding: utf-8 -*-
"""
工资核算脚本：调用服务端(Java)考勤系统接口，计算 2026 年 7 月工资
==============================================================
调用接口拿到所有员工考勤数据，按规则计算工资：
  1. 固定薪水：日薪=底薪/21.75，时薪=日薪/8
     - 迟到/早退 按时薪按分钟扣款
     - 请假 扣 1 天(8小时)工资
     - 缺勤(旷工) 扣 3 倍日薪
  2. 销售：底薪+提成，销售额<10万提成3%，>=10万提成5%
  3. 个税(深圳/全国)：应发-起征点5000-五险一金(20%) 后按月度超额累进税率
输出：
  1. 本月共计发薪（实发总额）
  2. 按部门平均薪水
  3. 按部门折线图（各部门累计实发工资随日期增长）
  4. 分部门饼图（各部门实发工资占比）

用法：
  python salary_calc.py [接口地址] [用户名]
  默认接口: http://localhost:8080  默认用户: wangfang  密码: 123456
"""
import sys
import csv
import datetime

import requests
import matplotlib
matplotlib.use('Agg')  # 无界面后端，生成图片文件
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'SimSun']
plt.rcParams['axes.unicode_minus'] = False

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:8080'
USERNAME = sys.argv[2] if len(sys.argv) > 2 else 'wangfang'
PASSWORD = '123456'
YEAR, MONTH = 2026, 7

# 个税月度超额累进税率表：上限(含) -> [税率, 速算扣除数]
TAX_BRACKETS = [
    (3000, 0.03, 0),
    (12000, 0.10, 210),
    (25000, 0.20, 1410),
    (35000, 0.25, 2660),
    (55000, 0.30, 4410),
    (80000, 0.35, 7160),
    (float('inf'), 0.45, 15160),
]
TAX_THRESHOLD = 5000          # 个税起征点
SOCIAL_RATE = 0.2             # 五险一金个人比例（与考勤服务保持一致）
DAILY_DAYS = 21.75            # 月计薪天数
HOURS_PER_DAY = 8             # 每日标准工时


def login():
    r = requests.post(f'{BASE_URL}/api/auth/login',
                      json={'username': USERNAME, 'password': PASSWORD}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data['code'] != 0:
        raise RuntimeError('登录失败: ' + data['message'])
    return data['data']['token']


def fetch_attendance():
    token = login()
    r = requests.get(f'{BASE_URL}/api/attendance/month',
                     params={'year': YEAR, 'month': MONTH},
                     headers={'Authorization': f'Bearer {token}'}, timeout=15)
    r.raise_for_status()
    data = r.json()['data']
    print(f'从服务端接口获取到 {len(data["employees"])} 名员工考勤数据（{YEAR}年{MONTH}月）')
    return data


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
        late = max(to_minutes(rec.get('checkInTime')) - to_minutes('08:30:00'), 0)
        return round(hourly * late / 60, 2)
    if status == '早退':
        early = max(to_minutes('18:00:00') - to_minutes(rec.get('checkOutTime')), 0)
        return round(hourly * early / 60, 2)
    if status == '迟到早退':
        late = max(to_minutes(rec.get('checkInTime')) - to_minutes('08:30:00'), 0)
        early = max(to_minutes('18:00:00') - to_minutes(rec.get('checkOutTime')), 0)
        return round(hourly * (late + early) / 60, 2)
    if status == '请假':
        return daily
    if status == '缺勤':
        return daily * 3
    return 0.0


def calc_tax(taxable):
    """月度个人所得税"""
    if taxable <= 0:
        return 0.0
    for ceiling, rate, quick in TAX_BRACKETS:
        if taxable <= ceiling:
            return round(max(taxable * rate - quick, 0), 2)
    return 0.0


def compute_employee(emp):
    """按规则计算一名员工的工资，返回 dict 及按天明细"""
    base = float(emp.get('baseSalary') or 0)
    records = emp.get('records') or []
    salary_type = emp.get('salaryType')

    if salary_type == 'SALES':
        sales = float(emp.get('monthlySales') or 0)
        commission = round(sales * 0.05 if sales >= 100000 else sales * 0.03, 2)
        gross = round(base + commission, 2)
        deduction = 0.0
        daily_map = {}          # 日期 -> 当日应发(税前)
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


def main():
    data = fetch_attendance()
    results = [compute_employee(e) for e in data['employees']]

    # ---------- 1. 本月共计发薪 ----------
    total_net = round(sum(r['net'] for r in results), 2)
    total_gross = round(sum(r['gross'] for r in results), 2)
    total_tax = round(sum(r['tax'] for r in results), 2)
    print('=' * 60)
    print(f'2026年7月工资汇总')
    print(f'  应发总额: {total_gross:,.2f} 元')
    print(f'  个税总额: {total_tax:,.2f} 元')
    print(f'  本月共计发薪(实发): {total_net:,.2f} 元')
    print('=' * 60)

    # ---------- 2. 按部门统计平均薪水 ----------
    dept = {}
    for r in results:
        dept.setdefault(r['department'], []).append(r)
    print('按部门平均薪水:')
    print(f"{'部门':<8}{'人数':>5}{'平均应发':>14}{'平均实发':>14}")
    for name, items in dept.items():
        avg_gross = sum(i['gross'] for i in items) / len(items)
        avg_net = sum(i['net'] for i in items) / len(items)
        print(f'{name:<8}{len(items):>5}{avg_gross:>14,.2f}{avg_net:>14,.2f}')

    # ---------- 3. 折线图：各部门累计实发工资（按日期） ----------
    dates = sorted({d for r in results for d in r['daily_net']})
    line_data = {name: [0.0] * len(dates) for name in dept}
    for name, items in dept.items():
        cum = 0.0
        for i, day in enumerate(dates):
            cum += sum(it['daily_net'].get(day, 0.0) for it in items)
            line_data[name][i] = round(cum, 2)

    plt.figure(figsize=(11, 5.5))
    for name, values in line_data.items():
        plt.plot(dates, values, marker='o', markersize=3, label=name)
    plt.xlabel('日期')
    plt.ylabel('累计实发工资（元）')
    plt.title('2026年7月 各部门累计发薪趋势')
    plt.xticks(rotation=45)
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig('dept_line_chart.png', dpi=120)
    plt.close()
    print('\n已生成折线图: dept_line_chart.png')

    # ---------- 4. 饼图：分部门实发工资占比 ----------
    plt.figure(figsize=(6.5, 6.5))
    labels = list(dept.keys())
    sizes = [sum(i['net'] for i in items) for items in dept.values()]
    plt.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, counterclock=False,
            colors=['#5b8ff9', '#61ddaa', '#f6bd16'])
    plt.title('2026年7月 分部门实发工资占比')
    plt.tight_layout()
    plt.savefig('dept_pie_chart.png', dpi=120)
    plt.close()
    print('已生成饼图: dept_pie_chart.png')

    # ---------- 导出明细 CSV ----------
    with open('salary_detail.csv', 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['姓名', '部门', '职位', '薪资类型', '底薪', '考勤扣款', '提成',
                         '应发工资', '五险一金', '个税', '实发工资'])
        for r in results:
            writer.writerow([r['name'], r['department'], r['position'], r['salaryType'],
                             r['base'], r['deduction'], r['commission'],
                             r['gross'], r['social'], r['tax'], r['net']])
    print('已导出明细: salary_detail.csv')


if __name__ == '__main__':
    main()
