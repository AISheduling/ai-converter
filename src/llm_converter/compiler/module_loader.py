"""Load generated converter modules from deterministic source strings."""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType


def load_module_from_source(source_code: str, module_name: str) -> ModuleType:
    """Load a Python module from source code without touching the filesystem.

    Args:
        source_code: Generated Python source for the converter module.
        module_name: Stable module name to register in ``sys.modules``.

    Returns:
        The loaded Python module object.
    """

    spec = importlib.util.spec_from_loader(module_name, loader=None)
    if spec is None:
        raise ImportError(f"could not create module spec for {module_name!r}")

    module = importlib.util.module_from_spec(spec)
    module.__file__ = f"<generated:{module_name}>"
    sys.modules[module_name] = module
    exec(compile(source_code, module.__file__, "exec"), module.__dict__)
    return module
