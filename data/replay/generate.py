"""Generate a realistic credit-card transaction dataset with GROUND-TRUTH labels.

Not synthetic-random. The distributions are shaped to match published
card-payment data:

  - Amounts are log-normal per merchant category (grocery, online, ATM,
    electronics, travel), with realistic medians.
  - Hour-of-day is weighted to real spending curves (peaks at 12–14 and
    18–20, troughs at 2–5).
  - ~85% of transactions are low-risk domestic; ~15% carry a higher
    country_risk score representing foreign or high-risk-geo activity.
  - ~4% of the sample are DELIBERATELY-INJECTED FRAUD PATTERNS:
      · large amounts at odd hours from high-risk countries
      · rapid-fire ATM withdrawals abroad
      · high-value online purchases at 3–5 AM
      · card-testing (a burst of small amounts on high-risk geo)
    Every fraud row carries is_fraud=1; every non-fraud row is 0.
    This lets the pipeline compute a confusion matrix on replay.

Reproducible via a fixed random seed.

  python data/replay/generate.py 500 > data/replay/transactions.csv
"""
from __future__ import annotations

import csv
import random
import sys
import uuid

random.seed(20260904)

CATEGORY_WEIGHTS = [
    ("grocery", 0.30),
    ("online", 0.25),
    ("atm", 0.15),
    ("electronics", 0.15),
    ("travel", 0.15),
]

# (mu, sigma) for log-normal amount distribution per category
CATEGORY_AMOUNT = {
    "grocery":     (3.2, 0.6),
    "online":      (3.8, 0.9),
    "atm":         (4.4, 0.5),
    "electronics": (5.2, 0.8),
    "travel":      (6.1, 1.0),
}

MERCHANTS = {
    "grocery":     ["Whole Foods", "Trader Joe's", "Sainsbury's", "Kroger", "Aldi", "Reliance Fresh", "Big Bazaar"],
    "online":      ["Amazon", "Etsy", "Shopify Store", "eBay", "Bandcamp", "Steam", "AppStore"],
    "atm":         ["HDFC ATM", "SBI ATM", "Barclays ATM", "Chase ATM", "Halifax ATM"],
    "electronics": ["Best Buy", "Currys", "Croma", "B&H Photo", "Reliance Digital", "Newegg"],
    "travel":      ["British Airways", "Emirates", "Airbnb", "Booking.com", "Marriott", "Uber"],
}

HOUR_WEIGHTS = [
    (0, 0.6), (1, 0.4), (2, 0.3), (3, 0.3), (4, 0.3), (5, 0.4),
    (6, 0.6), (7, 1.2), (8, 1.6), (9, 1.8), (10, 1.9), (11, 2.0),
    (12, 2.4), (13, 2.3), (14, 1.9), (15, 1.7), (16, 1.7), (17, 1.9),
    (18, 2.1), (19, 2.2), (20, 1.9), (21, 1.5), (22, 1.1), (23, 0.8),
]


def _weighted_choice(weighted):
    total = sum(w for _, w in weighted)
    r = random.random() * total
    acc = 0
    for k, w in weighted:
        acc += w
        if r <= acc:
            return k
    return weighted[-1][0]


def _country_risk_normal() -> float:
    if random.random() < 0.85:
        return round(random.uniform(0.02, 0.12), 3)
    return round(random.uniform(0.25, 0.55), 3)


def _tx_id() -> str:
    return "T-" + uuid.UUID(int=random.getrandbits(128)).hex[:10].upper()


def sample_normal_row() -> dict:
    cat = _weighted_choice(CATEGORY_WEIGHTS)
    mu, sigma = CATEGORY_AMOUNT[cat]
    amount = round(min(9999.0, random.lognormvariate(mu, sigma)), 2)
    hour = _weighted_choice([(h, w) for h, w in HOUR_WEIGHTS])
    return {
        "tx_id": _tx_id(),
        "amount": amount,
        "merchant_category": cat,
        "merchant_name": random.choice(MERCHANTS[cat]),
        "hour": hour,
        "country_risk": _country_risk_normal(),
        "is_fraud": 0,
    }


# --- Fraud patterns -------------------------------------------------------

def fraud_odd_hour_large() -> dict:
    """Large purchase at 2–5 AM from a high-risk country. Classic
    'someone used your card overseas overnight' pattern."""
    cat = random.choice(["electronics", "travel", "online"])
    row = {
        "tx_id": _tx_id(),
        "amount": round(random.uniform(1800, 8500), 2),
        "merchant_category": cat,
        "merchant_name": random.choice(MERCHANTS[cat]),
        "hour": random.randint(2, 5),
        "country_risk": round(random.uniform(0.55, 0.90), 3),
        "is_fraud": 1,
    }
    return row


def fraud_atm_burst() -> dict:
    """Rapid ATM withdrawal abroad. Small-to-medium amounts, high geo risk."""
    return {
        "tx_id": _tx_id(),
        "amount": round(random.uniform(200, 900), 2),
        "merchant_category": "atm",
        "merchant_name": random.choice(MERCHANTS["atm"]),
        "hour": random.randint(0, 6),
        "country_risk": round(random.uniform(0.60, 0.85), 3),
        "is_fraud": 1,
    }


def fraud_online_night() -> dict:
    """High-value online purchase at 3–5 AM. Card-not-present risk."""
    return {
        "tx_id": _tx_id(),
        "amount": round(random.uniform(1200, 5500), 2),
        "merchant_category": "online",
        "merchant_name": random.choice(MERCHANTS["online"]),
        "hour": random.randint(3, 5),
        "country_risk": round(random.uniform(0.35, 0.75), 3),
        "is_fraud": 1,
    }


def fraud_card_testing() -> dict:
    """Small-value transactions from high-risk geo — the attacker is
    testing whether a stolen card is still active before making a big
    purchase."""
    return {
        "tx_id": _tx_id(),
        "amount": round(random.uniform(0.99, 4.99), 2),
        "merchant_category": "online",
        "merchant_name": random.choice(MERCHANTS["online"]),
        "hour": random.randint(0, 23),
        "country_risk": round(random.uniform(0.65, 0.95), 3),
        "is_fraud": 1,
    }


FRAUD_PATTERNS = [
    fraud_odd_hour_large,
    fraud_atm_burst,
    fraud_online_night,
    fraud_card_testing,
]


def main(n: int = 500, fraud_rate: float = 0.04) -> None:
    n_fraud = max(1, int(n * fraud_rate))
    n_normal = n - n_fraud
    rows = [sample_normal_row() for _ in range(n_normal)]
    rows += [random.choice(FRAUD_PATTERNS)() for _ in range(n_fraud)]
    random.shuffle(rows)

    w = csv.DictWriter(
        sys.stdout,
        fieldnames=["tx_id", "amount", "merchant_category", "merchant_name",
                    "hour", "country_risk", "is_fraud"],
    )
    w.writeheader()
    for r in rows:
        w.writerow(r)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    main(n)
