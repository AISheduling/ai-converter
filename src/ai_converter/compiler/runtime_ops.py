"""Pure runtime helpers used by generated MappingIR converter modules."""

from __future__ import annotations

import ast
import copy
import operator
from collections.abc import Callable, Mapping, Sequence
from typing import Any

DROP_SENTINEL = object()


class UnsafeExpressionError(ValueError):
    """Raised when a derive or predicate expression uses a disallowed construct."""


def get_path_value(payload: Any, path: str) -> Any:
    """Resolve a dotted source or target path against a Python payload.

    The resolver supports dotted object paths, numeric list indices, and list
    wildcards in the form ``items[].id``.

    Args:
        payload: Input object to resolve against.
        path: Canonical dotted path to resolve.

    Returns:
        The resolved value, ``None`` when a scalar branch is missing, or an empty
        list when a wildcard branch is missing.
    """

    if not path:
        return payload
    return _resolve_segments(payload, path.split("."))


def assign_path(target: dict[str, Any], path: str, value: Any, *, allow_overwrite: bool = False) -> None:
    """Assign one value into a nested dictionary target path.

    Args:
        target: Mutable target dictionary that receives the converted value.
        path: Canonical dotted target path.
        value: Value to assign. The drop sentinel is ignored.
        allow_overwrite: Whether an existing value may be overwritten.

    Returns:
        None.

    Raises:
        ValueError: If the assignment conflicts with an existing value.
    """

    if value is DROP_SENTINEL:
        return

    cursor: dict[str, Any] = target
    parts = path.split(".")
    traversed_parts: list[str] = []
    for part in parts[:-1]:
        traversed_parts.append(part)
        next_value = cursor.get(part)
        if next_value is None:
            next_value = {}
            cursor[part] = next_value
        elif not isinstance(next_value, dict):
            ancestor_path = ".".join(traversed_parts)
            raise ValueError(
                f"target path {path!r} conflicts with existing parent value at {ancestor_path!r}"
            )
        cursor = next_value

    final_key = parts[-1]
    if final_key in cursor and not allow_overwrite and cursor[final_key] != value:
        raise ValueError(f"target path {path!r} already has a different value")
    cursor[final_key] = copy.deepcopy(value)


def copy_value(value: Any) -> Any:
    """Return a defensive copy of one runtime value.

    Args:
        value: Runtime value to copy.

    Returns:
        A deep copy of the value.
    """

    return copy.deepcopy(value)


def cast_value(value: Any, to_type: str) -> Any:
    """Cast one runtime value into a supported target scalar type.

    Args:
        value: Runtime value to cast.
        to_type: Target type label such as ``int`` or ``bool``.

    Returns:
        The converted value, preserving ``None`` when the input is missing.
    """

    if value is None:
        return None
    if isinstance(value, list):
        return [cast_value(item, to_type) for item in value]

    normalized = to_type.strip().lower()
    if normalized == "str":
        return str(value)
    if normalized == "int":
        return int(float(value))
    if normalized == "float":
        return float(value)
    if normalized == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"true", "1", "yes", "y"}:
            return True
        if text in {"false", "0", "no", "n"}:
            return False
        raise ValueError(f"cannot cast {value!r} to bool")
    if normalized == "list":
        return list(value) if isinstance(value, Sequence) and not isinstance(value, str) else [value]
    if normalized == "dict":
        if isinstance(value, Mapping):
            return dict(value)
        raise ValueError(f"cannot cast {type(value).__name__} to dict")
    raise ValueError(f"unsupported cast target {to_type!r}")


def map_enum_value(value: Any, mapping: dict[str, Any]) -> Any:
    """Map one enum-like value through a deterministic lookup table.

    Args:
        value: Runtime enum value to translate.
        mapping: Mapping table keyed by stringified source values.

    Returns:
        The mapped value or the original value when no explicit mapping exists.
    """

    if value is None:
        return None
    if isinstance(value, list):
        return [map_enum_value(item, mapping) for item in value]
    return copy.deepcopy(mapping.get(str(value), value))


def unit_convert_value(value: Any, factor: float, *, from_unit: str | None = None, to_unit: str | None = None) -> Any:
    """Apply a deterministic scale-factor unit conversion.

    Args:
        value: Runtime numeric value or collection of numeric values.
        factor: Multiplicative conversion factor.
        from_unit: Optional source-unit label for diagnostics.
        to_unit: Optional target-unit label for diagnostics.

    Returns:
        The scaled numeric value or collection.
    """

    if value is None:
        return None
    if isinstance(value, list):
        return [unit_convert_value(item, factor, from_unit=from_unit, to_unit=to_unit) for item in value]

    scaled = float(value) * factor
    if isinstance(value, int) and float(scaled).is_integer():
        return int(scaled)
    return scaled


def split_value(value: Any, delimiter: str) -> list[str]:
    """Split one scalar value into a deterministic list of string parts.

    Args:
        value: Scalar value to split.
        delimiter: Delimiter used to break the string.

    Returns:
        A list of stripped, non-empty string parts.
    """

    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [part.strip() for part in str(value).split(delimiter) if part.strip()]


def merge_values(values: list[Any], delimiter: str) -> str:
    """Merge a value collection into one delimited string.

    Args:
        values: Runtime values to join together.
        delimiter: Delimiter inserted between parts.

    Returns:
        The merged string.
    """

    flattened: list[str] = []
    for value in values:
        if value is None or value is DROP_SENTINEL:
            continue
        if isinstance(value, list):
            flattened.extend(str(item) for item in value if item is not None)
            continue
        flattened.append(str(value))
    return delimiter.join(flattened)


def nest_values(values: dict[str, Any]) -> dict[str, Any]:
    """Combine step outputs into one nested dictionary payload.

    Args:
        values: Named runtime values keyed by their declared semantic child keys.

    Returns:
        A nested dictionary payload that preserves the declared child keys.
    """

    nested: dict[str, Any] = {}
    for key, value in values.items():
        if value is None or value is DROP_SENTINEL:
            continue
        nested[key] = copy.deepcopy(value)
    return nested


def unnest_value(value: Any, child_path: str) -> Any:
    """Extract one child value from a nested payload.

    Args:
        value: Nested runtime value.
        child_path: Dotted child path inside the runtime value.

    Returns:
        The resolved child value.
    """

    return get_path_value(value, child_path)


def default_value(value: Any, default: Any) -> Any:
    """Replace a missing runtime value with a deterministic default.

    Args:
        value: Candidate runtime value.
        default: Default value applied when the candidate is empty.

    Returns:
        The original value when present, otherwise the provided default.
    """

    if value is None or value == "" or value == []:
        return copy.deepcopy(default)
    return copy.deepcopy(value)


def drop_value() -> Any:
    """Return the runtime drop sentinel used to skip target assignments.

    Args:
        None.

    Returns:
        The shared drop sentinel object.
    """

    return DROP_SENTINEL


def derive_value(expression: str, variables: dict[str, Any]) -> Any:
    """Evaluate one safe derive expression against runtime variables.

    Args:
        expression: Restricted expression string.
        variables: Runtime variable bindings exposed to the expression.

    Returns:
        The evaluated expression result.
    """

    return evaluate_expression(expression, variables)


def validate_value(value: Any, predicate: str, variables: dict[str, Any], *, message: str | None = None) -> Any:
    """Validate one runtime value against a restricted predicate expression.

    Args:
        value: Value being validated.
        predicate: Restricted boolean expression string.
        variables: Runtime variable bindings exposed to the predicate.
        message: Optional custom failure message.

    Returns:
        The original value when the predicate passes.

    Raises:
        ValueError: If the predicate evaluates to a falsey result.
    """

    context = dict(variables)
    context["value"] = value
    outcome = evaluate_expression(predicate, context)
    if bool(outcome):
        return value
    raise ValueError(message or f"validation predicate failed: {predicate}")


def check_condition(kind: str, value: Any, *, expected: Any = None, description: str | None = None) -> None:
    """Check one precondition or postcondition inside a generated converter.

    Args:
        kind: Condition kind such as ``exists`` or ``non_null``.
        value: Runtime value referenced by the condition.
        expected: Optional comparison value for equality checks.
        description: Optional human-readable description.

    Returns:
        None.

    Raises:
        ValueError: If the condition fails.
    """

    if kind == "exists" and value is None:
        raise ValueError(description or "required value does not exist")
    if kind == "non_null" and value is None:
        raise ValueError(description or "required value is null")
    if kind == "equals" and value != expected:
        raise ValueError(description or f"expected {expected!r}, got {value!r}")


def evaluate_expression(expression: str, variables: dict[str, Any]) -> Any:
    """Evaluate a restricted expression against runtime variables.

    Args:
        expression: Restricted expression string.
        variables: Runtime variable bindings exposed to the expression.

    Returns:
        The evaluated expression result.

    Raises:
        UnsafeExpressionError: If the expression uses a disallowed construct.
    """

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError(f"invalid expression syntax: {expression}") from exc
    evaluator = _SafeExpressionEvaluator(variables)
    return evaluator.visit(tree.body)


def validate_expression(expression: str, allowed_names: set[str]) -> None:
    """Validate restricted expression syntax and names without evaluating it.

    Args:
        expression: Restricted expression string.
        allowed_names: Runtime variable names exposed to the expression.

    Returns:
        None.

    Raises:
        UnsafeExpressionError: If the expression uses unsupported syntax or
            references a name outside the explicit runtime context.
    """

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError(f"invalid expression syntax: {expression}") from exc
    _SafeExpressionValidator(allowed_names).visit(tree.body)


def _resolve_segments(current: Any, segments: list[str]) -> Any:
    """Resolve a parsed path segment list against one runtime payload.

    Args:
        current: Current runtime object being traversed.
        segments: Remaining path segments.

    Returns:
        The resolved runtime value.
    """

    if not segments:
        return current

    segment = segments[0]
    remaining = segments[1:]

    if isinstance(current, list):
        if segment.isdigit():
            index = int(segment)
            if index >= len(current):
                return None
            return _resolve_segments(current[index], remaining)
        return [_resolve_segments(item, segments) for item in current]

    wildcard = segment.endswith("[]")
    key = segment[:-2] if wildcard else segment

    if not isinstance(current, Mapping):
        return [] if wildcard else None

    next_value = current.get(key)
    if wildcard:
        if next_value is None:
            return []
        if not isinstance(next_value, list):
            return []
        if not remaining:
            return next_value
        return [_resolve_segments(item, remaining) for item in next_value]
    return _resolve_segments(next_value, remaining)


class _SafeExpressionEvaluator(ast.NodeVisitor):
    """Evaluate a limited AST with an explicit allowlist of operations."""

    _binary_operators: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
    }
    _unary_operators: dict[type[ast.unaryop], Callable[[Any], Any]] = {
        ast.Not: operator.not_,
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }
    _comparison_operators: dict[type[ast.cmpop], Callable[[Any, Any], Any]] = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.In: lambda left, right: left in right,
        ast.NotIn: lambda left, right: left not in right,
    }
    _allowed_functions = {
        "bool": bool,
        "float": float,
        "int": int,
        "len": len,
        "max": max,
        "min": min,
        "round": round,
        "sorted": sorted,
        "str": str,
        "sum": sum,
    }

    def __init__(self, variables: dict[str, Any]) -> None:
        """Initialize the evaluator with explicit runtime variables.

        Args:
            variables: Runtime variable bindings available to the expression.

        Returns:
            None.
        """

        self._variables = dict(variables)

    def visit_Constant(self, node: ast.Constant) -> Any:
        """Evaluate one constant AST node.

        Args:
            node: Constant node to evaluate.

        Returns:
            The constant value.
        """

        return node.value

    def visit_Name(self, node: ast.Name) -> Any:
        """Resolve one variable or allowed function name.

        Args:
            node: Name node to resolve.

        Returns:
            The resolved runtime value or allowed callable.

        Raises:
            UnsafeExpressionError: If the name is not allowed.
        """

        if node.id in self._variables:
            return self._variables[node.id]
        if node.id in self._allowed_functions:
            return self._allowed_functions[node.id]
        raise UnsafeExpressionError(f"unknown name {node.id!r} in restricted expression")

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        """Evaluate a boolean ``and`` or ``or`` expression.

        Args:
            node: Boolean operation node.

        Returns:
            The boolean-operation result.
        """

        values = [self.visit(value) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise UnsafeExpressionError("unsupported boolean operator")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        """Evaluate a binary arithmetic expression.

        Args:
            node: Binary operation node.

        Returns:
            The arithmetic result.
        """

        operator_type: type[ast.operator] = type(node.op)
        operation = self._binary_operators.get(operator_type)
        if operation is None:
            raise UnsafeExpressionError("unsupported binary operator")
        return operation(self.visit(node.left), self.visit(node.right))

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        """Evaluate a unary expression.

        Args:
            node: Unary operation node.

        Returns:
            The unary-expression result.
        """

        operator_type: type[ast.unaryop] = type(node.op)
        operation = self._unary_operators.get(operator_type)
        if operation is None:
            raise UnsafeExpressionError("unsupported unary operator")
        return operation(self.visit(node.operand))

    def visit_Compare(self, node: ast.Compare) -> Any:
        """Evaluate a chained comparison expression.

        Args:
            node: Comparison node.

        Returns:
            ``True`` when every comparison succeeds, otherwise ``False``.
        """

        left = self.visit(node.left)
        for comparator, operator_node in zip(node.comparators, node.ops, strict=True):
            right = self.visit(comparator)
            operator_type: type[ast.cmpop] = type(operator_node)
            operation = self._comparison_operators.get(operator_type)
            if operation is None:
                raise UnsafeExpressionError("unsupported comparison operator")
            if not operation(left, right):
                return False
            left = right
        return True

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        """Evaluate a ternary expression.

        Args:
            node: Conditional-expression node.

        Returns:
            The selected branch result.
        """

        return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)

    def visit_List(self, node: ast.List) -> Any:
        """Evaluate a list literal.

        Args:
            node: List-literal node.

        Returns:
            The evaluated Python list.
        """

        return [self.visit(element) for element in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> Any:
        """Evaluate a tuple literal.

        Args:
            node: Tuple-literal node.

        Returns:
            The evaluated Python tuple.
        """

        return tuple(self.visit(element) for element in node.elts)

    def visit_Dict(self, node: ast.Dict) -> Any:
        """Evaluate a dictionary literal.

        Args:
            node: Dictionary-literal node.

        Returns:
            The evaluated Python dictionary.
        """

        return {
            self.visit(key): self.visit(value)
            for key, value in zip(node.keys, node.values, strict=True)
        }

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        """Evaluate a subscript expression over safe runtime values.

        Args:
            node: Subscript-expression node.

        Returns:
            The indexed runtime value.
        """

        container = self.visit(node.value)
        index = self.visit(node.slice)
        return container[index]

    def visit_Slice(self, node: ast.Slice) -> slice:
        """Evaluate one slice literal.

        Args:
            node: Slice-expression node.

        Returns:
            The resolved Python slice object.
        """

        lower = self.visit(node.lower) if node.lower is not None else None
        upper = self.visit(node.upper) if node.upper is not None else None
        step = self.visit(node.step) if node.step is not None else None
        return slice(lower, upper, step)

    def visit_Call(self, node: ast.Call) -> Any:
        """Evaluate a call to an explicitly allowlisted builtin.

        Args:
            node: Function-call node.

        Returns:
            The call result.

        Raises:
            UnsafeExpressionError: If the call target is not allowlisted.
        """

        func = self.visit(node.func)
        if func not in self._allowed_functions.values():
            raise UnsafeExpressionError("function calls are limited to explicit safe builtins")
        args = [self.visit(arg) for arg in node.args]
        kwargs = {
            keyword.arg: self.visit(keyword.value)
            for keyword in node.keywords
            if keyword.arg is not None
        }
        return func(*args, **kwargs)

    def generic_visit(self, node: ast.AST) -> Any:
        """Reject any AST node that is not explicitly allowlisted.

        Args:
            node: AST node that is not explicitly supported.

        Returns:
            This method never returns successfully.

        Raises:
            UnsafeExpressionError: Always, because the node is unsupported.
        """

        raise UnsafeExpressionError(f"unsupported expression construct: {type(node).__name__}")


class _SafeExpressionValidator(ast.NodeVisitor):
    """Validate the same limited AST accepted by ``_SafeExpressionEvaluator``."""

    _allowed_functions = set(_SafeExpressionEvaluator._allowed_functions)
    _binary_operators = tuple(_SafeExpressionEvaluator._binary_operators)
    _unary_operators = tuple(_SafeExpressionEvaluator._unary_operators)
    _comparison_operators = tuple(_SafeExpressionEvaluator._comparison_operators)

    def __init__(self, allowed_names: set[str]) -> None:
        """Initialize the static validator with explicit runtime names.

        Args:
            allowed_names: Variable names exposed to the expression.

        Returns:
            None.
        """

        self._allowed_names = set(allowed_names)

    def visit_Constant(self, node: ast.Constant) -> None:
        """Accept literal constants.

        Args:
            node: Constant node to inspect.

        Returns:
            None.
        """

        return None

    def visit_Name(self, node: ast.Name) -> None:
        """Validate one variable or allowlisted function name.

        Args:
            node: Name node to inspect.

        Returns:
            None.

        Raises:
            UnsafeExpressionError: If the name is not available.
        """

        if node.id in self._allowed_names or node.id in self._allowed_functions:
            return None
        raise UnsafeExpressionError(f"unknown name {node.id!r} in restricted expression")

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        """Validate a boolean operation.

        Args:
            node: Boolean operation node.

        Returns:
            None.
        """

        if not isinstance(node.op, (ast.And, ast.Or)):
            raise UnsafeExpressionError("unsupported boolean operator")
        for value in node.values:
            self.visit(value)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        """Validate a binary arithmetic operation.

        Args:
            node: Binary operation node.

        Returns:
            None.
        """

        if not isinstance(node.op, self._binary_operators):
            raise UnsafeExpressionError("unsupported binary operator")
        self.visit(node.left)
        self.visit(node.right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        """Validate a unary operation.

        Args:
            node: Unary operation node.

        Returns:
            None.
        """

        if not isinstance(node.op, self._unary_operators):
            raise UnsafeExpressionError("unsupported unary operator")
        self.visit(node.operand)

    def visit_Compare(self, node: ast.Compare) -> None:
        """Validate a chained comparison.

        Args:
            node: Comparison node.

        Returns:
            None.
        """

        self.visit(node.left)
        for comparator, operator_node in zip(node.comparators, node.ops, strict=True):
            if not isinstance(operator_node, self._comparison_operators):
                raise UnsafeExpressionError("unsupported comparison operator")
            self.visit(comparator)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        """Validate a Python conditional expression.

        Args:
            node: Conditional expression node.

        Returns:
            None.
        """

        self.visit(node.test)
        self.visit(node.body)
        self.visit(node.orelse)

    def visit_List(self, node: ast.List) -> None:
        """Validate a list literal.

        Args:
            node: List-literal node.

        Returns:
            None.
        """

        for element in node.elts:
            self.visit(element)

    def visit_Tuple(self, node: ast.Tuple) -> None:
        """Validate a tuple literal.

        Args:
            node: Tuple-literal node.

        Returns:
            None.
        """

        for element in node.elts:
            self.visit(element)

    def visit_Dict(self, node: ast.Dict) -> None:
        """Validate a dictionary literal.

        Args:
            node: Dictionary-literal node.

        Returns:
            None.
        """

        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                raise UnsafeExpressionError("unsupported expression construct: DictUnpack")
            self.visit(key)
            self.visit(value)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        """Validate a subscript expression.

        Args:
            node: Subscript-expression node.

        Returns:
            None.
        """

        self.visit(node.value)
        self.visit(node.slice)

    def visit_Slice(self, node: ast.Slice) -> None:
        """Validate one slice literal.

        Args:
            node: Slice-expression node.

        Returns:
            None.
        """

        if node.lower is not None:
            self.visit(node.lower)
        if node.upper is not None:
            self.visit(node.upper)
        if node.step is not None:
            self.visit(node.step)

    def visit_Call(self, node: ast.Call) -> None:
        """Validate a call to an explicitly allowlisted builtin.

        Args:
            node: Function-call node.

        Returns:
            None.
        """

        if not isinstance(node.func, ast.Name):
            raise UnsafeExpressionError("function calls are limited to explicit safe builtins")
        if node.func.id in self._allowed_names:
            raise UnsafeExpressionError(
                f"name {node.func.id!r} is a runtime variable and cannot be called as a safe builtin"
            )
        if node.func.id not in self._allowed_functions:
            raise UnsafeExpressionError(f"unknown name {node.func.id!r} in restricted expression")
        for arg in node.args:
            self.visit(arg)
        for keyword in node.keywords:
            if keyword.arg is None:
                raise UnsafeExpressionError("unsupported expression construct: KeywordUnpack")
            self.visit(keyword.value)

    def generic_visit(self, node: ast.AST) -> None:
        """Reject any AST node that is not explicitly allowlisted.

        Args:
            node: AST node that is not explicitly supported.

        Returns:
            This method never returns successfully.
        """

        raise UnsafeExpressionError(f"unsupported expression construct: {type(node).__name__}")
