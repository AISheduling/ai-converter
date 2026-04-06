"""Synthetic benchmark foundation for deterministic L0/L1 bundle generation."""

from .drift_generation import (
    AddFieldOperator,
    AppliedDriftManifest,
    ChangeEnumSurfaceOperator,
    ChangeValueFormatOperator,
    DriftSpec,
    DropOptionalFieldOperator,
    FlattenFieldOperator,
    InjectSparseObjectsOperator,
    MergeFieldsOperator,
    NestFieldOperator,
    RenameFieldOperator,
    SplitFieldOperator,
    apply_drift_to_payload,
)
from .generators.deterministic.scenario_sampler import sample_canonical_scenario
from .renderers.l0_renderer import render_l0_payload
from .renderers.l1_renderer import render_l1_payload
from .scenario import (
    CanonicalScenario,
    CanonicalTask,
    DeterministicScenarioMetadata,
    SampledScenario,
    ScenarioSamplerConfig,
)
from .storage import BundleStore, BundleStoreExport, DatasetBundle, DatasetBundleMetadata, DriftLineage
from .templates import (
    L0TemplateSpec,
    ShapeVariantPolicy,
    ShapeVariantSpec,
    TaskFieldAliases,
    select_shape_variant,
)

__all__ = [
    "AddFieldOperator",
    "AppliedDriftManifest",
    "BundleStore",
    "BundleStoreExport",
    "CanonicalScenario",
    "CanonicalTask",
    "ChangeEnumSurfaceOperator",
    "ChangeValueFormatOperator",
    "DatasetBundle",
    "DatasetBundleMetadata",
    "DeterministicScenarioMetadata",
    "DriftLineage",
    "DriftSpec",
    "DropOptionalFieldOperator",
    "FlattenFieldOperator",
    "InjectSparseObjectsOperator",
    "L0TemplateSpec",
    "MergeFieldsOperator",
    "NestFieldOperator",
    "RenameFieldOperator",
    "SampledScenario",
    "ScenarioSamplerConfig",
    "ShapeVariantPolicy",
    "ShapeVariantSpec",
    "SplitFieldOperator",
    "TaskFieldAliases",
    "apply_drift_to_payload",
    "render_l0_payload",
    "render_l1_payload",
    "sample_canonical_scenario",
    "select_shape_variant",
]
