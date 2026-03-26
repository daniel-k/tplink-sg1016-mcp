"""Response parsing for the TP-Link switch web interface.

The switch returns HTML pages with embedded <script> blocks containing
JavaScript variable declarations. This module extracts and converts those
variables into Python types.
"""

import re
from enum import Enum
from typing import Any

import json5

_SCRIPT_RE = re.compile(r"<script>(.*?)</script>", re.DOTALL)
_VAR_RE = re.compile(r"var\s+(?P<name>[a-zA-Z0-9_]+)\s*=\s*(?P<value>[^;]+);")
_ARRAY_RE = re.compile(r"\s*new\s*Array\s*\((?P<items>[^)]+)\)")


class VarType(Enum):
    STR = "str"
    INT = "int"
    LIST = "list"
    DICT = "dict"


def extract_variables(page: str) -> dict[str, str]:
    """Extract all JavaScript variable declarations from HTML script blocks."""
    result: dict[str, str] = {}
    for script_match in _SCRIPT_RE.finditer(page):
        for var_match in _VAR_RE.finditer(script_match.group(1)):
            result[var_match.group("name")] = var_match.group("value")
    return result


def convert_value(raw: str, var_type: VarType) -> Any:
    """Convert a raw JavaScript value string to the appropriate Python type."""
    match var_type:
        case VarType.STR:
            return raw.strip("'\"")
        case VarType.INT:
            return int(raw)
        case VarType.LIST:
            m = _ARRAY_RE.match(raw)
            if not m:
                return []
            return [item.strip(' ,\r\n\t"') for item in m.group("items").split(",")]
        case VarType.DICT:
            return json5.loads(raw) if raw else None


def get_variable(page: str, name: str, var_type: VarType) -> Any:
    """Extract a single named variable from an HTML page."""
    variables = extract_variables(page)
    raw = variables.get(name)
    if raw is None:
        return None
    return convert_value(raw, var_type)


def get_variables(page: str, specs: list[tuple[str, VarType]]) -> dict[str, Any]:
    """Extract multiple named variables from an HTML page."""
    raw_vars = extract_variables(page)
    result: dict[str, Any] = {}
    for name, var_type in specs:
        raw = raw_vars.get(name)
        result[name] = convert_value(raw, var_type) if raw is not None else None
    return result
