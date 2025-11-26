"""Standalone ERPL RFC reader for a single SAP table.

Copy this file into any repository (with DuckDB and ERPL available) to run a
limited query against an SAP system using sap_rfc_read_table.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol
from urllib.parse import urlencode

import duckdb

DEFAULT_DB_PATH = ":memory:"
DEFAULT_CONFIG_PATH = "secrets/config.json"
DEFAULT_EXTENSION_DIR = "./.duckdb/extensions"
DEFAULT_CUSTOM_EXTENSION_REPO = "http://get.erpl.io"
DEFAULT_TABLE = "DFKKKO"
DEFAULT_LIMIT = 10
DEFAULT_DATS_COLUMNS = ("CPUDT", "BLDAT", "BUDAT", "WWERT", "VATDATE")


class ConnectionProtocol(Protocol):
    """Minimal protocol for DuckDB connections used by the runner."""

    def execute(self, sql: str) -> "ConnectionProtocol":
        ...

    def fetchall(self) -> list[Any]:
        ...

    def close(self) -> None:
        ...


@dataclass
class SapConnectionConfig:
    """SAP connection configuration loaded from the JSON file."""

    custom_extension_repository: str = DEFAULT_CUSTOM_EXTENSION_REPO
    extension_name: str = "erpl"
    sap_ashost: str | None = None
    sap_sysnr: str | None = None
    sap_user: str = ""
    sap_password: str = ""
    sap_client: str = ""
    sap_lang: str = "EN"
    table_selection: str = DEFAULT_TABLE
    sap_router: str | None = None
    sap_mshost: str | None = None
    sap_msserv: str | None = None
    sap_r3name: str | None = None
    sap_group: str | None = None


class ConfigLoader:
    """Loads SAP connection configuration from disk."""

    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH) -> None:
        self._config_path = config_path

    def load(self) -> SapConnectionConfig:
        """Load and parse the JSON configuration file."""
        if not os.path.exists(self._config_path):
            raise FileNotFoundError(
                f"Configuration file not found at '{self._config_path}'. "
                "Please create it based on the README."
            )
        with open(self._config_path, "r", encoding="utf-8") as handle:
            raw_config = json.load(handle)
        return SapConnectionConfig(**raw_config)


class DuckDBConnector:
    """Creates DuckDB connections with the required ERPL settings."""

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        extension_dir: str = DEFAULT_EXTENSION_DIR,
        connect_func: Callable[..., duckdb.DuckDBPyConnection] = duckdb.connect,
    ) -> None:
        self._db_path = db_path
        self._extension_dir = extension_dir
        self._connect_func = connect_func

    def connect(self, config: SapConnectionConfig) -> duckdb.DuckDBPyConnection:
        """Create a DuckDB connection with unsigned extensions enabled."""
        db_config = {
            "allow_unsigned_extensions": "true",
            "extension_directory": self._extension_dir,
            "custom_extension_repository": config.custom_extension_repository,
        }
        return self._connect_func(
            database=self._db_path, read_only=False, config=db_config
        )


class SapConnectionStringBuilder:
    """Builds DuckDB ATTACH connection strings for SAP via ERPL."""

    @staticmethod
    def build(config: SapConnectionConfig) -> str:
        """Construct the sap:// connection string from configuration."""
        params: list[tuple[str, str]] = []

        if config.sap_mshost or config.sap_msserv or config.sap_r3name:
            params.extend(
                [
                    ("mshost", config.sap_mshost or ""),
                    ("msserv", config.sap_msserv or ""),
                    ("r3name", config.sap_r3name or ""),
                ]
            )
            if not all(value for _, value in params[-3:]):
                raise ValueError(
                    "mshost, msserv, and r3name are required for message server connections"
                )
            if config.sap_group:
                params.append(("group", config.sap_group))
        else:
            if not config.sap_ashost or not config.sap_sysnr:
                raise ValueError(
                    "sap_ashost and sap_sysnr are required for application server connections"
                )
            params.extend(
                [
                    ("ashost", config.sap_ashost),
                    ("sysnr", config.sap_sysnr),
                ]
            )

        params.extend(
            [
                ("client", config.sap_client),
                ("user", config.sap_user),
                ("passwd", config.sap_password),
                ("lang", config.sap_lang),
            ]
        )
        if config.sap_router:
            params.append(("saprouter", config.sap_router))

        query_string = urlencode(params)
        return f"sap://?{query_string}"


class ErplSapRunner:
    """Coordinates installing ERPL, attaching SAP, and running a query."""

    def __init__(
        self,
        connector: DuckDBConnector,
        query_limit: int = DEFAULT_LIMIT,
        connection_string_builder: SapConnectionStringBuilder | None = None,
        dats_columns: Iterable[str] = DEFAULT_DATS_COLUMNS,
    ) -> None:
        self._connector = connector
        self._query_limit = query_limit
        self._connection_string_builder = (
            connection_string_builder or SapConnectionStringBuilder()
        )
        self._dats_columns = tuple(dats_columns)

    def run(self, config: SapConnectionConfig) -> list[Any]:
        """Execute the ERPL demo workflow."""
        connection = self._connector.connect(config)
        try:
            self._install_extension(connection, config.extension_name)
            self._attach_or_configure_sap(connection, config)
            return self._query_table(connection, config.table_selection)
        finally:
            connection.close()

    def _install_extension(
        self, connection: ConnectionProtocol, extension_name: str
    ) -> None:
        """Install and load the ERPL extension."""
        connection.execute(f"FORCE INSTALL {extension_name};")
        connection.execute(f"LOAD {extension_name};")

    def _attach_or_configure_sap(
        self, connection: ConnectionProtocol, config: SapConnectionConfig
    ) -> None:
        """Attach the SAP system to DuckDB via the ERPL extension."""
        # Preferred path: app server via SAP parameters (matches ERPL pragmas used in connector).
        if config.sap_ashost and config.sap_sysnr:
            settings = [
                ("sap_ashost", config.sap_ashost),
                ("sap_sysnr", config.sap_sysnr),
                ("sap_user", config.sap_user),
                ("sap_password", config.sap_password),
                ("sap_client", config.sap_client),
                ("sap_lang", config.sap_lang),
            ]
            for key, value in settings:
                connection.execute(f"SET {key} = '{value}';")
            if config.sap_router:
                connection.execute(f"SET sap_router = '{config.sap_router}';")
            return

        # Fallback for message-server scenarios: build attach string.
        connection_string = self._connection_string_builder.build(config)
        attach_sql = f"ATTACH '{connection_string}' AS sap_system;"
        connection.execute(attach_sql)

    def _query_table(
        self, connection: ConnectionProtocol, table_name: str
    ) -> list[Any]:
        """Run the sample SAP table query."""
        if "'" in table_name:
            raise ValueError("Table name cannot contain quotes")
        cast_clause = self._build_cast_clause()
        query_sql = (
            f"SELECT * {cast_clause} "
            f"FROM sap_read_table('{table_name}') "
            f"LIMIT {self._query_limit};"
        )
        return connection.execute(query_sql).fetchall()

    def _build_cast_clause(self) -> str:
        """Cast problematic DATS fields to VARCHAR to avoid BC date errors."""
        if not self._dats_columns:
            return ""
        casts = ", ".join(
            f"CAST({col} AS VARCHAR) AS {col}" for col in self._dats_columns
        )
        return f"REPLACE ({casts})"


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="ERPL SAP RFC quickstart demo")
    parser.add_argument(
        "--config",
        default=os.getenv("ERPL_CONFIG_PATH", DEFAULT_CONFIG_PATH),
        help="Path to JSON config (default: secrets/config.json or ERPL_CONFIG_PATH)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Limit for sap_rfc_read_table (default: 10)",
    )
    parser.add_argument(
        "--table",
        default=DEFAULT_TABLE,
        help="SAP table to read (default: DFKKKO)",
    )
    parser.add_argument(
        "--extension-dir",
        default=os.getenv("DUCKDB_EXTENSION_DIRECTORY", DEFAULT_EXTENSION_DIR),
        help="DuckDB extension directory (default: ./.duckdb/extensions)",
    )
    parser.add_argument(
        "--no-cast-dats",
        action="store_true",
        help="Disable casting DATS columns to VARCHAR",
    )
    parser.add_argument(
        "--dats-columns",
        default=",".join(DEFAULT_DATS_COLUMNS),
        help="Comma-separated DATS columns to cast (default: CPUDT,BLDAT,BUDAT,WWERT,VATDATE)",
    )
    return parser.parse_args()


def run_demo(
    *,
    config_loader: ConfigLoader | None = None,
    runner: ErplSapRunner | None = None,
    args: argparse.Namespace | None = None,
) -> None:
    """Entry point for running the ERPL quickstart demo."""
    cli_args = args or parse_args()
    dats_columns = tuple(
        filter(None, (col.strip() for col in cli_args.dats_columns.split(",")))
    )
    try:
        loader = config_loader or ConfigLoader(cli_args.config)
        config = loader.load()
        config.table_selection = cli_args.table

        connector = DuckDBConnector(extension_dir=cli_args.extension_dir)
        erpl_runner = runner or ErplSapRunner(
            connector=connector,
            query_limit=cli_args.limit,
            dats_columns=() if cli_args.no_cast_dats else dats_columns,
        )
        results = erpl_runner.run(config)

        print("\n--- Query Results ---")
        if results:
            for row in results:
                print(row)
        else:
            print("No results returned from the query.")
    except FileNotFoundError as error:
        print(f"\nConfiguration Error: {error}")
        print(
            "--- Please create the `secrets/config.json` file with your SAP credentials. ---"
        )
    except duckdb.IOException as error:
        print(f"\nConnection Error: {error}")
        print("--- Troubleshooting ---")
        print("- Ensure you have internet access to download the extension.")
        print(
            "- Verify that your SAP connection details in 'secrets/config.json' are correct."
        )
        print(
            "- Check for any firewall rules that might be blocking the connection to the SAP system."
        )
    except Exception as error:  # pylint: disable=broad-except
        print(f"\nAn unexpected error occurred: {error}")


def main() -> None:
    """CLI wrapper."""
    run_demo()


if __name__ == "__main__":
    main()
