from prometheus_client import Gauge, start_http_server

# Gauges (all values updated by bot)
bot_mode = Gauge('bot_mode', 'Bot mode', ['mode'])
exchange_connected = Gauge('exchange_connected', 'Exchange connectivity (1=ok,0=down)')
ws_connected = Gauge('ws_connected', 'Websocket connectivity (1=ok,0=down)')
api_latency_ms = Gauge('api_latency_ms', 'API latency in milliseconds')
last_tick_age_seconds = Gauge('last_tick_age_seconds', 'Seconds since last tick')
current_price_usd = Gauge('current_price_usd', 'Current price in USD')
equity_usd = Gauge('equity_usd', 'Account equity in USD')
pnl_total_usd = Gauge('pnl_total_usd', 'Total PnL in USD')
pnl_daily_usd = Gauge('pnl_daily_usd', 'Daily PnL in USD')
drawdown_pct = Gauge('drawdown_pct', 'Drawdown percentage')
fees_total_usd = Gauge('fees_total_usd', 'Total fees in USD')
capital_deployed_pct = Gauge('capital_deployed_pct', 'Capital deployed percentage')
open_orders_count = Gauge('open_orders_count', 'Open orders count')
failed_orders_count_1h = Gauge('failed_orders_count_1h', 'Failed orders in last hour')
reconciliation_ok = Gauge('reconciliation_ok', 'Reconciliation status (1=ok,0=error)')
volatility_regime = Gauge('volatility_regime', 'Volatility regime flag', ['regime'])
volatility_confidence = Gauge('volatility_confidence', 'Volatility confidence [0,1]')
trend_state = Gauge('trend_state', 'Trend state flag', ['state'])
trend_pause = Gauge('trend_pause', 'Trading paused by trend (1=yes,0=no)')
rsi = Gauge('rsi', 'RSI 14')
adx = Gauge('adx', 'ADX 14')
atr = Gauge('atr', 'ATR 14')
grid_center_price = Gauge('grid_center_price', 'Grid center price')
grid_lower_bound = Gauge('grid_lower_bound', 'Grid lower bound')
grid_upper_bound = Gauge('grid_upper_bound', 'Grid upper bound')
grid_spacing = Gauge('grid_spacing', 'Grid spacing')


def start_metrics_server(port: int = 9000) -> None:
    # Expose metrics at http://0.0.0.0:<port>/metrics
    start_http_server(port)
