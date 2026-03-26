"""FastMCP server exposing the TP-Link SG1016PE switch API as tools."""

import dataclasses
import os
from typing import Any

from fastmcp import FastMCP

from .client import SwitchClient, SwitchError
from .models import PoePowerLimit, PoePriority, PortSpeed

mcp = FastMCP(
    "TP-Link SG1016PE",
    instructions=(
        "MCP server for managing a TP-Link SG1016PE Easy Smart switch. "
        "Provides tools to query device info, port status, PoE status, "
        "and to configure port settings and PoE parameters."
    ),
)

_client: SwitchClient | None = None


def _get_client() -> SwitchClient:
    global _client
    if _client is None:
        host = os.environ.get("TPLINK_HOST", "192.168.0.1")
        port = int(os.environ.get("TPLINK_PORT", "80"))
        username = os.environ.get("TPLINK_USERNAME", "admin")
        password = os.environ.get("TPLINK_PASSWORD", "")
        use_ssl = os.environ.get("TPLINK_USE_SSL", "false").lower() == "true"
        verify_ssl = os.environ.get("TPLINK_VERIFY_SSL", "false").lower() == "true"
        _client = SwitchClient(
            host=host,
            port=port,
            username=username,
            password=password,
            use_ssl=use_ssl,
            verify_ssl=verify_ssl,
        )
    return _client


def _to_dict(obj: Any) -> Any:
    """Convert dataclass instances (and lists thereof) to plain dicts."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]
    return obj


@mcp.tool()
async def get_device_info() -> dict[str, Any]:
    """Get general device information (name, MAC, IP, firmware, hardware)."""
    client = _get_client()
    info = await client.get_device_info()
    return _to_dict(info)


@mcp.tool()
async def get_port_states() -> list[dict[str, Any]]:
    """Get the state of all switch ports (enabled, speed, flow control)."""
    client = _get_client()
    states = await client.get_port_states()
    return _to_dict(states)


@mcp.tool()
async def get_poe_port_states() -> list[dict[str, Any]]:
    """Get PoE state for all PoE-capable ports (power, voltage, current, status)."""
    client = _get_client()
    states = await client.get_poe_port_states()
    return _to_dict(states)


@mcp.tool()
async def get_poe_global_state() -> dict[str, Any] | str:
    """Get the global PoE power budget (limit, consumption, remaining)."""
    client = _get_client()
    state = await client.get_poe_global_state()
    if state is None:
        return "PoE is not available on this device"
    return _to_dict(state)


@mcp.tool()
async def set_port_state(
    port: int,
    enabled: bool,
    speed: str = "AUTO",
    flow_control: bool = False,
) -> str:
    """Enable/disable a switch port and configure its speed and flow control.

    Args:
        port: Port number (1-based).
        enabled: Whether the port should be enabled.
        speed: One of: AUTO, HALF_10M, FULL_10M, HALF_100M, FULL_100M, FULL_1000M.
        flow_control: Whether to enable flow control.
    """
    client = _get_client()
    try:
        port_speed = PortSpeed[speed.upper()]
    except KeyError:
        valid = [s.name for s in PortSpeed if s not in (PortSpeed.LINK_DOWN, PortSpeed.UNKNOWN)]
        return f"Invalid speed '{speed}'. Valid: {', '.join(valid)}"
    try:
        await client.set_port_state(
            port, enabled=enabled, speed=port_speed, flow_control=flow_control
        )
    except SwitchError as e:
        return f"Error: {e}"
    state = f"enabled={enabled}, speed={speed}, flow_control={flow_control}"
    return f"Port {port} updated: {state}"


@mcp.tool()
async def set_poe_limit(limit: float) -> str:
    """Set the global PoE power budget limit in watts.

    Args:
        limit: Power budget in watts. Must be within the device's supported range.
    """
    client = _get_client()
    try:
        await client.set_poe_limit(limit)
    except SwitchError as e:
        return f"Error: {e}"
    return f"PoE global power limit set to {limit}W"


@mcp.tool()
async def set_poe_port(
    port: int,
    enabled: bool,
    priority: str = "HIGH",
    power_limit: str = "AUTO",
) -> str:
    """Configure PoE settings for a specific port.

    Args:
        port: Port number (1-based).
        enabled: Whether PoE should be enabled on this port.
        priority: PoE priority. One of: HIGH, MIDDLE, LOW.
        power_limit: AUTO, CLASS_1-4, or a float 0.1-30.0 for custom watts.
    """
    client = _get_client()

    try:
        poe_priority = PoePriority[priority.upper()]
    except KeyError:
        return f"Invalid priority '{priority}'. Valid: HIGH, MIDDLE, LOW"

    poe_power_limit: PoePowerLimit | float
    try:
        poe_power_limit = PoePowerLimit[power_limit.upper()]
    except KeyError:
        try:
            poe_power_limit = float(power_limit)
        except ValueError:
            return (
                f"Invalid power_limit '{power_limit}'. Use AUTO, CLASS_1-4, or a float (0.1-30.0)"
            )

    try:
        await client.set_poe_port_settings(
            port, enabled=enabled, priority=poe_priority, power_limit=poe_power_limit
        )
    except SwitchError as e:
        return f"Error: {e}"
    state = f"enabled={enabled}, priority={priority}, power_limit={power_limit}"
    return f"Port {port} PoE updated: {state}"
