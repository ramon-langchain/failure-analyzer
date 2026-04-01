# Repository Instructions

## Environment

- This project targets Python `3.14`.
- Install development dependencies with `uv sync --extra dev`.

## Verification

- Run the test suite with `uv run pytest tests`.
- Run type checking with `uv run ty check`.

## Local GitHub Actions Demo

- Use `uv run python scripts/run_local_github_actions_demo.py` to simulate the example GitHub Actions workflow locally.
- The helper prints the paths to the generated summary, report, invocation context, and artifact directory.
