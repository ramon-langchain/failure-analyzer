# failure-analyzer

Warning: experimental. Expect breaking changes, rough edges, and prompt/model behavior changes.

`failure-analyzer` wraps a test command, streams its output, and invokes a LangChain Deep Agent to explain failures when the command exits non-zero.

If a `.env` file is present in the current repository, it is loaded automatically before model initialization.

If `LANGSMITH_API_KEY` or `FAILURE_ANALYZER_LANGSMITH_API_KEY` is present, `failure-analyzer` automatically enables LangSmith tracing for the analyzer run. In GitHub Actions, the default LangSmith project name is the base name of `GITHUB_REPOSITORY`. Outside GitHub Actions, the fallback default is `failure-analyzer`.

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
      command: go test -json -race -cover -timeout 10s ./...
      go-version: "1.24.13"
      langsmith-project: my-ci-failure-analyzer
      allow-rerun: false
      instructions: |
        Focus on flaky-test evidence first.
```

Inside the reusable workflow, `failure-analyzer` is installed from the same commit as the workflow itself, so the workflow definition and tool code stay in sync.

Prefer wrapped commands that emit structured or richly annotated output when that is available. For example:

- `go test -json -race -cover ./...` instead of plain `go test ./...`
- test runners that can emit JSON, JUnit XML, TAP, or similarly structured diagnostics

The analyzer can still work with plain text output, but structured output usually gives it better evidence and clearer timing.

Recommended caller permissions:

```yaml
permissions:
  contents: read
  pull-requests: read
  issues: write
  actions: read
```

- `contents: read` is required for checkout.
- `pull-requests: read` is optional and enables extra pull-request context in the analyzer prompt, such as the PR number, title, submitter, head/base refs, and PR link.
- `issues: write` is required only if you want `failure-analyzer` to post a short PR comment.
- `actions: read` is optional and enables extra workflow-history context in the analyzer prompt, including previous failed runs for the current PR when that data is available.

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
- `LANGSMITH_API_KEY`
- `FAILURE_ANALYZER_LANGSMITH_API_KEY`

If both the `FAILURE_ANALYZER_*` and standard provider names are present, `failure-analyzer` prefers the `FAILURE_ANALYZER_*` versions.

Optional inputs:

- `working-directory`
- `go-version`
- `python-version`
- `model`
- `instructions`
- `langsmith-project`
- `allow-rerun`
- `flags`

`allow-rerun` defaults to `false`. When enabled, the agent may rerun the wrapped test command or a narrowed variant if that will materially improve the diagnosis, but it is instructed to keep those reruns short and to aim to finish within about two minutes total.

The reusable workflow writes the full Markdown analysis to the GitHub Actions job summary automatically and preserves the wrapped command's exit code.

To enable LangSmith tracing in the reusable workflow:

1. Add a repository or organization Actions secret named `LANGSMITH_API_KEY` or `FAILURE_ANALYZER_LANGSMITH_API_KEY`.
2. Optionally set the `langsmith-project` workflow input to override the default project name. If you do not set it, `failure-analyzer` uses the base name of `GITHUB_REPOSITORY`.
3. Re-run the workflow. Tracing turns on automatically when the key is present.

When the caller workflow is running on a pull request and grants `issues: write`, `failure-analyzer` also generates a separate one-paragraph PR comment and posts it to the PR thread. That short comment links back to the full workflow run summary.

The reusable workflow also builds an optional invocation-context file and appends it to the analyzer system prompt. Depending on which GitHub APIs are readable in the current run, that context can include:

- base GitHub Actions runtime metadata like workflow name, run id, ref, sha, actor, runner OS/arch, and run URL
- pull-request metadata like PR number, title, URL, author, and head/base refs
- previous failed workflow runs for the same PR head SHA, with links back to those runs

These sections are modular. If the relevant API call is not readable with the current token permissions, that section is simply omitted.

When `failure-analyzer` runs in GitHub Actions, it also exposes an artifact output directory to the agent through `FAILURE_ANALYZER_OUTPUT_DIR`. The agent can copy or generate helpful files there, mention them in the report as `artifact:path/to/file.ext`, and the workflow will upload that directory as a GitHub Actions artifact and rewrite those references into real artifact links in the final summary and PR comment.

This repo also includes a manual demo workflow at [.github/workflows/example-go-ci-demo.yml](/Users/ramon/langchain/failure-analyzer/.github/workflows/example-go-ci-demo.yml) that runs the intentionally failing Go sample in `examples/go-ci-demo`. Add one of the supported provider secrets to this repository, then trigger `Example Go CI Demo` from the Actions tab to see the summary output end to end.

When `go-version` is set, the reusable workflow installs Go with `actions/setup-go` and enables Go module caching using `${working-directory}/go.sum`. uv caching is enabled explicitly through `astral-sh/setup-uv`.

## Direct CLI Usage

One-off usage:

```bash
uvx --from git+https://github.com/ramon-langchain/failure-analyzer.git failure-analyzer go test -json -race -cover -timeout 10s ./...
```

Persistent install:

```bash
uv tool install --upgrade --from git+https://github.com/ramon-langchain/failure-analyzer.git failure-analyzer
failure-analyzer go test -json -race -cover -timeout 10s ./...
```

Optional LangSmith tracing for direct CLI usage:

```bash
export LANGSMITH_API_KEY=...
export LANGSMITH_PROJECT=my-local-failure-analysis
failure-analyzer go test -json -race -cover -timeout 10s ./...
```

You can also use the prefixed env vars:

```bash
export FAILURE_ANALYZER_LANGSMITH_API_KEY=...
export FAILURE_ANALYZER_LANGSMITH_PROJECT=my-local-failure-analysis
failure-analyzer go test -json -race -cover -timeout 10s ./...
```

If you want the analyzer to be allowed to rerun tests briefly during diagnosis:

```bash
failure-analyzer --allow-rerun go test -json -race -cover -timeout 10s ./...
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
  run: uvx --from git+https://github.com/ramon-langchain/failure-analyzer.git failure-analyzer -C . go test -json -race -cover -timeout 10s ./...
```
