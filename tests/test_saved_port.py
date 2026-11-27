from pathlib import Path

import pytest


@pytest.fixture
def saved_port(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "skills/rig-remote-ops/scripts"))
    from setup_connection import reinstall_port
    return reinstall_port


def test_reinstall_keeps_nondefault_port(saved_port):
    record = dict(host="100.64.0.42", port=8123, tier=1, hostname="RIG")
    assert saved_port(record, record["host"], "rig") == 8123


@pytest.mark.parametrize("changed", [{"host": "100.64.0.99"}, {"hostname": "OTHER"}, {"tier": 3}, {"port": 0}])
def test_reinstall_rejects_incompatible_record(saved_port, changed):
    record = dict(host="100.64.0.42", port=8123, tier=1, hostname="RIG")
    record.update(changed)
    with pytest.raises(ValueError):
        saved_port(record, "100.64.0.42", "RIG")
