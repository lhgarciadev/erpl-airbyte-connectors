# ERPL local setup and validation

Quick reference for installing the ERPL DuckDB extension locally (uv + Python) and validating RFC connectivity, incorporating the upstream quickstart guidance.

## Prerequisites
- Python 3.10+, `uv`
- Network access to the SAP RFC host/port

## Install and load ERPL with uv
```bash
cd source-sapreadtable
uv run python - <<'PY'
import duckdb
con = duckdb.connect(config={"allow_unsigned_extensions": "true"})
con.sql("SET custom_extension_repository = 'http://get.erpl.io';")
con.sql("FORCE INSTALL erpl;")
con.sql("LOAD erpl;")
PY
```

Notes:
- `allow_unsigned_extensions` is required because ERPL binaries are unsigned.
- `FORCE INSTALL` will reuse the cached extension if already present.

## Validate RFC connectivity via ERPL
1) Connector check (preferred):  
```bash
uv run source-sapreadtable check --config secrets/config.json
```
2) Direct DuckDB ping (helps isolate Airbyte):  
```bash
uv run python - <<'PY'
import duckdb
con = duckdb.connect(config={"allow_unsigned_extensions": "true"})
con.sql("SET custom_extension_repository='http://get.erpl.io';")
con.sql("FORCE INSTALL erpl;")
con.sql("LOAD erpl;")
con.sql("PRAGMA sap_rfc_ping;")
PY
```
3) Network reachability sanity check (replace SYSNR):  
```bash
nc -vz <sap_ashost> 33<SYSNR>
```

## Credentials/config required (matches spec.yaml)
- `sap_ashost`, `sap_sysnr`, `sap_client`
- `sap_user`, `sap_password`
- Optional: `sap_lang` (default EN)
- `custom_extension_repository` (default `http://get.erpl.io`)
- `extension_name` (default `erpl`)
- `table_selection` for discovery/read

## Reference
- Quickstart: https://erpl.io/docs/get_started/quickstart-erpl
- Install doc: https://erpl.io/docs/get_started/install
