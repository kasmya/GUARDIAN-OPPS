"""Deliberately rule-based scorer. See DIARY.md section 1 for why."""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class Transaction:
    amount: float
    merchant_category: str
    hour: int
    country_risk: float = 0.1

    @classmethod
    def sample(cls) -> "Transaction":
        return cls(
            amount=round(random.uniform(5, 8000), 2),
            merchant_category=random.choice(
                ["grocery", "electronics", "travel", "atm", "online"]
            ),
            hour=random.randint(0, 23),
            country_risk=random.choice([0.05, 0.1, 0.2, 0.4]),
        )


def score_normal(tx: Transaction) -> float:
    amount_signal = min(1.0, tx.amount / 10000.0)
    hour_signal = 0.6 if tx.hour < 5 or tx.hour > 22 else 0.15
    cat_signal = {"electronics": 0.5, "online": 0.35, "atm": 0.4}.get(
        tx.merchant_category, 0.15
    )
    noise = random.random() * 0.15
    raw = 0.45 * amount_signal + 0.2 * hour_signal + 0.2 * cat_signal + 0.15 * noise
    return round(min(1.0, max(0.0, raw + tx.country_risk * 0.1)), 4)


def score_corrupt(tx: Transaction) -> float:
    """Simulates a silently-broken model. Distribution is shifted high — every
    transaction looks fraudulent. A real bank would start declining every card."""
    return round(random.betavariate(9, 1.4), 4)
