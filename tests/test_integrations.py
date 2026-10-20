from pathlib import Path

from app.integrations.com0com import Com0ComManager
from app.integrations.gs232 import GS232Parser
from app.integrations.hamlib import parse_hamlib_command
from app.integrations.n1mm import parse_n1mm_datagram


def test_n1mm_parser_ignores_bad_xml_and_accepts_angle():
    assert parse_n1mm_datagram("<N1MMRotor><goazi>123</goazi></N1MMRotor>") == 123
    assert parse_n1mm_datagram("broken") is None
    assert parse_n1mm_datagram("<N1MMRotor><goazi>999</goazi></N1MMRotor>") is None


def test_hamlib_commands():
    events = []
    response = parse_hamlib_command("P 45 10", get_azimuth=lambda: 0, set_azimuth=events.append, stop=lambda: events.append("stop"))
    assert response == "RPRT 0\n"
    assert events == [45]
    assert parse_hamlib_command("S", get_azimuth=lambda: 0, set_azimuth=events.append, stop=lambda: events.append("stop")) == "RPRT 0\n"
    assert events[-1] == "stop"


def test_gs232_commands():
    values = []
    parser = GS232Parser(lambda: 12, values.append, lambda: values.append("stop"))
    assert parser.handle("C") == "012\r\n"
    assert parser.handle("C2") == "012 000\r\n"
    assert parser.handle("M123") == "\r\n"
    assert values == [123]
    assert parser.handle("S") == "\r\n"
    assert values[-1] == "stop"


def test_com0com_explicit_path_and_custom_pair(monkeypatch, tmp_path):
    setupc = tmp_path / "setupc.exe"
    setupc.write_text("stub", encoding="ascii")
    setupc.chmod(0o755)
    fallback = tmp_path / "fallback.exe"
    fallback.write_text("fallback", encoding="ascii")
    fallback.chmod(0o755)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return "completed"

    monkeypatch.setattr("app.integrations.com0com.subprocess.run", fake_run)
    manager = Com0ComManager(
        setupc_path=setupc,
        which=lambda _name: str(fallback),
        env={},
    )
    assert manager.find_setupc() == Path(setupc)
    assert manager.status().can_create
    assert manager.create_pair("VCOM_A", "VCOM_B") == "completed"
    assert calls[0][0] == [str(setupc), "install", "PortName=VCOM_A", "PortName=VCOM_B"]

