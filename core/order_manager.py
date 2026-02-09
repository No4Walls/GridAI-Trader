import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class OrderRecord:
    order_id: str
    side: str
    price: float
    amount: float
    status: str
    grid_index: int
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    filled_at: Optional[str] = None
    fee: float = 0.0


class OrderManager:
    def __init__(
        self,
        place_order_fn: Optional[Callable[..., Dict[str, Any]]] = None,
        cancel_order_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
        fetch_order_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
        fetch_open_orders_fn: Optional[Callable[[], List[Dict[str, Any]]]] = None,
        dry_run: bool = False,
        max_retries: int = 5,
        retry_backoff: float = 2.0,
        rate_limit_per_second: float = 5.0,
        place_buy_order_fn: Optional[Callable[[float, float], Dict[str, Any]]] = None,
        place_sell_order_fn: Optional[Callable[[float, float], Dict[str, Any]]] = None,
    ) -> None:
        self._place_order_fn = place_order_fn
        self._place_buy_order_fn = place_buy_order_fn
        self._place_sell_order_fn = place_sell_order_fn
        self._cancel_order_fn = cancel_order_fn
        self._fetch_order_fn = fetch_order_fn
        self._fetch_open_orders_fn = fetch_open_orders_fn
        self._dry_run = dry_run
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._min_interval = 1.0 / rate_limit_per_second
        self._last_call_time: float = 0.0
        self._orders: Dict[str, OrderRecord] = {}
        self._order_counter: int = 0
        self._daily_order_count: int = 0
        self._daily_reset_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @property
    def orders(self) -> Dict[str, OrderRecord]:
        return self._orders

    @property
    def daily_order_count(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._daily_reset_date != today:
            self._daily_order_count = 0
            self._daily_reset_date = today
        return self._daily_order_count

    def _rate_limit(self) -> None:
        now = time.time()
        elapsed = now - self._last_call_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_time = time.time()

    def _retry_call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                self._rate_limit()
                return fn(*args, **kwargs)
            except Exception as e:
                last_error = e
                wait = self._retry_backoff * (2 ** attempt)
                logger.warning(
                    "Retry %d/%d after error: %s (waiting %.1fs)",
                    attempt + 1,
                    self._max_retries,
                    e,
                    wait,
                )
                time.sleep(wait)
        raise RuntimeError(
            f"Failed after {self._max_retries} retries: {last_error}"
        ) from last_error

    def place_order(
        self, side: str, price: float, amount: float, grid_index: int
    ) -> OrderRecord:
        if self._dry_run:
            self._order_counter += 1
            order_id = f"dry-{self._order_counter}"
            record = OrderRecord(
                order_id=order_id,
                side=side,
                price=price,
                amount=amount,
                status="open",
                grid_index=grid_index,
            )
            self._orders[order_id] = record
            self._daily_order_count += 1
            logger.info(
                "[DRY-RUN] Order placed: %s %s %.8f @ %.2f (grid=%d)",
                order_id,
                side,
                amount,
                price,
                grid_index,
            )
            return record

        # Choose the correct order placement function
        fn: Optional[Callable[..., Dict[str, Any]]]
        if side == "buy":
            fn = self._place_buy_order_fn or self._place_order_fn
        else:
            fn = self._place_sell_order_fn or self._place_order_fn
        if fn is None:
            raise RuntimeError("No place_order function configured for side %s" % side)
        result = self._retry_call(fn, amount, price)

        order_id = result["id"]
        record = OrderRecord(
            order_id=order_id,
            side=side,
            price=price,
            amount=amount,
            status=result.get("status", "open"),
            grid_index=grid_index,
        )
        self._orders[order_id] = record
        self._daily_order_count += 1
        logger.info(
            "Order placed: %s %s %.8f @ %.2f (grid=%d)",
            order_id,
            side,
            amount,
            price,
            grid_index,
        )
        return record

    def cancel_order(self, order_id: str) -> bool:
        if self._dry_run:
            if order_id in self._orders:
                self._orders[order_id].status = "cancelled"
            logger.info("[DRY-RUN] Order cancelled: %s", order_id)
            return True

        if self._cancel_order_fn is None:
            raise RuntimeError("No cancel_order function configured")

        try:
            self._retry_call(self._cancel_order_fn, order_id)
            if order_id in self._orders:
                self._orders[order_id].status = "cancelled"
            logger.info("Order cancelled: %s", order_id)
            return True
        except Exception:
            logger.exception("Failed to cancel order: %s", order_id)
            return False

    def check_order_status(self, order_id: str) -> Optional[str]:
        if self._dry_run:
            record = self._orders.get(order_id)
            return record.status if record else None

        if self._fetch_order_fn is None:
            raise RuntimeError("No fetch_order function configured")

        try:
            result = self._retry_call(self._fetch_order_fn, order_id)
            status = result.get("status", "unknown")
            if order_id in self._orders:
                self._orders[order_id].status = status
                if status == "closed":
                    self._orders[order_id].filled_at = datetime.now(
                        timezone.utc
                    ).isoformat()
                    fee_info = result.get("fee") or {}
                    self._orders[order_id].fee = fee_info.get("cost", 0.0)
            return status
        except Exception:
            logger.exception("Failed to check order %s", order_id)
            return None

    def reconcile_orders(self) -> List[str]:
        if self._dry_run:
            return []

        if self._fetch_open_orders_fn is None:
            return []

        try:
            exchange_orders = self._retry_call(self._fetch_open_orders_fn)
            exchange_ids = {o["id"] for o in exchange_orders}

            filled_ids: List[str] = []
            for oid, record in self._orders.items():
                if record.status == "open" and oid not in exchange_ids:
                    status = self.check_order_status(oid)
                    if status == "closed":
                        filled_ids.append(oid)
                    elif status == "cancelled":
                        logger.info("Order %s was externally cancelled", oid)

            return filled_ids
        except Exception:
            logger.exception("Reconciliation failed")
            return []

    def cancel_all_open(self) -> int:
        count = 0
        for oid, record in list(self._orders.items()):
            if record.status == "open":
                if self.cancel_order(oid):
                    count += 1
        return count

    def get_open_orders(self) -> List[OrderRecord]:
        return [r for r in self._orders.values() if r.status == "open"]

    def get_filled_orders(self) -> List[OrderRecord]:
        return [r for r in self._orders.values() if r.status == "closed"]

    def total_fees(self) -> float:
        return sum(r.fee for r in self._orders.values())

    def to_dict_list(self) -> List[Dict[str, Any]]:
        return [
            {
                "order_id": r.order_id,
                "side": r.side,
                "price": r.price,
                "amount": r.amount,
                "status": r.status,
                "grid_index": r.grid_index,
                "created_at": r.created_at,
                "filled_at": r.filled_at,
                "fee": r.fee,
            }
            for r in self._orders.values()
        ]
