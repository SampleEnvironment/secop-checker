# secop-checker

Schema checker for SECoP descriptive metadata. Python 3.12+.

## Commands

```sh
uv run pytest                          # run all tests
uv run pytest test/test_basic.py -k <name>  # single test
uv run --group typing mypy secop_check # mypy only
./typecheck                            # full typecheck: mypy + pyright + ty
uv run ruff check                      # lint (ALL rules selected)
uv run ruff check --fix                # lint + autofix
```

## CLI

```
secop-check <file.json>    # check a file
secop-check host:port      # check a live SEC node
secop-check -              # read JSON from stdin
```

Flags: `--json` (JSON output), `--version {latest,1.0,1.1,2.0}` (default 2.0), `--schema <url>` (additional schema repos).

## Structure

- `secop_check/` — library + CLI (`cmdline.py:main`)
- `defs/` — YAML schema definition files (SECoP versions, datatypes, properties, interfaces)
- `test/` — pytest, parameterized over `test/data/*.json`
- `web/` — Flask app for browser-based checking (dev only, hardcodes version 1.0)
- `bin/secop-check` — dev runner (appends project root to `sys.path`)

Checker uses a visitor pipeline defined in `visitors.py:VISITORS`: BasicStructure → Name → Interface → BaseProps → Accessible.

## Ruff

Configured in `pyproject.toml` under `[tool.ruff.lint]`. Select ALL, ignore D1/D203/D213/EM/FIX/S101/TD/TRY003. Single quotes. Max complexity 20.

## Gotchas

- `/*.json` in `.gitignore` — top-level JSON files are git-ignored (test data lives in `test/data/`)
- Tests hardcode version `'1.1'` — update if adding new version fixtures
- `ty` (from `typing` dep group) is a third-party type checker, used in the `typecheck` script
