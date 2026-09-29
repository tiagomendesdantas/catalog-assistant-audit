"""Cost and abuse limits for the live "ask your own question" endpoint.

Everything else on the demo is precomputed, so this is the only path that spends money. Limits are
kept in memory: they reset when the service restarts, which is why the API key also belongs to a
project with a monthly budget set in the OpenAI dashboard. That budget is the backstop; this class
keeps a single visitor, or a burst of them, from reaching it.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

# USD per million tokens (input, output), standard API rates. Each entry is copied from the
# provider's pricing page on the date noted; a model missing from this table has no known cost,
# so the live endpoint refuses to call it and cost reports show it as unknown.
# Reasoning tokens are billed as output and are included in completion_tokens.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {}


class UnknownPrice(KeyError):
    pass


def call_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICES_PER_MTOK:
        raise UnknownPrice(f"No verified price for {model}; add it to PRICES_PER_MTOK.")
    price_in, price_out = PRICES_PER_MTOK[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


@dataclass(frozen=True)
class Limits:
    per_ip_per_hour: int = 5
    per_ip_per_day: int = 20
    daily_usd: float = 2.00


class Blocked(Exception):
    """Raised when a live call would exceed a limit. The message is shown to the visitor."""


class SpendGuard:
    def __init__(self, limits: Limits | None = None, clock: Callable[[], float] = time.time):
        self.limits = limits or Limits()
        self._clock = clock
        self._lock = threading.Lock()
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._day = self._day_key()
        self._spent_today = 0.0
        self._reserved = 0.0

    def _day_key(self) -> int:
        return int(self._clock() // 86_400)

    def _roll_day(self) -> None:
        today = self._day_key()
        if today != self._day:
            self._day, self._spent_today, self._reserved = today, 0.0, 0.0

    def reserve(self, ip: str, worst_case_usd: float) -> None:
        """Admit a call or raise Blocked. Holds worst_case_usd until settle() is called."""
        with self._lock:
            self._roll_day()
            now = self._clock()
            calls = self._calls[ip]
            while calls and now - calls[0] > 86_400:
                calls.popleft()
            last_hour = sum(1 for t in calls if now - t <= 3_600)
            if last_hour >= self.limits.per_ip_per_hour:
                raise Blocked("Hourly limit for live questions reached. The examples still work.")
            if len(calls) >= self.limits.per_ip_per_day:
                raise Blocked("Daily limit for live questions reached. The examples still work.")
            if self._spent_today + self._reserved + worst_case_usd > self.limits.daily_usd:
                raise Blocked("The demo's daily budget is spent. The examples still work.")
            calls.append(now)
            self._reserved += worst_case_usd

    def settle(self, reserved_usd: float, actual_usd: float) -> None:
        with self._lock:
            self._roll_day()
            self._reserved = max(0.0, self._reserved - reserved_usd)
            self._spent_today += actual_usd

    @property
    def spent_today(self) -> float:
        with self._lock:
            self._roll_day()
            return self._spent_today
