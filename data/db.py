import os
import psycopg2
from psycopg2.extras import execute_values
from typing import Any, Dict, Iterable, Tuple


def get_conn():
    return psycopg2.connect(
        host=os.getenv('PGHOST', 'db'),
        port=int(os.getenv('PGPORT', '5432')),
        user=os.getenv('PGUSER', 'gridai'),
        password=os.getenv('PGPASSWORD', 'gridai'),
        dbname=os.getenv('PGDATABASE', 'gridai'),
    )


def ensure_schema() -> None:
    ddl = """
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
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()


def insert_trade_event(row: Dict[str, Any]) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO trade_events(ts, trade_id, side, price, qty, fee, pnl, regime, confidence, grid_level)
                VALUES (%(ts)s, %(trade_id)s, %(side)s, %(price)s, %(qty)s, %(fee)s, %(pnl)s, %(regime)s, %(confidence)s, %(grid_level)s)
                """,
                row,
            )
        conn.commit()


def upsert_candles(rows: Iterable[Tuple]) -> None:
    # rows: (ts, timeframe, open, high, low, close, volume)
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO candles(ts, timeframe, open, high, low, close, volume)
                VALUES %s
                ON CONFLICT (ts, timeframe) DO UPDATE SET
                  open=EXCLUDED.open,
                  high=EXCLUDED.high,
                  low=EXCLUDED.low,
                  close=EXCLUDED.close,
                  volume=EXCLUDED.volume
                """,
                rows,
            )
        conn.commit()


def upsert_indicator(ts, ema20, ema50, ema200, rsi_v, macd_v, macd_signal_v, bb_u, bb_l, atr_v, adx_v) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO indicators(ts, ema20, ema50, ema200, rsi, macd, macd_signal, bb_upper, bb_lower, atr, adx)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (ts) DO UPDATE SET
                  ema20=EXCLUDED.ema20, ema50=EXCLUDED.ema50, ema200=EXCLUDED.ema200,
                  rsi=EXCLUDED.rsi, macd=EXCLUDED.macd, macd_signal=EXCLUDED.macd_signal,
                  bb_upper=EXCLUDED.bb_upper, bb_lower=EXCLUDED.bb_lower,
                  atr=EXCLUDED.atr, adx=EXCLUDED.adx
                """,
                (ts, ema20, ema50, ema200, rsi_v, macd_v, macd_signal_v, bb_u, bb_l, atr_v, adx_v),
            )
        conn.commit()
