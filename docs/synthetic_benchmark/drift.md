# Synthetic Drift Generation

Synthetic drift generation lives under
`src/ai_converter/synthetic_benchmark/drift_generation/`.

Its job is narrow:

- take a deterministic base `L0` payload
- apply a versioned, deterministic operator sequence
- persist the resulting drift bundle with lineage metadata

It does not call live models, does not hit the network, and does not replace
the shared `ai_converter.drift` classifier or patch APIs.

## Supported Operator Surface

The current synthetic drift layer supports deterministic operators for:

- `add_field`
- `drop_optional_field`
- `rename_field`
- `nest_field`
- `flatten_field`
- `split_field`
- `merge_fields`
- `change_value_format`
- `change_enum_surface`
- `inject_sparse_objects`

Operators are record-scoped through `record_indexes`, so the same base bundle
can deterministically produce low-, medium-, and high-severity drifted `L0`
surfaces.

## Compatibility And Lineage

Each `DriftSpec` carries:

- `drift_id`
- `drift_type`
- `severity`
- `compatibility_class`
- ordered `operators`

Each persisted drift bundle carries:

- `drift_manifest.json`
- `lineage.json`

`lineage.json` records:

- `parent_bundle_id`
- `drift_id`
- `drift_type`
- `severity`
- `operator_sequence`
- `compatibility_class`

Compatible drift keeps traceability to the same canonical scenario and reuses
the base bundle's gold `L1` payload. Higher-severity drift still keeps lineage
but is expected to change the `L0` structure materially.

## Verification

Focused command:

```bash
python -m pytest tests/unit/synthetic_benchmark -q -p no:cacheprovider
```

Synthetic drift fixtures live under `tests/fixtures/synthetic_benchmark/drift/`.
