"""Render a self-contained HTML dashboard from the local finance DB.

One file, no external requests: data is embedded as JSON and charts are drawn
in inline SVG/JS. Theme-aware (light/dark). Colors come from the validated
data-viz reference palette.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import report
from .store import Store


def build_payload(store: Store, *, months: int = 12, recent: int = 40) -> dict:
    now = datetime.now(timezone.utc)
    m_start, m_end = report.month_bounds(now.year, now.month)
    this_month = report.summarize(store, start=m_start, end=m_end)

    accounts = []
    total_balance = 0
    for a in store.accounts():
        total_balance += a["balance_cents"] or 0
        accounts.append(
            {
                "name": a["name"],
                "org": a["org"],
                "currency": a["currency"],
                "balance_cents": a["balance_cents"] or 0,
                "available_cents": a["available_cents"],
                "balance_date": a["balance_date"],
            }
        )

    recent_rows = []
    for r in store.transactions(limit=recent, include_pending=True):
        recent_rows.append(
            {
                "date": report.fmt_date(r["posted"]),
                "account": store.account_name(r["account_id"]),
                "payee": r["payee"] or r["description"],
                "description": r["description"],
                "category": r["category"] or "Uncategorized",
                "amount_cents": r["amount_cents"],
                "pending": bool(r["pending"]),
            }
        )

    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "month_label": f"{now.year:04d}-{now.month:02d}",
        "total_balance_cents": total_balance,
        "accounts": accounts,
        "this_month": {
            "income_cents": this_month["income_cents"],
            "spending_cents": this_month["spending_cents"],
            "net_cents": this_month["net_cents"],
            "by_category": this_month["by_category"],
        },
        "trend": report.monthly_trend(store, months=months),
        "budgets": report.budget_status(store, year=now.year, month=now.month),
        "recent": recent_rows,
    }


def render(store: Store, *, months: int = 12, recent: int = 40) -> str:
    payload = build_payload(store, months=months, recent=recent)
    data_json = json.dumps(payload, separators=(",", ":"))
    return _HTML.replace("/*__DATA__*/{}", data_json)


def build(
    store: Store,
    out_path: Path | str,
    *,
    months: int = 12,
    recent: int = 40,
) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(store, months=months, recent=recent))
    return out


# ---------------------------------------------------------------------------
# The page. Palette roles come from references/palette.md (validated).
# ---------------------------------------------------------------------------
_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Finance Dashboard</title>
<style>
:root{
  color-scheme: light dark;
  --plane:#f9f9f7; --surface:#fcfcfb; --surface-2:#ffffff;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,0.10);
  --series-1:#2a78d6; --series-2:#008300;
  --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b;
  --success-text:#006300;
}
@media (prefers-color-scheme: dark){
  :root:where(:not([data-theme="light"])){
    --plane:#0d0d0d; --surface:#1a1a19; --surface-2:#222220;
    --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
    --series-1:#3987e5; --series-2:#008300;
    --success-text:#0ca30c;
  }
}
:root[data-theme="dark"]{
  --plane:#0d0d0d; --surface:#1a1a19; --surface-2:#222220;
  --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,0.10);
  --series-1:#3987e5; --series-2:#008300;
  --success-text:#0ca30c;
}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:14px;line-height:1.4}
.wrap{max-width:1120px;margin:0 auto;padding:24px 20px 64px}
header{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:20px}
h1{font-size:20px;margin:0;font-weight:650}
.sub{color:var(--muted);font-size:12px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 18px}
.grid{display:grid;gap:16px}
.tiles{grid-template-columns:repeat(auto-fit,minmax(180px,1fr));margin-bottom:16px}
.tile .label{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.tile .value{font-size:26px;font-weight:650;margin-top:4px}
.tile .value.neg{color:var(--critical)} .tile .value.pos{color:var(--success-text)}
.two{grid-template-columns:1fr 1fr;margin-bottom:16px}
@media(max-width:820px){.two{grid-template-columns:1fr}}
h2{font-size:14px;margin:0 0 14px;font-weight:650}
.acct{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--grid)}
.acct:last-child{border-bottom:0}
.acct .n{color:var(--ink)} .acct .o{color:var(--muted);font-size:12px}
.acct .b{font-variant-numeric:tabular-nums;font-weight:600}
.bar-row{display:grid;grid-template-columns:130px 1fr auto;align-items:center;gap:10px;margin:7px 0}
.bar-row .cat{color:var(--ink-2);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-track{background:var(--grid);border-radius:4px;height:16px;overflow:hidden}
.bar-fill{display:block;height:100%;min-width:2px;border-radius:4px;background:var(--series-1)}
.bar-row .amt{font-variant-numeric:tabular-nums;font-size:13px;color:var(--ink)}
.bud .bar-fill.ok{background:var(--good)} .bud .bar-fill.warn{background:var(--warning)}
.bud .bar-fill.over{background:var(--critical)}
.bud .amt.over{color:var(--critical)}
.legend{display:flex;gap:16px;margin-bottom:8px;font-size:12px;color:var(--ink-2)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.dot{width:10px;height:10px;border-radius:50%;display:inline-block}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--grid)}
th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.03em}
td.num{text-align:right;font-variant-numeric:tabular-nums}
td.neg{color:var(--critical)} td.pos{color:var(--success-text)}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;background:var(--surface-2);
  border:1px solid var(--border);color:var(--ink-2);font-size:11px}
.pending{color:var(--muted);font-style:italic}
.empty{color:var(--muted);padding:8px 0}
.chart-wrap{overflow-x:auto}
svg{display:block;max-width:100%}
.tt{position:fixed;pointer-events:none;background:var(--surface-2);border:1px solid var(--border);
  border-radius:8px;padding:6px 9px;font-size:12px;color:var(--ink);box-shadow:0 4px 14px rgba(0,0,0,.15);
  opacity:0;transition:opacity .08s;z-index:10;white-space:nowrap}
.section-title{display:flex;justify-content:space-between;align-items:baseline}
.theme-btn{background:var(--surface-2);border:1px solid var(--border);border-radius:8px;color:var(--ink-2);
  padding:5px 10px;font-size:12px;cursor:pointer}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Finance Dashboard</h1>
      <div class="sub" id="sub"></div>
    </div>
    <button class="theme-btn" id="themeBtn">Toggle theme</button>
  </header>

  <div class="grid tiles" id="tiles"></div>

  <div class="grid two">
    <div class="card">
      <h2>Accounts</h2>
      <div id="accounts"></div>
    </div>
    <div class="card">
      <div class="section-title"><h2>Spending by category</h2><span class="sub" id="catMonth"></span></div>
      <div id="bycat"></div>
    </div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <h2>Income &amp; spending — last 12 months</h2>
    <div class="legend">
      <span><i class="dot" style="background:var(--series-1)"></i>Spending</span>
      <span><i class="dot" style="background:var(--series-2)"></i>Income</span>
    </div>
    <div class="chart-wrap"><div id="trend"></div></div>
  </div>

  <div class="grid two">
    <div class="card">
      <div class="section-title"><h2>Budget vs actual</h2><span class="sub" id="budMonth"></span></div>
      <div id="budgets" class="bud"></div>
    </div>
    <div class="card">
      <h2>Recent transactions</h2>
      <div class="chart-wrap"><div id="recent"></div></div>
    </div>
  </div>
</div>

<div class="tt" id="tt"></div>

<script>
const DATA = /*__DATA__*/{};
const tt = document.getElementById('tt');
const usd = c => (c<0?'-':'') + '$' + Math.abs(c/100).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const usdPlain = c => '$' + Math.abs(c/100).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
function showTip(html,e){tt.innerHTML=html;tt.style.opacity=1;moveTip(e);}
function moveTip(e){const p=12;let x=e.clientX+p,y=e.clientY+p;
  const r=tt.getBoundingClientRect();
  if(x+r.width>innerWidth)x=e.clientX-r.width-p;
  if(y+r.height>innerHeight)y=e.clientY-r.height-p;
  tt.style.left=x+'px';tt.style.top=y+'px';}
function hideTip(){tt.style.opacity=0;}

// ---- header ----
document.getElementById('sub').textContent = 'Generated ' + DATA.generated_at;
document.getElementById('catMonth').textContent = DATA.month_label;
document.getElementById('budMonth').textContent = DATA.month_label;

// ---- tiles ----
const tm = DATA.this_month;
const tiles = [
  {label:'Total balance', value:usd(DATA.total_balance_cents)},
  {label:'Income · '+DATA.month_label, value:usd(tm.income_cents), cls:'pos'},
  {label:'Spending · '+DATA.month_label, value:usd(tm.spending_cents)},
  {label:'Net · '+DATA.month_label, value:usd(tm.net_cents), cls: tm.net_cents<0?'neg':'pos'},
];
document.getElementById('tiles').innerHTML = tiles.map(t=>
  `<div class="card tile"><div class="label">${t.label}</div>
   <div class="value ${t.cls||''}">${t.value}</div></div>`).join('');

// ---- accounts ----
const accEl = document.getElementById('accounts');
if(!DATA.accounts.length){accEl.innerHTML='<div class="empty">No accounts yet — run <code>sync</code>.</div>';}
else accEl.innerHTML = DATA.accounts.map(a=>
  `<div class="acct"><div><div class="n">${esc(a.name)}</div><div class="o">${esc(a.org||'')}</div></div>
   <div class="b">${usd(a.balance_cents)}</div></div>`).join('');

// ---- spending by category (single-hue bars; label carries identity) ----
const bc = tm.by_category;
const bcEl = document.getElementById('bycat');
if(!bc.length){bcEl.innerHTML='<div class="empty">No spending recorded this month.</div>';}
else{
  const max = Math.max(...bc.map(d=>d.spent_cents));
  bcEl.innerHTML = bc.map(d=>{
    const w = max? (d.spent_cents/max*100):0;
    return `<div class="bar-row" data-tip="${esc(d.category)}: ${usdPlain(d.spent_cents)} · ${d.count} txn">
      <span class="cat" title="${esc(d.category)}">${esc(d.category)}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${w}%"></span></span>
      <span class="amt">${usdPlain(d.spent_cents)}</span></div>`;
  }).join('');
  bindTips(bcEl);
}

// ---- budgets ----
const bud = DATA.budgets;
const budEl = document.getElementById('budgets');
if(!bud.rows.length){budEl.innerHTML='<div class="empty">No budgets set. Use <code>budget set &lt;category&gt; &lt;amount&gt;</code>.</div>';}
else{
  budEl.innerHTML = bud.rows.map(r=>{
    const pct = Math.min(r.pct*100,100);
    const cls = r.pct>1?'over':(r.pct>=0.85?'warn':'ok');
    const amtcls = r.remaining_cents<0?'amt over':'amt';
    return `<div class="bar-row" data-tip="${esc(r.category)}: ${usdPlain(r.actual_cents)} of ${usdPlain(r.budget_cents)} (${Math.round(r.pct*100)}%)">
      <span class="cat" title="${esc(r.category)}">${esc(r.category)}</span>
      <span class="bar-track"><span class="bar-fill ${cls}" style="width:${pct}%"></span></span>
      <span class="${amtcls}">${usdPlain(r.actual_cents)}/${usdPlain(r.budget_cents)}</span></div>`;
  }).join('');
  bindTips(budEl);
}

// ---- trend line chart ----
renderTrend(DATA.trend);
function renderTrend(series){
  const el=document.getElementById('trend');
  if(!series.length){el.innerHTML='<div class="empty">Not enough history yet.</div>';return;}
  const W=Math.max(560,series.length*70), H=240, m={t:14,r:14,b:26,l:52};
  const iw=W-m.l-m.r, ih=H-m.t-m.b;
  const maxv=Math.max(1,...series.map(d=>Math.max(d.spending_cents,d.income_cents)));
  const x=i=>m.l + (series.length===1? iw/2 : i*iw/(series.length-1));
  const y=v=>m.t + ih - (v/maxv)*ih;
  const line=(key)=>series.map((d,i)=>(i?'L':'M')+x(i).toFixed(1)+' '+y(d[key]).toFixed(1)).join(' ');
  const ticks=4, grid=[];
  for(let i=0;i<=ticks;i++){const v=maxv*i/ticks,yy=y(v);
    grid.push(`<line x1="${m.l}" y1="${yy.toFixed(1)}" x2="${W-m.r}" y2="${yy.toFixed(1)}" stroke="var(--grid)"/>
      <text x="${m.l-8}" y="${(yy+3).toFixed(1)}" text-anchor="end" font-size="10" fill="var(--muted)">${usdPlain(v)}</text>`);}
  const xlab=series.map((d,i)=> (i%Math.ceil(series.length/6)===0||i===series.length-1)?
    `<text x="${x(i).toFixed(1)}" y="${H-8}" text-anchor="middle" font-size="10" fill="var(--muted)">${d.month.slice(2)}</text>`:'').join('');
  const dots=(key,color)=>series.map((d,i)=>
    `<circle cx="${x(i).toFixed(1)}" cy="${y(d[key]).toFixed(1)}" r="4" fill="${color}" stroke="var(--surface)" stroke-width="2"/>`).join('');
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img">
    ${grid.join('')}
    <path d="${line('spending_cents')}" fill="none" stroke="var(--series-1)" stroke-width="2"/>
    <path d="${line('income_cents')}" fill="none" stroke="var(--series-2)" stroke-width="2"/>
    ${dots('spending_cents','var(--series-1)')}${dots('income_cents','var(--series-2)')}
    ${xlab}
    <rect id="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/>
  </svg>`;
  const svg=el.querySelector('svg');
  svg.addEventListener('mousemove',e=>{
    const r=svg.getBoundingClientRect();
    const px=(e.clientX-r.left)*(W/r.width);
    let bi=0,bd=1e9; series.forEach((d,i)=>{const dd=Math.abs(x(i)-px);if(dd<bd){bd=dd;bi=i;}});
    const d=series[bi];
    showTip(`<b>${d.month}</b><br>Spending: ${usdPlain(d.spending_cents)}<br>Income: ${usdPlain(d.income_cents)}<br>Net: ${usd(d.net_cents)}`,e);
  });
  svg.addEventListener('mouseleave',hideTip);
}

// ---- recent txns ----
const rEl=document.getElementById('recent');
if(!DATA.recent.length){rEl.innerHTML='<div class="empty">No transactions yet.</div>';}
else rEl.innerHTML=`<table><thead><tr>
   <th>Date</th><th>Payee</th><th>Category</th><th class="num">Amount</th></tr></thead><tbody>`+
   DATA.recent.map(t=>`<tr>
     <td>${t.date}${t.pending?' <span class="pending">·pending</span>':''}</td>
     <td>${esc(t.payee)}<div class="o" style="color:var(--muted);font-size:11px">${esc(t.account)}</div></td>
     <td><span class="pill">${esc(t.category)}</span></td>
     <td class="num ${t.amount_cents<0?'neg':'pos'}">${usd(t.amount_cents)}</td></tr>`).join('')+
   `</tbody></table>`;

function bindTips(root){root.querySelectorAll('[data-tip]').forEach(n=>{
  n.addEventListener('mouseenter',e=>showTip(n.dataset.tip,e));
  n.addEventListener('mousemove',moveTip);
  n.addEventListener('mouseleave',hideTip);});}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

// ---- theme toggle ----
document.getElementById('themeBtn').addEventListener('click',()=>{
  const r=document.documentElement;
  const cur=r.getAttribute('data-theme');
  const dark=cur? cur==='dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  r.setAttribute('data-theme', dark?'light':'dark');
});
</script>
</body>
</html>"""
