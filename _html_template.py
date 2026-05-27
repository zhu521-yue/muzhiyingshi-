#!/usr/bin/env python3
"""HTML 模板生成 - 多公司看板前端页面（含主题色、logo、年月选择器）"""


def get_html_template(company_name, brand, theme_color, logo_url, company_id):
    """生成完整看板 HTML"""
    data_url = f'/{company_id}/api/data'
    refresh_url = f'/{company_id}/api/refresh'

    # 根据主题色生成深色和浅色变体
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{brand} {company_name} · 勤奋指数看板</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
:root {{
  --primary:{theme_color};
  --primary-dark:{theme_color}CC;
  --primary-light:{theme_color}DD;
  --primary-dim:{theme_color}1F;
  --black:#1A1A1A;--gray-900:#111;--gray-800:#222;--gray-700:#333;
  --gray-500:#666;--gray-300:#AAA;--gray-100:#F4F4F4;
  --white:#FFF;--bg:#F5F5F5;--card:#FFF;--border:#E0E0E0;
  --shadow-sm:0 2px 8px rgba(0,0,0,.06);--shadow:0 4px 16px rgba(0,0,0,.10);
  --shadow-lg:0 8px 32px rgba(0,0,0,.15);--radius:10px;
  --transition:.25s cubic-bezier(.4,0,.2,1);
}}
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box}}
html{{scroll-behavior:smooth}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--black);line-height:1.6;overflow-x:hidden}}
.reveal{{opacity:0;transform:translateY(28px);transition:opacity .55s ease,transform .55s ease}}
.reveal.visible{{opacity:1;transform:translateY(0)}}
.header{{background:var(--black);color:var(--white);padding:0 40px;height:72px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;box-shadow:0 2px 20px rgba(0,0,0,.4)}}
.header-left{{display:flex;align-items:center;gap:16px}}
.header-logo{{display:flex;align-items:center;gap:10px}}
.header-logo .logo-wrap{{width:40px;height:40px;border-radius:8px;background:var(--primary);display:flex;align-items:center;justify-content:center;padding:4px}}
.header-logo .logo-wrap img{{height:28px;width:auto;filter:brightness(0) invert(1)}}
.header-logo .brand{{font-size:20px;font-weight:900;letter-spacing:2px;color:var(--white)}}
.header-divider{{width:1px;height:28px;background:rgba(255,255,255,.2)}}
.header-title{{font-size:15px;font-weight:500;opacity:.85}}
.header-right{{display:flex;align-items:center;gap:20px}}
.header-stat{{text-align:center}}
.header-stat .s-val{{font-size:18px;font-weight:800;color:var(--primary-light);line-height:1}}
.header-stat .s-lbl{{font-size:11px;opacity:.6;margin-top:2px}}
.live-dot{{display:flex;align-items:center;gap:6px;font-size:12px;opacity:.7}}
.live-dot::before{{content:'';width:7px;height:7px;border-radius:50%;background:#4ade80;animation:blink 2s infinite;flex-shrink:0}}
@keyframes blink{{0%,100%{{opacity:1}}50%{{opacity:.2}}}}
.refresh-btn{{background:var(--primary);border:none;color:var(--white);padding:7px 18px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600;transition:background var(--transition),transform var(--transition);box-shadow:0 2px 8px {theme_color}66}}
.refresh-btn:hover{{background:var(--primary-light);transform:translateY(-1px)}}
/* === PLACEHOLDER_TMPL_P2 === */
.hero{{background:linear-gradient(135deg,var(--gray-900) 0%,var(--gray-800) 50%,color-mix(in srgb,{theme_color} 20%,#111) 100%);padding:36px 40px;position:relative;overflow:hidden}}
.hero::before{{content:'';position:absolute;top:-60px;right:-60px;width:240px;height:240px;border-radius:50%;background:radial-gradient(circle,{theme_color}40,transparent 70%);pointer-events:none}}
.hero-inner{{max-width:1400px;margin:0 auto;position:relative}}
.hero-label{{font-size:12px;font-weight:700;letter-spacing:3px;color:var(--primary);text-transform:uppercase;margin-bottom:8px}}
.hero-title{{font-size:32px;font-weight:900;color:var(--white);margin-bottom:12px}}
.hero-controls{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:14px;color:rgba(255,255,255,.5)}}
.hero-controls select{{background:#333;color:#fff;border:1px solid #555;border-radius:4px;padding:4px 8px;font-size:14px;cursor:pointer;appearance:auto}}
.hero-controls select:focus{{outline:none;border-color:var(--primary)}}
.query-btn{{background:var(--primary);border:none;color:#fff;padding:5px 16px;border-radius:4px;cursor:pointer;font-size:13px;font-weight:600;margin-left:8px;transition:background .2s,transform .2s}}
.query-btn:hover{{filter:brightness(1.1);transform:translateY(-1px)}}
.container{{max-width:1400px;margin:0 auto;padding:28px 40px}}
.section-title{{font-size:17px;font-weight:800;margin:36px 0 16px;display:flex;align-items:center;gap:10px;color:var(--gray-900)}}
.section-title::before{{content:'';display:block;width:4px;height:20px;background:var(--primary);border-radius:2px;flex-shrink:0}}
.section-title .s-tag{{font-size:11px;font-weight:700;background:var(--primary-dim);color:var(--primary);padding:2px 8px;border-radius:4px}}
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:28px}}
.kpi-card{{background:var(--card);border-radius:var(--radius);padding:22px 24px;box-shadow:var(--shadow-sm);border:1px solid var(--border);position:relative;overflow:hidden;transition:transform var(--transition),box-shadow var(--transition)}}
.kpi-card::after{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--primary);transform:scaleX(0);transform-origin:left;transition:transform var(--transition)}}
.kpi-card:hover{{transform:translateY(-3px);box-shadow:var(--shadow)}}
.kpi-card:hover::after{{transform:scaleX(1)}}
.kpi-card .icon{{width:40px;height:40px;border-radius:8px;background:var(--primary-dim);display:flex;align-items:center;justify-content:center;font-size:18px;margin-bottom:14px}}
.kpi-card .label{{font-size:12px;font-weight:600;color:var(--gray-500);text-transform:uppercase;letter-spacing:1px;margin-bottom:6px}}
.kpi-card .value{{font-size:30px;font-weight:900;color:var(--black);line-height:1}}
.kpi-card .value.primary{{color:var(--primary)}}
.kpi-card .sub{{font-size:12px;color:var(--gray-500);margin-top:6px}}
.chart-row{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:24px}}
.chart-box{{background:var(--card);border-radius:var(--radius);padding:22px 24px;box-shadow:var(--shadow-sm);border:1px solid var(--border)}}
.chart-box h3{{font-size:14px;font-weight:700;margin-bottom:16px;color:var(--gray-700);display:flex;align-items:center;gap:8px}}
.chart-box h3::before{{content:'';display:block;width:3px;height:14px;background:var(--primary);border-radius:2px}}
.chart-box canvas{{max-height:300px}}
.tabs-wrapper{{background:var(--card);border-radius:var(--radius);border:1px solid var(--border);overflow:hidden;margin-bottom:24px;box-shadow:var(--shadow-sm)}}
.tabs{{display:flex;background:var(--gray-100);border-bottom:2px solid var(--border);padding:0 4px}}
.tab{{padding:12px 28px;cursor:pointer;font-size:14px;font-weight:600;color:var(--gray-500);border:none;background:none;position:relative;transition:color var(--transition)}}
.tab::after{{content:'';position:absolute;bottom:-2px;left:0;right:0;height:2px;background:var(--primary);transform:scaleX(0);transition:transform var(--transition)}}
.tab:hover{{color:var(--primary)}}
.tab.active{{color:var(--primary)}}
.tab.active::after{{transform:scaleX(1)}}
.tab-content{{display:none;padding:24px}}
.tab-content.active{{display:block;animation:fadeIn .3s ease}}
@keyframes fadeIn{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}
.table-wrap{{background:var(--card);border-radius:var(--radius);box-shadow:var(--shadow-sm);border:1px solid var(--border);overflow:hidden;margin-bottom:24px}}
.table-header{{padding:16px 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--border);background:var(--gray-100)}}
.table-header h3{{font-size:14px;font-weight:700;color:var(--gray-700)}}
.table-scroll{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
thead tr{{background:#fafafa}}
th{{padding:10px 14px;text-align:left;font-weight:700;font-size:12px;color:var(--gray-500);text-transform:uppercase;letter-spacing:.8px;border-bottom:1px solid var(--border);white-space:nowrap}}
td{{padding:11px 14px;border-bottom:1px solid #f0f0f0;white-space:nowrap}}
tbody tr:hover{{background:{theme_color}0A}}
.rank{{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;font-size:12px;font-weight:800;background:var(--gray-100);color:var(--gray-500)}}
.rank-1{{background:linear-gradient(135deg,#E8B84B,#C9920A);color:#fff;box-shadow:0 2px 8px rgba(200,145,10,.4)}}
.rank-2{{background:linear-gradient(135deg,#9CA3AF,#6B7280);color:#fff}}
.rank-3{{background:linear-gradient(135deg,#C4813A,#96510F);color:#fff}}
.progress-bar{{height:4px;background:var(--gray-100);border-radius:2px;margin-top:4px;overflow:hidden}}
.progress-bar .fill{{height:100%;background:linear-gradient(90deg,var(--primary-dark),var(--primary));border-radius:2px;transition:width 1s ease}}
.tag{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600}}
.tag-primary{{background:var(--primary-dim);color:var(--primary)}}
.tag-gray{{background:var(--gray-100);color:var(--gray-700)}}
.tag-dark{{background:var(--gray-800);color:var(--white)}}
.filter-row th{{padding:4px 6px}}
.filter-row input{{width:100%;padding:4px 8px;font-size:12px;border:1px solid var(--border);border-radius:4px;background:var(--white)}}
.filter-row input:focus{{outline:none;border-color:var(--primary)}}
.system-cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px}}
.system-card{{background:var(--card);border-radius:var(--radius);border:1px solid var(--border);overflow:hidden;box-shadow:var(--shadow-sm);transition:transform var(--transition),box-shadow var(--transition)}}
.system-card:hover{{transform:translateY(-4px);box-shadow:var(--shadow-lg)}}
.system-card-header{{background:var(--black);padding:14px 20px;display:flex;align-items:center;justify-content:space-between}}
.system-card-header .name{{font-size:15px;font-weight:800;color:var(--white)}}
.system-card-header .badge{{background:var(--primary);color:var(--white);font-size:12px;font-weight:700;padding:2px 10px;border-radius:20px}}
.system-card-body{{padding:16px 20px}}
.system-stat-row{{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #f4f4f4;font-size:13px}}
.system-stat-row:last-child{{border-bottom:none}}
.system-stat-row .s-key{{color:var(--gray-500)}}
.system-stat-row .s-val{{font-weight:700;color:var(--black)}}
.heatmap-wrap{{background:var(--card);border-radius:var(--radius);border:1px solid var(--border);overflow:hidden;margin-bottom:24px;box-shadow:var(--shadow-sm)}}
.heatmap{{display:grid;gap:0}}
.heatmap-cell{{padding:14px 10px;text-align:center;font-size:13px;font-weight:600;border:1px solid rgba(0,0,0,.05);transition:transform var(--transition)}}
.heatmap-cell:hover{{transform:scale(1.05);box-shadow:var(--shadow);z-index:1;position:relative}}
.heatmap-header{{background:var(--black);color:var(--white);font-size:12px;letter-spacing:1px}}
.heatmap-row-label{{background:var(--gray-100);color:var(--gray-700);font-weight:700}}
.heatmap-total{{background:var(--primary-dim);color:var(--primary);font-weight:800}}
.footer{{background:var(--black);color:rgba(255,255,255,.4);text-align:center;padding:20px;font-size:12px;letter-spacing:1px;margin-top:40px}}
.footer span{{color:var(--primary)}}
.loading-screen{{min-height:300px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;color:var(--gray-500)}}
.spinner{{width:36px;height:36px;border:3px solid {theme_color}33;border-top-color:var(--primary);border-radius:50%;animation:spin .8s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
@media(max-width:1024px){{.chart-row{{grid-template-columns:1fr}}}}
@media(max-width:768px){{.header{{padding:12px 16px;height:auto;flex-wrap:wrap;gap:8px}}.container{{padding:16px}}.hero{{padding:24px 16px}}.hero-title{{font-size:22px}}.kpi-grid{{grid-template-columns:1fr 1fr}}.system-cards{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<header class="header">
  <div class="header-left">
    <div class="header-logo">
      <div class="logo-wrap"><img src="{logo_url}" alt="{brand}"></div>
      <div class="brand">{brand}</div>
    </div>
    <div class="header-divider"></div>
    <div class="header-title">{company_name} · 勤奋指数看板</div>
  </div>
  <div class="header-right">
    <div class="header-stat"><div class="s-val" id="hdTotal">—</div><div class="s-lbl">总勤奋次数</div></div>
    <div class="header-stat"><div class="s-val" id="hdAvg">—</div><div class="s-lbl">人均次数</div></div>
    <div class="live-dot">实时数据</div>
    <button class="refresh-btn" onclick="queryData()">查询</button>
  </div>
</header>
<div class="hero">
  <div class="hero-inner">
    <div class="hero-label">DILIGENCE INDEX</div>
    <div class="hero-title">{company_name}</div>
    <div class="hero-controls">
      <select id="selYear"></select>年勤奋指数看板 · 数据区间：
      <select id="selMonthFrom"></select> —
      <select id="selMonthTo"></select>
      · 职能岗 / 营销岗 / 产品岗
      <button class="query-btn" onclick="queryData()">查询</button>
    </div>
  </div>
</div>
<div class="container" id="app">
  <div class="loading-screen"><div class="spinner"></div><div>请选择年份和月份后点击查询</div></div>
</div>
<footer class="footer">
  <span>{brand}</span> {company_name} · 勤奋指数看板 &copy; 2026 | 数据来源：钉钉考勤API
</footer>
<!-- === PLACEHOLDER_TMPL_JS === -->
<script>
const DATA_URL='{data_url}';
const REFRESH_URL='{refresh_url}';
const PRIMARY='{theme_color}';
let DATA=null,charts={{}};
const BLACK='#1A1A1A',GRAY='#888';

// 初始化年月选择器
(function initControls(){{
  const now=new Date();
  const selYear=document.getElementById('selYear');
  for(let y=now.getFullYear();y>=2024;y--){{
    const opt=document.createElement('option');
    opt.value=y;opt.textContent=y;
    selYear.appendChild(opt);
  }}
  const selFrom=document.getElementById('selMonthFrom');
  const selTo=document.getElementById('selMonthTo');
  for(let m=1;m<=12;m++){{
    const o1=document.createElement('option');
    o1.value=m;o1.textContent=m+'月';
    selFrom.appendChild(o1);
    const o2=document.createElement('option');
    o2.value=m;o2.textContent=m+'月';
    selTo.appendChild(o2);
  }}
  selFrom.value=1;
  selTo.value=Math.min(now.getMonth()+1,12);
  // 页面打开时先加载缓存数据（快），用户点查询才强制刷新
  loadCachedData();
}})();

async function loadCachedData(){{
  const app=document.getElementById('app');
  app.innerHTML='<div class="loading-screen"><div class="spinner"></div><div>加载中...</div></div>';
  const params=getSelectedParams();
  try{{
    let res=await fetch(DATA_URL+'?'+params);
    let data=await res.json();
    let retries=0;
    while(data.loading&&retries<60){{
      await new Promise(r=>setTimeout(r,2000));
      res=await fetch(DATA_URL+'?'+params);data=await res.json();retries++;
    }}
    if(data.error){{app.innerHTML=`<div class="loading-screen"><div style="color:var(--primary)">⚠ ${{data.error}}</div><div style="font-size:12px;margin-top:8px">点击"查询"重新获取数据</div></div>`;return;}}
    DATA=data;renderDashboard(DATA);
  }}catch(e){{app.innerHTML=`<div class="loading-screen"><div>点击"查询"获取数据</div></div>`;}}
}}

function getSelectedParams(){{
  const year=document.getElementById('selYear').value;
  const from=parseInt(document.getElementById('selMonthFrom').value);
  const to=parseInt(document.getElementById('selMonthTo').value);
  const months=[];
  for(let m=Math.min(from,to);m<=Math.max(from,to);m++)months.push(m);
  return `year=${{year}}&months=${{months.join(',')}}`;
}}

function animateNumber(el,target,dur=900,dec=0){{
  const start=performance.now();
  (function step(ts){{
    const t=Math.min((ts-start)/dur,1),ease=1-Math.pow(1-t,3);
    const val=target*ease;
    el.textContent=dec>0?val.toFixed(dec):Math.round(val).toLocaleString();
    if(t<1)requestAnimationFrame(step);
    else el.textContent=dec>0?target.toFixed(dec):target.toLocaleString();
  }})(start);
}}

function initReveal(){{
  const io=new IntersectionObserver(es=>{{es.forEach(e=>{{if(e.isIntersecting)e.target.classList.add('visible')}});}},{{threshold:0.1}});
  document.querySelectorAll('.reveal').forEach(el=>io.observe(el));
}}

function getHeatColor(v,max){{const r=v/max;if(r>.75)return PRIMARY;if(r>.5)return PRIMARY+'AA';if(r>.25)return PRIMARY+'55';return PRIMARY+'22'}}
function getHeatText(v,max){{return v/max>.45?'#fff':BLACK}}

Chart.defaults.font.family="'-apple-system','PingFang SC','Microsoft YaHei',sans-serif";
Chart.defaults.color=GRAY;

function renderDashboard(d){{
  const app=document.getElementById('app');
  const m=d.monthly;
  const total=m.find(x=>x.月份==='合计')||m[m.length-1];
  animateNumber(document.getElementById('hdTotal'),total.勤奋次数合计,1000);
  animateNumber(document.getElementById('hdAvg'),total.人均勤奋次数,800,2);

  app.innerHTML=`
    <div class="kpi-grid">
      <div class="kpi-card reveal"><div class="icon">👥</div><div class="label">累计总人次</div><div class="value primary">${{total.总人数}}</div><div class="sub">${{d.month_labels[0]}}–${{d.month_labels[d.month_labels.length-1]}}累计</div></div>
      <div class="kpi-card reveal"><div class="icon">💪</div><div class="label">勤奋次数合计</div><div class="value">${{total.勤奋次数合计.toLocaleString()}}</div><div class="sub">人均 <strong style="color:var(--primary)">${{total.人均勤奋次数}}</strong> 次</div></div>
    </div>
    <div class="section-title reveal">三大岗位总览 <span class="s-tag">OVERVIEW</span></div>
    <div class="system-cards reveal" id="sysCards"></div>
    <div class="section-title reveal">月度趋势 <span class="s-tag">TREND</span></div>
    <div class="chart-row reveal">
      <div class="chart-box"><h3>人均勤奋次数 · 月度变化</h3><canvas id="cMonthly"></canvas></div>
      <div class="chart-box"><h3>勤奋次数合计 · 月度变化</h3><canvas id="cTotal"></canvas></div>
    </div>
    <div class="section-title reveal">岗位对比 <span class="s-tag">COMPARE</span></div>
    <div class="chart-row reveal">
      <div class="chart-box"><h3>岗位人均勤奋次数</h3><canvas id="cSys"></canvas></div>
      <div class="chart-box"><h3>岗位 × 月份趋势</h3><canvas id="cCross"></canvas></div>
    </div>
    <div class="section-title reveal">月度热力图 <span class="s-tag">HEATMAP</span></div>
    <div class="heatmap-wrap reveal"><div class="heatmap" id="heatmap"></div></div>
    <div class="section-title reveal">各岗位详情 <span class="s-tag">DETAIL</span></div>
    <div class="tabs-wrapper reveal">
      <div class="tabs" id="sysTabs"></div>
      <div id="sysContent"></div>
    </div>
    <div class="section-title reveal">全公司勤奋排名 TOP20 <span class="s-tag">RANKING</span></div>
    <div class="table-wrap reveal">
      <div class="table-header"><h3>全公司 · 勤奋次数 TOP 20</h3></div>
      <div class="table-scroll"><table id="tblRank"><thead><tr><th>排名</th><th>姓名</th><th>工号</th><th>部门</th><th>岗位</th><th>累计勤奋次数</th><th>月均</th></tr><tr class="filter-row"><th><input onkeyup="filterTable('tblRank')" placeholder="筛选"></th><th><input onkeyup="filterTable('tblRank')" placeholder="筛选"></th><th><input onkeyup="filterTable('tblRank')" placeholder="筛选"></th><th><input onkeyup="filterTable('tblRank')" placeholder="筛选"></th><th><input onkeyup="filterTable('tblRank')" placeholder="筛选"></th><th><input onkeyup="filterTable('tblRank')" placeholder="筛选"></th><th><input onkeyup="filterTable('tblRank')" placeholder="筛选"></th></tr></thead><tbody id="rankBody"></tbody></table></div>
    </div>`;
  renderSysCards(d);renderCharts(d);renderHeatmap(d);renderSysTabs(d);renderRanking(d);initReveal();
}}

function renderSysCards(d){{
  const el=document.getElementById('sysCards');
  const icons={{'职能岗':'🏢','营销岗':'📣','产品岗':'📦'}};
  el.innerHTML=d.systems.map(s=>`
    <div class="system-card">
      <div class="system-card-header"><div class="name">${{icons[s.岗位]||''}} ${{s.岗位}}</div><div class="badge">人均 ${{s.人均勤奋次数}}</div></div>
      <div class="system-card-body">
        <div class="system-stat-row"><span class="s-key">总人次</span><span class="s-val">${{s.总人次}}</span></div>
        <div class="system-stat-row"><span class="s-key">勤奋次数合计</span><span class="s-val">${{(s.勤奋次数合计||0).toLocaleString()}}</span></div>
        <div class="system-stat-row"><span class="s-key">人均勤奋次数</span><span class="s-val">${{s.人均勤奋次数}}</span></div>
      </div>
    </div>`).join('');
}}

function renderCharts(d){{
  const m=d.monthly.filter(x=>x.月份!=='合计');
  const labels=m.map(x=>x.月份);
  const gc='rgba(0,0,0,.05)';
  if(charts.m)charts.m.destroy();
  charts.m=new Chart(document.getElementById('cMonthly'),{{type:'line',data:{{labels,datasets:[
    {{label:'人均勤奋次数',data:m.map(x=>x.人均勤奋次数),borderColor:PRIMARY,backgroundColor:PRIMARY+'14',fill:true,tension:.4,pointRadius:6,pointBackgroundColor:PRIMARY,borderWidth:2.5}}
  ]}},options:{{responsive:true,plugins:{{legend:{{position:'top',labels:{{usePointStyle:true,boxWidth:8}}}}}},scales:{{y:{{beginAtZero:true,grid:{{color:gc}}}}}}}}}});

  if(charts.h)charts.h.destroy();
  charts.h=new Chart(document.getElementById('cTotal'),{{type:'bar',data:{{labels,datasets:[{{label:'勤奋次数合计',data:m.map(x=>x.勤奋次数合计),backgroundColor:PRIMARY+'CC',borderRadius:6,borderSkipped:false}}]}},options:{{responsive:true,plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true,grid:{{color:gc}}}}}}}}}});

  const sys=d.systems;const sc=[PRIMARY,BLACK,'#888'];
  if(charts.s)charts.s.destroy();
  charts.s=new Chart(document.getElementById('cSys'),{{type:'bar',data:{{labels:sys.map(x=>x.岗位),datasets:[{{label:'人均勤奋次数',data:sys.map(x=>x.人均勤奋次数),backgroundColor:sc,borderRadius:8,borderSkipped:false}}]}},options:{{responsive:true,plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true,grid:{{color:gc}}}}}}}}}});

  const cross=d.cross_analysis;const months=d.month_labels;
  if(charts.c)charts.c.destroy();
  charts.c=new Chart(document.getElementById('cCross'),{{type:'line',data:{{labels:months,datasets:cross.map((c,i)=>({{label:c.岗位,data:months.map(mm=>c[mm]),borderColor:sc[i],backgroundColor:sc[i]+'20',fill:i===0,tension:.4,pointRadius:6,pointBackgroundColor:sc[i],borderWidth:i===0?3:2}}))}},options:{{responsive:true,plugins:{{legend:{{position:'top',labels:{{usePointStyle:true,boxWidth:8}}}}}},scales:{{y:{{beginAtZero:true,grid:{{color:gc}}}}}}}}}});
}}

function renderHeatmap(d){{
  const el=document.getElementById('heatmap');
  const cross=d.cross_analysis,months=d.month_labels;
  el.style.gridTemplateColumns=`120px repeat(${{months.length}},1fr) 120px`;
  const allV=cross.flatMap(c=>months.map(mm=>c[mm]));
  const mx=Math.max(...allV);
  let h='<div class="heatmap-cell heatmap-header">岗位</div>';
  months.forEach(mm=>h+=`<div class="heatmap-cell heatmap-header">${{mm}}</div>`);
  h+='<div class="heatmap-cell heatmap-header">累计人均</div>';
  cross.forEach(c=>{{
    h+=`<div class="heatmap-cell heatmap-row-label">${{c.岗位}}</div>`;
    months.forEach(mm=>{{const v=c[mm];h+=`<div class="heatmap-cell" style="background:${{getHeatColor(v,mx)}};color:${{getHeatText(v,mx)}}">${{v}}</div>`}});
    h+=`<div class="heatmap-cell heatmap-total">${{c.累计人均}}</div>`;
  }});
  el.innerHTML=h;
}}

function renderSysTabs(d){{
  const jobs=d.job_types||['全部岗位','职能岗','营销岗','产品岗'];
  const tabsEl=document.getElementById('sysTabs');
  const contentEl=document.getElementById('sysContent');
  tabsEl.innerHTML=jobs.map((s,i)=>`<button class="tab ${{i===0?'active':''}}" onclick="switchTab('${{s}}',this)">${{s}}</button>`).join('');
  let html='';
  jobs.forEach((s,i)=>{{
    const sys=d[s];if(!sys)return;
    const maxD=Math.max(...sys.departments.map(r=>r.人均勤奋次数),1);
    const maxR=Math.max(...sys.rankings.map(r=>r.累计勤奋次数),1);
    const tid='tbl_'+s.replace(/[^a-zA-Z0-9]/g,'_')+'_';
    let deptRows=sys.departments.map((r,idx)=>`<tr><td><span class="rank ${{idx<3?'rank-'+(idx+1):''}}"> ${{idx+1}}</span></td><td><strong>${{r.部门}}</strong></td><td>${{r.人次}}</td><td><strong style="color:var(--primary)">${{r.人均勤奋次数}}</strong><div class="progress-bar"><div class="fill" style="width:${{(r.人均勤奋次数/maxD*100).toFixed(1)}}%"></div></div></td><td>${{r.勤奋次数合计}}</td></tr>`).join('');
    let rankRows=sys.rankings.slice(0,20).map(r=>`<tr><td><span class="rank ${{r.排名<=3?'rank-'+r.排名:''}}">${{r.排名}}</span></td><td><strong>${{r.姓名}}</strong></td><td>${{r.工号}}</td><td>${{r.部门}}</td><td><strong style="color:var(--primary)">${{r.累计勤奋次数}}</strong><div class="progress-bar"><div class="fill" style="width:${{(r.累计勤奋次数/maxR*100).toFixed(1)}}%"></div></div></td><td>${{r.月均勤奋次数}}</td></tr>`).join('');
    const deptFilter='<tr class="filter-row">'+['#','部门','人次','人均勤奋','合计'].map(()=>'<th><input onkeyup="filterTable(\\''+tid+'dept\\')" placeholder="筛选"></th>').join('')+'</tr>';
    const rankFilter='<tr class="filter-row">'+['排名','姓名','工号','部门','累计勤奋','月均'].map(()=>'<th><input onkeyup="filterTable(\\''+tid+'rank\\')" placeholder="筛选"></th>').join('')+'</tr>';
    html+=`<div class="tab-content ${{i===0?'active':''}}" id="tab-${{s}}">
      <div class="table-wrap"><div class="table-header"><h3>${{s}} · 部门排名</h3></div><div class="table-scroll"><table id="${{tid}}dept"><thead><tr><th>#</th><th>部门</th><th>人次</th><th>人均勤奋</th><th>合计</th></tr>${{deptFilter}}</thead><tbody>${{deptRows}}</tbody></table></div></div>
      <div class="table-wrap"><div class="table-header"><h3>${{s}} · 个人排名</h3></div><div class="table-scroll"><table id="${{tid}}rank"><thead><tr><th>排名</th><th>姓名</th><th>工号</th><th>部门</th><th>累计勤奋</th><th>月均</th></tr>${{rankFilter}}</thead><tbody>${{rankRows}}</tbody></table></div></div>
    </div>`;
  }});
  contentEl.innerHTML=html;
}}

function switchTab(name,btn){{
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t=>t.classList.remove('active'));
  btn.classList.add('active');
  const tc=document.getElementById('tab-'+name);if(tc)tc.classList.add('active');
}}

function renderRanking(d){{
  const body=document.getElementById('rankBody');
  const top20=d.all_rankings.slice(0,20);
  const mx=Math.max(...top20.map(r=>r.累计勤奋次数),1);
  const tagMap={{'职能岗':'tag-dark','营销岗':'tag-primary','产品岗':'tag-gray'}};
  body.innerHTML=top20.map(r=>`<tr><td><span class="rank ${{r.排名<=3?'rank-'+r.排名:''}}">${{r.排名}}</span></td><td><strong>${{r.姓名}}</strong></td><td style="color:var(--gray-500)">${{r.工号}}</td><td>${{r.部门}}</td><td><span class="tag ${{tagMap[r.岗位]||'tag-gray'}}">${{r.岗位}}</span></td><td><strong style="color:var(--primary)">${{r.累计勤奋次数}}</strong><div class="progress-bar"><div class="fill" style="width:${{(r.累计勤奋次数/mx*100).toFixed(1)}}%"></div></div></td><td>${{r.月均勤奋次数}}</td></tr>`).join('');
}}

async function queryData(){{
  const app=document.getElementById('app');
  app.innerHTML='<div class="loading-screen"><div class="spinner"></div><div>正在从钉钉获取数据...</div></div>';
  const params=getSelectedParams();
  try{{
    let res=await fetch(REFRESH_URL+'?'+params);
    let data=await res.json();
    let retries=0;
    while(data.loading&&retries<120){{
      await new Promise(r=>setTimeout(r,3000));
      res=await fetch(DATA_URL+'?'+params);data=await res.json();retries++;
      if(data.loading){{const el=app.querySelector('.loading-screen div:last-child');if(el)el.textContent=data.message||'加载中...('+retries*3+'秒)';}}
    }}
    if(data.error){{app.innerHTML=`<div class="loading-screen"><div style="color:var(--primary)">⚠ ${{data.error}}</div></div>`;return;}}
    DATA=data;renderDashboard(DATA);
  }}catch(e){{app.innerHTML=`<div class="loading-screen"><div style="color:var(--primary)">⚠ 加载失败: ${{e.message}}</div></div>`;}}
}}

async function forceRefresh(){{
  const params=getSelectedParams();
  const app=document.getElementById('app');
  app.innerHTML='<div class="loading-screen"><div class="spinner"></div><div>正在刷新...</div></div>';
  try{{
    let res=await fetch(REFRESH_URL+'?'+params);let data=await res.json();
    if(data.error){{app.innerHTML=`<div class="loading-screen"><div style="color:var(--primary)">⚠ ${{data.error}}</div></div>`;return;}}
    DATA=data;renderDashboard(DATA);
  }}catch(e){{app.innerHTML=`<div class="loading-screen"><div style="color:var(--primary)">⚠ 刷新失败: ${{e.message}}</div></div>`;}}
}}

function filterTable(tableId){{
  const table=document.getElementById(tableId);
  if(!table)return;
  const filterRow=table.querySelector('.filter-row');
  if(!filterRow)return;
  const inputs=filterRow.querySelectorAll('input');
  const filters=[...inputs].map(inp=>inp.value.toLowerCase());
  const rows=table.querySelectorAll('tbody tr');
  rows.forEach(row=>{{
    const cells=row.querySelectorAll('td');
    let show=true;
    filters.forEach((f,i)=>{{
      if(f&&cells[i]){{
        const text=cells[i].textContent.toLowerCase();
        if(!text.includes(f))show=false;
      }}
    }});
    row.style.display=show?'':'none';
  }});
}}
</script>
</body>
</html>'''
