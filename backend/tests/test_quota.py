from decimal import Decimal as D

from app.services.quota import Usage, evaluate, fair_price_deviates


def test_over_quota_by_amount_only():
    r = evaluate(D("1000000"), D("3000"), Usage(D("850000"), D("2000")), D("220000"), D("500"), 0.1)
    assert r.remaining_amount == D("150000")
    assert r.over_quota is True
    assert r.qty_exceeded is False
    assert r.low_quota is False  # 已超额时不再报配额阈值提醒


def test_qty_exceeded_does_not_trigger_over_quota():
    r = evaluate(D("1000000"), D("100"), Usage(D("0"), D("90")), D("50000"), D("20"), 0.1)
    assert r.over_quota is False
    assert r.qty_exceeded is True


def test_low_quota_warning():
    r = evaluate(D("1000000"), D("3000"), Usage(D("850000"), D("0")), D("100000"), D("1"), 0.1)
    assert r.after_remaining_amount == D("50000")
    assert r.over_quota is False
    assert r.low_quota is True


def test_exact_remaining_is_not_over():
    r = evaluate(D("100"), D("10"), Usage(D("40"), D("0")), D("60"), D("1"), 0.0)
    assert r.over_quota is False


def test_fair_price_deviation():
    assert fair_price_deviates(D("440"), D("430"), 0.1) is False
    assert fair_price_deviates(D("480"), D("430"), 0.1) is True
    assert fair_price_deviates(D("100"), None, 0.1) is False
