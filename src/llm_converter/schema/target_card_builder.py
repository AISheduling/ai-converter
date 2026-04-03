"""Export nested Pydantic models into compact target schema cards."""

from __future__ import annotations

from enum import Enum
from types import NoneType, UnionType
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import PydanticUndefined

from .target_card_models import TargetFieldCard, TargetSchemaCard


def build_target_schema_card(model_type: type[BaseModel]) -> TargetSchemaCard:
    """Build a compact schema card from a Pydantic model class."""

    return TargetSchemaCard(
        model_name=model_type.__name__,
        module_name=model_type.__module__,
        description=_clean_docstring(model_type.__doc__),
        fields=[_build_field_card(name, field_info.annotation, field_info, name) for name, field_info in model_type.model_fields.items()],
    )


def _build_field_card(name: str, annotation: Any, field_info: Any, path: str) -> TargetFieldCard:
    base_annotation, required = _unwrap_optional(annotation, field_info.is_required())
    nested_model = _extract_model(base_annotation)
    enum_values = _extract_enum_values(base_annotation)
    children = []
    if nested_model is not None:
        children = [
            _build_field_card(
                child_name,
                child_info.annotation,
                child_info,
                f"{path}.{child_name}",
            )
            for child_name, child_info in nested_model.model_fields.items()
        ]

    description = field_info.description
    if description is None:
        extra = getattr(field_info, "json_schema_extra", None) or {}
        description = extra.get("description")

    default = None if field_info.default is PydanticUndefined else field_info.default
    return TargetFieldCard(
        name=name,
        path=path,
        type_label=_render_type_label(base_annotation),
        required=required,
        description=description,
        default=_stringify_default(default),
        enum_values=enum_values,
        children=children,
    )


def _unwrap_optional(annotation: Any, required: bool) -> tuple[Any, bool]:
    origin = get_origin(annotation)
    if origin in (UnionType, getattr(__import__("typing"), "Union")):
        args = [arg for arg in get_args(annotation) if arg is not NoneType]
        if len(args) == 1 and len(args) != len(get_args(annotation)):
            return args[0], False
    return annotation, required


def _extract_model(annotation: Any) -> type[BaseModel] | None:
    origin = get_origin(annotation)
    if origin in (list, tuple, set):
        args = get_args(annotation)
        return _extract_model(args[0]) if args else None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _extract_enum_values(annotation: Any) -> list[str]:
    origin = get_origin(annotation)
    if origin is Literal:
        return sorted(str(value) for value in get_args(annotation))
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return sorted(str(member.value) for member in annotation)
    return []


def _render_type_label(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is Literal:
        return "literal"
    if origin in (list, tuple, set):
        args = get_args(annotation)
        inner = _render_type_label(args[0]) if args else "any"
        return f"list[{inner}]"
    if origin in (dict,):
        args = get_args(annotation)
        key_label = _render_type_label(args[0]) if args else "any"
        value_label = _render_type_label(args[1]) if len(args) > 1 else "any"
        return f"dict[{key_label}, {value_label}]"
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation).replace("typing.", "")


def _stringify_default(default: Any) -> Any:
    if default is None:
        return None
    if isinstance(default, (str, int, float, bool)):
        return default
    return repr(default)


def _clean_docstring(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
