# Synthetic Benchmark Foundation

`TASK-Bench-01` established the deterministic base bundle workflow under
`src/ai_converter/synthetic_benchmark/`. `TASK-Bench-02` extends that same
package with heterogeneous `L0` rendering, synthetic drift generation, and
lineage-aware drift bundle persistence.

## Design Rules

- `CanonicalScenario` remains the single source of truth.
- `render_l1_payload(...)` continues to produce the gold target payload.
- `render_l0_payload(...)` can now project the same scenario into multiple
  deterministic source-side shapes through template-level shape variants.
- `LLMTemplateGenerator` can synthesize additional `L0TemplateSpec` candidates
  through the shared `ai_converter.llm` boundary, but the generated output is
  still only a template surface layered on top of the same canonical scenario.
- Synthetic drift mutates only `L0` bundle surfaces. It does not change the
  canonical scenario and does not require live models or network access.
- Drift bundles keep explicit lineage back to a parent base bundle.

## Package Layout

- `scenario/models.py`: canonical task/scenario models and sampler metadata
- `templates/common.py`: shared alias and optional-field contracts
- `templates/models.py`: `L0TemplateSpec`
- `templates/shape_variants.py`: deterministic same-type record variants
- `generators/deterministic/scenario_sampler.py`: seeded deterministic sampling
- `generators/llm/`: prompt building, validation gates, accepted-template cache,
  and bounded LLM-assisted template generation
- `renderers/l1_renderer.py`: canonical `L1` projection
- `renderers/l0_renderer.py`: template-driven and shape-aware `L0` projection
- `drift_generation/models.py`: versioned drift specs and applied manifests
- `drift_generation/operators.py`: deterministic record-level drift operators
- `drift_generation/apply.py`: high-level drift application helper
- `storage/models.py`: bundle, metadata, manifest, and lineage-aware models
- `storage/lineage.py`: parent/child drift lineage metadata
- `storage/bundle_store.py`: deterministic JSON persistence helpers

## Persistence Layout

Each base bundle keeps the deterministic foundation layout:

```text
<bundle_dir>/
|-- scenario.json
|-- template.json
|-- l0.json
|-- l1.json
|-- manifest.json
`-- metadata.json
```

Drift bundles keep the same base files and add deterministic drift-sidecar
artifacts:

```text
<drift_bundle_dir>/
|-- scenario.json
|-- template.json
|-- l0.json
|-- l1.json
|-- manifest.json
|-- metadata.json
|-- drift_manifest.json
`-- lineage.json
```

`manifest.json` is the explicit bundle-level artifact index for the persisted
layout, while `metadata.json` keeps reproducibility and identity fields such as
the seed, template source, generator version, and bundle kind.

`lineage.json` links the drift bundle back to its parent bundle through
`parent_bundle_id`, `drift_type`, `severity`, `operator_sequence`, and
`compatibility_class`.

## Verification

Focused command:

```bash
python -m pytest tests/unit/synthetic_benchmark -q -p no:cacheprovider
```

The package remains intentionally offline-only. Synthetic drift exists to
produce reproducible `L0` changes and lineage artifacts, not to replace the
shared `ai_converter.drift` classifier or later benchmark/reporting tasks.
LLM-assisted template generation follows the same rule: tests stay offline
through fake adapters and cached trace artifacts.
