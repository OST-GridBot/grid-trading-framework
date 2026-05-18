#!/usr/bin/env python3
"""
live_worker.py — Hintergrund-Service für Live-Trading-Bots.

Start:  python live_worker.py
Stop:   Ctrl+C  (sauberer Shutdown — KEINE Order-Cancels, Bot ruht nur)

Funktional (Phase Live-3):
    - Periodisches run_update() fuer alle aktiven Live-Bots
      (mode="live", status="running")
    - Intervall aus config.settings.WORKER_INTERVAL_SECONDS (Default 30s)
    - Robust gegen Netzwerk-Errors, Exceptions, Rate-Limits
    - State-Dateien in data/cache/:
        * live_worker.pid              Single-Instance-Check
        * live_worker_heartbeat.json   Status fuer Streamlit-Anzeige
    - Plattformunabhaengig (macOS / Windows / Linux): pathlib.Path,
      signal.SIGINT (Ctrl+C). SIGTERM POSIX-only via hasattr-Check.

Nahtlose Wiederaufnahme: BotStore-State plus clientOrderId-Match in
LiveRunner._poll_open_orders erkennen offene LIMIT-Orders bei Binance
beim naechsten Worker-Start korrekt wieder.

Autor: Enes Eryilmaz
Projekt: Grid-Trading-Framework (Bachelorarbeit OST)
"""
import os
import sys
import time
import json
import signal
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

# Repo-Pfad in sys.path damit src.* importiert werden kann, wenn das
# Script direkt via "python live_worker.py" gestartet wird.
REPO = Path(__file__).resolve().parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from config.settings import CACHE_DIR, WORKER_INTERVAL_SECONDS
from src.trading.bot_store import store
from src.trading.engine import make_bot_runner

# MLT-3: Cache-Print-Spam reduzieren — sonst bei jedem Worker-Tick
# (alle 30s) zweimal "Cache (aktuell): ..." pro Live-Bot.
from src.data import cache_manager
cache_manager.set_quiet(True)


HEARTBEAT_PATH = Path(CACHE_DIR) / "live_worker_heartbeat.json"
PID_PATH       = Path(CACHE_DIR) / "live_worker.pid"

# Modul-globales Stop-Flag (vom Signal-Handler gesetzt). Tests koennen es
# ebenfalls toggeln um eine Test-Iteration vorzeitig zu beenden.
_running = True


# ---------------------------------------------------------------------------
# Signal-Handler
# ---------------------------------------------------------------------------

def _handle_shutdown(signum, frame):
    """
    Sauberer Shutdown: setzt _running=False, damit die Hauptschleife im
    naechsten Check beendet. KEINE Order-Cancels — offene LIMIT-Orders
    bleiben bei Binance bestehen, der Bot ruht nur.
    """
    global _running
    sig_name = "SIGINT" if signum == signal.SIGINT else f"signal {signum}"
    print(f"\n[Worker] {sig_name} empfangen — beende sauber...")
    _running = False


# ---------------------------------------------------------------------------
# Heartbeat & PID-Lock
# ---------------------------------------------------------------------------

def _write_heartbeat(**kwargs) -> None:
    """
    Schreibt aktuellen Worker-Status in HEARTBEAT_PATH. Wird von der
    Streamlit-UI gelesen (page_live_trading._show_worker_status).

    Atomic via Temp-File + os.replace (LF-1-Fix): write_text truncates+writes,
    weshalb ein gleichzeitiger Reader die Datei im Truncate-Window leer sieht.
    Mit os.replace wird der Wechsel atomar (POSIX + Windows auf gleichem FS).
    """
    data = {
        "pid":        os.getpid(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    data.update(kwargs)
    try:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = HEARTBEAT_PATH.with_suffix(HEARTBEAT_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, HEARTBEAT_PATH)
    except Exception as e:
        # Heartbeat-Schreibfehler darf den Worker nicht stoppen.
        print(f"[Worker] Heartbeat-Schreibfehler: {e}")


def _check_pid_lock() -> bool:
    """
    Single-Instance-Check (best-effort, POSIX-orientiert):
    - Existiert kein PID-File: PID schreiben, return True.
    - Existiert ein PID-File mit lebendem Prozess: return False.
    - Existiert ein PID-File mit toter PID (stale): ueberschreiben, return True.

    LF-2-Fix: os.kill(pid, 0) unterscheidet zwischen ProcessLookupError
    (ESRCH: PID existiert nicht → stale) und PermissionError (EPERM: PID
    existiert, gehoert anderem User → konservativ blockieren). Vorher wurde
    EPERM faelschlich als stale interpretiert (PermissionError ist Subklasse
    von OSError) — kritisch bei PID-Recycling auf privilegierte Prozesse.

    Auf Windows hat os.kill(pid, 0) eine etwas andere Semantik, aber der
    Best-Effort-Check funktioniert in der Praxis. Bei Race-Conditions
    (zwei Worker gleichzeitig starten) ist das Verhalten undefiniert —
    fuer Single-User-App akzeptabel (siehe LF-3 in Commit-Body).
    """
    if PID_PATH.exists():
        try:
            old_pid = int(PID_PATH.read_text().strip())
        except Exception:
            old_pid = None
        if old_pid is not None and old_pid != os.getpid():
            # Pruefen ob Prozess lebt
            try:
                os.kill(old_pid, 0)
                # Lebt — Lock verweigern
                print(f"[Worker] Es laeuft bereits ein Worker (PID {old_pid}).")
                print(f"[Worker] Falls dieser nicht mehr aktiv ist, manuell "
                      f"loeschen: {PID_PATH}")
                return False
            except ProcessLookupError:
                # ESRCH: PID existiert nicht -> stale PID
                print(f"[Worker] Stale PID-File ({old_pid}) wird "
                      f"ueberschrieben.")
            except PermissionError:
                # EPERM: PID existiert, gehoert anderem User
                # Konservativ blockieren — kein Doppel-Worker riskieren.
                print(f"[Worker] PID {old_pid} existiert (anderer Owner). "
                      f"Falls dies kein Worker ist, manuell loeschen: "
                      f"{PID_PATH}")
                return False
            except OSError as e:
                # Andere errno-Werte: defensive als stale behandeln
                print(f"[Worker] PID-Check unklar (errno={e.errno}), "
                      f"behandle als stale.")
    try:
        PID_PATH.parent.mkdir(parents=True, exist_ok=True)
        PID_PATH.write_text(str(os.getpid()))
    except Exception as e:
        print(f"[Worker] Konnte PID-File nicht schreiben: {e}")
        return False
    return True


def _cleanup() -> None:
    """
    Wird beim Shutdown aufgerufen: schreibt 'stopped'-Heartbeat,
    loescht PID-File. KEINE Order-Cancels (gemaess Briefing).

    Bewahrt die letzten Lauf-Infos (last_run_bots, last_run_errors,
    last_run_at, ...) aus dem vorherigen Heartbeat — damit die UI nach
    Stopp noch zeigen kann: "letzter Lauf hatte N Bots, M Errors".
    """
    prev = {}
    try:
        if HEARTBEAT_PATH.exists():
            prev = json.loads(HEARTBEAT_PATH.read_text())
    except Exception:
        prev = {}
    # Felder die in den stopped-Heartbeat uebernommen werden duerfen
    preserved = {
        k: prev[k] for k in (
            "started_at", "last_run_at", "last_run_finished_at",
            "last_run_bots", "last_run_errors", "interval_seconds",
        ) if k in prev
    }
    _write_heartbeat(
        status="stopped",
        stopped_at=datetime.now(timezone.utc).isoformat(),
        **preserved,
    )
    try:
        PID_PATH.unlink()
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[Worker] PID-File konnte nicht geloescht werden: {e}")


# ---------------------------------------------------------------------------
# Hauptschleife
# ---------------------------------------------------------------------------

def _run_iteration() -> tuple:
    """
    Eine Worker-Iteration: alle laufenden Live-Bots durchgehen.
    Returns (n_bots, n_errors) fuer Heartbeat.

    Drei try/except-Ebenen:
        1. BotStore-Read (defensiv falls Datei korrupt)
        2. make_bot_runner (defensiv falls Bot inzwischen geloescht)
        3. run_update (defensiv gegen API-Errors, GridBot-Crashes)
    """
    try:
        live_bots = [
            b for b in store.get_all_bots(mode="live")
            if b.get("status") == "running"
        ]
    except Exception as e:
        print(f"[Worker] BotStore-Read-Fehler: {e}")
        return (0, 1)

    n_bots = len(live_bots)
    n_errors = 0

    for bot in live_bots:
        bot_id = bot.get("bot_id", "?")
        try:
            runner = make_bot_runner(bot_id)
        except Exception as e:
            print(f"[Worker] Bot {bot_id}: Runner-Setup-Fehler: "
                  f"{type(e).__name__}: {e}")
            n_errors += 1
            continue
        try:
            result = runner.run_update()
        except Exception as e:
            print(f"[Worker] Bot {bot_id}: run_update-Exception: "
                  f"{type(e).__name__}: {e}")
            n_errors += 1
            continue

        if isinstance(result, dict):
            err = result.get("error")
            if err:
                print(f"[Worker] Bot {bot_id}: {err}")
                n_errors += 1
            else:
                new_trades = result.get("new_trades") or []
                if new_trades:
                    print(f"[Worker] Bot {bot_id}: {len(new_trades)} "
                          f"neue Trade(s)")

    return (n_bots, n_errors)


def _interruptible_sleep(total_seconds: int) -> None:
    """
    Schlaeft in 1-Sekunden-Schritten und prueft _running nach jedem
    Schritt. Damit reagiert Ctrl+C innerhalb von max 1s, nicht erst
    nach voller Intervall-Dauer.
    """
    for _ in range(int(total_seconds)):
        if not _running:
            return
        time.sleep(1)


def main(max_iterations: Optional[int] = None) -> int:
    """
    Worker-Hauptfunktion.

    Args:
        max_iterations: Optional. None = laeuft ewig (bis Ctrl+C).
                        Ganzzahl = beendet nach so vielen Iterationen
                        (fuer Tests).

    Returns:
        Exit-Code (0 = OK, 1 = bereits laufender Worker, 2 = Fatal-Error).
    """
    global _running
    _running = True  # Reset (Tests koennen es ggf. vorher gesetzt haben)

    # Signal-Handler installieren
    try:
        signal.signal(signal.SIGINT, _handle_shutdown)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _handle_shutdown)
    except (ValueError, OSError) as e:
        # In manchen Test-Setups (z.B. Background-Thread) kann signal-
        # Setup fehlschlagen. Worker laeuft trotzdem.
        print(f"[Worker] Signal-Handler-Setup nicht moeglich: {e}")

    # Single-Instance-Check
    if not _check_pid_lock():
        return 1

    # LF-4-Fix: min. 1s — schuetzt vor Konfig-Unfall (float < 1 oder 0)
    interval = max(1, int(WORKER_INTERVAL_SECONDS))
    started_at = datetime.now(timezone.utc).isoformat()

    print(f"[Worker] Live-Trading-Worker gestartet (PID {os.getpid()})")
    print(f"[Worker] Intervall: {interval}s. Ctrl+C zum Beenden.")
    _write_heartbeat(
        status="running",
        started_at=started_at,
        interval_seconds=interval,
        last_run_bots=0,
        last_run_errors=0,
    )

    iteration = 0
    try:
        while _running:
            ts_start = datetime.now(timezone.utc)
            n_bots, n_errors = _run_iteration()
            ts_end = datetime.now(timezone.utc)
            next_run = ts_end + timedelta(seconds=interval)

            _write_heartbeat(
                status="running",
                started_at=started_at,
                last_run_at=ts_start.isoformat(),
                last_run_finished_at=ts_end.isoformat(),
                last_run_bots=n_bots,
                last_run_errors=n_errors,
                next_run_at=next_run.isoformat(),
                interval_seconds=interval,
            )

            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                print(f"[Worker] max_iterations={max_iterations} erreicht.")
                break

            if not _running:
                break

            _interruptible_sleep(interval)
        print("[Worker] Hauptschleife beendet.")
    except Exception as e:
        # Defensive Top-Level-Klammer — sollte mit den 3 try/except-Ebenen
        # nicht greifen, aber sicher ist sicher.
        print(f"[Worker] FATAL: {type(e).__name__}: {e}")
        return 2
    finally:
        _cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
