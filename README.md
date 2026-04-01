# failure-analyzer

Warning: experimental. Expect breaking changes, rough edges, and prompt/model behavior changes.

`failure-analyzer` wraps a test command, streams its output, and invokes a LangChain Deep Agent to explain failures when the command exits non-zero.

If a `.env` file is present in the current repository, it is loaded automatically before model initialization.

`failure-analyzer` also borrows the main Deep Agents memory and skills conventions:

- memory files, in load order:
  - `~/.deepagents/failure-analyzer/AGENTS.md`
  - `<project-root>/.deepagents/AGENTS.md`
  - `<project-root>/AGENTS.md`
- skills directories, in precedence order:
  - `~/.deepagents/failure-analyzer/skills/`
  - `~/.agents/skills/`
  - `<project-root>/.deepagents/skills/`
  - `<project-root>/.agents/skills/`
  - `~/.claude/skills/`
  - `<project-root>/.claude/skills/`

`<project-root>` is the nearest parent directory containing `.git`. You can override the user-level Deep Agents agent name with `FAILURE_ANALYZER_AGENT_NAME`.

## GitHub Actions

Recommended usage is the reusable workflow:

```yaml
jobs:
  test:
    uses: ramon-langchain/failure-analyzer/.github/workflows/analyze.yml@main
    secrets: inherit
    with:
      command: go test ./...
      go-version: "1.24.13"
```

Inside the reusable workflow, `failure-analyzer` is installed from the same commit as the workflow itself, so the workflow definition and tool code stay in sync.

Recommended caller permissions:

```yaml
permissions:
  contents: read
  issues: write
  actions: read
```

- `contents: read` is required for checkout.
- `issues: write` is required only if you want `failure-analyzer` to post a short PR comment.
- `actions: read` is optional and only enables the agent to inspect prior workflow runs to judge flakiness.

If you do not want PR comments or flaky-run inspection, this also works:

```yaml
permissions:
  contents: read
```

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
- `go-version`
- `python-version`
- `model`
- `flags`

The reusable workflow writes the full Markdown analysis to the GitHub Actions job summary automatically and preserves the wrapped command's exit code.

When the caller workflow is running on a pull request and grants `issues: write`, `failure-analyzer` also generates a separate one-paragraph PR comment and posts it to the PR thread. That short comment links back to the full workflow run summary.

This repo also includes a manual demo workflow at [.github/workflows/example-go-ci-demo.yml](/Users/ramon/langchain/failure-analyzer/.github/workflows/example-go-ci-demo.yml) that runs the intentionally failing Go sample in `examples/go-ci-demo`. Add one of the supported provider secrets to this repository, then trigger `Example Go CI Demo` from the Actions tab to see the summary output end to end.

When `go-version` is set, the reusable workflow installs Go with `actions/setup-go` and enables Go module caching using `${working-directory}/go.sum`. uv caching is enabled explicitly through `astral-sh/setup-uv`.

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

The reusable workflow at [.github/workflows/analyze.yml](/Users/ramon/langchain/failure-analyzer/.github/workflows/analyze.yml) relies on the step summary instead of artifact upload. If you prefer wiring the raw steps yourself, this still works:

```yaml
- name: Run tests with analysis
  id: failure_analyzer
  run: uvx --from git+https://github.com/ramon-langchain/failure-analyzer.git failure-analyzer -C . go test ./...
```
