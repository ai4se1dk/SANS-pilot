Perform a broad, non-destructive functional test of the `sans-pilot` MCP server.

The goal is to verify that `sans-pilot` exposes `sans-fitter` functionality correctly. Do not expect the MCP server to independently correct, reinterpret, or validate scientific results produced by `sans-fitter`. Clearly distinguish:

1. MCP transport/schema/artifact failures;
2. `sans-pilot` adapter failures;
3. errors or limitations explicitly identified as coming from `sans-fitter`;
4. behavior and limitations explicitly documented by `sans-fitter`.

Do not infer an error's originating layer from its wording. If the response does
not identify the origin, report it as unknown.

Start by discovering the available MCP tools. Exercise every exposed SANS tool at least once where practical.

Data selection:

- Call `list-uploaded-sans-files` first.
- Prefer these uploads if available:
  - `simulated_sans_data_with_resolution.csv`
  - `simulated_sans_data.csv`
- Confirm selected files using the returned stored `file` values.
- If they are unavailable, use deterministic simulations with explicit seeds.
- Do not inspect unrelated uploads.
- Do not request large CSV or posterior-chain artifacts unless needed to diagnose a problem.

Test the following areas:

1. Discovery

- Describe server capabilities.
- List supported formats.
- List uploaded SANS files.
- List available models.
- List structure factors.
- List polydispersity options.
- List curated examples.
- Confirm that `read-sans-artifact` is exposed.

2. Data loading and inspection

- Inspect both selected datasets.
- Report Q range, point count, dI availability, dQ availability, units, masks, warnings, and provenance.
- Inspect at least one curated text/XML example and one HDF5 example.
- Distinguish values returned by the loaders from your own interpretation.

3. Plotting and artifacts

- Plot one uploaded dataset without fitting.
- Verify that the result remains an MCP tool result.
- Verify that the tool result contains artifact metadata with `name`, `mime_type`, `bytes`, a lazy internal `sans-pilot://artifact/<token>` URI, and a signed browser `download_url`.
- Verify that generated PNG plots are also returned as MCP image content and display automatically in the chat.
- CSV and text artifact contents must remain lazy and must not be inlined.
- Call `read-sans-artifact` with one returned image URI and confirm that it returns valid MCP image content and the same `download_url`.
- Treat `sans-pilot://` artifact URIs as internal MCP references and never render them as browser links. Present the returned `download_url` as a Markdown link labelled with the artifact name; do not invent, rewrite, or decode it, and do not paste encoded image data into the conversation.
- Ask the operator to click the PNG link and confirm the downloaded filename and image content. Record this browser check as `pending` until the operator responds.
- Retain at least one image URI and download URL for the persistence checks near the end of this test.

4. Processing

- Crop a dataset to a valid Q range.
- Apply at least one scalar operation.
- If two compatible datasets are available, test subtraction and division.
- Report the units, dI, dQ, warnings, and preprocessing provenance exactly as returned.
- Do not impose your own unit, covariance, or resolution-propagation rules.
- Request one processed CSV and verify that its artifact metadata contains `bytes`, a lazy internal `sans-pilot://artifact/<token>` URI, and a browser `download_url` without inlining the CSV contents.
- Call `read-sans-artifact` with the CSV URI and a deliberately small `limit`. Verify `offset`, `bytes_returned`, `next_offset`, `complete`, and that the same `download_url` is returned; continue from `next_offset` and confirm that chunks can be reconstructed in order.
- Present the CSV `download_url` as a filename-labelled Markdown link. Ask the operator to confirm that it downloads with the expected filename and CSV header, or report the browser check as `pending`.
- Retain the CSV URI and download URL for the persistence checks near the end of this test.

5. Model discovery

- Retrieve the parameter contract for:
  - an atomic `sphere`;
  - `sphere` with a discovered structure factor;
  - a two-component additive composite.
- Confirm that returned parameter names can be used unchanged in a fit request.

6. Simulation

- Generate one seeded sphere simulation.
- Generate one seeded matched sample/background pair.
- Confirm reproducibility by repeating one simulation with the same seed.
- Keep generating truth separate from fitted estimates.

7. Point-estimate fitting

- Fit a seeded sphere simulation using BUMPS/Amoeba.
- Vary radius, scale, and background while keeping SLD parameters fixed.
- Run one LMFit/SciPy method as a pass-through test.
- Report the native objective, optimizer status, parameters, uncertainties, and warnings exactly as returned.
- Do not normalize objectives or override the returned optimizer status.
- Do not assume objectives from different engines are directly comparable.
- Test one polydisperse model.
- Test one form-factor/structure-factor model.
- Test one additive composite using discovered parameter names.

8. Optimizer pass-through

- Submit one valid engine-specific option through `fit.options`.
- Confirm that the option is accepted and echoed in the fit configuration. Do
  not claim that it reached an internal optimizer unless the response proves it.
- Submit one unsupported optimizer method once and confirm that the resulting `sans-fitter` error is transported clearly.
- Do not retry the identical invalid request.

9. Bayesian fitting

- Run a small diagnostic DREAM fit on seeded simulated data.
- Use measured simulated uncertainties.
- Report requested settings and the posterior summary returned by `sans-fitter`.
- Report R-hat and ESS exactly when present.
- Do not invent convergence thresholds or add an independent convergence decision.
- Do not request the posterior chain unless needed to diagnose transport.

10. Model-free P(r)

- Run a bounded Dmax scan and report the returned Rg/I(0) and data chi-squared values. Sans-fitter documents a good Dmax as showing an Rg/I(0) plateau and a minimum in data chi-squared.
- Run automatic P(r) inversion using a Dmax selected from those returned scan quantities.
- Run one manual inversion using an `(n_terms, alpha)` pair returned by the tools.
- Report Dmax, Rg, I(0), alpha, basis terms, background, data chi-squared, effective degrees of freedom, oscillation, positivity, condition/rank diagnostics, and dependency warnings.
- Do not add an independent alpha-stability rule or recompute fit statistics.

11. Error propagation
    Perform each invalid call only once:

- an unknown model name;
- an invalid parameter name;
- mismatched arithmetic Q grids, if suitable inputs can be generated;
- an unsupported fit engine or method;
- an invalid P(r) configuration.
  Report the error origin only when it is explicit in the response; otherwise mark it as unknown. The preferred behavior for scientific validation is a clear propagated dependency error.

12. Concurrency and worker-capacity behavior
    If parallel tool calls are supported:

- issue several simultaneous inspections of the same upload;
- start at least three scientific worker operations in parallel, such as two fits and one P(r) inversion, so the configured two-worker capacity is exceeded;
- while those operations are active, issue one lightweight discovery or inspection call and confirm that the server remains responsive;
- confirm that all scientific calls eventually complete, with excess calls waiting rather than failing because no worker slot is available;
- mix inspection, processing, fitting, and inversion requests using the same source;
- confirm there are no transient “No datasets were found” failures, warning leakage, workspace collisions, or artifact-token collisions;
- report the observed completion order and elapsed times when available, but do not infer exact queue internals from timing alone.

13. Cancellation behavior

- Do not attempt to test the chat Stop button inside this same full-report run, because stopping the run also prevents the report from completing.
- State that cancellation requires a separate operator-assisted test: start a deliberately long fit, click Stop while it is running, then verify from server logs and process metrics that the scientific worker process terminates promptly and its partial workspace is removed.
- Distinguish cancellation of a running worker from cancellation while waiting for a worker slot.

14. Persistent artifact and browser-download behavior

- Near the end of the test, call `read-sans-artifact` again with the image and CSV URIs retained from earlier sections. Confirm that both still resolve after intervening tool calls and return browser download URLs byte-for-byte identical to the originals.
- Confirm that MCP artifact access remains user-scoped; do not attempt to inspect another user's artifacts. Note that browser download URLs are non-expiring bearer capabilities in the first implementation.
- Ask the operator to alter one signature character and one filename path component, once each, and confirm that neither modified URL returns an artifact. Do not paste modified URLs into the report.
- State that process/pod-restart persistence requires a separate operator-assisted test: retain the artifact URIs and browser links, restart the sans-pilot container or Kubernetes deployment without rotating `SANS_PILOT_DOWNLOAD_SIGNING_KEY`, start a new turn as the same user, call `read-sans-artifact` with the retained URIs, and click the original browser links.
- In Kubernetes, verify that an artifact created before a replica restart can still be read and downloaded afterward, demonstrating that the file and token manifest are on shared persistent storage and the signing key is stable.
- Do not request or perform automatic artifact deletion. Report storage persistence separately from client chat-history retention.

Produce a concise final report containing:

- tools exercised;
- passed functionality;
- failed functionality;
- exact reproducible requests for failures;
- explicit error origin, or `unknown` when the response does not identify it;
- internal artifact URI, `read-sans-artifact`, browser-download link, chunking, tamper rejection, and persistence behavior;
- concurrency and worker-queue results;
- whether the separate operator-assisted cancellation and restart-persistence tests are still required;
- scientific caveats exactly as returned by `sans-fitter`;
- a prioritized issue list.

Do not treat different optimizer objective values as equivalent unless the returned metadata explicitly establishes the same normalization. Do not modify uploaded data or add scientific conclusions that are not present in the returned results or documented by `sans-fitter`. Redact complete download URLs, signatures, artifact tokens, user identifiers, and internal service addresses from any saved report.
