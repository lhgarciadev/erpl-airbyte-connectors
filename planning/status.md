# Project Status: ERPL Airbyte Connectors

## Overview
This project hosts Airbyte source connectors for SAP systems, leveraging the `erpl` DuckDB extension for high-performance data extraction.

## Active Development Phase
**Phase 1: Modernization & Tooling (Current)**

## Roadmap
- [x] **Initialization**: Project structure analysis.
- [ ] **Documentation Fixes**: Corrected READMEs to reflect actual project purpose.
- [x] **Tooling Migration**: Replaced Poetry with `uv`, updated Makefile.
- [ ] **Code Quality**: Fixed linting errors in `source.py`.
- [ ] **Verification**: Run full test suite.
- [ ] **Feature**: Implement `source-sapbics` (Future).
- [ ] **Feature**: Implement `source-sapodp` (Future).

## Architecture
- **Core**: Python Airbyte CDK wrapper.
- **Engine**: DuckDB with `erpl` extension.
- **Protocol**: SAP RFC.

## Recent Logs
- **2025-11-24**: Migrated to `uv`, fixed `ruff` errors, established `planning/` directory.
