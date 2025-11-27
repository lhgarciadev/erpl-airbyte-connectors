#
# Copyright (c) 2024 DataZoo GmbH, all rights reserved.
#


import json
import logging
import time
from collections.abc import Generator, Mapping
from typing import Any

import duckdb
from airbyte_cdk.models import (
    AirbyteCatalog,
    AirbyteConnectionStatus,
    AirbyteMessage,
    AirbyteRecordMessage,
    AirbyteStateMessage,
    AirbyteStream,
    ConfiguredAirbyteCatalog,
    Status,
    SyncMode,
    Type,
)
from airbyte_cdk.sources import Source


class SourceRfcReadTable(Source):
    def check(self, logger: logging.Logger, config: json) -> AirbyteConnectionStatus:
        """
        :param config:  the user-input config object conforming to the connector's spec.yaml
        :param logger:  logger object
        :return AirbyteConnectionStatus: the connection status object. It succeeds when the ping works, fails otherwise.
        """
        con = self._create_connection_with_erpl(logger, config)
        try:
            con.sql("PRAGMA sap_rfc_ping")
            return AirbyteConnectionStatus(status=Status.SUCCEEDED, message="ERPL connection test succeeded")
        except Exception as e:
            message = str(e)
            return AirbyteConnectionStatus(status=Status.FAILED, message=f"ERPL connection test failed: {message}")

    def discover(self, logger: logging.Logger, config: json) -> AirbyteCatalog:
        """
        :param config: A Mapping of the user input configuration as defined in the connector spec.
        :param logger:  logger object
        """
        selection = config["table_selection"]
        logger.info("ERPL Source Stream Discovery - selection: %s", selection)

        # Create a connection with ERPL extension loaded
        con = self._create_connection_with_erpl(logger, config)
        res = con.sql(f"SELECT * FROM sap_show_tables(TABLENAME='{selection}') ORDER BY 1")

        streams = []
        while batch := res.fetchmany():
            for row in batch:
                stream = self._convert_row_to_stream(row, logger, config, con)
                streams.append(stream)

        return AirbyteCatalog(streams=streams)

    def _convert_row_to_stream(
        self, row: Mapping[str, Any], logger: logging.Logger, _config: json, con: duckdb.DuckDBPyConnection
    ) -> AirbyteStream:
        """
        Convert a row from the result of sap_show_tables into an AirbyteStream object.
        :param row: A row from the result of sap_show_tables
        :param logger: The logger object
        :param con: The connection to ERPL
        :return: An AirbyteStream object
        """
        technical_name = row[0]
        _text = row[1]
        _table_type = row[2]

        logger.debug("ERPL Source Stream Discovery - stream is: %s", technical_name)
        json_schema = self._create_json_schema_for_table(technical_name, con)

        supported_modes = [SyncMode.full_refresh, SyncMode.incremental]
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
            json_schema=json_schema,
            supported_sync_modes=supported_modes,
            source_defined_cursor=source_defined_cursor,
            default_cursor_field=default_cursor,
        )

    def _create_json_schema_for_table(self, table_name: str, con: duckdb.DuckDBPyConnection) -> Mapping[str, Any]:
        """
        Create a JSON schema for a table.
        :param table_name: The name of the table
        :param con: The connection to ERPL
        :return: A JSON schema for the table
        """
        schema = con.sql(f"SELECT * FROM sap_describe_fields('{table_name}') ORDER BY 1").fetchall()
        properties = {}
        for row in schema:
            field_name = row[2]
            field_text = row[3]
            field_type = row[4]
            field_length = int(row[5])
            field_decimals = int(row[6])

            properties[field_name] = {
                "type": self._convert_erpl_field_type_to_json_schema_type(field_type),
                "length": field_length,
                "decimals": field_decimals,
                "description": field_text,
            }

        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "properties": properties,
        }

    def _convert_erpl_field_type_to_json_schema_type(self, erpl_field_type: str) -> str:
        """
        Convert an ERPL field type to a JSON schema type.
        :param erpl_field_type: The ERPL field type
        :return: The JSON schema type
        """
        type_map = {
            "ACCP": "number",
            "CHAR": "string",
            "CLNT": "string",
            "CURR": "number",
            "CUKY": "string",
            "DATS": "string",
            "DEC": "number",
            "FLTP": "number",
            "INT1": "integer",
            "INT2": "integer",
            "INT4": "integer",
            "LANG": "string",
            "LCHR": "string",
            "LRAW": "string",
            "NUMC": "string",
            "PREC": "integer",
            "QUAN": "number",
            "RAW": "string",
            "RAWSTRING": "string",
            "RSTR": "string",
            "STRING": "string",
            "STRG": "string",
            "SSTR": "string",
            "TIMS": "string",
            "UNIT": "string",
        }

        if erpl_field_type in type_map:
            return type_map[erpl_field_type]
        raise ValueError(f"Unsupported ERPL field type: {erpl_field_type}")

    def read(
        self,
        logger: logging.Logger,
        config: json,
        catalog: ConfiguredAirbyteCatalog,
        state: dict[str, Any] | None = None,
    ) -> Generator[AirbyteMessage, None, None]:
        """
        :param config: A Mapping of the user input configuration as defined in the connector spec.
        :param catalog: The configured catalog.
        :param state: The user provided state.
        :param logger:  logger object
        """
        con = self._create_connection_with_erpl(logger, config)
        safe_state: dict[str, Any] = state or {}

        logger.debug("Starting ERPL Source read for all streams ...")
        for configured_stream in catalog.streams:
            stream = configured_stream.stream
            sync_mode = configured_stream.sync_mode
            cursor_field = configured_stream.cursor_field

            # Get the stream state
            stream_state = safe_state.get(stream.name, {})

            yield from self._read_stream(logger, config, stream, con, stream_state, sync_mode, cursor_field)

    def _read_stream(
        self,
        logger: logging.Logger,
        _config: json,
        stream: AirbyteStream,
        con: duckdb.DuckDBPyConnection,
        state: dict[str, Any],
        sync_mode: SyncMode | str,
        cursor_field: list[str],
    ) -> Generator[AirbyteMessage, None, None]:
        """
        Read a stream from ERPL.
        :param logger: The logger object
        :param config: The user input configuration
        :param stream: The stream to read
        :param con: The connection to ERPL
        :param state: The user provided state
        :return: A generator of AirbyteMessages
        """
        state = state or {}
        sync_mode_value = sync_mode.value if isinstance(sync_mode, SyncMode) else sync_mode

        logger.debug(
            "Starting ERPL Source read for stream: %s, sync_mode: %s, cursor_field: %s",
            stream.name,
            sync_mode_value,
            cursor_field,
        )

        # Build the Pushdown Filter for SAP OpenSQL
        # This prevents "Conversion Error" and "SAPSQL_DATA_LOSS" by filtering at the source
        filter_option = ""
        if sync_mode_value == "incremental" and cursor_field:
            cursor_name = cursor_field[0]
            # state is the inner state for this stream, e.g. {"AEDAT": "20240101"}
            last_state_value = state.get(cursor_name)

            if last_state_value:
                # Sanitize the value for SQL literal inclusion
                safe_value = str(last_state_value).replace("'", "''")
                
                # OpenSQL Syntax: FIELD GE 'VALUE'
                # DuckDB requires doubled single quotes for literals inside the string
                filter_option = f", FILTER='{cursor_name} GE ''{safe_value}'''"
                
                logger.info(f"Reading incrementally for {stream.name} with filter: {filter_option}")

        query = f"SELECT * FROM sap_read_table('{stream.name}'{filter_option})"
        res = con.sql(query)

        max_cursor_value = None

        while batch := res.fetchmany():
            for row in batch:
                msg = self._convert_row_to_message(res.columns, row, stream)

                if sync_mode_value == "incremental" and cursor_field:
                    cursor_value = msg.record.data.get(cursor_field[0])
                    if cursor_value and (max_cursor_value is None or cursor_value > max_cursor_value):
                        max_cursor_value = cursor_value

                yield msg

        if sync_mode_value == "incremental" and max_cursor_value is not None:
            # Update state structure to be nested under stream name
            # This ensures the 'read' method can correctly retrieve it in subsequent runs
            new_stream_state = {cursor_field[0]: max_cursor_value}
            new_global_state = {stream.name: new_stream_state}
            
            yield AirbyteMessage(
                type=Type.STATE,
                state=AirbyteStateMessage(data=new_global_state),
            )

    def _convert_row_to_message(self, columns: list[str], row: list[Any], stream: AirbyteStream) -> AirbyteMessage:
        """
        Convert a row from ERPL to an AirbyteMessage.
        :param row: The row to convert
        :param stream: The stream to which the row belongs
        :return: An AirbyteMessage
        """
        data = dict(zip(columns, row, strict=False))
        return AirbyteMessage(
            type=Type.RECORD, record=AirbyteRecordMessage(stream=stream.name, data=data, emitted_at=int(time.time()))
        )

    def _create_connection_with_erpl(self, logger: logging.Logger, config: json) -> duckdb.DuckDBPyConnection:
        """
        Create a connection with ERPL extension loaded.
        :param logger: The logger object
        :param config: The user input configuration
        :return: A connection with ERPL extension loaded
        """
        logger.info("Creating DuckDB connection with ERPL extension loaded ...")

        custom_extension_repository = config["custom_extension_repository"]
        sap_ashost = config["sap_ashost"]
        sap_sysnr = config["sap_sysnr"]
        sap_user = config["sap_user"]
        sap_password = config["sap_password"]
        sap_client = config["sap_client"]
        sap_lang = config["sap_lang"]

        safe_config = {
            "custom_extension_repository": custom_extension_repository,
            "sap_ashost": sap_ashost,
            "sap_sysnr": sap_sysnr,
            "sap_user": self._mask_secret(sap_user),
            "sap_password": self._mask_secret(sap_password),
            "sap_client": sap_client,
            "sap_lang": sap_lang,
        }
        logger.debug("ERPL connection parameters (sanitized): %s", safe_config)

        # Create a connection with ERPL extension loaded
        con = duckdb.connect(config={"allow_unsigned_extensions": "true"})
        con.sql(f"SET custom_extension_repository = '{custom_extension_repository}';")
        con.install_extension(config["extension_name"])
        con.load_extension(config["extension_name"])

        # Set ERPL connection parameters
        con.sql(f"""
            SET sap_ashost = '{sap_ashost}';
            SET sap_sysnr = '{sap_sysnr}';
            SET sap_user = '{sap_user}';
            SET sap_password = '{sap_password}';
            SET sap_client = '{sap_client}';
            SET sap_lang = '{sap_lang}';
        """)

        return con

    @staticmethod
    def _mask_secret(secret: str) -> str:
        """Return a masked representation of a secret to avoid leaking credentials in logs."""
        if not secret:
            return ""
        if len(secret) <= 4:
            return "*" * len(secret)
        return f"{secret[0]}***{secret[-1]}"