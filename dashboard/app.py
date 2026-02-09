import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Flask, jsonify, render_template_string
from flask_socketio import SocketIO

logger = logging.getLogger(__name__)

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GridAI Trader Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#0d1117;color:#c9d1d9}
.header{background:#161b22;padding:16px 24px;border-bottom:1px solid #30363d;display:flex;justify-content:space-between;align-items:center}
.header h1{font-size:20px;color:#58a6ff}
.status-badge{padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600}
.status-ok{background:#238636;color:#fff}
.status-warn{background:#d29922;color:#fff}
.status-pause{background:#da3633;color:#fff}
.grid-container{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;padding:16px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px}
.card h3{color:#8b949e;font-size:13px;text-transform:uppercase;margin-bottom:12px;letter-spacing:0.5px}
.metric{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #21262d}
.metric-label{color:#8b949e;font-size:13px}
.metric-value{color:#c9d1d9;font-weight:600;font-size:14px}
.positive{color:#3fb950}
.negative{color:#f85149}
.chart-container{height:250px;position:relative}
.trades-table{width:100%;border-collapse:collapse;font-size:12px}
.trades-table th{text-align:left;padding:8px;color:#8b949e;border-bottom:1px solid #30363d}
.trades-table td{padding:6px 8px;border-bottom:1px solid #21262d}
.grid-viz{display:flex;flex-direction:column;gap:2px}
.grid-level{display:flex;align-items:center;gap:8px;padding:3px 8px;border-radius:4px;font-size:11px}
.grid-buy{background:rgba(63,185,80,0.1);border-left:3px solid #3fb950}
.grid-sell{background:rgba(248,81,73,0.1);border-left:3px solid #f85149}
.grid-active{opacity:1}
.grid-inactive{opacity:0.5}
.risk-check{display:flex;justify-content:space-between;align-items:center;padding:6px 0}
.risk-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px}
.risk-ok{background:#3fb950}
.risk-warn{background:#d29922}
.risk-bad{background:#f85149}
@media(max-width:768px){.grid-container{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="header">
  <h1>GridAI Trader</h1>
  <div>
    <span class="status-badge" id="riskBadge">Loading...</span>
    <span class="status-badge" id="modeBadge" style="background:#1f6feb;color:#fff;margin-left:8px">--</span>
  </div>
</div>
<div class="grid-container">
  <div class="card">
    <h3>Portfolio</h3>
    <div id="portfolio">
      <div class="metric"><span class="metric-label">Capital</span><span class="metric-value" id="capital">--</span></div>
      <div class="metric"><span class="metric-label">BTC Held</span><span class="metric-value" id="btcHeld">--</span></div>
      <div class="metric"><span class="metric-label">Total P&L</span><span class="metric-value" id="totalPnl">--</span></div>
      <div class="metric"><span class="metric-label">Daily P&L</span><span class="metric-value" id="dailyPnl">--</span></div>
      <div class="metric"><span class="metric-label">Drawdown</span><span class="metric-value" id="drawdown">--</span></div>
      <div class="metric"><span class="metric-label">Total Fees</span><span class="metric-value" id="totalFees">--</span></div>
      <div class="metric"><span class="metric-label">Trades</span><span class="metric-value" id="tradeCount">--</span></div>
    </div>
  </div>
  <div class="card">
    <h3>AI & Trend</h3>
    <div class="metric"><span class="metric-label">Volatility Regime</span><span class="metric-value" id="regime">--</span></div>
    <div class="metric"><span class="metric-label">AI Confidence</span><span class="metric-value" id="confidence">--</span></div>
    <div class="metric"><span class="metric-label">Trend State</span><span class="metric-value" id="trendState">--</span></div>
    <div class="metric"><span class="metric-label">RSI</span><span class="metric-value" id="rsi">--</span></div>
    <div class="metric"><span class="metric-label">ADX</span><span class="metric-value" id="adx">--</span></div>
    <div class="metric"><span class="metric-label">Trend Pause</span><span class="metric-value" id="trendPause">--</span></div>
  </div>
  <div class="card">
    <h3>Risk Status</h3>
    <div id="riskChecks"></div>
  </div>
  <div class="card" style="grid-column:span 2">
    <h3>Equity Curve</h3>
    <div class="chart-container"><canvas id="equityChart"></canvas></div>
  </div>
  <div class="card">
    <h3>Grid Levels</h3>
    <div class="metric"><span class="metric-label">Center</span><span class="metric-value" id="gridCenter">--</span></div>
    <div class="metric"><span class="metric-label">Bounds</span><span class="metric-value" id="gridBounds">--</span></div>
    <div class="metric"><span class="metric-label">Spacing</span><span class="metric-value" id="gridSpacing">--</span></div>
    <div class="grid-viz" id="gridLevels" style="max-height:200px;overflow-y:auto;margin-top:8px"></div>
  </div>
  <div class="card" style="grid-column:span 2">
    <h3>Recent Trades</h3>
    <div style="max-height:300px;overflow-y:auto">
      <table class="trades-table">
        <thead><tr><th>ID</th><th>Buy</th><th>Sell</th><th>Amt</th><th>Profit</th><th>Fee</th><th>Time</th></tr></thead>
        <tbody id="tradesBody"></tbody>
      </table>
    </div>
  </div>
</div>
<script>
const socket = io();
let equityChart;

function initChart(){
  const ctx = document.getElementById('equityChart').getContext('2d');
  equityChart = new Chart(ctx, {
    type:'line',
    data:{labels:[],datasets:[{label:'Equity (USDT)',data:[],borderColor:'#58a6ff',backgroundColor:'rgba(88,166,255,0.1)',fill:true,tension:0.1,pointRadius:0}]},
    options:{responsive:true,maintainAspectRatio:false,scales:{x:{display:true,ticks:{color:'#8b949e',maxTicksLimit:10},grid:{color:'#21262d'}},y:{ticks:{color:'#8b949e'},grid:{color:'#21262d'}}},plugins:{legend:{display:false}}}
  });
}

function fmt(v,d=2){return v!=null?Number(v).toFixed(d):'--'}
function pnlClass(v){return v>0?'positive':v<0?'negative':''}

socket.on('update', function(data){
  if(data.position){
    const p=data.position;
    document.getElementById('capital').textContent='$'+fmt(p.current_capital);
    document.getElementById('btcHeld').textContent=fmt(p.btc_held,8);
    const pnl=p.total_pnl||0;
    const el=document.getElementById('totalPnl');
    el.textContent='$'+fmt(pnl);el.className='metric-value '+pnlClass(pnl);
    const dp=p.daily_pnl||0;
    const del=document.getElementById('dailyPnl');
    del.textContent='$'+fmt(dp);del.className='metric-value '+pnlClass(dp);
    document.getElementById('drawdown').textContent=fmt(p.drawdown_pct)+'%';
    document.getElementById('totalFees').textContent='$'+fmt(p.total_fees);
    document.getElementById('tradeCount').textContent=p.trade_count||0;
  }
  if(data.volatility){
    document.getElementById('regime').textContent=data.volatility.regime||'--';
    document.getElementById('confidence').textContent=fmt(data.volatility.confidence*100,1)+'%';
  }
  if(data.trend){
    document.getElementById('trendState').textContent=data.trend.state||'--';
    document.getElementById('rsi').textContent=fmt(data.trend.rsi);
    document.getElementById('adx').textContent=fmt(data.trend.adx);
    document.getElementById('trendPause').textContent=data.trend.should_pause?'YES':'NO';
  }
  if(data.risk){
    const badge=document.getElementById('riskBadge');
    if(data.risk.paused){badge.textContent='PAUSED';badge.className='status-badge status-pause'}
    else if(data.risk.overall_action==='WARN'){badge.textContent='WARNING';badge.className='status-badge status-warn'}
    else{badge.textContent='RUNNING';badge.className='status-badge status-ok'}
    const rc=document.getElementById('riskChecks');
    if(data.risk.checks){
      rc.innerHTML=data.risk.checks.map(c=>{
        const dot=c.action==='OK'?'risk-ok':c.action==='WARN'?'risk-warn':'risk-bad';
        return `<div class="risk-check"><span><span class="risk-dot ${dot}"></span>${c.name}</span><span class="metric-value">${fmt(c.value)}/${fmt(c.threshold)}</span></div>`;
      }).join('');
    }
  }
  if(data.grid){
    document.getElementById('gridCenter').textContent='$'+fmt(data.grid.center_price);
    document.getElementById('gridBounds').textContent='$'+fmt(data.grid.lower_bound)+' - $'+fmt(data.grid.upper_bound);
    document.getElementById('gridSpacing').textContent='$'+fmt(data.grid.spacing);
    if(data.grid.levels){
      const gl=document.getElementById('gridLevels');
      gl.innerHTML=data.grid.levels.slice(0,20).map(l=>{
        const cls=l.side==='buy'?'grid-buy':'grid-sell';
        const act=l.is_active?'grid-active':'grid-inactive';
        const st=l.filled?'[FILLED]':l.is_active?'[ACTIVE]':'';
        return `<div class="grid-level ${cls} ${act}">$${fmt(l.price)} ${l.side.toUpperCase()} ${st}</div>`;
      }).join('');
    }
  }
  if(data.mode){document.getElementById('modeBadge').textContent=data.mode.toUpperCase()}
  if(data.equity_history&&data.equity_history.length>0){
    equityChart.data.labels=data.equity_history.map(e=>e.timestamp?e.timestamp.slice(11,19):'');
    equityChart.data.datasets[0].data=data.equity_history.map(e=>e.equity);
    equityChart.update('none');
  }
  if(data.trades){
    const tb=document.getElementById('tradesBody');
    tb.innerHTML=data.trades.slice(-50).reverse().map(t=>{
      const pc=pnlClass(t.net_profit_usdt);
      return `<tr><td>${t.trade_id||''}</td><td>$${fmt(t.buy_price)}</td><td>$${fmt(t.sell_price)}</td><td>${fmt(t.amount,6)}</td><td class="${pc}">$${fmt(t.net_profit_usdt)}</td><td>$${fmt(t.fee_usdt,4)}</td><td>${(t.timestamp||'').slice(0,19)}</td></tr>`;
    }).join('');
  }
});

initChart();
</script>
</body>
</html>
"""


def create_app(
    db_path: str = "state/gridai.db",
    state_provider: Optional[Any] = None,
) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("JWT_SECRET", "gridai-dev-secret")
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

    @app.route("/")
    def index():
        return render_template_string(DASHBOARD_HTML)

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.route("/api/state")
    def api_state():
        if state_provider:
            return jsonify(state_provider())
        return jsonify(_load_state_from_db(db_path))

    def _load_state_from_db(path: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        try:
            if not Path(path).exists():
                return result
            with sqlite3.connect(path) as conn:
                rows = conn.execute("SELECT key, value FROM state").fetchall()
                state = dict(rows)
                result["position"] = {
                    "current_capital": float(state.get("current_capital", 0)),
                    "btc_held": float(state.get("btc_held", 0)),
                    "total_fees": float(state.get("total_fees", 0)),
                    "trade_count": int(state.get("trade_count", 0)),
                    "initial_capital": float(state.get("initial_capital", 0)),
                }

                eq_rows = conn.execute(
                    "SELECT timestamp, equity_usdt FROM equity_snapshots ORDER BY id DESC LIMIT 200"
                ).fetchall()
                result["equity_history"] = [
                    {"timestamp": r[0], "equity": r[1]} for r in reversed(eq_rows)
                ]

                trade_rows = conn.execute(
                    "SELECT * FROM trades ORDER BY rowid DESC LIMIT 50"
                ).fetchall()
                result["trades"] = [
                    {
                        "trade_id": r[0], "buy_price": r[3], "sell_price": r[4],
                        "amount": r[5], "profit_usdt": r[6], "fee_usdt": r[7],
                        "net_profit_usdt": r[8], "timestamp": r[9],
                    }
                    for r in reversed(trade_rows)
                ]
        except Exception:
            logger.exception("Error loading state from DB")
        return result

    def background_push():
        while True:
            try:
                if state_provider:
                    data = state_provider()
                else:
                    data = _load_state_from_db(db_path)
                socketio.emit("update", data)
            except Exception:
                logger.exception("Error in background push")
            socketio.sleep(2)

    socketio.start_background_task(background_push)

    app.socketio = socketio
    return app


def run_dashboard(
    host: str = "0.0.0.0",
    port: int = 8080,
    db_path: str = "state/gridai.db",
    state_provider: Optional[Any] = None,
) -> None:
    app = create_app(db_path=db_path, state_provider=state_provider)
    logging.basicConfig(level=logging.INFO)
    logger.info("Dashboard starting on %s:%d", host, port)
    app.socketio.run(app, host=host, port=port, log_output=True)
