"""FastMCP server exposing the TP-Link SG1016PE switch API as tools."""

import dataclasses
import enum
import os
from typing import Any

from fastmcp import FastMCP

from .client import SwitchClient, SwitchError
from .models import PoePowerLimit, PoePriority, PortSpeed, VlanPortMembership

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
        return {f.name: _to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, enum.Enum):
        return obj.name
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
async def get_port_statistics() -> list[dict[str, Any]]:
    """Get per-port packet statistics (TX/RX good/bad packet counts, link status).

    Counters are cumulative since last switch reboot and wrap at 2^32.
    """
    client = _get_client()
    stats = await client.get_port_statistics()
    return _to_dict(stats)


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
async def get_vlan_config() -> dict[str, Any]:
    """Get the 802.1Q VLAN configuration.

    Returns whether 802.1Q is enabled, the max VLAN count, and each VLAN
    with its ID, name, tagged ports, and untagged ports.
    """
    client = _get_client()
    config = await client.get_vlan_config()
    return _to_dict(config)


@mcp.tool()
async def get_pvid_config() -> dict[str, Any]:
    """Get the per-port PVID (default VLAN ID) settings.

    Returns whether 802.1Q is enabled and the PVID assigned to each port.
    Incoming untagged frames on a port are assigned to its PVID.
    """
    client = _get_client()
    config = await client.get_pvid_config()
    return _to_dict(config)


@mcp.tool()
async def set_vlan_enabled(enabled: bool) -> str:
    """Enable or disable 802.1Q VLAN mode on the switch.

    Args:
        enabled: True to enable, False to disable.
    """
    client = _get_client()
    try:
        await client.set_vlan_enabled(enabled=enabled)
    except SwitchError as e:
        return f"Error: {e}"
    return f"802.1Q VLAN {'enabled' if enabled else 'disabled'}"


@mcp.tool()
async def create_or_update_vlan(
    vid: int,
    name: str,
    tagged_ports: list[int] | None = None,
    untagged_ports: list[int] | None = None,
) -> str:
    """Create or modify an 802.1Q VLAN.

    Ports not listed in tagged_ports or untagged_ports become non-members.

    Args:
        vid: VLAN ID (1-4094).
        name: VLAN name (alphanumeric, max 10 chars).
        tagged_ports: List of port numbers that should be tagged members.
        untagged_ports: List of port numbers that should be untagged members.
    """
    client = _get_client()
    memberships: dict[int, VlanPortMembership] = {}
    for p in tagged_ports or []:
        memberships[p] = VlanPortMembership.TAGGED
    for p in untagged_ports or []:
        if p in memberships:
            return f"Error: port {p} listed in both tagged and untagged"
        memberships[p] = VlanPortMembership.UNTAGGED
    try:
        await client.create_or_update_vlan(vid, name, memberships)
    except SwitchError as e:
        return f"Error: {e}"
    return f"VLAN {vid} ('{name}') created/updated"


@mcp.tool()
async def delete_vlan(vid: int) -> str:
    """Delete an 802.1Q VLAN.

    Args:
        vid: VLAN ID to delete. VLAN 1 (Default) cannot be deleted.
    """
    client = _get_client()
    try:
        await client.delete_vlan(vid)
    except SwitchError as e:
        return f"Error: {e}"
    return f"VLAN {vid} deleted"


@mcp.tool()
async def set_port_pvid(port: int, pvid: int) -> str:
    """Set the PVID (default VLAN) for a port.

    Incoming untagged frames on this port will be assigned to this VLAN.

    Args:
        port: Port number (1-based).
        pvid: VLAN ID to assign as the port's default.
    """
    client = _get_client()
    try:
        await client.set_port_pvid(port, pvid)
    except SwitchError as e:
        return f"Error: {e}"
    return f"Port {port} PVID set to {pvid}"


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
