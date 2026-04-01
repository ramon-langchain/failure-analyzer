# go-ci-demo

Small Go module for exercising `failure-analyzer` against realistic CI-style failures.

## What it contains

- `pricing`: order pricing and shipping helpers
- `accounts`: user account normalization and retry-policy helpers
- A mix of passing and failing unit tests

## Run the tests

```bash
cd examples/go-ci-demo
go test ./...
```

## Run through the analyzer

From the repo root:

```bash
uv run failure-analyzer -C examples/go-ci-demo go test ./...
```

Or from inside the example project:

```bash
cd examples/go-ci-demo
uv run ../../. failure-analyzer go test ./...
```

The current test suite is intentionally not green. It includes a couple of realistic logic regressions so the analyzer has something non-trivial to inspect.

## GitHub Actions demo

This repository includes a manual workflow at [.github/workflows/example-go-ci-demo.yml](/Users/ramon/langchain/failure-analyzer/.github/workflows/example-go-ci-demo.yml) that runs this example through `failure-analyzer` on GitHub Actions.

To use it:

1. Add at least one supported provider secret to the repository, such as `OPENAI_API_KEY` or `FAILURE_ANALYZER_OPENAI_API_KEY`.
2. Open the `Example Go CI Demo` workflow in the Actions tab.
3. Click `Run workflow`.

The workflow is expected to fail, and the analysis will be written to the run summary.
