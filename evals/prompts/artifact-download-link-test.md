Perform a focused, non-destructive test of browser-download links returned by
`sans-pilot`.

This is an artifact transport and client-integration test, not a scientific
model-assessment exercise. Do not inspect unrelated uploads, add scientific
interpretation, print encoded file contents, or reveal internal
`sans-pilot://artifact/<token>` URIs in user-facing prose.

The browser links tested here are non-expiring bearer capabilities in the first
implementation. Anyone possessing a link can download its artifact. Show links
only where this prompt explicitly requires them, and redact tokens and
signatures from the final report.

## 1. Discovery and configuration

- Discover the available MCP tools and confirm that `read-sans-artifact` is
  exposed.
- State that the test requires artifact metadata to contain `name`, `mime_type`,
  `bytes`, an internal `uri`, and a browser `download_url`.
- If `download_url` is absent, stop and report that public artifact downloads
  are not configured or that the deployed server is stale.
- Confirm that each `download_url` uses HTTP(S) or an absolute same-origin path.
  It must not contain an internal service hostname such as `sans-pilot:8001`.

## 2. Generate downloadable PNG and CSV artifacts

- Generate a small seeded sphere simulation with a low point count and request
  its CSV export.
- Verify that the response contains both PNG and CSV artifact metadata.
- For each artifact, verify that `name`, `mime_type`, `bytes`, internal `uri`,
  and `download_url` are present and plausible.
- Confirm that the PNG is also returned as MCP image content.
- Confirm that CSV contents are not inlined in the original tool result.
- Do not print the internal artifact URIs.

## 3. Present browser links

Present exactly two Markdown links for the operator to test, labelled with the
returned filenames:

- the PNG `download_url`;
- the CSV `download_url`.

Do not construct, shorten, rewrite, decode, or otherwise modify either URL.
After presenting the links, ask the operator to click both and report whether:

1. each request succeeds without Docker- or Kubernetes-internal hostnames;
2. the downloaded filename matches the artifact `name`;
3. the PNG opens as a valid image;
4. the CSV begins with the expected header and is not an HTML error page.

Do not claim that browser downloading passed until the operator confirms these
observations.

## 4. MCP retrieval and link stability

- Call `read-sans-artifact` for both artifacts using their internal URIs without
  displaying those URIs to the user.
- Confirm that each read result returns the same `name`, `mime_type`, and
  `bytes` as the original metadata.
- Confirm that `read-sans-artifact` returns a `download_url` for each artifact.
- Verify that each returned URL is byte-for-byte identical to its original URL.
  This checks the first implementation's non-expiring deterministic link
  behavior; do not infer a future expiration policy.
- Confirm that the image read returns MCP image content.
- Read only a small first chunk of the CSV and confirm its header without
  pasting the complete file.

## 5. Invalid-link behavior

This section is operator-assisted. Perform each check at most once and do not
paste the modified URLs back into the chat:

- Change one character in a link signature and confirm the request does not
  return the artifact.
- Change the filename path component and confirm the request does not return
  the artifact.

Record only the HTTP status or visible failure behavior. Do not test another
user's artifacts and do not attempt token enumeration.

## 6. Restart persistence

Provide an operator checkpoint:

1. retain the two original links and internal URIs outside any committed report;
2. restart the `sans-pilot` container or Kubernetes deployment without rotating
   `SANS_PILOT_DOWNLOAD_SIGNING_KEY`;
3. continue in the same conversation as the same user;
4. call `read-sans-artifact` for both retained internal URIs;
5. verify that the returned browser links exactly match the originals;
6. click both original links again and confirm that their files still download.

If no restart is performed, mark this section as pending rather than passed.
Do not rotate the signing key during this test because rotation intentionally
invalidates existing links.

## Final report

Produce a concise report containing:

- tool discovery result;
- PNG and CSV metadata checks;
- whether user-facing Markdown links were rendered correctly;
- operator-confirmed browser download results, or `pending`;
- filename, MIME type, and content sanity checks;
- stable-link comparison results;
- invalid-signature and invalid-filename behavior, or `pending`;
- restart-persistence result, or `pending`;
- exact reproducible tool requests for failures;
- explicit error origin only when returned, otherwise `unknown`.

Redact complete download URLs, signatures, artifact tokens, user identifiers,
and internal service addresses from the final report. Do not add scientific
conclusions.
