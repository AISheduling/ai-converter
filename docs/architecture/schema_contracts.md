"""Architecture notes for schema contracts."""

# Schema Contracts

Schema contracts add a schema-first bridge between profiling outputs and future LLM-driven synthesis steps.

## Package layout

- `src/ai_converter/schema/source_spec_models.py`: canonical `SourceSchemaSpec` and `SourceFieldSpec` models.
- `src/ai_converter/schema/source_spec_normalizer.py`: deterministic normalization for field names, aliases, and examples.
- `src/ai_converter/schema/source_spec_aggregator.py`: deterministic merge/post-processing for multiple source-schema candidates.
- `src/ai_converter/schema/target_card_models.py`: compact prompt-oriented card models for the fixed L1 schema.
- `src/ai_converter/schema/target_card_builder.py`: recursive exporter from nested Pydantic models to `TargetSchemaCard`.
- `src/ai_converter/schema/evidence_packer.py`: budgeted deterministic packing of a `ProfileReport` into a compact fact bundle.

## Design constraints

- `dsl-core/` is read-only and treated as the external L1 reference library.
- `TargetSchemaCard` is intentionally compact; it preserves nested structure, required flags, descriptions, defaults, and enum/literal values without dumping the full JSON schema.
- `SourceSchemaSpec` aggregation is deterministic and input-order independent.
- Evidence packing uses a deterministic character-budget approximation instead of tokenizer-specific accounting.
- If the mandatory summary alone cannot fit the requested budget, `pack_profile_evidence()` raises `EvidenceBudgetExceededError` instead of returning an oversized bundle.

## Minimal flow

The normal schema-contract handoff looks like this:

1. Start from a deterministic `ProfileReport`.
2. Normalize or merge source-side fields into one `SourceSchemaSpec`.
3. Export the target `Pydantic` model into a compact `TargetSchemaCard`.
4. Pack the profiling report into a bounded evidence bundle for later prompt rendering.

```python
from pydantic import BaseModel, Field

from ai_converter.profiling import build_profile_report
from ai_converter.schema import build_target_schema_card, pack_profile_evidence


class DemoTask(BaseModel):
    id: str = Field(description="Task identifier")


report = build_profile_report("tests/fixtures/profiling/projects.json")
card = build_target_schema_card(DemoTask)
bundle = pack_profile_evidence(report, budget=1400, mode="balanced")

print(report.schema_fingerprint)
print(card.model_name)
print(bundle.summary.field_count)
```

## Focused verification

Run the schema-focused test suite with:

```bash
python -m pytest tests/unit/schema -q -p no:cacheprovider
```

Schema fixtures live in `tests/fixtures/schema/`.
