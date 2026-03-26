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
_VAR_RE = re.compile(
    r"var\s+(?P<name>[a-zA-Z0-9_]+)\s*=\s*(?P<value>[^;\n]+?)\s*;?\s*$",
    re.MULTILINE,
)
_BRACE_VAR_RE = re.compile(
    r"var\s+(?P<name>[a-zA-Z0-9_]+)\s*=\s*\{",
)
_ARRAY_RE = re.compile(
    r"\s*(?:new\s*Array\s*\((?P<items_paren>[^)]+)\)|\[(?P<items_bracket>[^\]]+)\])"
)


class VarType(Enum):
    STR = "str"
    INT = "int"
    LIST = "list"
    DICT = "dict"


def _extract_braced_value(text: str, start: int) -> str | None:
    """Extract a brace-delimited value from text, starting at the opening '{'."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_variables(page: str) -> dict[str, str]:
    """Extract all JavaScript variable declarations from HTML script blocks."""
    result: dict[str, str] = {}
    for script_match in _SCRIPT_RE.finditer(page):
        script = script_match.group(1)
        # First pass: extract brace-delimited (object) values that may span
        # multiple lines — the simple single-line regex can truncate these.
        for m in _BRACE_VAR_RE.finditer(script):
            brace_start = m.end() - 1  # position of the '{'
            value = _extract_braced_value(script, brace_start)
            if value is not None:
                result[m.group("name")] = value
        # Second pass: single-line variables (strings, ints, arrays).
        # Skip names already captured by the brace pass.
        for var_match in _VAR_RE.finditer(script):
            name = var_match.group("name")
            if name not in result:
                result[name] = var_match.group("value")
    return result


def convert_value(raw: str, var_type: VarType) -> Any:
    """Convert a raw JavaScript value string to the appropriate Python type."""
    match var_type:
        case VarType.STR:
            return raw.strip("'\"")
        case VarType.INT:
            return int(raw.strip())
        case VarType.LIST:
            m = _ARRAY_RE.match(raw)
            if not m:
                return []
            items = m.group("items_paren") or m.group("items_bracket") or ""
            return [item.strip(' ,\r\n\t"') for item in items.split(",")]
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
