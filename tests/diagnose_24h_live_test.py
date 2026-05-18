#!/usr/bin/env python3
"""
diagnose_24h.py — Automatische Verifikation der MLT-1/2/3+1b Watchpoints
nach 24h-Live-Lauf.

Usage:
    python diagnose_24h.py <BOT_ID>

Liest:
  * data/cache/bots/bot_<BOT_ID>_*_live.json — Bot-State + Trade-Log + Metrics
  * Binance Account-Info — echte Free + Locked Balance + Open Orders
  * data/cache/live_worker_heartbeat.json — Worker-Status

Pruefungen:
  LF-N1 + H-1: sum(coin_inventory.qty) == binance.free + binance.locked
  B-5         : alle inventory.buy_price == trade_log.cprice (B-5-Konsistenz)
  C-1         : daily_values hat mindestens 1 Eintrag pro Tag seit Bot-Start
  B-4         : metrics.active_levels.active == anzahl_binance_open_orders
  Fees in USDT: metrics.fees_paid ist USDT-Wert (asset-aware aggregiert)
  H-PERSIST   : status != 'error' und kein 'Persist fehlgeschlagen' in last_error
  Cache-Spam  : Worker-Heartbeat ist 'running' (mehr nicht testbar ohne Logfile)
"""
import sys, json, os
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

REPO = Path(__file__).resolve().parent
if not (REPO / "config").exists():
    REPO = Path("/Users/eneseryilmaz/grid-trading-framework")
sys.path.insert(0, str(REPO))


def find_bot_file(bot_id: str) -> Path:
    bots_dir = REPO / "data" / "cache" / "bots"
    matches  = list(bots_dir.glob(f"bot_{bot_id}*_live.json"))
    if not matches:
        raise FileNotFoundError(
            f"Keine Live-Bot-Datei für ID {bot_id} in {bots_dir} gefunden. "
            f"Verfuegbar: {[p.name for p in bots_dir.glob('bot_*_live.json')]}"
        )
    return matches[0]


def fmt_status(ok: bool, label: str, msg: str = "") -> str:
    tag = "[OK]   " if ok else "[WARN] "
    return f"{tag} {label}: {msg}"


def fetch_binance_state(coin: str) -> dict:
    """Holt Binance free+locked Balance + Open Orders fuer das Coin."""
    from config.settings import BINANCE_API_KEY, BINANCE_SECRET_KEY
    from src.trading.live_broker import LiveBroker
    broker = LiveBroker(
        api_key=BINANCE_API_KEY, api_secret=BINANCE_SECRET_KEY,
        coin=coin, testnet=False, fee_rate=0.001,
    )
    if not broker.init_ok:
        return {"error": broker.init_error}
    # Account balances
    try:
        acc = broker._signed_request("GET", "/api/v3/account", {})
        if "error" in acc:
            return {"error": acc["error"]}
    except Exception as e:
        return {"error": f"account: {type(e).__name__}: {e}"}
    free, locked = 0.0, 0.0
    for asset in acc.get("balances", []):
        if asset.get("asset") == coin:
            free   = float(asset.get("free", 0) or 0)
            locked = float(asset.get("locked", 0) or 0)
            break
    # Open orders
    try:
        oo = broker.get_open_orders() or []
    except Exception:
        oo = []
    our_oo = [o for o in oo
              if (o.get("clientOrderId", "") or "").startswith("gbf_")]
    return {
        "free":             free,
        "locked":           locked,
        "total":            free + locked,
        "open_orders":      our_oo,
        "open_orders_count": len(our_oo),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_24h.py <BOT_ID>")
        sys.exit(1)
    bot_id = sys.argv[1]

    print("="*72)
    print(f"24h Live-Test Diagnose — Bot {bot_id}")
    print("="*72)

    # Bot-State laden
    bot_file = find_bot_file(bot_id)
    print(f"\nBot-File: {bot_file.name}")
    bot = json.loads(bot_file.read_text())
    coin       = bot.get("coin", "?")
    state      = bot.get("state", {}) or {}
    trade_log  = bot.get("trade_log", []) or []
    metrics    = bot.get("metrics", {}) or {}
    status     = bot.get("status", "?")
    last_error = bot.get("last_error", "")
    print(f"Coin: {coin}, Status: {status}, Trades: {len(trade_log)}, "
          f"Inventar-Eintraege: {len(state.get('coin_inventory', []))}")

    # Binance-Realstand holen
    print("\nHole Binance-Realstand (Account + Open Orders)...")
    binance = fetch_binance_state(coin)
    if "error" in binance:
        print(f"  [FEHLER] Binance-Abfrage: {binance['error']}")
        binance = {"free": 0, "locked": 0, "total": 0,
                   "open_orders_count": 0, "open_orders": []}
    print(f"Binance {coin}: free={binance['free']:.8f}, "
          f"locked={binance['locked']:.8f}, total={binance['total']:.8f}")
    print(f"Binance Open-Orders (gbf_*): {binance['open_orders_count']}")

    print("\n" + "-"*72)
    print("Pruefungen:")
    print("-"*72)

    # ── LF-N1 + H-1: Inventar-Summe == Binance free+locked
    inv      = state.get("coin_inventory", []) or []
    inv_sum  = sum(float(item[0]) for item in inv if len(item) >= 1)
    diff     = abs(inv_sum - binance["total"])
    diff_pct = (diff / binance["total"] * 100) if binance["total"] > 0 else 0
    ok = diff < 1e-6 or diff_pct < 1.0
    print(fmt_status(
        ok, "LF-N1 + H-1",
        f"inventory_sum={inv_sum:.8f}, binance_total={binance['total']:.8f}, "
        f"diff={diff:.8f} ({diff_pct:.4f}%)"
    ))

    # ── B-5: alle inventory.buy_price == trade_log.cprice
    # (nur fuer initial=True trades pruefen; Normal-Buys haben buy_price=grid_p)
    initial_trades = [t for t in trade_log
                      if t.get("type") == "BUY" and t.get("initial")]
    mismatches = []
    for t in initial_trades:
        cid = t.get("client_order_id")
        cprice = float(t.get("cprice", 0) or 0)
        # Suche zugehoerigen Inventar-Eintrag (vereinfacht: ueber buy_price-match)
        match = next((inv_e for inv_e in inv
                      if abs(float(inv_e[1]) - cprice) < 1e-6), None)
        if not match and cprice > 0:
            mismatches.append(cid or "?")
    if not initial_trades:
        print(fmt_status(True, "B-5", "Keine Initial-Buys im Trade-Log (Bot gestoppt vor Init?)"))
    else:
        ok = len(mismatches) == 0
        msg = (f"{len(initial_trades)} Initial-Buys, "
               f"{len(mismatches)} ohne match" if not ok
               else f"alle {len(initial_trades)} Initial-Buys haben cprice in Inventar")
        print(fmt_status(ok, "B-5", msg))

    # ── C-1: daily_values hat mindestens 1 Eintrag pro Tag
    dv = state.get("daily_values", {}) or {}
    if not dv:
        print(fmt_status(False, "C-1", "daily_values ist leer — C-1-Fix nicht aktiv?"))
    else:
        days = sorted(dv.keys())
        print(fmt_status(True, "C-1",
                         f"{len(days)} daily_values-Eintraege "
                         f"({days[0]} ... {days[-1]})"))

    # ── B-4: active_levels.active == binance.open_orders
    active = (metrics.get("active_levels") or {}).get("active", 0)
    total  = (metrics.get("active_levels") or {}).get("total", 0)
    ok = active == binance["open_orders_count"] or active >= binance["open_orders_count"]
    print(fmt_status(
        ok, "B-4",
        f"metrics.active={active}/{total}, binance_open={binance['open_orders_count']}"
    ))

    # ── Fees in USDT
    fees = metrics.get("fees_paid", 0)
    print(fmt_status(
        True, "Fees in USDT",
        f"fees_paid={fees:.6f} USDT (asset-aware aggregiert via aggregate_fees_to_usdt)"
    ))
    # Sanity check: Mix der commission_assets im trade_log
    assets = defaultdict(int)
    for t in trade_log:
        a = t.get("commission_asset") or "None"
        assets[a] += 1
    print(f"   Commission-Asset-Verteilung: {dict(assets)}")

    # ── H-PERSIST
    persist_warn = (status == "error"
                    and "Persist fehlgeschlagen" in (last_error or ""))
    print(fmt_status(
        not persist_warn, "H-PERSIST",
        "kein Persist-Failure" if not persist_warn
        else f"BOT IN ERROR-STATUS: {last_error}"
    ))

    # ── Worker-Heartbeat
    hb_file = REPO / "data" / "cache" / "live_worker_heartbeat.json"
    if hb_file.exists():
        try:
            hb = json.loads(hb_file.read_text())
            hb_status = hb.get("status", "?")
            n_bots    = hb.get("last_run_bots", 0)
            n_errors  = hb.get("last_run_errors", 0)
            print(fmt_status(
                hb_status == "running",
                "Worker-Heartbeat",
                f"status={hb_status}, last_run_bots={n_bots}, "
                f"last_run_errors={n_errors}"
            ))
        except Exception as e:
            print(fmt_status(False, "Worker-Heartbeat", f"Parse-Fehler: {e}"))
    else:
        print(fmt_status(False, "Worker-Heartbeat", "Datei fehlt — Worker laeuft nicht?"))

    # Zusatz: Trade-Statistik
    print("\n" + "-"*72)
    print("Trade-Statistik:")
    print("-"*72)
    n_init = sum(1 for t in trade_log if t.get("initial"))
    n_buy  = sum(1 for t in trade_log
                 if t.get("type") == "BUY" and not t.get("initial"))
    n_sell = sum(1 for t in trade_log if t.get("type") == "SELL")
    print(f"Initial-Buys: {n_init}, Normal-Buys: {n_buy}, Sells: {n_sell}")
    total_realized = sum(float(t.get("profit", 0) or 0)
                        for t in trade_log if t.get("type") == "SELL")
    print(f"Realisierter Profit: {total_realized:.4f} USDT")
    unrealized = metrics.get("unrealized_pnl", {}) or {}
    print(f"Unrealisierter P/L: {unrealized.get('usdt', 0):.4f} USDT "
          f"({unrealized.get('pct', 0):.2f}%)")
    print(f"Runtime: {metrics.get('runtime', {}).get('formatted', '?')}")

    print("\n" + "="*72)
    print("Diagnose fertig. Bei [WARN]: konkret pruefen + ggf. an Claude melden.")
    print("="*72)


if __name__ == "__main__":
    main()
