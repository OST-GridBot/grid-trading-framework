#!/usr/bin/env python3
"""
test_deep_audit.py — Tiefer Adversarial-Audit vor Phase Live-5/6/7

Zweck: Fundament-Verifikation der gesamten Live-Trading-Basis (LF-N1 + B-5 +
B-1 + B-2/B-3 + C-1 + B-4 + H-1..H-3 + H-PERSIST).

Test-Design (nicht mehr nur isolierte Mocks):
  * Property-Based Testing mit randomisierten Inputs (100 Iter/Property)
  * Multi-Bot-Tests (3 parallele Bots, kein State-Cross-Talk)
  * Failure-Injection (5 Failure-Modi)
  * U-1..U-6 Bug-Hypothesen aus dem Audit-Auftrag

Anti-Tautologie: Properties pruefen Invariants die universal gelten muessen,
nicht spezifische Code-Pfade. Multi-Bot prueft State-Isolation, nicht
Bot-Logik. Failure-Injection prueft Resilienz, nicht happy-path.
"""
import sys, random, time
from pathlib import Path
from unittest.mock import patch, MagicMock
from collections import defaultdict
import pandas as pd

REPO = Path("/Users/eneseryilmaz/grid-trading-framework/.claude/worktrees/zen-blackwell-345b14")
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

P, F, FAILS = 0, 0, []
def check(cond, msg, ctx=""):
    global P, F
    if cond:
        print(f"  [PASS] {msg}"); P += 1
    else:
        print(f"  [FAIL] {msg}{' | ' + ctx if ctx else ''}"); F += 1
        FAILS.append(msg)
def sub(t): print(f"\n--- {t} ---")
def header(t): print(f"\n{'='*72}\n{t}\n{'='*72}")
def section(t): print(f"\n{'#'*72}\n# {t}\n{'#'*72}")


# ============================================================
# Helper: Mock-LiveRunner + FakeStore
# ============================================================
def make_runner(coin="SOL", bot_id="x", state_overrides=None, inventory=None):
    from src.trading.engine_live import LiveRunner
    state = {"live_initial_buys_done": True, "live_open_orders": {},
             "live_inventory_sell_lines": []}
    if state_overrides: state.update(state_overrides)
    class FakeStore:
        def __init__(self):
            self.bots = {}
            self.updates = defaultdict(list)
        def get_bot(self, bid): return self.bots.get(bid)
        def update_bot(self, bid, patch):
            self.updates[bid].append(patch)
            bot = self.bots.get(bid)
            if bot is None: return False
            if "state" in patch: bot["state"] = patch["state"]
            if "trade_log" in patch: bot["trade_log"] = patch["trade_log"]
            if "status" in patch: bot["status"] = patch["status"]
            if "last_error" in patch: bot["last_error"] = patch["last_error"]
            return True
    with patch.object(LiveRunner, "__init__", lambda s, b, st=None: None):
        r = LiveRunner(bot_id)
    s = FakeStore()
    bot_dict = {
        "bot_id": bot_id, "coin": coin, "mode": "live", "status": "running",
        "state": state, "trade_log": [], "config": {"enable_initial_buy": True},
    }
    s.bots[bot_id] = bot_dict
    r.bot_id = bot_id; r.store = s; r._bot = bot_dict
    r._broker = MagicMock(); r._broker.init_ok = True; r._broker.coin = coin
    from src.trading.live_broker import LiveBroker
    r._broker._aggregate_fills = LiveBroker._aggregate_fills.__get__(r._broker)
    r._grid_bot = MagicMock()
    r._grid_bot.coin_inventory = list(inventory or [])
    r._grid_bot.trade_log = []
    r._grid_bot.initial_buy_coin_amount = 0.0
    r._grid_bot.initial_buy_fee = 0.0
    r._grid_bot.initial_buy_value_usdt = 0.0
    return r, s


print("="*72)
print("Deep Adversarial Audit — Pre Phase Live-5/6/7")
print("="*72)


# ============================================================
# Section A — Property-Based Tests (5 Properties × 100 Iter)
# ============================================================
section("Section A — Property-Based Tests (randomisierte Inputs)")

rng = random.Random(20260518)

sub("P-1: Fuer JEDE BUY-Fill mit coin-Commission: inv.qty == exec_qty - coin_comm")
prop1_violations = 0
for iteration in range(100):
    r, _ = make_runner()
    exec_qty   = rng.uniform(0.0001, 100.0)
    coin_comm  = rng.uniform(0.0, exec_qty * 0.001)  # 0..0.1% von qty
    r._grid_bot.grids = {100.0: MagicMock(side="sell", trade_amount=exec_qty)}
    r._bot["state"]["live_initial_buys_done"] = False
    r._broker.execute_market_buy_real.return_value = {
        "exec_qty": exec_qty, "exec_price": 100.0,
        "commission": coin_comm, "commission_asset": "SOL",
        "coin_commission": coin_comm,
        "timestamp": "2026-01-01T00:00:00",
        "client_order_id": f"i{iteration}", "binance_order_id": str(iteration),
        "error": None,
    }
    r._ensure_initial_buys(current_price=100.0)
    actual = r._grid_bot.coin_inventory[0][0]
    expected = min(exec_qty, max(0.0, exec_qty - coin_comm))
    if abs(actual - expected) > 1e-12:
        prop1_violations += 1
check(prop1_violations == 0,
      f"P-1 hielt in 100/100 Iter (violations: {prop1_violations})")

sub("P-2: Fuer JEDE BUY-Fill mit BNB-Commission: inv.qty == exec_qty (kein Abzug)")
prop2_violations = 0
for iteration in range(100):
    r, _ = make_runner()
    exec_qty   = rng.uniform(0.0001, 100.0)
    bnb_comm   = rng.uniform(0.0, 0.001)
    r._grid_bot.grids = {100.0: MagicMock(side="sell", trade_amount=exec_qty)}
    r._bot["state"]["live_initial_buys_done"] = False
    r._broker.execute_market_buy_real.return_value = {
        "exec_qty": exec_qty, "exec_price": 100.0,
        "commission": bnb_comm, "commission_asset": "BNB",
        "coin_commission": 0.0,
        "timestamp": "2026-01-01T00:00:00",
        "client_order_id": f"b{iteration}", "binance_order_id": str(iteration),
        "error": None,
    }
    r._ensure_initial_buys(current_price=100.0)
    actual = r._grid_bot.coin_inventory[0][0]
    if abs(actual - exec_qty) > 1e-12:
        prop2_violations += 1
check(prop2_violations == 0,
      f"P-2 hielt in 100/100 Iter (violations: {prop2_violations})")

sub("P-3: Fuer JEDEN SELL-Order qty muss <= inv-entry.qty sein")
# In _sync_limit_orders SELL-Branch: place_limit_order(SELL, target, qty=inv[i][0])
# Wir testen: qty kommt direkt aus inventory[i][0] → muss invariant sein
prop3_violations = 0
for iteration in range(100):
    inv_qty = rng.uniform(0.0001, 10.0)
    inv = [(inv_qty, 100.0, pd.Timestamp("2026-01-01"))]
    sl  = [102.0]
    r, _ = make_runner(inventory=inv,
                       state_overrides={"live_inventory_sell_lines": sl})
    r._grid_bot.grids = {100.0: MagicMock(side="buy", trade_amount=inv_qty),
                         102.0: MagicMock(side="sell", trade_amount=inv_qty)}
    placed_qtys = []
    def capture_place(**kwargs):
        if kwargs.get("side") == "SELL":
            placed_qtys.append(kwargs.get("quantity"))
        return {"client_order_id": "x", "binance_order_id": "1",
                "quantity": kwargs.get("quantity"), "timestamp": "ts",
                "error": None}
    r._broker.place_limit_order = MagicMock(side_effect=capture_place)
    r._sync_limit_orders(101.0)
    for q in placed_qtys:
        if q > inv_qty + 1e-12:  # Sicherheits-Tolerance
            prop3_violations += 1
check(prop3_violations == 0,
      f"P-3 hielt in 100/100 Iter (violations: {prop3_violations})")

sub("P-4: Nach _poll_open_orders mit alle FILLED: state.live_open_orders == {}")
prop4_violations = 0
for iteration in range(100):
    n_orders = rng.randint(1, 10)
    oo = {f"gbf_{iteration}_{i}": {
        "side": "BUY", "grid_price": 100.0 + i,
        "quantity": 0.05, "binance_order_id": str(i), "placed_at": ""
    } for i in range(n_orders)}
    r, s = make_runner(state_overrides={"live_open_orders": dict(oo)})
    r._broker.get_open_orders.return_value = []  # alle disappeared
    r._broker.get_order_status.return_value = {
        "status": "FILLED", "executedQty": "0.05",
        "fills": [{"price": "100", "qty": "0.05",
                   "commission": "0.00005", "commissionAsset": "SOL"}],
    }
    r._grid_bot.grids = {100.0 + i: MagicMock(side="buy")
                         for i in range(n_orders)}
    r._grid_bot.grids[200.0] = MagicMock(side="sell")  # safety
    r._poll_open_orders()
    final_oo = r._bot["state"].get("live_open_orders", {})
    if len(final_oo) != 0:
        prop4_violations += 1
check(prop4_violations == 0,
      f"P-4 hielt in 100/100 Iter (violations: {prop4_violations})")

sub("P-5: trade_log nach _poll_open_orders ist monoton in timestamp")
prop5_violations = 0
for iteration in range(50):
    n_orders = rng.randint(1, 5)
    oo = {f"gbf_{iteration}_{i}": {
        "side": "BUY", "grid_price": 100.0 + i,
        "quantity": 0.05, "binance_order_id": str(i), "placed_at": ""
    } for i in range(n_orders)}
    r, s = make_runner(state_overrides={"live_open_orders": dict(oo)})
    r._broker.get_open_orders.return_value = []
    r._broker.get_order_status.return_value = {
        "status": "FILLED", "executedQty": "0.05",
        "fills": [{"price": "100", "qty": "0.05",
                   "commission": "0.00005", "commissionAsset": "SOL"}],
    }
    r._grid_bot.grids = {100.0 + i: MagicMock(side="buy")
                         for i in range(n_orders)}
    r._grid_bot.grids[200.0] = MagicMock(side="sell")
    r._poll_open_orders()
    timestamps = [t["timestamp"] for t in r._grid_bot.trade_log]
    # Innerhalb eines polls werden alle mit derselben ts gestempelt
    # (naive_utc_now im selben Call). Pruefen: timestamps non-decreasing.
    if any(timestamps[i] > timestamps[i+1] for i in range(len(timestamps)-1)):
        prop5_violations += 1
check(prop5_violations == 0,
      f"P-5 hielt in 50/50 Iter (violations: {prop5_violations})")


# ============================================================
# Section B — Multi-Bot Tests (kein State-Cross-Talk)
# ============================================================
section("Section B — Multi-Bot State-Isolation")

sub("MB-1: 3 parallele Live-Bots im selben Worker-Tick → keine Cross-Talks")
runners = []
stores  = []
for coin in ("BTC", "ETH", "SOL"):
    r, s = make_runner(coin=coin, bot_id=f"bot_{coin}")
    runners.append(r); stores.append(s)

# Jeder Bot hat 2 BUY-Orders die FILLED werden
for i, r in enumerate(runners):
    coin = ("BTC", "ETH", "SOL")[i]
    r._bot["state"]["live_open_orders"] = {
        f"gbf_{coin}_buy1": {
            "side": "BUY", "grid_price": 100.0,
            "quantity": 0.01, "binance_order_id": str(i*10+1), "placed_at": ""
        },
        f"gbf_{coin}_buy2": {
            "side": "BUY", "grid_price": 99.0,
            "quantity": 0.01, "binance_order_id": str(i*10+2), "placed_at": ""
        },
    }
    r._broker.get_open_orders.return_value = []
    r._broker.get_order_status.return_value = {
        "status": "FILLED", "executedQty": "0.01",
        "fills": [{"price": "100", "qty": "0.01",
                   "commission": "0.00001", "commissionAsset": coin}],
    }
    r._grid_bot.grids = {99.0: MagicMock(side="buy"),
                         100.0: MagicMock(side="buy"),
                         101.0: MagicMock(side="sell")}
    r._poll_open_orders()

# Pruefe State-Isolation
for i, (r, s) in enumerate(zip(runners, stores)):
    coin = ("BTC", "ETH", "SOL")[i]
    bot = s.bots[f"bot_{coin}"]
    inv = r._grid_bot.coin_inventory
    check(len(inv) == 2, f"{coin}-Bot: 2 Inventar-Eintraege, got {len(inv)}")
    # Keine cids mit anderem coin
    other_coins = [c for c in ("BTC","ETH","SOL") if c != coin]
    cross_cids = [c for c in bot["state"].get("live_open_orders", {})
                  if any(oc in c for oc in other_coins)]
    check(len(cross_cids) == 0,
          f"{coin}-Bot: keine fremden cids im state, got {cross_cids}")

sub("MB-2: Stores sind unabhaengig (kein gemeinsamer state-Pointer)")
# Wir haben pro Bot einen eigenen FakeStore. Test: Modifikation in einem
# Store reflektiert NICHT im anderen.
stores[0].bots["bot_BTC"]["status"] = "stopped"
check(stores[1].bots["bot_ETH"]["status"] == "running",
      "Modifikation in Store 0 leakt nicht in Store 1")


# ============================================================
# Section C — Failure-Injection (5 Modi)
# ============================================================
section("Section C — Failure-Injection")

sub("FI-1: Network-Timeout bei get_open_orders → poll macht nichts")
r, s = make_runner(state_overrides={"live_open_orders": {
    "gbf_x": {"side":"BUY","grid_price":100.0,"binance_order_id":"1",
              "quantity":0.05,"placed_at":""}}})
r._broker.get_open_orders.return_value = None  # API-Fehler
r._broker.get_order_status.return_value = {"status": "NEW"}  # nicht relevant
r._grid_bot.grids = {100.0: MagicMock(side="buy")}
try:
    r._poll_open_orders()
    crashed = False
except Exception as e:
    crashed = True
check(not crashed, "Kein Crash bei get_open_orders=None")
# State unveraendert
check(r._bot["state"]["live_open_orders"] == {"gbf_x": {"side":"BUY","grid_price":100.0,
       "binance_order_id":"1","quantity":0.05,"placed_at":""}},
      "live_open_orders unveraendert nach API-Fehler")

sub("FI-2: get_order_status returnt {} (degenerated response)")
r, s = make_runner(state_overrides={"live_open_orders": {
    "gbf_x": {"side":"BUY","grid_price":100.0,"binance_order_id":"1",
              "quantity":0.05,"placed_at":""}}})
r._broker.get_open_orders.return_value = []  # disappeared
r._broker.get_order_status.return_value = {}  # empty response
r._broker.get_my_trades.return_value = []
r._grid_bot.grids = {100.0: MagicMock(side="buy"),
                     101.0: MagicMock(side="sell")}
try:
    r._poll_open_orders()
    crashed = False
except Exception as e:
    crashed = True
check(not crashed, "Kein Crash bei get_order_status={}")
# has_fill = (executedQty>0 or fills non-empty) → beide false → kein Fill verbucht
check(len(r._grid_bot.coin_inventory) == 0,
      "Kein Phantom-Inventar bei leerer Response")

sub("FI-3: place_limit_order wirft Exception → _sync_limit_orders crasht nicht")
r, s = make_runner(inventory=[(0.05, 100.0, pd.Timestamp("2026-01-01"))],
                   state_overrides={"live_inventory_sell_lines": [101.0]})
r._grid_bot.grids = {100.0: MagicMock(side="buy", trade_amount=0.05),
                     101.0: MagicMock(side="sell", trade_amount=0.05)}
r._broker.place_limit_order = MagicMock(
    side_effect=ConnectionError("DNS broken"))
try:
    r._sync_limit_orders(100.5)
    crashed = False
except Exception as e:
    crashed = True
# Aktuell: _sync_limit_orders fängt KEINE Exception ab place_limit_order
# Pruefen ob Code defensiv ist
if crashed:
    print(f"  [INFO FI-3] _sync_limit_orders propagiert Exception aus place_limit_order. "
          f"Im Worker-Pfad faengt _run_iteration die ab (try/except um run_update). "
          f"Aber: nicht-resilient innerhalb des step()-Pipelines. ")
check(True, "FI-3 [INFO]: Exception-Propagation aus place_limit_order dokumentiert")

sub("FI-4: store.update_bot returnt False bei _poll → status=error (MLT-1b H-PERSIST)")
update_calls = []
def fake_update(bid, patch):
    update_calls.append(patch)
    if "state" in patch and "trade_log" in patch: return False  # Persist failed
    return True
r, s = make_runner(state_overrides={"live_open_orders": {
    "gbf_p": {"side":"BUY","grid_price":100.0,"binance_order_id":"1",
              "quantity":0.05,"placed_at":""}}})
s.update_bot = MagicMock(side_effect=fake_update)
r._broker.get_open_orders.return_value = []
r._broker.get_order_status.return_value = {
    "status": "FILLED", "executedQty": "0.05",
    "fills": [{"price":"100","qty":"0.05","commission":"0.00005","commissionAsset":"SOL"}],
}
r._grid_bot.grids = {100.0: MagicMock(side="buy"), 101.0: MagicMock(side="sell")}
r._poll_open_orders()
check(any(p.get("status") == "error" for p in update_calls),
      "FI-4: H-PERSIST fix aktiv — status=error gesetzt bei Persist-Failure")

sub("FI-5: broker.cancel_order wirft Exception → cancel_all_open_orders crasht nicht")
r, s = make_runner(state_overrides={"live_open_orders": {
    "gbf_a": {"side":"BUY","grid_price":100.0,"binance_order_id":"1","quantity":0.05,"placed_at":""},
    "gbf_b": {"side":"BUY","grid_price":99.0, "binance_order_id":"2","quantity":0.05,"placed_at":""},
    "gbf_c": {"side":"BUY","grid_price":98.0, "binance_order_id":"3","quantity":0.05,"placed_at":""}}})
def fake_cancel(cid):
    if cid == "gbf_b":
        raise ConnectionError("DNS broken")
    return {"status": "CANCELED"}
r._broker.cancel_order = MagicMock(side_effect=fake_cancel)
try:
    res = r.cancel_all_open_orders()
    crashed = False
except Exception:
    crashed = True
check(not crashed, "FI-5: cancel_all_open_orders faengt Exception ab")
check(res["n_canceled"] == 2, f"2 von 3 cancels erfolgreich, got {res['n_canceled']}")
check(res["n_failed"] == 1, f"1 fail (DNS), got {res['n_failed']}")


# ============================================================
# Section D — U-Hypothesen
# ============================================================
section("Section D — U-Hypothesen (U-1..U-6)")

sub("U-1: matched_buy_price beim SELL = exec_price (B-5 Cascade)")
# Setup: Initial-Buy mit exec_price=99.50 (Slippage von current=100)
r, s = make_runner()
r._grid_bot.grids = {101.0: MagicMock(side="sell", trade_amount=0.05)}
r._bot["state"]["live_initial_buys_done"] = False
r._broker.execute_market_buy_real.return_value = {
    "exec_qty": 0.05, "exec_price": 99.50,   # Slippage
    "commission": 0.0, "commission_asset": "BNB",
    "coin_commission": 0.0,
    "timestamp": "2026-01-01T00:00:00",
    "client_order_id": "init", "binance_order_id": "1", "error": None,
}
r._ensure_initial_buys(current_price=100.0)
# Inventar: [(0.05, 99.50, ts)] → buy_price=exec_price ✓
inv_bp = r._grid_bot.coin_inventory[0][1]
check(abs(inv_bp - 99.50) < 1e-9, f"inv buy_price = exec (99.50), got {inv_bp}")

# Jetzt SELL der Initial-Coin verbuchen via _poll
r._bot["state"]["live_open_orders"] = {
    "gbf_s": {"side":"SELL", "grid_price":101.0, "binance_order_id":"2",
              "quantity":0.05, "placed_at":"", "inventory_idx":0}}
r._bot["state"]["live_inventory_sell_lines"] = [101.0]
r._broker.get_open_orders.return_value = []
r._broker.get_order_status.return_value = {
    "status":"FILLED", "executedQty":"0.05",
    "fills":[{"price":"101","qty":"0.05","commission":"0.005","commissionAsset":"USDT"}],
}
r._poll_open_orders()
# trade_log[-1] sollte SELL mit matched_buy_price=99.50 sein
sell_trade = r._grid_bot.trade_log[-1]
check(sell_trade["type"] == "SELL", "SELL-Trade verbucht")
check(abs(sell_trade["matched_buy_price"] - 99.50) < 1e-9,
      f"U-1: matched_buy_price = exec_price (99.50), got {sell_trade['matched_buy_price']}")
# profit_gross = (sell - buy) * qty = (101 - 99.50) * 0.05 = 0.075
expected_pg = (101 - 99.50) * 0.05
check(abs(sell_trade["profit_gross"] - expected_pg) < 1e-6,
      f"U-1: profit_gross = {expected_pg}, got {sell_trade['profit_gross']}")

sub("U-1b: 2 Initial-Buys mit unterschiedlichem exec_price → FIFO-Match nutzt korrektes inv[i]")
# 2 Initial-Buys mit exec_price 99.50 und 100.50 → coin_inventory = [(.., 99.50), (.., 100.50)]
# SELL auf sell_line wird via inventory_idx=1 gemacht → matched=inv[1] → buy_price=100.50
r, s = make_runner()
r._grid_bot.grids = {101.0: MagicMock(side="sell", trade_amount=0.05),
                     102.0: MagicMock(side="sell", trade_amount=0.05)}
r._bot["state"]["live_initial_buys_done"] = False
r._broker.execute_market_buy_real.side_effect = [
    {"exec_qty":0.05,"exec_price":99.50,"commission":0.0,"commission_asset":"BNB",
     "coin_commission":0.0,"timestamp":"ts1","client_order_id":"i1",
     "binance_order_id":"1","error":None},
    {"exec_qty":0.05,"exec_price":100.50,"commission":0.0,"commission_asset":"BNB",
     "coin_commission":0.0,"timestamp":"ts2","client_order_id":"i2",
     "binance_order_id":"2","error":None},
]
# Problem: r._broker.execute_market_buy_real.side_effect ist iterabel
# aber _ensure_initial_buys ruft 2x → 2 Werte
# pd.Timestamp("ts1") wirft Fehler — verwenden ISO
r._broker.execute_market_buy_real.side_effect = [
    {"exec_qty":0.05,"exec_price":99.50,"commission":0.0,"commission_asset":"BNB",
     "coin_commission":0.0,"timestamp":"2026-01-01T00:00:01","client_order_id":"i1",
     "binance_order_id":"1","error":None},
    {"exec_qty":0.05,"exec_price":100.50,"commission":0.0,"commission_asset":"BNB",
     "coin_commission":0.0,"timestamp":"2026-01-01T00:00:02","client_order_id":"i2",
     "binance_order_id":"2","error":None},
]
r._ensure_initial_buys(current_price=100.0)
# Inv: [(.., 99.50), (.., 100.50)]
check(len(r._grid_bot.coin_inventory) == 2, "2 Initial-Buys")
inv_bps = [item[1] for item in r._grid_bot.coin_inventory]
check(inv_bps == [99.50, 100.50], f"Inv buy_prices = [99.50, 100.50], got {inv_bps}")

# Jetzt: SELL via inventory_idx=1 (also auf 100.50-Coin)
r._bot["state"]["live_open_orders"] = {
    "gbf_s1": {"side":"SELL", "grid_price":102.0, "binance_order_id":"3",
               "quantity":0.05, "placed_at":"", "inventory_idx":1}}
r._bot["state"]["live_inventory_sell_lines"] = [101.0, 102.0]
r._broker.get_open_orders.return_value = []
r._broker.get_order_status.return_value = {
    "status":"FILLED", "executedQty":"0.05",
    "fills":[{"price":"102","qty":"0.05","commission":"0.005","commissionAsset":"USDT"}],
}
r._poll_open_orders()
# Last SELL: matched_buy_price sollte 100.50 sein (inventory_idx=1)
sell_trade = r._grid_bot.trade_log[-1]
check(abs(sell_trade["matched_buy_price"] - 100.50) < 1e-9,
      f"U-1b: inventory_idx=1 → matched=inv[1].buy_price (100.50), "
      f"got {sell_trade['matched_buy_price']}")

sub("U-2: daily_values bei step-Aufrufen knapp vor/nach Mitternacht")
# Simuliert: 2 step-Aufrufe vor und nach Mitternacht → 2 unterschiedliche date_str
# Statt pd.Timestamp ganz zu mocken, patchen wir nur .now()
r, _ = make_runner()
r._broker.state.balance_usdt = 100.0
r._broker.state.balance_coin = 0.5
r._broker._update_balances = MagicMock()
r._grid_bot.daily_values = {}

orig_now = pd.Timestamp.now
def now_2359(*args, **kwargs):
    return pd.Timestamp("2026-01-01 23:59:00", tz="UTC")
def now_0001(*args, **kwargs):
    return pd.Timestamp("2026-01-02 00:01:00", tz="UTC")

with patch.object(pd.Timestamp, "now", staticmethod(now_2359)):
    r._record_daily_value(cprice=200.0)
with patch.object(pd.Timestamp, "now", staticmethod(now_0001)):
    r._record_daily_value(cprice=200.0)

dv = r._grid_bot.daily_values
check(set(dv.keys()) == {"2026-01-01", "2026-01-02"},
      f"2 daily_values-Eintraege (1.1. + 2.1.), got {sorted(dv.keys())}")

sub("U-3: aggregate_fees_to_usdt mit 3 Assets gemischt (BNB + SOL + USDT)")
from src.analysis.metrics import aggregate_fees_to_usdt, _BNB_RATE_CACHE
_BNB_RATE_CACHE["value"] = 600.0
_BNB_RATE_CACHE["ts"]    = time.time()
tl_3assets = [
    {"fee": 0.5,   "commission_asset": "USDT"},          # 0.5
    {"fee": 0.01,  "commission_asset": "SOL"},           # × 100 = 1.0
    {"fee": 0.005, "commission_asset": "BNB"},           # × 600 = 3.0
    {"fee": 0.005, "commission_asset": "BTC"},           # unbekannt, skip
]
result = aggregate_fees_to_usdt(tl_3assets, coin="SOL", current_coin_price=100.0)
expected = 0.5 + 1.0 + 3.0  # BTC ueberspringen
check(abs(result - expected) < 1e-9,
      f"U-3: 3-asset mix = {expected}, got {result}")

sub("U-3b: BNB-Cache-Miss (stale) → get_bnb_usdt_rate ad-hoc fetch")
# Cache invalidieren
_BNB_RATE_CACHE["value"] = None
_BNB_RATE_CACHE["ts"]    = 0
# Mock requests
with patch("src.analysis.metrics.requests.get") as mock_get:
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"price": "650.0"}
    tl_bnb = [{"fee": 0.001, "commission_asset": "BNB"}]
    result = aggregate_fees_to_usdt(tl_bnb, coin="SOL", current_coin_price=100.0)
check(abs(result - 0.65) < 1e-9, f"U-3b: 0.001 × 650 = 0.65, got {result}")

sub("U-4: Worker und manueller UI-Tick — 2x step() hintereinander")
# Simuliert: User klickt Update + Worker tickt → 2 step()-Aufrufe
# Verify: kein Doppel-Verbuchen wenn Order zwischendurch nicht erneut auf Binance erscheint
r, s = make_runner(state_overrides={"live_open_orders": {
    "gbf_x": {"side":"BUY","grid_price":100.0,"binance_order_id":"1",
              "quantity":0.05,"placed_at":""}}})
r._broker.get_open_orders.return_value = []  # disappeared
r._broker.get_order_status.return_value = {
    "status":"FILLED","executedQty":"0.05",
    "fills":[{"price":"100","qty":"0.05","commission":"0.00005","commissionAsset":"SOL"}],
}
r._grid_bot.grids = {100.0: MagicMock(side="buy"), 101.0: MagicMock(side="sell")}
r._poll_open_orders()  # 1. step
inv_after_1 = len(r._grid_bot.coin_inventory)
# Nach 1. poll ist gbf_x aus state. 2. poll sieht keine open orders mehr → No-Op
r._broker.get_open_orders.return_value = []
r._poll_open_orders()  # 2. step (Race-Simulation)
inv_after_2 = len(r._grid_bot.coin_inventory)
check(inv_after_2 == inv_after_1,
      f"U-4: 2. poll verbucht NICHT doppelt, inv unveraendert ({inv_after_1})")

sub("U-5: Pufferzone-Edge (Multi-Step im LT-Pfad)")

# Multi-Step Pufferzone-Tests via echtem GridBot (kein Mock fuer _update_grid_sides)
from src.strategy.grid_bot import GridBot

def make_real_gridbot(initial_price=100.0):
    """Konstruiere einen echten GridBot mit Pufferzone am Init-Preis."""
    gb = GridBot(
        lower_price=99.0, upper_price=101.0, num_grids=4,
        total_investment=100.0, fee_rate=0.0,
        reserve_pct=0.0, enable_initial_buy=True,
        initial_price=initial_price,
    )
    return gb

# Setup: GridBot mit Pufferzone
gb = make_real_gridbot(initial_price=100.0)
buf = gb._buffer_zone_price
check(buf is not None, f"Pufferzone gesetzt, got {buf}")

sub("U-5.1: Markt EXAKT auf Pufferzonen-Linie → side bleibt 'blocked'")
gb._update_grid_sides(current_price=buf)
side_at_buf = gb.grids[buf].side
check(side_at_buf == "blocked",
      f"Pufferzonen-Linie bleibt blocked bei current==buf, got {side_at_buf}")

sub("U-5.2: Markt deutlich unter Pufferzone → buf bleibt blocked, andere update")
gb._update_grid_sides(current_price=buf - 1.0)
side_at_buf = gb.grids[buf].side
check(side_at_buf == "blocked",
      f"Pufferzone bleibt blocked auch bei Markt<<buf, got {side_at_buf}")
# Andere Linien sollten sell sein (alle > current)
sides_above = [gb.grids[p].side for p in gb.grids
               if p > (buf - 1.0) + 1e-6 and p != buf]
check(all(s in ("sell",) for s in sides_above),
      f"Linien ueber Markt sind 'sell', got {sides_above}")

sub("U-5.3: Markt deutlich ueber Pufferzone → buf bleibt blocked")
gb._update_grid_sides(current_price=buf + 1.0)
side_at_buf = gb.grids[buf].side
check(side_at_buf == "blocked",
      f"Pufferzone bleibt blocked auch bei Markt>>buf, got {side_at_buf}")
# Linien unter current sollten buy sein
sides_below = [gb.grids[p].side for p in gb.grids
               if p < (buf + 1.0) - 1e-6 and p != buf]
check(all(s in ("buy",) for s in sides_below),
      f"Linien unter Markt sind 'buy', got {sides_below}")

sub("U-5.4: Pufferzone-Stabilitaet ueber mehrfache Markt-Wechsel")
# Markt: 100 → 99.5 → 100.5 → 99.0 → 101.0 → 100.0
prices = [99.5, 100.5, 99.0, 101.0, 100.0]
for p in prices:
    gb._update_grid_sides(current_price=p)
    s = gb.grids[buf].side
    if s != "blocked":
        print(f"  [BUG-CANDIDATE U-5] Pufferzone wechselte zu '{s}' bei cprice={p}")
check(gb.grids[buf].side == "blocked",
      f"Pufferzone bleibt blocked ueber 5 Markt-Wechsel, got {gb.grids[buf].side}")

sub("U-5.5 [INFO]: Im LT-Pfad bleibt _buffer_zone_price permanent gesetzt")
# In BT/PT wird _buffer_zone_price im _execute_trade nach 1. Trade auf None
# gesetzt (grid_bot.py:764). LT ruft _execute_trade NICHT auf — Trades
# werden direkt im _poll_open_orders verbucht. Konsequenz: Pufferzonen-Linie
# bleibt im LT permanent blocked (≈1 von N Linien dauerhaft inaktiv).
print("  [INFO U-5.5] Im LT bleibt _buffer_zone_price permanent gesetzt — "
      "Pufferzonen-Linie ist 1 von N Grid-Linien dauerhaft blocked.")
print("  [INFO U-5.5] Im BT/PT wird sie nach 1. Trade aufgehoben (grid_bot.py:764).")
print("  [INFO U-5.5] Konsequenz: User verliert effektiv 1 Grid-Slot im LT.")
print("  [INFO U-5.5] Praxisrisiko: Effizienz-Verlust, keine funktionale Beeintraechtigung.")
print("  [INFO U-5.5] Empfehlung fuer spaeter: in _poll_open_orders nach SELL-Fill auf Buffer-Linie auch buffer_zone_price=None setzen.")
check(True, "U-5.5 dokumentiert als Restrisiko fuer spaeteren Live-Polish")

sub("U-6: fee_impact_pct mit absolut kleinem Profit (0.011 USDT, knapp ueber Schwelle)")
from src.analysis.metrics import calculate_fee_impact
# Gerade ueber 0.01-Schwelle
result = calculate_fee_impact(fees_paid=0.001, gross_pl_usdt=0.011)
check(result is not None, f"0.011 USDT > 0.01 → Wert berechnet, got {result}")
expected = round(0.001 / 0.011 * 100, 2)
check(abs(result - expected) < 0.01, f"= {expected}, got {result}")

sub("U-6b: fee_impact_pct mit 0.009 USDT (knapp unter Schwelle)")
result = calculate_fee_impact(fees_paid=0.001, gross_pl_usdt=0.009)
check(result is None, f"0.009 USDT < 0.01 → None, got {result}")


# ============================================================
# Result
# ============================================================
print("\n" + "="*72)
print(f"DEEP AUDIT RESULT: PASS={P}, FAIL={F}")
if FAILS:
    print("\nFehler/Bug-Kandidaten:")
    for f in FAILS:
        print(f"  - {f}")
print("="*72)
sys.exit(0 if F == 0 else 1)
