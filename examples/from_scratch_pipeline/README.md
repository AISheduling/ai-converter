# From-Scratch Pipeline Example

This example shows the full `ai-converter` path starting from several small JSON inputs and a local `Pydantic` target model.

It demonstrates:

- how several source JSON files become one deterministic profiling baseline
- how those source examples can include nested arrays and objects inside arrays without changing the core walkthrough
- how a target `Pydantic` model becomes a `TargetSchemaCard`
- how the current LLM-backed synthesis layer produces a `SourceSchemaSpec` and `MappingIR`
- how that `MappingIR` becomes a compiled `ConverterPackage`
- how the compiled converter is used on a fresh record and validated structurally
- how a drifted source dataset is profiled and classified without live repair loops

## Files

- `run_example.py`: runnable end-to-end example
- `source_samples/*.json`: baseline source examples used to build the converter
- `convert_record.json`: fresh record converted by the compiled package
- `drift_samples/*.json`: candidate source data used for drift detection

The shipped JSON examples intentionally contain richer source structure, including:

- top-level arrays such as `labels`
- arrays of objects such as `subtasks` and `milestones`
- nested arrays inside those objects such as `subtasks[].notes` and `milestones[].owners`

The walkthrough still maps only the core flat fields into the target payload so the end-to-end flow stays easy to follow.

## Configure The Example

`run_example.py` keeps the OpenAI-compatible connection settings as constants near the top of the file:

- `OPENAI_BASE_URL`
- `OPENAI_API_TOKEN`
- `OPENAI_MODEL`

Replace the token and endpoint values before using a live OpenAI-compatible service.

The same code path also accepts an injected fake client, so repository tests can run offline without network access.

## Run The Example

From the repository root:

```bash
python examples/from_scratch_pipeline/run_example.py
```

By default the script writes generated artifacts under `examples/from_scratch_pipeline/generated/`.

The exported `converter_package/` directory contains:

- `manifest.json`: the machine-readable package description and focused validation metadata
- `from_scratch_converter.py`: the generated converter module that executes the compiled `MappingIR`
- `mapping_ir.json`: the normalized `MappingIR` payload that was compiled into the generated module

## Step Order And Why Each Step Exists

1. Combine `source_samples/*.json` into one baseline dataset.
   Why: profiling and prompt generation expect one deterministic source evidence bundle, but real onboarding often starts from several small example payloads.
2. Build a `ProfileReport` from that combined baseline.
   Why: the profile captures stable field statistics, representative samples, and a schema fingerprint that the later schema and drift stages can reuse.
3. Build a `TargetSchemaCard` from the local `Pydantic` model.
   Why: the synthesis step needs a compact machine-readable description of the target contract, not only the Python class.
4. Create `OpenAILLMAdapter` with the example-local `base_url`, `api_token`, and `model` constants.
   Why: this is the live synthesis entry point when you want the example to talk to a real OpenAI-compatible endpoint.
5. Run `MappingSynthesizer.synthesize_source_schema(...)`.
   Why: this turns the profile evidence into an explicit `SourceSchemaSpec` that later stages can validate and compare during drift detection.
6. Run `MappingSynthesizer.synthesize_mapping(...)`.
   Why: this produces the `MappingIR` program that describes how source fields become target fields.
7. Select the best mapping candidate and normalize narrow recoverable reference mistakes when needed.
   Why: some live OpenAI-compatible responses can parse as `MappingIR` but still confuse source-field names, target paths, and step ids; the example repairs only those deterministic reference-shape mistakes before crossing the compile boundary.
8. Validate and compile the `MappingIR`.
   Why: validation catches any remaining structural mistakes before code generation, and compilation produces a reusable `ConverterPackage` with exportable artifacts.
9. Convert `convert_record.json` and validate the result against the target `Pydantic` model.
   Why: this proves the compiled converter works on a fresh input record, not only on the synthesis inputs.
10. Build a profile for `drift_samples/*.json`, classify the drift, and write the heuristic resolution.
   Why: after the first converter exists, the next operational question is whether new source data is still compatible or needs a local patch or a full rebuild.
11. Apply the compatible patch with `apply_converter_patch(...)` and persist the patched schema and patched `MappingIR`.
   Why: compatible drift is only actionable once the example shows the concrete local artifacts you would carry forward instead of regenerating the whole converter from scratch.

## Generated Artifacts

The script writes the most important intermediate artifacts so you can inspect each phase directly:

- `combined_baseline.json`
- `baseline_profile.json`
- `target_schema_card.json`
- `llm_source_schema_trace.json`
- `source_schema.json`
- `mapping_candidate_0.trace.json`
- `mapping_selection.json`
- `mapping_ir.json`
- `mapping_validation.json`
- `converter_package/`
- `converted_payload.json`
- `structural_validation.json`
- `combined_drift_candidate.json`
- `drift_profile.json`
- `drift_report.json`
- `drift_resolution.json`
- `drift_patch.json`
- `patched_source_schema.json`
- `patched_mapping_ir.json`
- `summary.json`

## Offline Verification

Repository tests run the same example path with an injected fake OpenAI client instead of a live network call.

That offline seam also covers two live-robustness cases:

- strict `json_schema` rejection from an OpenAI-compatible proxy, which falls back to plain `json_object` mode and is still validated locally;
- semantically sloppy but parseable `MappingIR` candidates, where the example rewrites only recoverable reference mistakes such as source names being used where step ids are required.

Focused smoke command:

```bash
python -m pytest tests/integration/converter_pipeline -q -p no:cacheprovider
```
