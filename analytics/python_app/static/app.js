/* Python 前端逻辑：调用 Python 后台（FastAPI），Python 后台再调Java 考勤服务 */
let token = localStorage.getItem("py_token") || "";

const $ = (id) => document.getElementById(id);

// ---------------- 通用请求 ----------------
async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(path, { ...options, headers });
  const body = await res.json().catch(() => ({}));
  if (body.code !== 0) throw new Error(body.detail || body.message || "请求失败");
  return body.data;
}

// ---------------- 登录 ----------------
$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = $("username").value.trim();
  const password = $("password").value;
  $("login-msg").textContent = "";
  try {
    const data = await api("/api/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
      headers: { "Content-Type": "application/json" }, // 登录时还没有 token
    });
    token = data.token;
    localStorage.setItem("py_token", token);
    $("user-info").textContent = `${data.name}（${data.departmentName} · ${data.position}）`;
    $("login-view").classList.add("hidden");
    $("main-view").classList.remove("hidden");
    loadDashboard();
  } catch (err) {
    $("login-msg").textContent = "登录失败：" + err.message;
  }
});

$("logout-btn").addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST" }); } catch (_) {}
  token = ""; localStorage.removeItem("py_token");
  location.reload();
});

// ---------------- 图表 ----------------
let lineChart, pieChart;
function initCharts() {
  lineChart = echarts.init($("line-chart"));
  pieChart = echarts.init($("pie-chart"));
  window.addEventListener("resize", () => { lineChart.resize(); pieChart.resize(); });
}

function renderCharts(overview) {
  const { line, pie } = overview;

  lineChart.setOption({
    tooltip: { trigger: "axis" },
    legend: { data: line.series.map((s) => s.name) },
    grid: { left: 70, right: 20, top: 40, bottom: 60 },
    xAxis: { type: "category", data: line.dates.map((d) => d.slice(5)), axisLabel: { rotate: 45 } },
    yAxis: { type: "value", name: "累计实发（元）" },
    series: line.series.map((s) => ({
      name: s.name, type: "line", smooth: true, symbolSize: 5, data: s.values,
    })),
  });

  pieChart.setOption({
    tooltip: { trigger: "item", formatter: "{b}: {c} 元 ({d}%)" },
    legend: { bottom: 0 },
    series: [{
      type: "pie", radius: ["40%", "68%"], center: ["50%", "45%"],
      label: { formatter: "{b}\n{d}%" },
      data: pie,
    }],
  });
}

// ---------------- 主数据加载 ----------------
async function loadDashboard() {
  try {
    const overview = await api("/api/overview?year=2026&month=7");
    const s = overview.summary;
    $("c-net").textContent = s.totalNet.toLocaleString("zh-CN", { minimumFractionDigits: 2 }) + " 元";
    $("c-gross").textContent = s.totalGross.toLocaleString("zh-CN", { minimumFractionDigits: 2 }) + " 元";
    $("c-tax").textContent = s.totalTax.toLocaleString("zh-CN", { minimumFractionDigits: 2 }) + " 元";
    $("c-social").textContent = s.totalSocial.toLocaleString("zh-CN", { minimumFractionDigits: 2 }) + " 元";

    $("dept-table").querySelector("tbody").innerHTML = overview.deptStats.map((d) => `
      <tr>
        <td>${d.department}</td><td>${d.count}</td>
        <td>${d.avgGross.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}</td>
        <td>${d.avgNet.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}</td>
        <td>${d.totalNet.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}</td>
      </tr>`).join("");

    renderCharts(overview);
    await loadSalaryList();
  } catch (err) {
    showMsg("加载数据失败：" + err.message, false);
  }
}

async function loadSalaryList() {
  const list = await api("/api/salary/list?year=2026&month=7");
  $("salary-table").querySelector("tbody").innerHTML = list.map((r) => `
    <tr>
      <td><input type="checkbox" class="row-check" value="${r.id}" ${r.status !== "待发放" ? "disabled" : ""} /></td>
      <td>${r.name}</td><td>${r.departmentName}</td>
      <td>${r.grossSalary}</td><td>${r.netSalary}</td>
      <td>${r.status}</td>
    </tr>`).join("");
}

// ---------------- 发薪 ----------------
function selectedIds() {
  return [...document.querySelectorAll(".row-check:checked")].map((c) => Number(c.value));
}

$("check-all").addEventListener("change", (e) => {
  document.querySelectorAll(".row-check").forEach((c) => {
    if (!c.disabled) c.checked = e.target.checked;
  });
});

function showMsg(text, ok = true) {
  const el = $("pay-msg");
  el.textContent = text;
  el.className = "msg" + (ok ? " ok" : "");
}

$("pay-btn").addEventListener("click", async () => {
  const ids = selectedIds();
  if (!ids.length) return showMsg("请先勾选要发放的工资单", false);
  try {
    const data = await api("/api/salary/pay", { method: "POST", body: JSON.stringify({ ids }) });
    showMsg(`已投递 ${data.sent}/${data.total} 条发放请求到 RabbitMQ，稍后刷新查看结果`, true);
    setTimeout(loadSalaryList, 3000);
  } catch (err) {
    showMsg("发薪失败：" + err.message, false);
  }
});

$("simulate-btn").addEventListener("click", async () => {
  showMsg("正在向队列投递 20000 条模拟发放请求…", true);
  try {
    const data = await api("/api/salary/simulate", { method: "POST", body: JSON.stringify({ count: 20000 }) });
    showMsg(`已投递 ${data.sent} 条，消费者按自身能力逐条消费（削峰填谷），可在 RabbitMQ 管理台查看积压`, true);
  } catch (err) {
    showMsg("模拟失败：" + err.message, false);
  }
});

// ---------------- 初始化 ----------------
initCharts();
if (token) {
  $("login-view").classList.add("hidden");
  $("main-view").classList.remove("hidden");
  loadDashboard();
}
