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

