import logging

import pytest
from airbyte_cdk.models import ConfiguredAirbyteCatalog, ConfiguredAirbyteStream, SyncMode

from source_sapreadtable.source import SourceRfcReadTable


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test-source")


def test_convert_row_to_stream_with_aedat(logger: logging.Logger) -> None:
    source = SourceRfcReadTable()
    source._create_json_schema_for_table = (  # type: ignore[method-assign]
        lambda table_name, con: {"type": "object", "properties": {"AEDAT": {"type": "string"}}}
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
        lambda table_name, con: {"type": "object", "properties": {"BUKRS": {"type": "string"}}}
    )

    row = ("BKPF", "Accounting Documents", "T")
    stream = source._convert_row_to_stream(row, logger, {}, None)

    assert stream.supported_sync_modes == [SyncMode.full_refresh, SyncMode.incremental]
    assert stream.source_defined_cursor is False
    assert stream.default_cursor_field == []


def test_read_handles_none_state(logger: logging.Logger) -> None:
    source = SourceRfcReadTable()
    source._create_connection_with_erpl = lambda logger, config: None  # type: ignore[method-assign]
    source._read_stream = lambda *args, **kwargs: iter([])  # type: ignore[method-assign]

    empty_catalog = ConfiguredAirbyteCatalog(streams=[])
    messages = list(source.read(logger, {}, empty_catalog, None))

    assert messages == []
