CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS candles (
  ts timestamptz NOT NULL,
  timeframe text NOT NULL,
  open numeric NOT NULL,
  high numeric NOT NULL,
  low numeric NOT NULL,
  close numeric NOT NULL,
  volume numeric DEFAULT 0,
  PRIMARY KEY (ts, timeframe)
);
SELECT create_hypertable('candles', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS indicators (
  ts timestamptz NOT NULL PRIMARY KEY,
  ema20 numeric, ema50 numeric, ema200 numeric,
  rsi numeric, macd numeric, macd_signal numeric,
  bb_upper numeric, bb_lower numeric,
  atr numeric, adx numeric
);
SELECT create_hypertable('indicators', 'ts', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS trade_events (
  ts timestamptz NOT NULL,
  trade_id text,
  side text,
  price numeric,
  qty numeric,
  fee numeric,
  pnl numeric,
  regime text,
  confidence numeric,
  grid_level int
);
SELECT create_hypertable('trade_events', 'ts', if_not_exists => TRUE);
