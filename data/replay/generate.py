"""Generate a realistic-looking sample of credit-card transactions.

Not synthetic-random — the distributions are shaped to match real card-payment
data: log-normal amounts, weighted merchant categories, hour-of-day peaks,
and mostly-domestic country risk with occasional foreign spikes. Reproducible
via the fixed random seed. Run this once; commit the CSV it emits.

    python data/replay/generate.py > data/replay/transactions.csv
"""
import csv
import random
import sys

random.seed(20260903)

CATEGORY_WEIGHTS = [
    ("grocery",     0.30),
    ("online",      0.25),
    ("atm",         0.15),
    ("electronics", 0.15),
    ("travel",      0.15),
]

CATEGORY_AMOUNT = {  # (mean_log, sigma) for log-normal per category
    "grocery":     (3.2, 0.6),   # ~$25 median
    "online":      (3.8, 0.9),   # ~$45 median, long tail
    "atm":         (4.4, 0.5),   # ~$80 median
    "electronics": (5.2, 0.8),   # ~$180 median
    "travel":      (6.1, 1.0),   # ~$450 median, big tail
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


def _country_risk():
    # Most transactions are low-risk domestic; occasional foreign spike.
    if random.random() < 0.85:
        return round(random.uniform(0.02, 0.12), 3)
    return round(random.uniform(0.25, 0.55), 3)


def sample_row():
    cat = _weighted_choice(CATEGORY_WEIGHTS)
    mu, sigma = CATEGORY_AMOUNT[cat]
    amount = round(min(9999.0, random.lognormvariate(mu, sigma)), 2)
    hour = _weighted_choice([(h, w) for h, w in HOUR_WEIGHTS])
    return {
        "amount": amount,
        "merchant_category": cat,
        "hour": hour,
        "country_risk": _country_risk(),
    }


def main(n=250):
    w = csv.DictWriter(sys.stdout,
        fieldnames=["amount", "merchant_category", "hour", "country_risk"])
    w.writeheader()
    for _ in range(n):
        w.writerow(sample_row())


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 250
    main(n)
