import logging
from typing import Any, Dict, List

import numpy as np

logger = logging.getLogger(__name__)


def compute_sharpe_ratio(
    returns: List[float], risk_free_rate: float = 0.0, periods_per_year: float = 252 * 288
) -> float:
    if not returns or len(returns) < 2:
        return 0.0
    arr = np.array(returns, dtype=float)
    excess = arr - risk_free_rate / periods_per_year
    mean_ret = np.mean(excess)
    std_ret = np.std(excess, ddof=1)
    if std_ret == 0:
        return 0.0
    return float(mean_ret / std_ret * np.sqrt(periods_per_year))


def compute_max_drawdown(equity_curve: List[float]) -> float:
    if not equity_curve or len(equity_curve) < 2:
        return 0.0
    arr = np.array(equity_curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    drawdown = (peak - arr) / peak * 100
    return float(np.max(drawdown))


def compute_win_rate(trades: List[Dict[str, Any]]) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.get("net_profit_usdt", 0) > 0)
    return wins / len(trades) * 100


def compute_profit_factor(trades: List[Dict[str, Any]]) -> float:
    gross_profit = sum(
        t["net_profit_usdt"] for t in trades if t.get("net_profit_usdt", 0) > 0
    )
    gross_loss = abs(
        sum(t["net_profit_usdt"] for t in trades if t.get("net_profit_usdt", 0) < 0)
    )
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def compute_sortino_ratio(
    returns: List[float], risk_free_rate: float = 0.0, periods_per_year: float = 252 * 288
) -> float:
    if not returns or len(returns) < 2:
        return 0.0
    arr = np.array(returns, dtype=float)
    excess = arr - risk_free_rate / periods_per_year
    mean_ret = np.mean(excess)
    downside = arr[arr < 0]
    if len(downside) == 0:
        return float("inf") if mean_ret > 0 else 0.0
    downside_std = np.std(downside, ddof=1)
    if downside_std == 0:
        return 0.0
    return float(mean_ret / downside_std * np.sqrt(periods_per_year))


def compute_calmar_ratio(
    total_return_pct: float, max_drawdown_pct: float
) -> float:
    if max_drawdown_pct == 0:
        return 0.0
    return total_return_pct / max_drawdown_pct


def compute_all_metrics(
    equity_curve: List[float],
    trades: List[Dict[str, Any]],
    initial_capital: float,
) -> Dict[str, Any]:
    if not equity_curve:
        return {}

    returns = []
    for i in range(1, len(equity_curve)):
        if equity_curve[i - 1] > 0:
            returns.append(
                (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
            )

    final_equity = equity_curve[-1]
    total_return = final_equity - initial_capital
    total_return_pct = total_return / initial_capital * 100 if initial_capital > 0 else 0
    max_dd = compute_max_drawdown(equity_curve)

    total_fees = sum(t.get("fee_usdt", 0) for t in trades)

    return {
        "initial_capital": initial_capital,
        "final_equity": round(final_equity, 2),
        "total_return_usdt": round(total_return, 2),
        "total_return_pct": round(total_return_pct, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(compute_sharpe_ratio(returns), 4),
        "sortino_ratio": round(compute_sortino_ratio(returns), 4),
        "calmar_ratio": round(compute_calmar_ratio(total_return_pct, max_dd), 4),
        "win_rate_pct": round(compute_win_rate(trades), 2),
        "profit_factor": round(compute_profit_factor(trades), 4),
        "total_trades": len(trades),
        "total_fees_usdt": round(total_fees, 2),
        "avg_trade_profit": round(
            total_return / len(trades), 4
        ) if trades else 0,
    }
