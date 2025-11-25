# Incremental Sync Implementation

## 1. Purpose

This document outlines the implementation of the "Incremental | Append" sync functionality for the `source-sapreadtable` connector. The purpose of this feature is to allow users to sync only the new or updated records from SAP since the last sync, reducing the amount of data transferred and the time it takes to sync.

## 2. Implementation Details

The incremental sync functionality was implemented by modifying the `source-sapreadtable/source_sapreadtable/source.py` file. The key changes are:

### 2.1. Advertising Incremental Support (Flexible Cursor Field Selection)

The `_convert_row_to_stream` method was updated to advertise that streams support incremental syncs. This is now done with a more flexible approach for `source_defined_cursor` and `default_cursor_field`:

```python
        supported_modes = ["full_refresh", "incremental"]
        source_defined_cursor = False
        default_cursor = []

        if "AEDAT" in json_schema.get("properties", {}):
            source_defined_cursor = True
            default_cursor = ["AEDAT"]
            logger.debug(f"Stream {technical_name} has AEDAT, suggesting it as default cursor field.")
        else:
            logger.debug(f"Stream {technical_name} does not have AEDAT. User can manually select a cursor field.")

        return AirbyteStream(
            name=technical_name,
            text=text,
            table_type=table_type,
            json_schema=json_schema,
            supported_sync_modes=supported_modes,
            source_defined_cursor=source_defined_cursor,
            default_cursor_field=default_cursor,
        )
```

This ensures that:
*   Incremental sync is always advertised as a supported mode for all streams.
*   If the `AEDAT` field is present in a stream's schema, it will be suggested as the `default_cursor_field`.
*   If `AEDAT` is not present, `source_defined_cursor` will be `False` and no default cursor will be provided. In this case, the user will be able to manually select any other suitable cursor field from the stream's schema directly within the Airbyte UI, enhancing flexibility.


### 2.2. Handling State and Cursor in `read`

The `read` method was updated to handle the sync mode and pass the state and cursor information to the `_read_stream` method.

```python
    def read(
        self, logger: logging.Logger, config: json, catalog: ConfiguredAirbyteCatalog, state: dict[str, any]
    ) -> Generator[AirbyteMessage, None, None]:
        # ...
        for configured_stream in catalog.streams:
            stream = configured_stream.stream
            sync_mode = configured_stream.sync_mode
            cursor_field = configured_stream.cursor_field

            # Get the stream state
            stream_state = state.get(stream.name, {})

            for message in self._read_stream(logger, config, stream, con, stream_state, sync_mode, cursor_field):
                yield message
```

### 2.3. Incremental Logic in `_read_stream`

The `_read_stream` method was modified to include the core logic for incremental syncs. It now:
1.  Checks the `sync_mode`.
2.  If the sync mode is `incremental`, it modifies the SQL query to filter data based on the `cursor_field` and the last saved state.
3.  Tracks the maximum value of the cursor field seen during the sync.
4.  Emits a new `AirbyteMessage` of type `STATE` with the updated maximum cursor value at the end of the sync.

```python
    def _read_stream(
        self,
        logger: logging.Logger,
        config: json,
        stream: AirbyteStream,
        con: duckdb.DuckDBPyConnection,
        state: dict[str, any],
        sync_mode: str,
        cursor_field: list[str],
    ) -> Generator[AirbyteMessage, None, None]:
        # ...
        query = f"SELECT * FROM sap_read_table('{stream.name}')"

        if sync_mode == "incremental" and cursor_field and state.get(cursor_field[0]):
            last_state_value = state[cursor_field[0]]
            query += f" WHERE {cursor_field[0]} >= '{last_state_value}'"
            logger.info(f"Reading incrementally for {stream.name} with state: {state}")
        # ...
        if sync_mode == "incremental" and max_cursor_value is not None:
            new_state = {cursor_field[0]: max_cursor_value}
            yield AirbyteMessage(
                type=Type.STATE,
                state={"data": new_state},
            )
```

## 3. How to Use

To use the incremental sync feature:
1.  When setting up the connection in the Airbyte UI, select the "Incremental | Append" sync mode for the desired streams.
2.  Choose a cursor field from the available options. The connector suggests a default (`AEDAT`), but you can select any other suitable field from the stream's schema.
3.  The first sync for an incremental stream will behave like a full refresh. Subsequent syncs will only read new or updated records based on the cursor field.
