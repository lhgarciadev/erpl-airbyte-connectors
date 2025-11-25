# Build stage
FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim AS build

WORKDIR /app

# Copy lockfile and project definition
COPY pyproject.toml uv.lock ./

# Copy source code
COPY source_sapreadtable ./source_sapreadtable
COPY main.py ./
COPY README.md ./

# Install dependencies using uv
# --no-dev ensures dev dependencies are not installed
# --frozen ensures the lockfile is respected strictly
RUN uv sync --no-dev --frozen

# Runtime stage
FROM ghcr.io/astral-sh/uv:python3.10-bookworm-slim

WORKDIR /app

# Copy installed application and virtual environment from the build stage
COPY --from=build /app /app

# Set the entrypoint to run the Airbyte connector CLI using uv
ENTRYPOINT ["uv", "run", "source-sapreadtable"]

# No CMD is needed, as Airbyte will append the specific command (spec, check, discover, read)
# No EXPOSE 8000, as this is a connector, not a web server.