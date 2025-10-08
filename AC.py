import asyncio
import csv
from datetime import datetime

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Input
from textual.containers import Container

from pymodbus.client import AsyncModbusSerialClient
from pymodbus.exceptions import ModbusException
from pymodbus.framer import FramerType


# Register map (all holding registers)
REGISTERS = [
    {"name": "SET_NETWORK_COOLING_SETPOINT", "address": 0, "signed": True},
    {"name": "SET_NETWORK_HIGH_TEMP_ALARM_SETPOINT", "address": 1, "signed": True},
    {"name": "SET_NETWORK_LOW_TEMP_ALARM_SETPOINT", "address": 2, "signed": True},
    {"name": "SET_NETWORK_HEATER_SETPOINT", "address": 3, "signed": True},
    {"name": "SET_ENABLE_FLAGS", "address": 4, "signed": False},
    {"name": "READ_CONTROL_SETPOINT", "address": 5, "signed": True},
    {"name": "READ_HIGH_TEMP_SETPOINT", "address": 6, "signed": True},
    {"name": "READ_LOW_TEMP_SETPOINT", "address": 7, "signed": True},
    {"name": "READ_HEATER_SETPOINT", "address": 8, "signed": True},
    {"name": "READ_CONTROL_SENSOR", "address": 12, "signed": True},
    {"name": "READ_ALARM_STATUS", "address": 14, "signed": False},
    {"name": "READ_OUTPUT_STATUS", "address": 15, "signed": False},
    {"name": "READ_CONTACT_STATUS", "address": 16, "signed": False},
]

# Central dictionary for quick lookup of addresses and sign info
REGISTER_MAP = {reg["name"]: {"address": reg["address"], "signed": reg["signed"]} 
                for reg in REGISTERS}


async def read_register(client, reg, slave_id: int):
    """Read a single holding register with signed/unsigned handling."""
    try:
        rr = await client.read_holding_registers(reg["address"], count=1, unit=slave_id)
        if rr.isError():
            return f"ERROR {rr}"

        value = rr.registers[0]
        if reg.get("signed", False) and value >= 0x8000:
            value -= 0x10000
        return str(value)
    except ModbusException as e:
        return f"EXC {e}"


async def set_cooling_setpoint(client, value: int, slave_id: int = 1):
    """Write a signed 16-bit cooling setpoint to register 0"""
    if value < -32768 or value > 32767:
        return "Invalid range"

    rq = await client.write_register(0, value & 0xFFFF, unit=slave_id)
    if rq.isError():
        return f"Write error: {rq}"
    else:
        return f"Cooling setpoint written: {value}"


class ModbusApp(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    #main {
        height: 1fr;
    }
    Input {
        dock: bottom;
    }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, client, slave_id=1, interval=15, **kwargs):
        super().__init__(**kwargs)
        self.client = client
        self.slave_id = slave_id
        self.interval = interval
        self.table = None
        self.csv_file = open("modbus_log.csv", "a", newline="")
        self.csv_writer = csv.writer(self.csv_file)

        # If file is empty, write header
        if self.csv_file.tell() == 0:
            header = ["timestamp"] + [reg["name"] for reg in REGISTERS]
            self.csv_writer.writerow(header)

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="main"):
            yield DataTable()
            yield Input(placeholder="Enter new cooling setpoint and press Enter")
        yield Footer()

    async def on_mount(self) -> None:
        # Setup table
        self.table = self.query_one(DataTable)
        self.table.add_columns("Register", "Address", "Value")

        # Pre-populate rows with explicit keys
        for reg in REGISTERS:
            self.table.add_row(reg["name"], str(reg["address"]), "-", key=reg["name"])

        # Poll every interval seconds
        self.set_interval(self.interval, self.poll_registers)

    async def poll_registers(self) -> None:
        values = []
        for idx, reg in enumerate(REGISTERS):
            val = await read_register(self.client, reg, self.slave_id)
            self.table.update_cell_at((idx, 2), val)
            values.append(val)

        # Write to CSV
        row = [datetime.now().isoformat()] + values
        self.csv_writer.writerow(row)
        self.csv_file.flush()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user entering a new cooling setpoint"""
        try:
            value = int(event.value.strip())
            msg = await set_cooling_setpoint(self.client, value, self.slave_id)
            self.notify(msg, severity="information")
        except ValueError:
            self.notify("Invalid number", severity="error")
        event.input.value = ""

    async def on_unmount(self) -> None:
        self.csv_file.close()


async def run():
    client = AsyncModbusSerialClient(
        framer=FramerType.RTU,
        port="COM5",  # <-- change to your serial port
        baudrate=19200,
        stopbits=1,
        bytesize=8,
        parity="E",
        timeout=2,
    )

    await client.connect()
    if not client.connected:
        print("Could not connect to device")
        return

    try:
        app = ModbusApp(client, slave_id=1, interval=2)
        await app.run_async()
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(run())
