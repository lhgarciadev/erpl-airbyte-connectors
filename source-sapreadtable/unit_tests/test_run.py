import pytest

import source_sapreadtable.run as run_module


def test_run_invokes_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def fake_launch(source: object, argv: list[str]) -> None:
        calls["source"] = source
        calls["argv"] = argv

    monkeypatch.setattr(run_module, "launch", fake_launch)
    monkeypatch.setattr(run_module, "SourceRfcReadTable", lambda: "SOURCE")
    monkeypatch.setattr(run_module.sys, "argv", ["prog", "--option", "value"])

    run_module.run()

    assert calls["source"] == "SOURCE"
    assert calls["argv"] == ["--option", "value"]
