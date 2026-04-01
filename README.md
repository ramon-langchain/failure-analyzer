# failure-analyzer

Warning: experimental. Expect breaking changes, rough edges, and prompt/model behavior changes.

`failure-analyzer` wraps a test command, streams its output, and invokes a LangChain Deep Agent to explain failures when the command exits non-zero.

If a `.env` file is present in the current repository, it is loaded automatically before model initialization.

## GitHub Actions

Recommended usage is the reusable workflow:

```yaml
jobs:
  test:
    uses: ramon-langchain/failure-analyzer/.github/workflows/analyze.yml@main
    secrets: inherit
    with:
      command: go test ./...
```

Inside the reusable workflow, `failure-analyzer` is installed from the same commit as the workflow itself, so the workflow definition and tool code stay in sync.

The caller repository should define provider credentials as Actions secrets. Supported secret names are:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GOOGLE_API_KEY`
- `GOOGLE_CLOUD_PROJECT`
- `FAILURE_ANALYZER_OPENAI_API_KEY`
- `FAILURE_ANALYZER_ANTHROPIC_API_KEY`
- `FAILURE_ANALYZER_GOOGLE_API_KEY`
- `FAILURE_ANALYZER_GOOGLE_CLOUD_PROJECT`

If both the `FAILURE_ANALYZER_*` and standard provider names are present, `failure-analyzer` prefers the `FAILURE_ANALYZER_*` versions.

Optional inputs:

- `working-directory`
- `artifact-name`
- `python-version`
- `model`

The reusable workflow uploads the Markdown analysis as an artifact automatically and preserves the wrapped command's exit code.

## Direct CLI Usage

One-off usage:

```bash
uvx --from git+https://github.com/ramon-langchain/failure-analyzer.git failure-analyzer go test ./...
```

Persistent install:

```bash
uv tool install --upgrade --from git+https://github.com/ramon-langchain/failure-analyzer.git failure-analyzer
failure-analyzer go test ./...
```

The command preserves the wrapped test process exit code. On failures, it prints a Markdown report to stderr and can optionally save the same report with `--report-file`.

Use `-C /path/to/project` to run the wrapped command from a different working directory.

When `failure-analyzer` detects `GITHUB_ACTIONS=true`, it will:

- write the report to a stable file path automatically
- append the report to the GitHub Actions step summary when `GITHUB_STEP_SUMMARY` is available
- export the report path as the step output `failure_analyzer_report_path` when `GITHUB_OUTPUT` is available

The reusable workflow at [.github/workflows/analyze.yml](/Users/ramon/langchain/failure-analyzer/.github/workflows/analyze.yml) already uploads the report artifact automatically. If you prefer wiring the raw steps yourself, this still works:

```yaml
- name: Run tests with analysis
  id: failure_analyzer
  run: uvx --from git+https://github.com/ramon-langchain/failure-analyzer.git failure-analyzer -C . go test ./...

- name: Upload analysis report
  if: always() && steps.failure_analyzer.outputs.failure_analyzer_report_path != ''
  uses: actions/upload-artifact@v4
  with:
    name: failure-analyzer-report
    path: ${{ steps.failure_analyzer.outputs.failure_analyzer_report_path }}
```
