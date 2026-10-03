from rhscanner import safety
from rhscanner.report import format_safety

PONS_HOOK = "0x4e3468951d49f2eea976ed0d6e75ffcb44a9a544"


def test_all_14_checks_in_order_unknown_when_nothing_is_known():
    items = safety.checklist({"contract": None}, 0, False, None, None, None)
    assert [n for n, _, _ in items] == list(safety.CHECKS) and len(items) == 14
    assert {st for _, st, _ in items} == {"unknown"}


def test_checks_read_chain_data_and_second_opinions():
    report = {
        "contract": {"risky_functions": {"mint": ["mint(uint256)"]}, "renounced": False, "owner": "0x1",
                     "verified": None, "proxy_implementation": None},
        "liquidity": {"hooks": PONS_HOOK.upper().replace("0X", "0x"), "lp_burned_pct": 100.0},
        "holders": {"top10_pct": 62.0, "largest_pct": 9.0},
        "launch": {"dev_pct": 1.0, "dev_initial_pct": 4.0, "sniper_pct": 3.0, "bundle_pct": 0.0},
        "deployer": {"previous_launches": 0},
        "market": {"liquidity_usd": 25_000, "buys_h1": 40, "sells_h1": 10, "pair": "0xp"},
        "wash": {"transfers_5m": 12},
        "findings": [{"code": "wash_fomo_churn", "message": "Fomo churn %55"}],
        "pool": {"pool": "0xp"},
    }
    gp = {"is_open_source": "1", "hidden_owner": "1", "is_mintable": "1"}
    gt = {"gt_score": 30.0}
    got = {n: (st, text) for n, st, text in safety.checklist(report, 3, True, 900.0, gp, gt)}
    assert got["Fomo'da satış"] == ("ok", "3 farklı Fomo kullanıcısı satabildi")
    assert got["Kontrat fonksiyonları"][0] == "warn" and "GoPlus: mint" in got["Kontrat fonksiyonları"][1]
    assert got["Sahiplik"][0] == "warn" and "gizli sahip" in got["Sahiplik"][1]
    assert got["Kaynak kodu doğrulanmış"] == ("ok", "kaynak kodu doğrulanmış")  # from GoPlus
    assert got["Likidite"] == ("ok", "$25.0K (DexScreener)")
    assert got["LP kilidi"][0] == "ok" and got["V4 hook"][0] == "ok"
    assert got["Holder dağılımı"][0] == "warn"
    assert got["Geliştirici payı / satışı"][0] == "ok" and "sattı" in got["Geliştirici payı / satışı"][1]
    assert got["Geliştirici geçmişi"] == ("ok", "geliştiricinin ilk coini")
    assert got["Sahte hacim"] == ("warn", "Fomo churn %55")
    assert got["Piyasa bilgisi"][0] == "warn"  # GeckoTerminal score below 40
    assert [n for n, ok in safety.sources(report, gp, None)] == ["zincir", "GoPlus", "GeckoTerminal", "DexScreener"]


def test_pons_curve_coin_without_pool():
    got = {n: st for n, st, _ in safety.checklist({"contract": {}, "pool": None}, 0, True, 400.0, None, None)}
    assert got["LP kilidi"] == "ok" and got["V4 hook"] == "ok" and got["Likidite"] == "warn"  # ~$800 from Fomo buys


def test_report_has_one_trust_score():
    text = format_safety("TST", "0x" + "1" * 40, 91, safety.checklist({"contract": None}, 0, False, None, None, None),
                         [("zincir", True)])
    assert text.count("Güven puanı") == 1 and "91/100" in text and text.count("❔") == 14
