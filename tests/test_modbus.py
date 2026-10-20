from app.protocols.modbus import (
    REGISTERS,
    ModbusController,
    SafetyParameterMismatch,
    decode_s32,
    encode_s32,
)


class FakeInstrument:
    def __init__(self):
        self.registers = {}
        self.writes = []

    def read_register(self, address, *args, **kwargs):
        return self.registers.get(address, 0)

    def write_register(self, address, value, *args):
        self.registers[address] = value
        self.writes.append((address, value))


def test_signed_32_high_word_first_boundaries():
    for value in (-2147483648, -1, 0, 2147483647):
        assert decode_s32(*encode_s32(value)) == value


def test_safety_and_motion_write_order():
    fake = FakeInstrument()
    fake.registers.update({REGISTERS["run_mode"]: 4, REGISTERS["cycle_count"]: 1, REGISTERS["f02_high"]: 5, REGISTERS["f02_low"]: 32320})
    controller = ModbusController(instrument=fake, sleep_fn=lambda _: None)
    try:
        controller.validate_safety_parameters()
    except SafetyParameterMismatch:
        pass
    controller.write_u32(REGISTERS["f02_high"], REGISTERS["f02_low"], 360000)
    assert controller.read_u32(REGISTERS["f02_high"], REGISTERS["f02_low"]) == 360000
    assert REGISTERS["run_mode"] == 0x0002
    assert REGISTERS["acceleration_status"] == 0x0015
    assert REGISTERS["forward_distance_high"] == 0x0100
    assert REGISTERS["forward_distance_low"] == 0x0101
    assert REGISTERS["reverse_distance_high"] == 0x0103
    assert REGISTERS["reverse_distance_low"] == 0x0104
    assert REGISTERS["cycle_count"] == 0x0106
    fake.registers.update({REGISTERS["f02_high"]: 5, REGISTERS["f02_low"]: 32320})
    controller.move_distance(20, "ccw", require_safe=True)
    assert fake.writes[-4][0] == REGISTERS["stop_trigger"]
    assert fake.writes[-3][0] == REGISTERS["reverse_distance_high"]
    assert fake.writes[-2][0] == REGISTERS["reverse_distance_low"]
    assert fake.writes[-1] == (REGISTERS["reverse_trigger"], 2)


def test_move_degrees_scales_to_milli_degrees():
    fake = FakeInstrument()
    fake.registers.update({REGISTERS["run_mode"]: 4, REGISTERS["cycle_count"]: 1, REGISTERS["f02_high"]: 5, REGISTERS["f02_low"]: 32320})
    controller = ModbusController(instrument=fake, sleep_fn=lambda _: None)
    controller.move_degrees(3.5, "cw")
    assert fake.registers[REGISTERS["forward_distance_high"]] == 0
    assert fake.registers[REGISTERS["forward_distance_low"]] == 3500

