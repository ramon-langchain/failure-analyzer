# failure-analyzer

Warning: experimental. Expect breaking changes, rough edges, and prompt/model behavior changes.

`failure-analyzer` wraps a test command, streams its output, and invokes a LangChain Deep Agent to explain failures when the command exits non-zero.

If a `.env` file is present in the current repository, it is loaded automatically before model initialization.

## Usage

Recommended one-off usage:

```bash
uvx --from git+ssh://git@github.com/ramon-langchain/failure-analyzer.git failure-analyzer go test ./...
```

Recommended persistent install:

```bash
uv tool install --upgrade --from git+ssh://git@github.com/ramon-langchain/failure-analyzer.git failure-analyzer
failure-analyzer go test ./...
```

The command preserves the wrapped test process exit code. On failures, it prints a Markdown report to stderr and can optionally save the same report with `--report-file`.

Use `-C /path/to/project` to run the wrapped command from a different working directory.

## GitHub Actions

When `failure-analyzer` detects `GITHUB_ACTIONS=true`, it will:

- write the report to a stable file path automatically
- append the report to the GitHub Actions step summary when `GITHUB_STEP_SUMMARY` is available
- export the report path as the step output `failure_analyzer_report_path` when `GITHUB_OUTPUT` is available

That lets a workflow upload the report with `actions/upload-artifact` in a follow-up step:

```yaml
- name: Run tests with analysis
  id: failure_analyzer
  run: uv run failure-analyzer -C examples/go-ci-demo go test ./...

- name: Upload analysis report
  if: always() && steps.failure_analyzer.outputs.failure_analyzer_report_path != ''
  uses: actions/upload-artifact@v4
  with:
    name: failure-analyzer-report
    path: ${{ steps.failure_analyzer.outputs.failure_analyzer_report_path }}
```
