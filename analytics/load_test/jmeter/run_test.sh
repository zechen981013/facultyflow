#!/usr/bin/env bash
# ============================================================
# 一键运行 JMeter 压测并生成 HTML 报告（含 P90/P95）
# 用法：
#   ./run_test.sh            # 直接跑（工资单需有"待发放"数据）
#   ./run_test.sh --reset    # 先重置 2026年7月 工资单为"待发放"再跑
# 报告输出：report/index.html
# ============================================================
set -e
cd "$(dirname "$0")"

REPORT_DIR="report"
BASE="http://localhost:8080"
USER="wangfang"
PASS="123456"

# 清理上次结果
rm -rf "$REPORT_DIR" result.jtl jmeter.log
mkdir -p "$REPORT_DIR"

if [ "$1" == "--reset" ]; then
  echo ">> 重置 2026年7月 工资单为「待发放」..."
  TOKEN=$(curl -s -X POST "$BASE/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['token'])")
  curl -s -X POST "$BASE/api/salary/calculate?year=2026&month=7" \
    -H "Authorization: Bearer $TOKEN" >/dev/null
  echo ">> 完成"
fi

echo ">> 开始压测（登录100并发 / 工资列表100并发 / 发薪20并发 / 高并发模拟20000人）..."
jmeter -n -t pt_test.jmx -l result.jtl -e -o "$REPORT_DIR" -j jmeter.log

echo ""
echo "=============================================="
echo " 压测完成！"
echo " HTML 报告（含 P90/P95/TPS/错误率）:"
echo "   $REPORT_DIR/index.html"
echo " 原始采样数据: result.jtl"
echo "=============================================="
