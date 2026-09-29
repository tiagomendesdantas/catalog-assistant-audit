import pytest
from conftest import TEST_MODEL

from catalog_audit.guard import Blocked, Limits, SpendGuard, UnknownPrice, call_cost_usd


class FakeClock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_cost_uses_per_million_prices():
    assert call_cost_usd(TEST_MODEL, 1_000_000, 0) == pytest.approx(2.00)
    assert call_cost_usd(TEST_MODEL, 0, 1_000_000) == pytest.approx(8.00)
    assert call_cost_usd(TEST_MODEL, 2_000, 1_000) == pytest.approx(0.012)


def test_unknown_price_fails_closed():
    with pytest.raises(UnknownPrice):
        call_cost_usd("model-without-a-verified-price", 10, 10)


def test_hourly_limit_per_ip_then_recovers():
    clock = FakeClock()
    guard = SpendGuard(Limits(per_ip_per_hour=2, per_ip_per_day=10, daily_usd=100), clock)
    guard.reserve("a", 0.01)
    guard.reserve("a", 0.01)
    with pytest.raises(Blocked, match="Hourly"):
        guard.reserve("a", 0.01)
    guard.reserve("b", 0.01)  # other visitors are unaffected
    clock.t += 3_601
    guard.reserve("a", 0.01)


def test_daily_limit_per_ip():
    clock = FakeClock()
    guard = SpendGuard(Limits(per_ip_per_hour=100, per_ip_per_day=3, daily_usd=100), clock)
    for _ in range(3):
        guard.reserve("a", 0.01)
        clock.t += 10
    with pytest.raises(Blocked, match="Daily limit"):
        guard.reserve("a", 0.01)


def test_budget_counts_reservations_and_settles_to_actual_cost():
    clock = FakeClock()
    guard = SpendGuard(Limits(per_ip_per_hour=100, per_ip_per_day=100, daily_usd=1.00), clock)
    guard.reserve("a", 0.60)
    with pytest.raises(Blocked, match="budget"):
        guard.reserve("b", 0.60)  # the first call has not settled yet
    guard.settle(reserved_usd=0.60, actual_usd=0.05)
    assert guard.spent_today == pytest.approx(0.05)
    guard.reserve("b", 0.60)


def test_budget_resets_on_a_new_day():
    clock = FakeClock()
    guard = SpendGuard(Limits(per_ip_per_hour=100, per_ip_per_day=100, daily_usd=0.10), clock)
    guard.reserve("a", 0.10)
    guard.settle(0.10, 0.10)
    with pytest.raises(Blocked):
        guard.reserve("a", 0.01)
    clock.t += 86_400
    guard.reserve("a", 0.01)
