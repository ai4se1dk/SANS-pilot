# Manual MCP evaluations

This directory contains version-controlled prompts for manual, LLM-driven
integration testing of `sans-pilot`. These evaluations complement the automated
pytest suite under `test/`; they are not deterministic unit tests.

## Layout

```text
evals/
├── prompts/
│   ├── full-functional-test.md
│   ├── artifact-persistence-test.md
│   └── artifact-download-link-test.md
└── reports/
    └── .gitkeep
```

## Prompts

- `prompts/full-functional-test.md` exercises the complete exposed MCP surface,
  including discovery, data handling, fitting, inversion, artifacts,
  concurrency, and the operator-assisted cancellation checklist.
- `prompts/artifact-persistence-test.md` focuses on inline images, chunked
  CSV/text reads, user-scoped artifact access, and restart persistence.
- `prompts/artifact-download-link-test.md` focuses on signed browser links,
  client downloads, tamper rejection, stable links, and restart persistence.

Run prompts in a new chat after rebuilding/restarting the MCP deployment and
refreshing LibreChat's MCP tool catalog. Tests that require stopping a running
chat or restarting a pod are explicitly marked as operator-assisted and should
be performed separately from the main report-producing run.

## Reports

Generated reports are ignored by Git by default. Keep them under
`evals/reports/` for local comparison. Commit a report only when it is a
sanitized, intentional reference fixture.

Before sharing or committing a report, remove:

- chat and conversation IDs;
- user IDs and email addresses;
- stored upload names when they contain private identifiers;
- artifact tokens and internal URLs;
- access tokens, headers, and environment-specific secrets.

When a tool contract changes, update the relevant prompt in the same pull
request and rerun the corresponding evaluation.
