# Self-hosting CodeSheriff

## Docker

```bash
docker build -t codesheriff .
docker run --rm -v "$PWD:/work" -w /work codesheriff run
```

Mount the repo at `/work`; reports land in `.quality-reports/`. Pass keys
with `-e ANTHROPIC_API_KEY=...` (or OpenAI / Gemini equivalents). No daemon,
no network egress required for heuristic gates.

## SSO notes

- GitHub App (OAuth): set `GITHUB_TOKEN` from your IdP-backed machine user;
  the worker only needs `contents:read`, `pull-requests:write`,
  `checks:write`.
- GitLab: set `GITLAB_TOKEN` + `CI_PROJECT_ID` / `CI_MERGE_REQUEST_IID`
  (see `src/quality_gates/review/gitlab.py`); short-lived `CI_JOB_TOKEN`
  works for MR notes on self-managed instances.
- Keep tokens in your IdP secret store; never bake them into images.

## Air-gap with Ollama

```bash
# inside the air-gapped network
ollama serve & ollama pull llama3.2
QUALITY_REVIEW_MODE=single quality review --base main
```

Set `review.provider = "ollama"` (or `OPENAI_BASE_URL` to your Ollama host);
`offline = true` disables all LLM calls and runs heuristic gates only.
ReviewBench (`quality eval`) validates recall without network access.
