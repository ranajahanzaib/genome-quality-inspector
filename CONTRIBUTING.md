# Contributing

Contributions that improve the analyzer, API, interface, or documentation are welcome. For a substantial change, open an issue first to discuss its scope.

## Development setup

Install the tools listed in the [root README](README.md#requirements), then follow its [local setup](README.md#run-locally). Keep changes focused and include tests for behavior changes.

## Validation

Run the checks for the components you change:

```bash
cargo fmt --manifest-path crates/gqi-engine/Cargo.toml --check
cargo test --locked --manifest-path crates/gqi-engine/Cargo.toml
cargo clippy --locked --manifest-path crates/gqi-engine/Cargo.toml --all-targets -- -D warnings
```

From `apps/api`:

```bash
uv run pytest
uv run ruff check gqi_api tests migrations
uv run mypy gqi_api
```

From `apps/web`:

```bash
pnpm exec tsc --noEmit
pnpm lint
pnpm build
```

## Pull requests

Describe the problem and the change, list the checks you ran, and call out user-visible or compatibility changes. Update the documentation when behavior, setup, or supported inputs change.

## Issues

Use the repository issue templates for bug reports and feature requests. Do not include private sequence data, access tokens, or other credentials in an issue; report vulnerabilities using the process in [SECURITY.md](.github/SECURITY.md).
