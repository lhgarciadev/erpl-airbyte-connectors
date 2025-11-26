"""Standalone SAP Read Table exporter using ERPL + DuckDB.

This script mirrors the connector logic without Airbyte: it installs the ERPL
extension, connects to SAP via RFC, reads a table, and writes the result to a
CSV with column headers.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

import duckdb

DEFAULT_CONFIG_PATH = "secrets/config.json"
DEFAULT_EXTENSION_DIR = "./.duckdb/extensions"
DEFAULT_LIMIT = 100
DEFAULT_OUTPUT = "sap_export.csv"


def _escape(value: str) -> str:
    """Escape single quotes for safe use in SQL string literals."""
    return value.replace("'", "''")


@dataclass
class SapConnectionConfig:
    """SAP connection configuration loaded from JSON."""

    custom_extension_repository: str
    extension_name: str
    sap_ashost: str
    sap_sysnr: str
    sap_user: str
    sap_password: str
    sap_client: str
    sap_lang: str = "EN"
    table_selection: str = ""
    sap_router: str | None = None


class ConfigLoader:
    """Loads SAP connection configuration from disk."""

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH) -> None:
        self._config_path = config_path

    def load(self) -> SapConnectionConfig:
        """Load and parse the JSON configuration file."""
        if not os.path.exists(self._config_path):
            raise FileNotFoundError(
                f"Configuration file not found at '{self._config_path}'. "
                "Please create it based on the README/spec.yaml."
            )
        with open(self._config_path, "r", encoding="utf-8") as handle:
            raw_config = json.load(handle)
        return SapConnectionConfig(**raw_config)


class DuckDBConnector:
    """Creates DuckDB connections with the required ERPL settings."""

    def __init__(
        self,
        extension_dir: str = DEFAULT_EXTENSION_DIR,
        connect_func: Callable[..., duckdb.DuckDBPyConnection] = duckdb.connect,
    ) -> None:
        self._extension_dir = extension_dir
        self._connect_func = connect_func

    def connect(self, config: SapConnectionConfig) -> duckdb.DuckDBPyConnection:
        """Create a DuckDB connection with unsigned extensions enabled."""
        db_config = {
            "allow_unsigned_extensions": "true",
            "extension_directory": self._extension_dir,
            "custom_extension_repository": config.custom_extension_repository,
        }
        return self._connect_func(database=":memory:", read_only=False, config=db_config)


class SapReadTableExporter:
    """Coordinates installing ERPL, configuring SAP, and exporting data."""

    def __init__(
        self,
        connector: DuckDBConnector,
        logger: logging.Logger,
    ) -> None:
        self._connector = connector
        self._logger = logger

    def export(
        self,
        config: SapConnectionConfig,
        table_name: str,
        limit: int,
        output_csv: str,
    ) -> None:
        """Run the export pipeline end-to-end."""
        con = self._connector.connect(config)
        try:
            self._install_extension(con, config.extension_name, config.custom_extension_repository)
            self._configure_sap(con, config)
            dats_columns = self._detect_dats_columns(con, table_name)
            query = self._build_query(table_name, limit, dats_columns)
            self._logger.info("Executing query with LIMIT %s on table %s", limit, table_name)
            self._write_csv(con, query, output_csv)
            self._logger.info("Export complete: %s", output_csv)
        finally:
            con.close()

    def _install_extension(self, con: duckdb.DuckDBPyConnection, extension_name: str, repo: str) -> None:
        """Install and load the ERPL extension."""
        con.sql(f"SET custom_extension_repository = '{_escape(repo)}';")
        con.execute(f"FORCE INSTALL {_escape(extension_name)};")
        con.execute(f"LOAD {_escape(extension_name)};")

    def _configure_sap(self, con: duckdb.DuckDBPyConnection, config: SapConnectionConfig) -> None:
        """Set SAP connection parameters in DuckDB/ERPL."""
        settings = [
            ("sap_ashost", config.sap_ashost),
            ("sap_sysnr", config.sap_sysnr),
            ("sap_user", config.sap_user),
            ("sap_password", config.sap_password),
            ("sap_client", config.sap_client),
            ("sap_lang", config.sap_lang),
        ]
        for key, value in settings:
            con.execute(f"SET {key} = '{_escape(value)}';")
        if config.sap_router:
            con.execute(f"SET sap_router = '{_escape(config.sap_router)}';")

    def _detect_dats_columns(self, con: duckdb.DuckDBPyConnection, table_name: str) -> list[str]:
        """Return a list of DATS columns to cast to strings (avoids BC date issues)."""
        self._logger.debug("Inspecting DATS fields for table %s", table_name)
        res = con.sql(f"SELECT field FROM sap_describe_fields('{_escape(table_name)}') WHERE sap_type = 'DATS'")
        return [row[0] for row in res.fetchall()]

    def _build_query(self, table_name: str, limit: int, dats_columns: list[str]) -> str:
        """Build the SELECT query with optional DATS casts and limit."""
        if "'" in table_name:
            raise ValueError("Table name cannot contain quotes")
        cast_clause = ""
        if dats_columns:
            casts = ", ".join(f"CAST({col} AS VARCHAR) AS {col}" for col in dats_columns)
            cast_clause = f" REPLACE ({casts})"
        return (
            f"SELECT *{cast_clause} "
            f"FROM sap_read_table('{table_name}') "
            f"LIMIT {limit}"
        )

    def _write_csv(self, con: duckdb.DuckDBPyConnection, query: str, output_csv: str) -> None:
        """Write query results to CSV with headers."""
        os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
        con.execute(f"COPY ({query}) TO '{_escape(output_csv)}' WITH (HEADER, DELIMITER ',');")


def _build_logger(verbosity: int) -> logging.Logger:
    """Configure a simple console logger."""
    level = logging.DEBUG if verbosity > 0 else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s")
    return logging.getLogger("sapreadtable-export")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Export SAP table data to CSV via ERPL/DuckDB.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to config JSON (default: secrets/config.json)")
    parser.add_argument("--table", default=None, help="SAP table name; overrides table_selection in config")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Row limit for the query (default: 100)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output CSV path (default: sap_export.csv)")
    parser.add_argument(
        "--extension-dir",
        default=os.getenv("DUCKDB_EXTENSION_DIRECTORY", DEFAULT_EXTENSION_DIR),
        help="DuckDB extension directory (default: ./.duckdb/extensions or DUCKDB_EXTENSION_DIRECTORY)",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase log verbosity")
    return parser.parse_args()


def main() -> None:
    """CLI entrypoint."""
    args = parse_args()
    logger = _build_logger(args.verbose)

    loader = ConfigLoader(args.config)
    config = loader.load()
    if args.table:
        config.table_selection = args.table
    if not config.table_selection:
        raise ValueError("Table name is required (set table_selection in config or pass --table).")

    connector = DuckDBConnector(extension_dir=args.extension_dir)
    exporter = SapReadTableExporter(connector=connector, logger=logger)
    exporter.export(
        config=config,
        table_name=config.table_selection,
        limit=args.limit,
        output_csv=args.output,
    )


if __name__ == "__main__":
    main()
