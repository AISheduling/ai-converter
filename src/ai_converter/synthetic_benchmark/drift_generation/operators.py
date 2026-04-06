"""Deterministic record-level operators for synthetic drift generation."""

from __future__ import annotations

import copy
from typing import Any

from .models import (
    AddFieldOperator,
    ChangeEnumSurfaceOperator,
    ChangeValueFormatOperator,
    DropOptionalFieldOperator,
    FlattenFieldOperator,
    InjectSparseObjectsOperator,
    MergeFieldsOperator,
    NestFieldOperator,
    RenameFieldOperator,
    SplitFieldOperator,
    SyntheticDriftOperator,
)


def apply_operator_to_records(
    records: list[dict[str, Any]],
    operator: SyntheticDriftOperator,
) -> list[int]:
    """Apply one deterministic drift operator in place.

    Args:
        records: Mutable rendered records extracted from one `L0` payload.
        operator: Operator to apply.

    Returns:
        Concrete record indexes targeted by the operator.
    """

    indexes = _resolve_indexes(records, operator.record_indexes)
    if isinstance(operator, InjectSparseObjectsOperator):
        for index in indexes:
            _apply_inject_sparse_object(records[index], operator)
        return indexes

    for index in indexes:
        record = records[index]
        if isinstance(operator, AddFieldOperator):
            _set_nested(record, operator.path, copy.deepcopy(operator.value))
        elif isinstance(operator, DropOptionalFieldOperator):
            _pop_nested(record, operator.path)
        elif isinstance(operator, RenameFieldOperator):
            found, value = _pop_nested(record, operator.path)
            if found:
                _set_nested(record, operator.new_path, value)
        elif isinstance(operator, NestFieldOperator):
            found, value = _pop_nested(record, operator.path)
            if found:
                _set_nested(record, operator.new_path, value)
        elif isinstance(operator, FlattenFieldOperator):
            found, value = _pop_nested(record, operator.path)
            if found:
                _set_nested(record, operator.new_path, value)
        elif isinstance(operator, SplitFieldOperator):
            _apply_split(record, operator)
        elif isinstance(operator, MergeFieldsOperator):
            _apply_merge(record, operator)
        elif isinstance(operator, ChangeValueFormatOperator):
            _apply_value_format(record, operator)
        elif isinstance(operator, ChangeEnumSurfaceOperator):
            _apply_enum_surface(record, operator)
        else:
            raise TypeError(f"Unsupported operator kind: {operator.kind}")
    return indexes


def changed_paths_for_operator(operator: SyntheticDriftOperator) -> list[str]:
    """Return the primary paths affected by one operator.

    Args:
        operator: Operator to inspect.

    Returns:
        Stable list of changed field paths.
    """

    if isinstance(operator, AddFieldOperator):
        return [operator.path]
    if isinstance(operator, DropOptionalFieldOperator):
        return [operator.path]
    if isinstance(operator, RenameFieldOperator):
        return [operator.path, operator.new_path]
    if isinstance(operator, NestFieldOperator):
        return [operator.path, operator.new_path]
    if isinstance(operator, FlattenFieldOperator):
        return [operator.path, operator.new_path]
    if isinstance(operator, SplitFieldOperator):
        return [operator.path, *operator.new_paths]
    if isinstance(operator, MergeFieldsOperator):
        return [*operator.paths, operator.new_path]
    if isinstance(operator, ChangeValueFormatOperator):
        return [operator.path]
    if isinstance(operator, ChangeEnumSurfaceOperator):
        return [operator.path]
    if isinstance(operator, InjectSparseObjectsOperator):
        return list(operator.keep_paths)
    raise TypeError(f"Unsupported operator kind: {operator.kind}")


def _resolve_indexes(
    records: list[dict[str, Any]],
    record_indexes: list[int],
) -> list[int]:
    """Resolve the record scope for one operator.

    Args:
        records: Candidate record list.
        record_indexes: Optional explicit record indexes.

    Returns:
        Concrete in-range indexes to mutate.
    """

    if not record_indexes:
        return list(range(len(records)))
    return [index for index in record_indexes if index < len(records)]


def _apply_split(record: dict[str, Any], operator: SplitFieldOperator) -> None:
    """Split one scalar field into multiple output paths.

    Args:
        record: Record to mutate.
        operator: Split operator definition.
    """

    found, raw_value = _pop_nested(record, operator.path)
    if not found:
        return
    pieces = str(raw_value).split(operator.separator, maxsplit=1)
    if len(pieces) < len(operator.new_paths):
        pieces.extend("" for _ in range(len(operator.new_paths) - len(pieces)))
    for target_path, piece in zip(operator.new_paths, pieces, strict=False):
        _set_nested(record, target_path, piece)


def _apply_merge(record: dict[str, Any], operator: MergeFieldsOperator) -> None:
    """Merge multiple source fields into one output path.

    Args:
        record: Record to mutate.
        operator: Merge operator definition.
    """

    values: list[str] = []
    for path in operator.paths:
        found, value = _pop_nested(record, path)
        if not found:
            continue
        values.append(str(value))
    if not values:
        return
    _set_nested(record, operator.new_path, operator.separator.join(values))


def _apply_value_format(record: dict[str, Any], operator: ChangeValueFormatOperator) -> None:
    """Apply a deterministic value-format conversion to one field.

    Args:
        record: Record to mutate.
        operator: Value-format operator definition.
    """

    found, value = _pop_nested(record, operator.path)
    if not found:
        return
    if operator.format_style == "duration_text" and isinstance(value, (int, float)) and not isinstance(value, bool):
        integer_value = int(value)
        formatted = f"{integer_value} day" if integer_value == 1 else f"{integer_value} days"
    elif operator.format_style == "duration_iso" and isinstance(value, (int, float)) and not isinstance(value, bool):
        formatted = f"P{int(value)}D"
    else:
        formatted = str(value)
    _set_nested(record, operator.path, formatted)


def _apply_enum_surface(record: dict[str, Any], operator: ChangeEnumSurfaceOperator) -> None:
    """Rewrite one enum-like field using a fixed mapping.

    Args:
        record: Record to mutate.
        operator: Enum-surface operator definition.
    """

    found, value = _pop_nested(record, operator.path)
    if not found:
        return
    replacement = operator.mapping.get(str(value), str(value))
    _set_nested(record, operator.path, replacement)


def _apply_inject_sparse_object(
    record: dict[str, Any],
    operator: InjectSparseObjectsOperator,
) -> None:
    """Reduce one record to a sparse subset of fields.

    Args:
        record: Record to mutate.
        operator: Sparse-object operator definition.
    """

    sparse_record: dict[str, Any] = {}
    for path in operator.keep_paths:
        value = _get_nested(record, path)
        if value is None:
            continue
        _set_nested(sparse_record, path, copy.deepcopy(value))
    record.clear()
    record.update(sparse_record)


def _parent_for_path(
    record: dict[str, Any],
    path: str,
) -> tuple[dict[str, Any] | None, str]:
    """Resolve the parent container for a dotted path.

    Args:
        record: Record to inspect.
        path: Dotted path to resolve.

    Returns:
        A tuple of `(parent_container, leaf_key)`. The parent container is
        `None` when the path cannot be resolved.
    """

    segments = [segment for segment in path.split(".") if segment]
    if not segments:
        return None, ""
    current: dict[str, Any] = record
    for segment in segments[:-1]:
        candidate = current.get(segment)
        if not isinstance(candidate, dict):
            return None, segments[-1]
        current = candidate
    return current, segments[-1]


def _set_nested(record: dict[str, Any], path: str, value: Any) -> None:
    """Set one dotted path in a nested dictionary structure.

    Args:
        record: Record to mutate.
        path: Dotted path to populate.
        value: Value to assign.
    """

    segments = [segment for segment in path.split(".") if segment]
    if not segments:
        return
    current = record
    for segment in segments[:-1]:
        candidate = current.get(segment)
        if not isinstance(candidate, dict):
            candidate = {}
            current[segment] = candidate
        current = candidate
    current[segments[-1]] = value


def _pop_nested(record: dict[str, Any], path: str) -> tuple[bool, Any]:
    """Pop one dotted path from a nested dictionary structure.

    Args:
        record: Record to mutate.
        path: Dotted path to remove.

    Returns:
        A tuple of `(found, value)`.
    """

    parent, leaf = _parent_for_path(record, path)
    if parent is None or leaf not in parent:
        return False, None
    return True, parent.pop(leaf)


def _get_nested(record: dict[str, Any], path: str) -> Any:
    """Return one dotted-path value from a nested dictionary structure.

    Args:
        record: Record to inspect.
        path: Dotted path to resolve.

    Returns:
        The resolved value, or `None` when the path is absent.
    """

    segments = [segment for segment in path.split(".") if segment]
    current: Any = record
    for segment in segments:
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current
