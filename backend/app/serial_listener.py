"""
serial_listener.py
Reads STM32 serial data using pyserial directly in a daemon thread.
Works reliably on Windows (COM ports) and Linux (/dev/ttyUSBx) without
pyserial-asyncio.  A threading bridge pushes lines into the asyncio loop.

Runtime config can be changed via set_serial_config() — the listener
restarts automatically on the next cycle.

Environment variables:
    SERIAL_PORT      – serial port to open  (Windows default: COM3, Linux: /dev/ttyUSB0)
    BAUD_RATE        – baud rate            (default: 115200)
    SERIAL_SIMULATE  – set to "true" only when running without hardware (default: false)

Port detection:
    When the configured port is unavailable, the listener automatically scans
    all detected COM ports and opens whichever one responds first.  This means
    plugging in the STM32 on any port (e.g. COM12) is detected within one
    retry cycle (~5 s) with no manual configuration needed.
"""

import asyncio
import logging
import os
import random
import sys
import threading
import time
from typing import Callable, Awaitable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_DEFAULT_PORT = "COM3" if sys.platform == "win32" else "/dev/ttyUSB0"
RECONNECT_DELAY = 5

PacketCallback = Callable[[str], Awaitable[None]]

# Mutable runtime config — updated via set_serial_config()
_config: dict = {
    "port":     os.getenv("SERIAL_PORT",     _DEFAULT_PORT),
    "baud":     int(os.getenv("BAUD_RATE",   "115200")),
    "simulate": os.getenv("SERIAL_SIMULATE", "false").lower() in ("1", "true", "yes"),
}

_status: dict = {
    "connected": False,
    "port":      _config["port"],
    "baud":      _config["baud"],
    "mode":      "simulator" if _config["simulate"] else "serial",
    "error":     None,
}

# Signals the current listener sub-coroutine to exit so start_listener restarts
_config_changed = False
_serial_stop    = threading.Event()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_serial_status() -> dict:
    return dict(_status)


def set_serial_config(
    port: Optional[str]  = None,
    baud: Optional[int]  = None,
    simulate: Optional[bool] = None,
) -> None:
    """Update connection config and signal the listener to restart."""
    global _config_changed
    if port     is not None: _config["port"]     = port;     _status["port"]  = port
    if baud     is not None: _config["baud"]     = baud;     _status["baud"]  = baud
    if simulate is not None: _config["simulate"] = simulate; _status["mode"]  = "simulator" if simulate else "serial"
    _config_changed = True
    _serial_stop.set()   # interrupt any ongoing serial wait


def get_available_ports() -> list:
    """Return list of available serial ports (requires pyserial)."""
    try:
        from serial.tools import list_ports  # type: ignore
        return [
            {"port": p.device, "description": p.description, "hwid": p.hwid}
            for p in sorted(list_ports.comports())
        ]
    except ImportError:
        return []


# NOTE: These module-level aliases are captured at import time and are NOT
# updated when set_serial_config() is called. Use _config[] or get_serial_status()
# for the live values.  Kept only so existing imports don't break.
SERIAL_PORT = _config["port"]
BAUD_RATE   = _config["baud"]
SIMULATE    = _config["simulate"]


# ---------------------------------------------------------------------------
# Simulator – generates realistic demo telemetry when no hardware present
# ---------------------------------------------------------------------------

class _DemoSimulator:
    """Generates fake multi-node telemetry that drifts realistically."""

    _NODE_COUNT = 4
    _INTERVAL   = 0.5

    def __init__(self):
        self._state: dict = {}
        for nid in range(1, self._NODE_COUNT + 1):
            self._state[nid] = {
                "temp":        35.0 + random.uniform(0, 10),
                "current":     5.0  + random.uniform(0, 3),
                "vibration":   0.02 + random.uniform(0, 0.01),
                "state":       1,
                "spike_timer": random.randint(40, 80),
            }

    def next_packets(self) -> list:
        packets = []
        for nid, s in self._state.items():
            s["temp"]      += random.uniform(-0.3,  0.4)
            s["current"]   += random.uniform(-0.2,  0.3)
            s["vibration"] += random.uniform(-0.005, 0.006)
            s["temp"]       = max(20.0, min(85.0,  s["temp"]))
            s["current"]    = max(0.5,  min(25.0,  s["current"]))
            s["vibration"]  = max(0.005, min(0.20, s["vibration"]))

            s["spike_timer"] -= 1
            if s["spike_timer"] <= 0:
                kind = random.choice(["temp", "current"])
                if kind == "temp":
                    s["temp"] = 75.0 + random.uniform(0, 5)
                    packets.append(f"node_id={nid},alert=overtemp,value={s['temp']:.1f},action=power_cutoff")
                else:
                    s["current"] = 22.0 + random.uniform(0, 4)
                    packets.append(f"node_id={nid},alert=overcurrent,value={s['current']:.1f},action=power_cutoff")
                s["spike_timer"] = random.randint(60, 120)
                s["state"] = 3
            else:
                s["state"] = 1 if s["temp"] < 60 and s["current"] < 15 else 2

            packets.append(
                f"node_id={nid},"
                f"temp={s['temp']:.1f},"
                f"current={s['current']:.1f},"
                f"vibration={s['vibration']:.3f},"
                f"state={s['state']}"
            )
        return packets


# ---------------------------------------------------------------------------
# Simulator async runner (pure-software mode, no port needed)
# ---------------------------------------------------------------------------

async def _run_simulator(callback: PacketCallback) -> None:
    global _config_changed
    _config_changed      = False
    _status["connected"] = True
    _status["mode"]      = "simulator"
    _status["error"]     = None
    logger.info("Serial simulator running (4 virtual CAN nodes)")
    sim = _DemoSimulator()
    while not _config_changed:
        for packet in sim.next_packets():
            await callback(packet)
        await asyncio.sleep(_DemoSimulator._INTERVAL)
    logger.info("Simulator stopped — config changed")


# ---------------------------------------------------------------------------
# Real serial reader  (pyserial + daemon thread)
# ---------------------------------------------------------------------------

def _serial_thread_fn(
    queue: "asyncio.Queue[str]",
    loop: asyncio.AbstractEventLoop,
) -> None:
    """
    Blocking pyserial read loop in a daemon thread.

    Each retry cycle:
      1. Build candidate list: configured port first, then every other
         COM port currently visible to the OS.
      2. Try each candidate in order.
      3. Whichever opens first: set mode='demo', emit __CONNECTED__, run
         demo simulator until real STM32 packets arrive or config changes.
      4. If nothing opens: log WAIT state, wait RECONNECT_DELAY, repeat.
    """
    global _config_changed
    try:
        import serial  # type: ignore
        from serial.tools import list_ports as _lp  # type: ignore
    except ImportError:
        _status["error"] = "pyserial not installed — run: pip install pyserial"
        logger.error(_status["error"])
        return

    _serial_stop.clear()

    while not _serial_stop.is_set() and not _config_changed:
        baud = _config["baud"]
        configured_port = _config["port"]

        # Build candidate list: configured port first, then all other detected ports.
        # This means COM12 (or any other port) is tried immediately each cycle.
        detected   = [p.device for p in sorted(_lp.comports())]
        candidates = [configured_port] + [p for p in detected if p != configured_port]

        opened = False
        for port in candidates:
            if _serial_stop.is_set() or _config_changed:
                break
            try:
                logger.info("Trying serial port %s @ %d baud", port, baud)
                with serial.Serial(port, baud, timeout=1) as ser:
                    # ── Port opened successfully ──────────────────────────
                    opened = True
                    _config["port"]      = port   # remember which port we actually used
                    _status["port"]      = port
                    _status["baud"]      = baud
                    _status["connected"] = True
                    _status["error"]     = None
                    _status["mode"]      = "demo"
                    logger.info(
                        "Port %s open — demo simulator running, waiting for STM32 data", port
                    )
                    loop.call_soon_threadsafe(queue.put_nowait, "__CONNECTED__")

                    sim = _DemoSimulator()
                    last_sim_emit = 0.0

                    while not _serial_stop.is_set() and not _config_changed:
                        raw = ser.readline()
                        if raw:
                            line = raw.decode("utf-8", errors="replace").strip()
                            if line:
                                # Real STM32 packet
                                loop.call_soon_threadsafe(queue.put_nowait, line)
                            last_sim_emit = time.time()
                            continue
                        # No data this timeout cycle — emit demo packets
                        now = time.time()
                        if now - last_sim_emit >= _DemoSimulator._INTERVAL:
                            last_sim_emit = now
                            for packet in sim.next_packets():
                                loop.call_soon_threadsafe(queue.put_nowait, packet)

                    break  # exit candidates loop — we are done with this connection

            except Exception as exc:
                logger.debug("Port %s failed: %s", port, exc)
                continue   # try next candidate

        if not opened:
            # ── No port could be opened — WAIT state ─────────────────────
            _status["connected"] = False
            _status["mode"]      = "serial"
            all_tried = ", ".join(candidates) if candidates else "(none)"
            _status["error"] = (
                f"No usable COM port found (tried: {all_tried}). "
                f"Plug in the STM32 board and wait…"
            )
            logger.warning(
                "No COM port opened (tried: %s) — retrying in %ds", all_tried, RECONNECT_DELAY
            )
            loop.call_soon_threadsafe(queue.put_nowait, "__NO_PORT__")
            if _serial_stop.wait(timeout=RECONNECT_DELAY):
                break
            _serial_stop.clear()

    _status["connected"] = False
    logger.info("Serial thread exiting")


async def _run_serial_reader(
    callback: PacketCallback,
    on_status_change=None,      # async callable(status_dict) or None
) -> None:
    global _config_changed
    _config_changed = False
    loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    thread = threading.Thread(
        target=_serial_thread_fn, args=(queue, loop), daemon=True
    )
    thread.start()

    try:
        while not _config_changed:
            try:
                line = await asyncio.wait_for(queue.get(), timeout=1.0)
                if line == "__CONNECTED__":
                    # Port just opened — tell WS clients to update their badge
                    if on_status_change:
                        await on_status_change(get_serial_status())
                elif not line.startswith("__"):
                    await callback(line)
            except asyncio.TimeoutError:
                pass
    finally:
        _serial_stop.set()
        thread.join(timeout=3)

    logger.info("Serial reader stopped — config changed")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def start_listener(
    callback: PacketCallback,
    on_status_change=None,      # async callable(status_dict) or None
) -> None:
    """
    Runs forever.  Automatically restarts when set_serial_config() is called.
    Dispatches to the demo simulator or real pyserial reader based on config.
    on_status_change(status_dict) is called whenever the serial status changes
    (e.g. port opened → lets main.py broadcast over WebSocket immediately).
    """
    while True:
        if _config.get("simulate", False):
            await _run_simulator(callback)
        else:
            await _run_serial_reader(callback, on_status_change=on_status_change)
        await asyncio.sleep(0.5)
