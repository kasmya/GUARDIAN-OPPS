import random

from app.scoring import Transaction, score_corrupt, score_normal


def test_normal_score_bounds():
    random.seed(0)
    for _ in range(200):
        s = score_normal(Transaction.sample())
        assert 0.0 <= s <= 1.0


def test_corrupt_shifts_distribution_upward():
    random.seed(0)
    normal = [score_normal(Transaction.sample()) for _ in range(400)]
    corrupt = [score_corrupt(Transaction.sample()) for _ in range(400)]
    assert sum(corrupt) / len(corrupt) > sum(normal) / len(normal) + 0.15


def test_high_amount_late_hour_increases_score():
    random.seed(0)
    low = score_normal(Transaction(amount=20, merchant_category="grocery", hour=12))
    high = score_normal(Transaction(amount=8000, merchant_category="online", hour=3))
    assert high > low
