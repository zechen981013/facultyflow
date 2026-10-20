#!/usr/bin/env bash
# 一键运行 Python 自动化测试并生成 HTML 报告
# 用法：./run_tests.sh
set -e
cd "$(dirname "$0")"

rm -rf report
mkdir -p report

python3 -m pytest test_salary_flow.py --html=report/index.html --self-contained-html -v

echo ""
echo "=============================================="
echo " 测试完成！HTML 报告: report/index.html"
echo "=============================================="
