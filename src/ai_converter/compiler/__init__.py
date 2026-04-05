"""Public exports for the MappingIR compiler and runtime helpers."""

from __future__ import annotations

from .compiler import CompiledConverter, CompilationError, compile_mapping_ir
from .module_loader import load_module_from_source

__all__ = [
    "CompiledConverter",
    "CompilationError",
    "compile_mapping_ir",
    "load_module_from_source",
]
