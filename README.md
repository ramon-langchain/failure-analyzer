# test-analyzer

`test-analyzer` wraps a test command, streams its output, and invokes a LangChain Deep Agent to explain failures when the command exits non-zero.

If a `.env` file is present in the current repository, it is loaded automatically before model initialization.

## Usage

```bash
uvx --from . test-analyzer go test ./...
```

Or after installing the project dependencies locally:

```bash
uv run test-analyzer --model openai:gpt-5.4-mini go test ./...
```

The command preserves the wrapped test process exit code. On failures, it prints a Markdown report to stderr and can optionally save the same report with `--report-file`.

Use `-C /path/to/project` to run the wrapped command from a different working directory.

## GitHub Actions

When `test-analyzer` detects `GITHUB_ACTIONS=true`, it will:

- write the report to a stable file path automatically
- append the report to the GitHub Actions step summary when `GITHUB_STEP_SUMMARY` is available
- export the report path as the step output `test_analyzer_report_path` when `GITHUB_OUTPUT` is available

That lets a workflow upload the report with `actions/upload-artifact` in a follow-up step:

```yaml
- name: Run tests with analysis
  id: test_analyzer
  run: uv run test-analyzer -C examples/go-ci-demo go test ./...

- name: Upload analysis report
  if: always() && steps.test_analyzer.outputs.test_analyzer_report_path != ''
  uses: actions/upload-artifact@v4
  with:
    name: test-analyzer-report
    path: ${{ steps.test_analyzer.outputs.test_analyzer_report_path }}
```

## Standalone binaries

The repository includes a GitHub Actions workflow at [.github/workflows/build-binaries.yml](/Users/ramon/langchain/failure-analyzer/.github/workflows/build-binaries.yml) that builds standalone executables with PyInstaller for:

- Linux `amd64`
- Linux `arm64`
- Darwin `arm64`

It runs on tags matching `v*` and on manual dispatch, then uploads one `.tar.gz` artifact per target.
