import tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import dataclass
from typing import Optional, Tuple, Callable
import inspect
import threading, queue

# ---- pymodbus compatibility (3.x preferred; 2.x fallback) ----
try:
    from pymodbus.client import ModbusSerialClient  # 3.x
except Exception:
    from pymodbus.client.sync import ModbusSerialClient  # 2.x
from pymodbus.exceptions import ModbusException

# ----------------------------
# Defaults & register map
# ----------------------------
DEFAULT_PORT     = "COM10"
DEFAULT_BAUD     = 19200
DEFAULT_PARITY   = "E"   # Even
DEFAULT_STOPBITS = 1
DEFAULT_BYTESIZE = 8
DEFAULT_TIMEOUT  = 2.0
DEFAULT_UNIT_ID  = 1

REG_SET_COOL       = 0
REG_SET_ALARM_HI   = 1
REG_SET_ALARM_LO   = 2
REG_SET_HEATER     = 3

REG_ENABLE_FLAGS_READ       = 4
REG_ENABLE_FLAGS_WRITE_CAND = [4, 6]  # some firmwares require 6 for writing flags

REG_READ_SENSOR = 12

# Enable Flags bits (Seifert/SCE NextGen family)
BIT_INPUT1_INVERT        = 8     # used as "Power" (ACTIVE-LOW on your unit)
BIT_LOCK_KEYPAD          = 10    # always ON
BIT_TEMP_UNIT_FAHRENHEIT = 11    # always OFF (Celsius)
BIT_NETWORK_SETPOINTS: Optional[int] = 9   # set None if your unit doesn't support it

# Reasonable safety limits (device often enforces similar)
SAFE_C_LIMITS = {
    "low":   (-20.0,  25.0),
    "heat":  ( -5.0,  35.0),
    "cool":  ( 20.0,  60.0),  # most models reject cooling < ~20–25 C
    "high":  ( 30.0,  80.0),
}

# ----------------------------
# Helpers (0.1° scaling)
# ----------------------------
def to_signed_16(u: int) -> int:
    return u - 0x10000 if u >= 0x8000 else u

def reg_to_val(raw: int) -> float:
    return to_signed_16(int(raw)) / 10.0

def c_to_reg(val_c: float) -> int:
    return int(round(float(val_c) * 10))

def clamp(v: float, lo: float, hi: float) -> float:
    v = float(v)
    return lo if v < lo else hi if v > hi else v

# ----------------------------
# Robust Modbus controller (no GUI blocking)
# ----------------------------
@dataclass
class ACController:
    port: str = DEFAULT_PORT
    baudrate: int = DEFAULT_BAUD
    parity: str = DEFAULT_PARITY
    stopbits: int = DEFAULT_STOPBITS
    bytesize: int = DEFAULT_BYTESIZE
    timeout: float = DEFAULT_TIMEOUT
    unit: int = DEFAULT_UNIT_ID

    client: Optional[ModbusSerialClient] = None
    flags_write_addr: Optional[int] = None  # auto-detected

    # --- connect/disconnect ---
    def connect(self) -> bool:
        # Create fresh client each time to avoid stale handles after errors
        if self.client:
            try: self.client.close()
            except Exception: pass
            self.client = None

        self.client = ModbusSerialClient(
            port=self.port,
            baudrate=self.baudrate,
            parity=self.parity,
            stopbits=self.stopbits,
            bytesize=self.bytesize,
            timeout=self.timeout,
        )
        ok = self.client.connect()
        if ok:
            try:
                self._detect_flags_write_address()
            except Exception:
                pass
            # Enforce policy on connect (lock keypad, Celsius), preserve power & NET state
            try:
                cur = self.read_enable_flags()
                cur_power_on = self._power_on_from_flags(cur)  # ACTIVE-LOW mapping
                cur_net = self._net_on_from_flags(cur)
                self.write_flags(power_on=cur_power_on, force_net=cur_net)
            except Exception:
                # Don't fail connect if policy write fails
                pass
        return ok

    def close(self):
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    # --- modbus compat helpers ---
    def _kw_unit_for(self, fn):
        try:
            params = inspect.signature(fn).parameters
            if "slave" in params: return "slave"  # 3.x
            if "unit"  in params: return "unit"   # 2.x
        except Exception:
            pass
        return None

    def _supports_param(self, fn, name: str) -> bool:
        try: return name in inspect.signature(fn).parameters
        except Exception: return False

    def _read_hregs(self, address, count=1):
        fn = getattr(self.client, "read_holding_registers", None)
        if fn is not None:
            kw = self._kw_unit_for(fn)
            kwargs = {kw: self.unit} if kw else {}
            try:
                if self._supports_param(fn, "count") or self._supports_param(fn, "quantity"):
                    rr = fn(address, count, **kwargs)
                else:
                    rr = fn(address, **kwargs)
            except TypeError:
                try: rr = fn(address, **kwargs)
                except TypeError: rr = fn(address)
            if rr.isError(): raise ModbusException(rr)
            return rr
        fn = getattr(self.client, "read_holding_register", None)
        if fn is None: raise RuntimeError("Client missing read_holding_register(s)")
        kw = self._kw_unit_for(fn)
        kwargs = {kw: self.unit} if kw else {}
        try: rr = fn(address, **kwargs)
        except TypeError: rr = fn(address)
        if rr.isError(): raise ModbusException(rr)
        return rr

    def _write_reg(self, address, value):
        fn = getattr(self.client, "write_register", None)
        if fn is None: raise RuntimeError("Client missing write_register")
        kw = self._kw_unit_for(fn)
        kwargs = {kw: self.unit} if kw else {}
        wr = fn(address, int(value), **kwargs) if kwargs else fn(address, int(value))
        if wr.isError():
            code = getattr(wr, "exception_code", "??")
            raise ModbusException(f"ExceptionResponse(dev_id={self.unit}, function_code={wr.function_code}, exception_code={code})")
        return wr

    def _try_echo_write(self, addr, value) -> bool:
        try:
            self._write_reg(addr, value)
            return True
        except Exception:
            return False

    def _detect_flags_write_address(self):
        cur = self.read_enable_flags()
        for cand in REG_ENABLE_FLAGS_WRITE_CAND:
            if self._try_echo_write(cand, cur):
                self.flags_write_addr = cand
                return
        self.flags_write_addr = None

    # --- reads ---
    def read_enable_flags(self) -> int:
        rr = self._read_hregs(REG_ENABLE_FLAGS_READ, 1)
        return getattr(rr, "registers", [getattr(rr, "register", 0)])[0]

    def read_sensor_c(self) -> float:
        rr = self._read_hregs(REG_READ_SENSOR, 1)
        raw = getattr(rr, "registers", [getattr(rr, "register", 0)])[0]
        return reg_to_val(raw)  # we enforce Celsius in flags

    # --- flag helpers (ACTIVE-LOW power mapping) ---
    def _power_on_from_flags(self, flags: int) -> bool:
        # Bit=1 means "invert door contact" → your unit behaves active-low for Power.
        # Treat bit=0 as Power ON, bit=1 as Power OFF.
        return ((flags >> BIT_INPUT1_INVERT) & 1) == 0

    def _net_on_from_flags(self, flags: int) -> bool:
        return BIT_NETWORK_SETPOINTS is not None and ((flags >> BIT_NETWORK_SETPOINTS) & 1) == 1

    def write_flags(self, power_on: bool, force_net: Optional[bool] = None):
        """Lock keypad, force Celsius, control power. Preserve or set NET bit."""
        current = 0
        try:
            current = self.read_enable_flags()
        except Exception:
            pass
        net_on = self._net_on_from_flags(current) if force_net is None else bool(force_net)

        word = 0
        # ACTIVE-LOW: to turn ON, CLEAR the invert bit; to turn OFF, SET it
        if not power_on:
            word |= (1 << BIT_INPUT1_INVERT)    # OFF → set bit
        word |= (1 << BIT_LOCK_KEYPAD)          # always lock
        # Celsius → Fahrenheit bit OFF
        if net_on and BIT_NETWORK_SETPOINTS is not None:
            word |= (1 << BIT_NETWORK_SETPOINTS)

        addrs = [self.flags_write_addr] if self.flags_write_addr is not None else REG_ENABLE_FLAGS_WRITE_CAND
        last = None
        for a in [x for x in addrs if x is not None]:
            try:
                self._write_reg(a, word)
                self.flags_write_addr = a
                return
            except Exception as e:
                last = e
        if last: raise last

    # --- setpoints (Celsius only) ---
    def write_setpoints_c(self, heater_c: float, cooling_c: float):
        # Compute alarms to keep relationships valid at every intermediate write
        lo = heater_c - 2.0
        hi = cooling_c + 5.0

        # clamp to safe ranges
        lo       = clamp(lo,       *SAFE_C_LIMITS["low"])
        heater_c = clamp(heater_c, *SAFE_C_LIMITS["heat"])
        cooling_c= clamp(cooling_c,*SAFE_C_LIMITS["cool"])
        hi       = clamp(hi,       *SAFE_C_LIMITS["high"])

        # enforce order with 1°C separation
        eps = 1.0
        if not (lo < heater_c - eps and heater_c < cooling_c - eps and cooling_c < hi - eps):
            raise ValueError("Range must satisfy: Low < Heater < Cooling < High (≥1°C apart).")

        def do_writes():
            # WRITE ORDER IS IMPORTANT: low -> heat -> cool -> high
            for addr, val in [
                (REG_SET_ALARM_LO, c_to_reg(lo)),
                (REG_SET_HEATER,   c_to_reg(heater_c)),
                (REG_SET_COOL,     c_to_reg(cooling_c)),
                (REG_SET_ALARM_HI, c_to_reg(hi)),
            ]:
                self._write_reg(addr, val)

        # Temporarily enable Network Setpoints while writing, then restore
        initial = self.read_enable_flags()
        had_net   = self._net_on_from_flags(initial)
        had_power = self._power_on_from_flags(initial)
        try:
            if BIT_NETWORK_SETPOINTS is not None and not had_net:
                self.write_flags(power_on=had_power, force_net=True)
            do_writes()
        finally:
            if BIT_NETWORK_SETPOINTS is not None and not had_net:
                try:
                    self.write_flags(power_on=had_power, force_net=False)
                except Exception:
                    pass

# ----------------------------
# Worker thread to avoid GUI freeze
# ----------------------------
class ModbusWorker:
    """
    Serial/Modbus operations run here so Tk never blocks.
    Use submit(op, kwargs, on_done) to queue work.
    on_done(result, error) will be called back on Tk's main thread.
    """
    def __init__(self, tk_after: Callable[[int, Callable], str], controller: ACController):
        self._after = tk_after
        self.ctrl = controller
        self.q: "queue.Queue[tuple[str, dict, Callable]]" = queue.Queue()
        self.running = True
        self.lock = threading.Lock()  # avoid overlapping I/O on slow links
        self.th = threading.Thread(target=self._run, daemon=True)
        self.th.start()

    def stop(self):
        self.running = False
        self.q.put(("__stop__", {}, lambda *_: None))

    def submit(self, op: str, kwargs: dict, on_done: Callable[[object, Optional[Exception]], None]):
        """Queue an operation. on_done will be called on the Tk thread."""
        self.q.put((op, kwargs, on_done))

    def _cb(self, fn: Callable, *args):
        # Bounce result back to Tk main thread
        try:
            self._after(0, lambda: fn(*args))
        except Exception:
            pass

    def _run(self):
        while self.running:
            try:
                op, kwargs, done = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            if op == "__stop__":
                break

            result, error = None, None
            try:
                with self.lock:
                    if op == "connect":
                        result = self.ctrl.connect()
                    elif op == "disconnect":
                        self.ctrl.close()
                        result = True
                    elif op == "read_temp":
                        result = self.ctrl.read_sensor_c()
                    elif op == "read_flags":
                        result = self.ctrl.read_enable_flags()
                    elif op == "apply_power":
                        self.ctrl.write_flags(power_on=bool(kwargs.get("power_on")), force_net=None)
                        result = True
                    elif op == "apply_range":
                        self.ctrl.write_setpoints_c(heater_c=float(kwargs["heater_c"]),
                                                    cooling_c=float(kwargs["cooling_c"]))
                        result = True
                    else:
                        error = RuntimeError(f"Unknown operation: {op}")
            except Exception as e:
                # Ensure port is closed on severe errors (e.g., PermissionError)
                try: self.ctrl.close()
                except Exception: pass
                error = e

            self._cb(done, result, error)

# ----------------------------
# Simple dual-handle range slider (Canvas)
# ----------------------------
class RangeSlider(tk.Canvas):
    def __init__(self, master, min_val=0.0, max_val=60.0, init_low=15.0, init_high=20.0,
                 width=400, height=56, step=0.5, **kw):
        super().__init__(master, width=width, height=height, highlightthickness=0, **kw)
        self.min_val, self.max_val = float(min_val), float(max_val)
        self.low_val, self.high_val = float(init_low), float(init_high)
        self.step = float(step)
        self.pad = 12
        self.track_h = 6
        self.handle_r = 8
        self.dragging = None
        self.bind("<Button-1>", self.on_press)
        self.bind("<B1-Motion>", self.on_drag)
        self.bind("<ButtonRelease-1>", self.on_release)
        self.draw()

    def draw(self):
        self.delete("all")
        w, h = int(self["width"]), int(self["height"])
        x0, x1 = self.pad, w - self.pad
        y = h // 2
        # Track
        self.create_line(x0, y, x1, y, width=self.track_h, fill="#ddd")
        # Range fill
        lx = self.val_to_x(self.low_val)
        hx = self.val_to_x(self.high_val)
        self.create_line(lx, y, hx, y, width=self.track_h, fill="#8aa")
        # Handles
        self.low_handle  = self.create_oval(lx-self.handle_r, y-self.handle_r, lx+self.handle_r, y+self.handle_r, fill="#fff", outline="#444")
        self.high_handle = self.create_oval(hx-self.handle_r, y-self.handle_r, hx+self.handle_r, y+self.handle_r, fill="#fff", outline="#444")
        # Labels
        self.create_text(lx, y-18, text=f"{self.low_val:.1f}°C", font=("Segoe UI", 9))
        self.create_text(hx, y-18, text=f"{self.high_val:.1f}°C", font=("Segoe UI", 9))

    def val_to_x(self, v):
        v = max(self.min_val, min(self.max_val, v))
        w = int(self["width"])
        x0, x1 = self.pad, w - self.pad
        return x0 + (x1 - x0) * ((v - self.min_val) / (self.max_val - self.min_val))

    def x_to_val(self, x):
        w = int(self["width"])
        x0, x1 = self.pad, w - self.pad
        x = max(x0, min(x1, x))
        v = self.min_val + (self.max_val - self.min_val) * ((x - x0) / (x1 - x0))
        return round(v / self.step) * self.step

    def on_press(self, e):
        lx = self.val_to_x(self.low_val)
        hx = self.val_to_x(self.high_val)
        if abs(e.x - lx) < abs(e.x - hx):
            self.dragging = "low"
        else:
            self.dragging = "high"

    def on_drag(self, e):
        if not self.dragging: return
        v = self.x_to_val(e.x)
        if self.dragging == "low":
            self.low_val = min(v, self.high_val - 1.0)  # keep ≥1°C gap
        else:
            self.high_val = max(v, self.low_val + 1.0)
        self.draw()

    def on_release(self, _):
        self.dragging = None

    def get_values(self) -> Tuple[float, float]:
        # left handle = heater setpoint, right handle = cooling setpoint
        return (self.low_val, self.high_val)

# ----------------------------
# Tkinter App (minimal UI; non-blocking)
# ----------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AC Controller")
        self.geometry("460x290")
        self.resizable(False, False)

        self.controller = ACController()
        self.worker = ModbusWorker(self.after, self.controller)
        self.refresh_job = None
        self.refresh_inflight = False

        self._build_ui()
        self._update_indicator(False)

    # --- UI ---
    def _build_ui(self):
        # Connection row
        row = ttk.Frame(self)
        row.pack(fill="x", padx=12, pady=10)
        self.ind_canvas = tk.Canvas(row, width=14, height=14, highlightthickness=0)
        self.ind_canvas.grid(row=0, column=0, padx=(0,8))
        ttk.Button(row, text="Connect", command=self.connect).grid(row=0, column=1, padx=4)
        ttk.Button(row, text="Disconnect", command=self.disconnect).grid(row=0, column=2, padx=4)

        # Now (auto-refresh)
        frm_now = ttk.LabelFrame(self, text="Now")
        frm_now.pack(fill="x", padx=12, pady=(2,10))
        self.lbl_temp = ttk.Label(frm_now, text="Temperature: --.- °C")
        self.lbl_temp.pack(side="left", padx=8, pady=6)
        ttk.Label(frm_now, text="(updates every 5 s)").pack(side="left", padx=6)

        # Range slider for Heater/Cooling
        frm_range = ttk.LabelFrame(self, text="Temperature Range (Heater → Cooling)")
        frm_range.pack(fill="x", padx=12, pady=6)
        self.slider = RangeSlider(frm_range, min_val=0.0, max_val=60.0, init_low=15.0, init_high=20.0, width=400, height=56, step=0.5)
        self.slider.pack(padx=8, pady=6)
        ttk.Button(frm_range, text="Apply Range", command=self.apply_range).pack(pady=(0,6))

        # Power (Enable Flags policy baked-in)
        frm_flags = ttk.LabelFrame(self, text="Power")
        frm_flags.pack(fill="x", padx=12, pady=6)
        self.var_power = tk.BooleanVar(value=False)
        self.chk_power = ttk.Checkbutton(frm_flags, text="AC Power", variable=self.var_power, command=self.apply_power)
        self.chk_power.pack(anchor="w", padx=8, pady=6)

    def _update_indicator(self, connected: bool):
        self.ind_canvas.delete("all")
        color = "#2ecc71" if connected else "#e74c3c"
        self.ind_canvas.create_oval(1,1,13,13, fill=color, outline=color)

    # --- Connect / Disconnect (non-blocking) ---
    def connect(self):
        def on_done(ok, err):
            if err or not ok:
                self._update_indicator(False)
                msg = str(err) if err else "Failed to open serial port."
                messagebox.showerror("Connect error", msg)
                return
            self._update_indicator(True)
            # Sync power checkbox
            def on_flags(flags, e2):
                if e2 is None and isinstance(flags, int):
                    # ACTIVE-LOW → checked = ON
                    self.var_power.set(((flags >> BIT_INPUT1_INVERT) & 1) == 0)
                self._start_auto_refresh()
                messagebox.showinfo("Connected", f"Connected on {self.controller.port}")
            self.worker.submit("read_flags", {}, on_flags)

        self.worker.submit("connect", {}, on_done)

    def disconnect(self):
        self._stop_auto_refresh()
        def on_done(_ok, _err):
            self._update_indicator(False)
            messagebox.showinfo("Disconnected", "Serial connection closed")
        self.worker.submit("disconnect", {}, on_done)

    # --- Auto refresh every 5 seconds (non-overlapping) ---
    def _start_auto_refresh(self):
        self._stop_auto_refresh()
        self._do_refresh_loop()

    def _do_refresh_loop(self):
        if self.refresh_inflight:
            # Skip if a read is still running; reschedule
            self.refresh_job = self.after(5000, self._do_refresh_loop)
            return
        self.refresh_inflight = True
        def on_done(val, err):
            self.refresh_inflight = False
            if err is None and isinstance(val, (int, float)):
                self.lbl_temp.config(text=f"Temperature: {float(val):.1f} °C")
            else:
                self.lbl_temp.config(text=f"Temperature: --.- °C")
            self.refresh_job = self.after(5000, self._do_refresh_loop)
        self.worker.submit("read_temp", {}, on_done)

    def _stop_auto_refresh(self):
        if self.refresh_job:
            try: self.after_cancel(self.refresh_job)
            except Exception: pass
            self.refresh_job = None
        self.refresh_inflight = False

    # --- Actions (non-blocking) ---
    def apply_power(self):
        def on_done(_ok, err):
            if err:
                messagebox.showerror("Write error", str(err))
            else:
                messagebox.showinfo("OK", "Power/flags updated.")
        self.worker.submit("apply_power", {"power_on": self.var_power.get()}, on_done)

    def apply_range(self):
        heat, cool = self.slider.get_values()  # left→heater, right→cooling
        def on_done(_ok, err):
            if err:
                messagebox.showerror("Write error", str(err))
            else:
                messagebox.showinfo("OK", f"Range applied: Heater {heat:.1f}°C → Cooling {cool:.1f}°C")
        self.worker.submit("apply_range", {"heater_c": heat, "cooling_c": cool}, on_done)

    # --- cleanup ---
    def destroy(self):
        try:
            self._stop_auto_refresh()
            self.worker.stop()
        finally:
            super().destroy()

# ---- run ----
if __name__ == "__main__":
    App().mainloop()
