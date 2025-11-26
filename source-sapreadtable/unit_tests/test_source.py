import logging

import pytest
from airbyte_cdk.models import AirbyteStream, ConfiguredAirbyteCatalog, Status, SyncMode

from source_sapreadtable.source import SourceRfcReadTable


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test-source")


def test_convert_row_to_stream_with_aedat(logger: logging.Logger) -> None:
    source = SourceRfcReadTable()
    source._create_json_schema_for_table = (  # type: ignore[method-assign]
        lambda _table_name, _con: {"type": "object", "properties": {"AEDAT": {"type": "string"}}}
    )

    row = ("DFKKOP", "Test table", "T")
    stream = source._convert_row_to_stream(row, logger, {}, None)

    assert stream.name == "DFKKOP"
    assert stream.supported_sync_modes == [SyncMode.full_refresh, SyncMode.incremental]
    assert stream.source_defined_cursor is True
    assert stream.default_cursor_field == ["AEDAT"]


def test_convert_row_to_stream_without_aedat(logger: logging.Logger) -> None:
    source = SourceRfcReadTable()
    source._create_json_schema_for_table = (  # type: ignore[method-assign]
        lambda _table_name, _con: {"type": "object", "properties": {"BUKRS": {"type": "string"}}}
    )

    row = ("BKPF", "Accounting Documents", "T")
    stream = source._convert_row_to_stream(row, logger, {}, None)

    assert stream.supported_sync_modes == [SyncMode.full_refresh, SyncMode.incremental]
    assert stream.source_defined_cursor is False
    assert stream.default_cursor_field == []


def test_read_handles_none_state(logger: logging.Logger) -> None:
    source = SourceRfcReadTable()
    source._create_connection_with_erpl = lambda _logger, _config: None  # type: ignore[method-assign]
    source._read_stream = lambda *_args, **_kwargs: iter([])  # type: ignore[method-assign]

    empty_catalog = ConfiguredAirbyteCatalog(streams=[])
    messages = list(source.read(logger, {}, empty_catalog, None))

    assert messages == []


def test_check_success(monkeypatch: pytest.MonkeyPatch, logger: logging.Logger) -> None:
    source = SourceRfcReadTable()

    class DummyConnection:
        def sql(self, query: str):
            assert query == "PRAGMA sap_rfc_ping"

    monkeypatch.setattr(source, "_create_connection_with_erpl", lambda *_: DummyConnection())

    status = source.check(logger, {})

    assert status.status == Status.SUCCEEDED
    assert "succeeded" in status.message.lower()


def test_check_failure(monkeypatch: pytest.MonkeyPatch, logger: logging.Logger) -> None:
    source = SourceRfcReadTable()

    class DummyConnection:
        def sql(self, _query: str):
            raise RuntimeError("boom")

    monkeypatch.setattr(source, "_create_connection_with_erpl", lambda *_: DummyConnection())

    status = source.check(logger, {})

    assert status.status == Status.FAILED
    assert "boom" in status.message


def test_discover_builds_streams(monkeypatch: pytest.MonkeyPatch, logger: logging.Logger) -> None:
    source = SourceRfcReadTable()

    class DummyResult:
        def __init__(self) -> None:
            self.calls = 0

        def fetchmany(self):
            if self.calls == 0:
                self.calls += 1
                return [
                    ("DFKKOP", "Contract Accounting", "T"),
                    ("BKPF", "Docs", "T"),
                ]
            return []

    class DummyConnection:
        def sql(self, query: str) -> DummyResult:
            if "sap_show_tables" in query:
                return DummyResult()
            return DummyResult()

    def fake_schema(table_name: str, _con: object) -> dict[str, object]:
        if table_name == "DFKKOP":
            return {"type": "object", "properties": {"AEDAT": {"type": "string"}}}
        return {"type": "object", "properties": {"BUKRS": {"type": "string"}}}

    monkeypatch.setattr(source, "_create_connection_with_erpl", lambda *_: DummyConnection())
    monkeypatch.setattr(source, "_create_json_schema_for_table", fake_schema)

    catalog = source.discover(logger, {"table_selection": "DFKKOP"})

    stream_names = [stream.name for stream in catalog.streams]
    assert stream_names == ["DFKKOP", "BKPF"]
    assert catalog.streams[0].source_defined_cursor is True
    assert catalog.streams[0].default_cursor_field == ["AEDAT"]
    assert catalog.streams[1].source_defined_cursor is False


def test_read_stream_emits_state(logger: logging.Logger) -> None:
    source = SourceRfcReadTable()

    class DummyResult:
        def __init__(self) -> None:
            self.columns = ["AEDAT", "VALUE"]
            self.calls = 0

        def fetchmany(self):
            if self.calls == 0:
                self.calls += 1
                return [["2024-01-01", "a"], ["2024-02-01", "b"]]
            return []

    class DummyConnection:
        def sql(self, query: str) -> DummyResult:
            assert "sap_read_table('BKPF')" in query
            assert "AEDAT >= '2023-12-31'" in query
            return DummyResult()

    stream = AirbyteStream(name="BKPF", json_schema={}, supported_sync_modes=[SyncMode.incremental])

    messages = list(
        source._read_stream(  # type: ignore[protected-access]
            logger,
            {},
            stream,
            DummyConnection(),
            {"AEDAT": "2023-12-31"},
            SyncMode.incremental,
            ["AEDAT"],
        )
    )

    assert messages[-1].type.value == "STATE"
    assert messages[-1].state.data == {"AEDAT": "2024-02-01"}


def test_connection_logging_sanitizes_credentials(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    source = SourceRfcReadTable()

    class DummyConnection:
        def __init__(self) -> None:
            self.sql_calls: list[str] = []

        def sql(self, query: str) -> None:
            self.sql_calls.append(query)

        def install_extension(self, _name: str) -> None:  # pragma: no cover - simple passthrough
            return None

        def load_extension(self, _name: str) -> None:  # pragma: no cover - simple passthrough
            return None

    monkeypatch.setattr("source_sapreadtable.source.duckdb.connect", lambda **_kwargs: DummyConnection())

    config = {
        "custom_extension_repository": "https://example.com",
        "extension_name": "erpl",
        "sap_ashost": "ashost",
        "sap_sysnr": "00",
        "sap_user": "user123",
        "sap_password": "secret123",
        "sap_client": "100",
        "sap_lang": "EN",
    }

    with caplog.at_level(logging.DEBUG):
        source._create_connection_with_erpl(logging.getLogger("test"), config)

    log_messages = " ".join(caplog.messages)
    assert "secret123" not in log_messages
    assert "user123" not in log_messages
