import tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import dataclass
from typing import Optional, Tuple
import inspect

# Try modern import first (pymodbus 3.x), then legacy (2.x)
try:
    from pymodbus.client import ModbusSerialClient  # 3.x
except Exception:
    from pymodbus.client.sync import ModbusSerialClient  # 2.x
from pymodbus.exceptions import ModbusException

# ----------------------------
# Modbus/Device Defaults
# ----------------------------
DEFAULT_PORT     = "COM10"
DEFAULT_BAUD     = 19200
DEFAULT_PARITY   = "E"   # Even
DEFAULT_STOPBITS = 1
DEFAULT_BYTESIZE = 8
DEFAULT_TIMEOUT  = 2.0
DEFAULT_UNIT_ID  = 1

# Holding register map (typical Seifert/SCE NextGen)
REG_SET_COOL  = 0
REG_SET_ALARM_HI = 1
REG_SET_ALARM_LO = 2
REG_SET_HEATER   = 3

REG_ENABLE_FLAGS_READ        = 4            # readable
REG_ENABLE_FLAGS_WRITE_CAND  = [4, 6]       # some firmwares require 6 for write

REG_READ_CTL_SETPOINT = 5   # not used but kept for reference
REG_READ_SENSOR       = 12
REG_READ_ALARMS       = 14
REG_READ_OUTPUTS      = 15
REG_READ_CONTACTS     = 16

# Enable Flags (documented) bit indices
BIT_INPUT1_INVERT          = 8
BIT_LOCK_KEYPAD            = 10
BIT_TEMP_UNIT_FAHRENHEIT   = 11
# Many firmwares use bit 9 for “Use Network Setpoints”.
# If your unit differs, change it here; if unsupported, set to None.
BIT_NETWORK_SETPOINTS: Optional[int] = 9

# ----------------------------
# Helpers
# ----------------------------
def to_signed_16(u: int) -> int:
    return u - 0x10000 if u >= 0x8000 else u

def reg_to_c(value: int) -> float:
    return to_signed_16(int(value)) / 10.0

def c_to_reg(value_c: float) -> int:
    return int(round(float(value_c) * 10))

def f_to_reg(value_f: float) -> int:
    return int(round(float(value_f) * 10))

def c_to_f(c: float) -> float:
    return (float(c) * 9.0/5.0) + 32.0

def f_to_c(f: float) -> float:
    return (float(f) - 32.0) * 5.0/9.0

# Reasonable safety limits for enclosure AC (device will often enforce similar)
SAFE_C_LIMITS = {
    "low":   (-20.0,  25.0),
    "heat":  ( -5.0,  35.0),
    "cool":  ( 20.0,  60.0),   # most units reject < ~20–25 °C
    "high":  ( 30.0,  80.0),
}
SAFE_F_LIMITS = {
    "low":   ( -4.0,   77.0),  # ≈ -20..25 C
    "heat":  ( 23.0,   95.0),  # ≈ -5..35 C
    "cool":  ( 68.0,  140.0),  # ≈ 20..60 C
    "high":  ( 86.0,  176.0),  # ≈ 30..80 C
}

def clamp(v: float, lo: float, hi: float) -> float:
    v = float(v)
    return lo if v < lo else hi if v > hi else v

# ----------------------------
# Controller (robust across pymodbus variants)
# ----------------------------
@dataclass
class ACController:
    port: str
    baudrate: int = DEFAULT_BAUD
    parity: str = DEFAULT_PARITY
    stopbits: int = DEFAULT_STOPBITS
    bytesize: int = DEFAULT_BYTESIZE
    timeout: float = DEFAULT_TIMEOUT
    unit: int = DEFAULT_UNIT_ID

    client: Optional[ModbusSerialClient] = None
    flags_write_addr: Optional[int] = None  # autodetected

    def connect(self) -> bool:
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
        return ok

    def close(self):
        if self.client:
            self.client.close()
            self.client = None

    # ---------- Modbus compatibility helpers ----------
    def _kw_unit_for(self, fn):
        try:
            params = inspect.signature(fn).parameters
            if "slave" in params: return "slave"   # pymodbus 3.x
            if "unit"  in params: return "unit"    # pymodbus 2.x
        except Exception:
            pass
        return None

    def _supports_param(self, fn, name: str) -> bool:
        try:
            return name in inspect.signature(fn).parameters
        except Exception:
            return False

    def _call_read_hregs(self, address, count=1):
        # Prefer plural
        fn = getattr(self.client, "read_holding_registers", None)
        if fn is not None:
            kw_unit = self._kw_unit_for(fn)
            kwargs = {kw_unit: self.unit} if kw_unit else {}
            try:
                if self._supports_param(fn, "count") or self._supports_param(fn, "quantity"):
                    rr = fn(address, count, **kwargs)
                else:
                    rr = fn(address, **kwargs)
            except TypeError:
                try:
                    rr = fn(address, **kwargs)
                except TypeError:
                    rr = fn(address)
            if rr.isError():
                raise ModbusException(rr)
            return rr

        # Fallback singular
        fn = getattr(self.client, "read_holding_register", None)
        if fn is None:
            raise RuntimeError("Client has no read_holding_register(s) method.")
        kw_unit = self._kw_unit_for(fn)
        kwargs = {kw_unit: self.unit} if kw_unit else {}
        try:
            rr = fn(address, **kwargs)
        except TypeError:
            rr = fn(address)
        if rr.isError():
            raise ModbusException(rr)
        return rr

    def _write_reg(self, address, value):
        fn = getattr(self.client, "write_register", None)
        if fn is None:
            raise RuntimeError("Client has no write_register method.")
        kw_unit = self._kw_unit_for(fn)
        kwargs = {kw_unit: self.unit} if kw_unit else {}
        wr = fn(address, int(value), **kwargs) if kwargs else fn(address, int(value))
        if wr.isError():
            code = getattr(wr, "exception_code", "??")
            raise ModbusException(f"ExceptionResponse(dev_id={self.unit}, function_code={wr.function_code}, exception_code={code})")
        return wr

    def _try_write_same_value(self, address, value) -> bool:
        try:
            self._write_reg(address, value)
            return True
        except Exception:
            return False

    def _detect_flags_write_address(self):
        current = self.read_enable_flags()
        for cand in REG_ENABLE_FLAGS_WRITE_CAND:
            if self._try_write_same_value(cand, current):
                self.flags_write_addr = cand
                return
        self.flags_write_addr = None  # not writable on this model

    # ---------- Flags ----------
    def read_enable_flags(self) -> int:
        rr = self._call_read_hregs(REG_ENABLE_FLAGS_READ, 1)
        return getattr(rr, "registers", [getattr(rr, "register", 0)])[0]

    def device_is_fahrenheit(self) -> bool:
        flags = self.read_enable_flags()
        return bool((flags >> BIT_TEMP_UNIT_FAHRENHEIT) & 1)

    def _compose_flags_word(self, invert: bool, lock: bool, fahr: bool,
                            net_on: Optional[bool], current: Optional[int] = None) -> int:
        # CLEAN word: only documented bits set; all others 0 (many firmwares reject unknown bits)
        word = 0
        if invert: word |= (1 << BIT_INPUT1_INVERT)
        if lock:   word |= (1 << BIT_LOCK_KEYPAD)
        if fahr:   word |= (1 << BIT_TEMP_UNIT_FAHRENHEIT)
        if BIT_NETWORK_SETPOINTS is not None and net_on is True:
            word |= (1 << BIT_NETWORK_SETPOINTS)
        return word

    def _write_flags_clean(self, invert: bool, lock: bool, fahr: bool, net_on: Optional[bool]):
        word = self._compose_flags_word(invert, lock, fahr, net_on)
        addrs = [self.flags_write_addr] if self.flags_write_addr is not None else REG_ENABLE_FLAGS_WRITE_CAND
        last = None
        for addr in [a for a in addrs if a is not None]:
            try:
                self._write_reg(addr, word)
                self.flags_write_addr = addr
                return
            except Exception as e:
                last = e
        if last:
            raise last

    # Temporarily enable network setpoints around a write
    def _with_network_mode(self, do_write_fn):
        initial_flags = self.read_enable_flags()
        had_net = (BIT_NETWORK_SETPOINTS is not None) and bool((initial_flags >> BIT_NETWORK_SETPOINTS) & 1)
        # Try to enable NET only if we know the bit
        if BIT_NETWORK_SETPOINTS is not None:
            try:
                self._write_flags_clean(
                    invert=bool((initial_flags >> BIT_INPUT1_INVERT) & 1),
                    lock=bool((initial_flags >> BIT_LOCK_KEYPAD) & 1),
                    fahr=bool((initial_flags >> BIT_TEMP_UNIT_FAHRENHEIT) & 1),
                    net_on=True
                )
            except Exception:
                # If enabling NET fails, continue anyway (some models ignore this)
                pass

        # Perform the write
        try:
            do_write_fn()
        finally:
            # Restore original NET state if we changed it
            if BIT_NETWORK_SETPOINTS is not None:
                try:
                    self._write_flags_clean(
                        invert=bool((initial_flags >> BIT_INPUT1_INVERT) & 1),
                        lock=bool((initial_flags >> BIT_LOCK_KEYPAD) & 1),
                        fahr=bool((initial_flags >> BIT_TEMP_UNIT_FAHRENHEIT) & 1),
                        net_on=had_net
                    )
                except Exception:
                    pass

    # ---------- Reads ----------
    def read_sensor_c(self) -> float:
        rr = self._call_read_hregs(REG_READ_SENSOR, 1)
        val = getattr(rr, "registers", [getattr(rr, "register", 0)])[0]
        return reg_to_c(val)

    def read_status_regs(self) -> Tuple[int, int, int]:
        r1 = self._call_read_hregs(REG_READ_ALARMS, 1)
        r2 = self._call_read_hregs(REG_READ_OUTPUTS, 1)
        r3 = self._call_read_hregs(REG_READ_CONTACTS, 1)
        def one(r): return getattr(r, "registers", [getattr(r, "register", 0)])[0]
        return one(r1), one(r2), one(r3)

    # ---------- Writes ----------
    def write_setpoints(self, cool_in: float, hi_in: float, lo_in: float, heat_in: float, inputs_are_fahrenheit: bool):
        """
        Convert UI inputs to device units, validate ranges/relationships,
        then write in an order that never violates device checks: Low → Heater → Cooling → High.
        """
        dev_f = self.device_is_fahrenheit()

        # Convert UI -> device units
        if inputs_are_fahrenheit and not dev_f:
            cool = f_to_c(cool_in); hi = f_to_c(hi_in); lo = f_to_c(lo_in); heat = f_to_c(heat_in)
        elif (not inputs_are_fahrenheit) and dev_f:
            cool = c_to_f(cool_in); hi = c_to_f(hi_in); lo = c_to_f(lo_in); heat = c_to_f(heat_in)
        else:
            cool, hi, lo, heat = cool_in, hi_in, lo_in, heat_in

        # Validate & clamp to safe ranges in device units
        if dev_f:
            lo  = clamp(lo,  *SAFE_F_LIMITS["low"])
            heat= clamp(heat,*SAFE_F_LIMITS["heat"])
            cool= clamp(cool,*SAFE_F_LIMITS["cool"])
            hi  = clamp(hi,  *SAFE_F_LIMITS["high"])
            to_reg = f_to_reg
            unit_txt = "°F"
        else:
            lo  = clamp(lo,  *SAFE_C_LIMITS["low"])
            heat= clamp(heat,*SAFE_C_LIMITS["heat"])
            cool= clamp(cool,*SAFE_C_LIMITS["cool"])
            hi  = clamp(hi,  *SAFE_C_LIMITS["high"])
            to_reg = c_to_reg
            unit_txt = "°C"

        # Enforce relationships with margin so every step is valid
        # final: lo < heat < cool < hi (≥1 unit apart)
        eps = 1.0
        if not (lo < heat - eps and heat < cool - eps and cool < hi - eps):
            raise ValueError(f"Setpoint order must be Low < Heater < Cooling < High (≥1 {unit_txt} apart). "
                             f"Proposed: Low={lo:.1f}, Heat={heat:.1f}, Cool={cool:.1f}, High={hi:.1f} {unit_txt}")

        def do_writes():
            # WRITE ORDER IS IMPORTANT: low -> heat -> cool -> high
            for addr, val in [
                (REG_SET_ALARM_LO, to_reg(lo)),
                (REG_SET_HEATER,   to_reg(heat)),
                (REG_SET_COOL,     to_reg(cool)),
                (REG_SET_ALARM_HI, to_reg(hi)),
            ]:
                self._write_reg(addr, val)

        # Ensure network mode (if supported) while writing
        self._with_network_mode(do_writes)

# ----------------------------
# Tkinter GUI
# ----------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SCE AC Modbus Controller")
        self.geometry("720x610")
        self.resizable(False, False)

        self.controller: Optional[ACController] = None
        self.inputs_are_fahrenheit = False  # UI unit, synced from device on connect/sync

        self._build_ui()

    def _build_ui(self):
        frm_conn = ttk.LabelFrame(self, text="Connection")
        frm_conn.pack(fill="x", padx=10, pady=10)

        ttk.Label(frm_conn, text="Port:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.var_port = tk.StringVar(value=DEFAULT_PORT)
        ttk.Entry(frm_conn, textvariable=self.var_port, width=12).grid(row=0, column=1, padx=5)

        ttk.Label(frm_conn, text="Baud:").grid(row=0, column=2, sticky="w", padx=5)
        self.var_baud = tk.IntVar(value=DEFAULT_BAUD)
        ttk.Entry(frm_conn, textvariable=self.var_baud, width=8).grid(row=0, column=3, padx=5)

        ttk.Label(frm_conn, text="Parity:").grid(row=0, column=4, sticky="w", padx=5)
        self.var_parity = tk.StringVar(value=DEFAULT_PARITY)
        ttk.Combobox(frm_conn, textvariable=self.var_parity, values=["N","E","O"], width=3).grid(row=0, column=5, padx=5)

        ttk.Label(frm_conn, text="Stop:").grid(row=0, column=6, sticky="w", padx=5)
        self.var_stop = tk.IntVar(value=DEFAULT_STOPBITS)
        ttk.Combobox(frm_conn, textvariable=self.var_stop, values=[1,2], width=3).grid(row=0, column=7, padx=5)

        ttk.Label(frm_conn, text="Unit ID:").grid(row=0, column=8, sticky="w", padx=5)
        self.var_unit = tk.IntVar(value=DEFAULT_UNIT_ID)
        ttk.Entry(frm_conn, textvariable=self.var_unit, width=5).grid(row=0, column=9, padx=5)

        ttk.Button(frm_conn, text="Connect", command=self.connect).grid(row=0, column=10, padx=6)
        ttk.Button(frm_conn, text="Disconnect", command=self.disconnect).grid(row=0, column=11, padx=6)

        # Now
        frm_now = ttk.LabelFrame(self, text="Now")
        frm_now.pack(fill="x", padx=10, pady=5)
        ttk.Button(frm_now, text="Refresh", command=self.refresh).grid(row=0, column=0, padx=6, pady=6)
        self.lbl_temp = ttk.Label(frm_now, text="Internal Sensor: -- °C")
        self.lbl_temp.grid(row=0, column=1, padx=10, sticky="w")
        ttk.Button(frm_now, text="Sync Units from Device", command=self.sync_units).grid(row=0, column=2, padx=6)

        # Setpoints
        self.frm_sp = ttk.LabelFrame(self, text="Setpoints (°C)")
        self.frm_sp.pack(fill="x", padx=10, pady=10)
        self.var_cool = tk.DoubleVar(value=35.0)
        self.var_hi   = tk.DoubleVar(value=60.0)
        self.var_lo   = tk.DoubleVar(value=5.0)
        self.var_heat = tk.DoubleVar(value=10.0)

        self._row(self.frm_sp, 0, "Cooling Setpoint", self.var_cool)
        self._row(self.frm_sp, 1, "High Alarm", self.var_hi)
        self._row(self.frm_sp, 2, "Low Alarm", self.var_lo)
        self._row(self.frm_sp, 3, "Heater Setpoint", self.var_heat)
        ttk.Button(self.frm_sp, text="Write Setpoints", command=self.write_setpoints).grid(row=4, column=1, pady=8, sticky="w")

        # Flags
        frm_flags = ttk.LabelFrame(self, text="Enable Flags (auto-detect write addr)")
        frm_flags.pack(fill="x", padx=10, pady=10)
        self.var_net   = tk.BooleanVar(value=False)
        self.var_lock  = tk.BooleanVar(value=False)
        self.var_fahr  = tk.BooleanVar(value=False)
        self.var_invert= tk.BooleanVar(value=False)

        self.chk_net = ttk.Checkbutton(frm_flags, text="Use Network Setpoints", variable=self.var_net)
        if BIT_NETWORK_SETPOINTS is None:
            self.chk_net.state(["disabled"])
        self.chk_net.grid(row=0, column=0, sticky="w", padx=6, pady=4)

        ttk.Checkbutton(frm_flags, text="Lock Keypad", variable=self.var_lock).grid(row=0, column=1, sticky="w", padx=6, pady=4)
        ttk.Checkbutton(frm_flags, text="Fahrenheit (device)", variable=self.var_fahr, command=self.apply_ui_units_from_checkbox).grid(row=0, column=2, sticky="w", padx=6, pady=4)
        ttk.Checkbutton(frm_flags, text="Invert Door Contact", variable=self.var_invert).grid(row=0, column=3, sticky="w", padx=6, pady=4)
        ttk.Button(frm_flags, text="Read Flags", command=self.read_flags).grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Button(frm_flags, text="Write Flags", command=self.write_flags).grid(row=1, column=1, padx=6, pady=6, sticky="w")

        # Status
        frm_stat = ttk.LabelFrame(self, text="Status")
        frm_stat.pack(fill="x", padx=10, pady=10)
        self.lbl_alarms   = ttk.Label(frm_stat, text="Alarms: 0x0000")
        self.lbl_outputs  = ttk.Label(frm_stat, text="Outputs: 0x0000 (bit0=Heater, bit2=Ambient, bit3=Compressor)")
        self.lbl_contacts = ttk.Label(frm_stat, text="Contacts: 0x0000 (bit0..2 = Door 1..3)")
        self.lbl_alarms.grid(row=0, column=0, sticky="w", padx=6, pady=3)
        self.lbl_outputs.grid(row=1, column=0, sticky="w", padx=6, pady=3)
        self.lbl_contacts.grid(row=2, column=0, sticky="w", padx=6, pady=3)

    def _row(self, parent, r, label, var):
        ttk.Label(parent, text=label + ":").grid(row=r, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(parent, textvariable=var, width=10).grid(row=r, column=1, sticky="w", padx=4, pady=4)

    # ---------- UI helpers ----------
    def set_sp_frame_units(self, fahrenheit: bool):
        self.inputs_are_fahrenheit = fahrenheit
        self.frm_sp.configure(text=f"Setpoints ({'°F' if fahrenheit else '°C'})")

    def sync_units(self):
        if not self.controller:
            messagebox.showwarning("Not connected", "Connect first.")
            return
        try:
            dev_f = self.controller.device_is_fahrenheit()
            self.var_fahr.set(dev_f)
            self.set_sp_frame_units(dev_f)
            messagebox.showinfo("Units", f"Device is set to {'°F' if dev_f else '°C'}.")
        except Exception as e:
            messagebox.showerror("Units error", str(e))

    def apply_ui_units_from_checkbox(self):
        self.set_sp_frame_units(self.var_fahr.get())

    # ---------- Button handlers ----------
    def connect(self):
        try:
            port = self.var_port.get().strip()
            baud = int(self.var_baud.get())
            parity = self.var_parity.get().strip().upper()[:1] or "E"
            stopbits = int(self.var_stop.get())
            unit = int(self.var_unit.get())
            self.controller = ACController(port=port, baudrate=baud, parity=parity,
                                           stopbits=stopbits, bytesize=DEFAULT_BYTESIZE,
                                           timeout=DEFAULT_TIMEOUT, unit=unit)
            if not self.controller.connect():
                raise RuntimeError("Failed to open serial port.")
            self.sync_units()
            messagebox.showinfo("Connected", f"Connected to {port} (unit {unit})")
        except Exception as e:
            messagebox.showerror("Connect error", str(e))

    def disconnect(self):
        if self.controller:
            self.controller.close()
            self.controller = None
            messagebox.showinfo("Disconnected", "Serial connection closed")

    def refresh(self):
        if not self.controller:
            messagebox.showwarning("Not connected", "Connect first.")
            return
        try:
            temp_c = self.controller.read_sensor_c()
            self.lbl_temp.config(text=f"Internal Sensor: {temp_c:.1f} °C")
            alarms, outs, contacts = self.controller.read_status_regs()
            self.lbl_alarms.config(text=f"Alarms: 0x{alarms:04X}")
            self.lbl_outputs.config(text=f"Outputs: 0x{outs:04X} (bit0=Heater, bit2=Ambient, bit3=Compressor)")
            self.lbl_contacts.config(text=f"Contacts: 0x{contacts:04X} (bit0..2=Door1..3)")
        except Exception as e:
            messagebox.showerror("Read error", str(e))

    def write_setpoints(self):
        if not self.controller:
            messagebox.showwarning("Not connected", "Connect first.")
            return
        try:
            self.controller.write_setpoints(
                self.var_cool.get(),
                self.var_hi.get(),
                self.var_lo.get(),
                self.var_heat.get(),
                inputs_are_fahrenheit=self.inputs_are_fahrenheit,
            )
            messagebox.showinfo("Success", "Setpoints written.")
        except Exception as e:
            messagebox.showerror(
                "Write error",
                f"{e}\n\nTips:\n• Use the device’s unit shown in the Setpoints title.\n"
                "• Keep Low < Heater < Cooling < High (≥1° apart).\n"
                "• Cooling too low for enclosure AC (<~20–25 °C) will be rejected."
            )

    def read_flags(self):
        if not self.controller:
            messagebox.showwarning("Not connected", "Connect first.")
            return
        try:
            word = self.controller.read_enable_flags()
            self.var_invert.set(bool((word >> BIT_INPUT1_INVERT) & 1))
            self.var_lock.set(bool((word >> BIT_LOCK_KEYPAD) & 1))
            dev_f = bool((word >> BIT_TEMP_UNIT_FAHRENHEIT) & 1)
            self.var_fahr.set(dev_f)
            self.set_sp_frame_units(dev_f)
            if BIT_NETWORK_SETPOINTS is not None:
                self.var_net.set(bool((word >> BIT_NETWORK_SETPOINTS) & 1))
            messagebox.showinfo("Flags", f"RegFlags = 0x{word:04X}")
        except Exception as e:
            messagebox.showerror("Read error", str(e))

    def write_flags(self):
        if not self.controller:
            messagebox.showwarning("Not connected", "Connect first.")
            return
        try:
            self.controller._write_flags_clean(
                invert=self.var_invert.get(),
                lock=self.var_lock.get(),
                fahr=self.var_fahr.get(),
                net_on=(self.var_net.get() if BIT_NETWORK_SETPOINTS is not None else None),
            )
            self.sync_units()
            messagebox.showinfo("Success", "Flags written.")
        except Exception as e:
            messagebox.showerror("Write error", str(e))

if __name__ == "__main__":
    App().mainloop()
