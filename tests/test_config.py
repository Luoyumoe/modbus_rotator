from pathlib import Path

import json

from app.config import ConfigStore, RotatorConfig, get_config_path, load_config, save_config


def test_config_path_uses_localappdata(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\tester\AppData\Local")
    assert get_config_path() == Path(r"C:\Users\tester\AppData\Local") / "ModbusRotator" / "rotator_config.json"


def test_config_round_trip_and_atomic_parent(tmp_path):
    path = tmp_path / "nested" / "rotator_config.json"
    config = RotatorConfig(
        serial_port="COM10",
        true_azimuth_deg=123.5,
        com0com_setupc_path=r"C:\Tools\com0com\setupc.exe",
        com0com_left_port="VCOM_A",
        com0com_right_port="VCOM_B",
    )
    save_config(config, path)
    loaded = load_config(path)
    assert loaded.serial_port == "COM10"
    assert loaded.true_azimuth_deg == 123.5
    assert loaded.com0com_setupc_path.endswith(r"com0com\setupc.exe")
    assert loaded.com0com_left_port == "VCOM_A"
    assert loaded.com0com_right_port == "VCOM_B"
    assert not list(path.parent.glob("*.tmp"))


def test_store_delays_then_flushes(tmp_path):
    path = tmp_path / "config.json"
    store = ConfigStore(path=path)
    store.update(serial_port="COM11")
    store.flush()
    assert load_config(path).serial_port == "COM11"
    store.close()


def test_legacy_flat_schema_migrates(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"serial_port": "COM7", "smoothing_f08": 5, "n1mm_port": 12041}), encoding="utf-8")
    loaded = load_config(path)
    assert loaded.schema_version == 2
    assert loaded.serial_port == "COM7"
    assert loaded.registers.smoothing_f08 == 5
    assert loaded.network.n1mm_port == 12041


def test_missing_localappdata_uses_user_config_path(monkeypatch, tmp_path):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert get_config_path() == tmp_path / "ModbusRotator" / "rotator_config.json"

