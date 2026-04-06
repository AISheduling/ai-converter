# Synthetic Benchmark Foundation

`TASK-Bench-01` introduces the deterministic foundation for synthetic benchmark
artifacts under `src/ai_converter/synthetic_benchmark/`.

## Design

The package follows one simple rule:

- `CanonicalScenario` is the source of truth.
- `render_l1_payload(...)` produces the gold target payload.
- `render_l0_payload(...)` projects the same scenario into a configurable source-side JSON surface.
- `BundleStore` persists the scenario, template, `L0`, `L1`, and metadata as a repo-local bundle directory.

## Package Layout

- `scenario/models.py`: canonical task/scenario models and sampler metadata
- `templates/models.py`: `L0TemplateSpec` and alias configuration
- `generators/deterministic/scenario_sampler.py`: seeded deterministic sampling
- `renderers/l1_renderer.py`: canonical `L1` projection
- `renderers/l0_renderer.py`: template-driven `L0` projection
- `storage/models.py`: bundle and metadata models
- `storage/bundle_store.py`: deterministic JSON persistence helpers

## Persistence Layout

Each saved bundle uses a stable directory layout:

```text
<bundle_dir>/
├─ scenario.json
├─ template.json
├─ l0.json
├─ l1.json
└─ metadata.json
```

## Verification

Focused command:

```bash
python -m pytest tests/unit/synthetic_benchmark -q -p no:cacheprovider
```

The package is intentionally offline-only. `TASK-Bench-01` does not implement
drift generation, LLM template synthesis, or the benchmark harness itself.
