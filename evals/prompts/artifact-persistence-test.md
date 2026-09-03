Perform a focused, non-destructive test of persistent `sans-pilot` artifacts and the `read-sans-artifact` MCP tool.

This is an artifact transport and persistence test, not a scientific model-assessment exercise. Do not inspect unrelated uploads and do not expose artifact URIs as end-user download links outside this test report.

## 1. Discovery

- Discover the available MCP tools.
- Confirm that `read-sans-artifact` is exposed.
- Report the total number of exposed SANS tools.
- If `read-sans-artifact` is absent, stop and report that the deployment or LibreChat Agent tool configuration is stale.

## 2. Create and reopen an image artifact

- Generate a small seeded sphere simulation with a low point count and no CSV export.
- Record the returned PNG artifact metadata: `name`, `mime_type`, and internal `sans-pilot://artifact/<token>` URI.
- Confirm that the original simulation response includes MCP image content.
- Call `read-sans-artifact` with the PNG URI.
- Confirm that the read result contains the same artifact name and MIME type and returns MCP image content.
- Do not print base64 or encoded image bytes.

## 3. Create and read a CSV artifact in chunks

- Call `process-sans-data` with a small seeded simulation and `include_processed_csv: true`.
- Record the processed CSV artifact URI.
- Confirm that CSV contents are not inlined in the original processing response.
- Call `read-sans-artifact` with `offset: 0` and `limit: 64`.
- Verify the returned fields: `name`, `mime_type`, `bytes`, `offset`, `bytes_returned`, `next_offset`, `complete`, and `text`.
- Continue reading from each returned `next_offset` with a small limit until `complete: true`.
- Confirm that offsets are monotonic, chunks do not overlap, and concatenating them reconstructs a CSV beginning with the expected header.
- Do not paste the complete CSV into the final report; include only the header and chunk metadata.

## 4. Fit artifact retrieval

- Run one small seeded BUMPS/Amoeba sphere fit with only radius varied and with `include_sasview_parameters: true`.
- Record the `fit_plot.png` and `sasview_parameter_values.txt` artifact URIs.
- Reopen `fit_plot.png` with `read-sans-artifact` and confirm MCP image content is returned.
- Reopen `sasview_parameter_values.txt` with a bounded text read and confirm it begins with `sasview_parameter_values:`.
- Do not evaluate fit quality beyond reporting whether the tool completed.

## 5. Same-session durability

- Make at least five unrelated lightweight MCP calls after creating the artifacts.
- Re-read the original simulation PNG URI and processed CSV URI.
- Confirm that both still resolve and retain the same names, MIME types, and content metadata.
- Confirm that all generated artifact tokens are unique.

## 6. Error handling and user scope

Perform each invalid call only once:

- call `read-sans-artifact` with a malformed token;
- call it with a well-formed but nonexistent 32-character hexadecimal token;
- request a text chunk with an offset beyond the end of the CSV and confirm the returned empty/complete behavior is clear.

Do not attempt to access another user's artifact. Confirm only that the tool states artifacts are user-scoped and that unauthorized access is covered by the server contract.

## 7. Restart-persistence handoff

At the end, output a clearly labelled **operator-only persistence handoff** containing:

- one PNG artifact URI;
- one CSV artifact URI;
- the artifact names and MIME types;
- a short second-stage prompt that can be pasted into the same conversation after the `sans-pilot` container or Kubernetes deployment is restarted.

The second-stage prompt must instruct the assistant to:

1. call `read-sans-artifact` for both retained URIs as the same user;
2. verify PNG image content;
3. verify bounded CSV text retrieval;
4. report whether both token manifests and files survived the restart;
5. avoid adding scientific interpretation.

## Final report

Produce a concise report containing:

- tool discovery result;
- image inline/read result;
- CSV chunking result;
- fit artifact read result;
- same-session durability result;
- invalid-token behavior;
- unique-token check;
- whether a restart test is still pending;
- exact reproducible requests for failures;
- explicit error origin only when returned, otherwise `unknown`.

Do not add scientific conclusions. Do not present internal artifact URIs as normal user download links; include them only in the operator-only persistence handoff required for the restart test.
