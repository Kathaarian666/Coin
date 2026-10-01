from rhscanner.flow import flow_features


def test_flow_features_windows_and_prices():
    # t, side, trader, usd, price
    rows = [(0, 1, "a", 100, 1.0), (400, 1, "b", 50, 1.2), (700, 1, "c", 300, 2.0), (720, 0, "a", 80, 1.9),
            (750, 1, "d", 100, 2.4)]
    ts, side, trader, usd, price = (list(x) for x in zip(*rows))
    f = flow_features(ts, side, trader, usd, price, 4, first_ts=0, first_price=1.0,
                      wins=lambda w, t: 3 if w == "c" else 0)
    assert (f["b1"], f["b5"], f["prev5"], f["b10"], f["b30"]) == (1, 2, 1, 3, 4)
    assert f["usd10"] == 450 and f["sell10"] == 80 and f["avg10"] == 150
    assert f["hold30"] == 0.75  # a bought and sold
    assert f["runup"] == 2.4 and f["chg5"] == 2.4 / 1.2 and f["age_min"] == 12.5
    assert f["smart10"] == 1 and f["smart_wins10"] == 3
