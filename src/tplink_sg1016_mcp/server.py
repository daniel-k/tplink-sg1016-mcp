"""FastMCP server exposing the TP-Link SG1016PE switch API as tools."""

import dataclasses
import enum
import os
from typing import Any

from fastmcp import FastMCP

from .client import SwitchClient, SwitchError
from .models import (
    PoePowerLimit,
    PoePriority,
    PortSpeed,
    QosMode,
    QosPriority,
    VlanPortMembership,
)

mcp = FastMCP(
    "TP-Link SG1016PE",
    instructions=(
        "MCP server for managing a TP-Link SG1016PE Easy Smart switch. "
        "Provides tools to query and configure ports, PoE, VLANs, QoS, "
        "mirroring, LAGs, IGMP snooping, DHCP snooping, loop prevention, "
        "cable diagnostics, and more."
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


def _err(e: SwitchError) -> str:
    return f"Error: {e}"


# ===================================================================
# READ TOOLS
# ===================================================================


@mcp.tool()
async def get_device_info() -> dict[str, Any]:
    """Get general device information (name, MAC, IP, firmware, hardware)."""
    client = _get_client()
    return _to_dict(await client.get_device_info())


@mcp.tool()
async def get_dashboard() -> dict[str, Any]:
    """Get the main dashboard: uptime and per-port live TX/RX rates.

    Rates are in bytes/sec. Uptime is a string in seconds.
    """
    client = _get_client()
    return _to_dict(await client.get_dashboard())


@mcp.tool()
async def get_port_states() -> list[dict[str, Any]]:
    """Get the state of all switch ports (enabled, speed, flow control)."""
    client = _get_client()
    return _to_dict(await client.get_port_states())


@mcp.tool()
async def get_port_statistics() -> list[dict[str, Any]]:
    """Get per-port packet statistics (TX/RX good/bad packet counts, link status).

    Counters are cumulative since last switch reboot and wrap at 2^32.
    """
    client = _get_client()
    return _to_dict(await client.get_port_statistics())


@mcp.tool()
async def get_ip_settings() -> dict[str, Any]:
    """Get the switch's IP configuration (DHCP mode, IP, netmask, gateway)."""
    client = _get_client()
    return _to_dict(await client.get_ip_settings())


@mcp.tool()
async def get_led_status() -> dict[str, bool]:
    """Get whether the switch front-panel LEDs are on or off."""
    client = _get_client()
    return {"led_on": await client.get_led_status()}


@mcp.tool()
async def get_cable_diagnostics() -> list[dict[str, Any]]:
    """Get cable diagnostics results. Run run_cable_test first.

    Per-port status: NOT_TESTED, NO_CABLE, NORMAL, OPEN, SHORT, OPEN_SHORT, CROSSTALK.
    length_m is the detected cable length in meters.
    """
    client = _get_client()
    return _to_dict(await client.get_cable_diagnostics())


@mcp.tool()
async def get_igmp_snooping() -> dict[str, Any]:
    """Get IGMP snooping config and discovered multicast groups."""
    client = _get_client()
    return _to_dict(await client.get_igmp_snooping())


@mcp.tool()
async def get_lag_config() -> dict[str, Any]:
    """Get link aggregation group (LAG / port trunk) configuration.

    Shows configured LAG groups and their member ports.
    """
    client = _get_client()
    return _to_dict(await client.get_lag_config())


@mcp.tool()
async def get_port_mirror_config() -> dict[str, Any]:
    """Get port mirroring configuration.

    Shows the destination (monitoring) port and which source ports
    are mirrored for ingress and/or egress traffic.
    """
    client = _get_client()
    return _to_dict(await client.get_port_mirror_config())


@mcp.tool()
async def get_loop_prevention() -> dict[str, bool]:
    """Get whether loop prevention is enabled."""
    client = _get_client()
    return {"enabled": await client.get_loop_prevention()}


@mcp.tool()
async def get_qos_config() -> dict[str, Any]:
    """Get QoS mode and per-port priority queue settings.

    Mode is PORT_BASED, DOT1P_BASED, or DSCP_BASED.
    Per-port priority is LOWEST, NORMAL, MEDIUM, or HIGHEST.
    """
    client = _get_client()
    return _to_dict(await client.get_qos_config())


@mcp.tool()
async def get_bandwidth_limits() -> list[dict[str, Any]]:
    """Get per-port ingress/egress bandwidth rate limits.

    Rates are in kbps. 0 means unlimited.
    """
    client = _get_client()
    return _to_dict(await client.get_bandwidth_limits())


@mcp.tool()
async def get_storm_control() -> list[dict[str, Any]]:
    """Get per-port storm control settings.

    Shows rate limit and which traffic types are controlled
    (broadcast, multicast, unknown_unicast).
    """
    client = _get_client()
    return _to_dict(await client.get_storm_control())


@mcp.tool()
async def get_poe_port_states() -> list[dict[str, Any]]:
    """Get PoE state for all PoE-capable ports (power, voltage, current, status)."""
    client = _get_client()
    return _to_dict(await client.get_poe_port_states())


@mcp.tool()
async def get_poe_global_state() -> dict[str, Any] | str:
    """Get the global PoE power budget (limit, consumption, remaining)."""
    client = _get_client()
    state = await client.get_poe_global_state()
    if state is None:
        return "PoE is not available on this device"
    return _to_dict(state)


@mcp.tool()
async def get_poe_recovery() -> dict[str, Any]:
    """Get PoE auto-recovery (ping watchdog) config.

    When enabled, the switch pings devices on PoE ports and automatically
    restarts PoE if the device stops responding.
    """
    client = _get_client()
    return _to_dict(await client.get_poe_recovery())


@mcp.tool()
async def get_poe_extend() -> dict[str, Any]:
    """Get PoE extend mode per port.

    When enabled on a port, PoE range extends to 250m at 10Mbps.
    """
    client = _get_client()
    return _to_dict(await client.get_poe_extend())


@mcp.tool()
async def get_dhcp_snooping() -> dict[str, Any]:
    """Get DHCP snooping configuration (enabled state and trusted/untrusted ports)."""
    client = _get_client()
    return _to_dict(await client.get_dhcp_snooping())


@mcp.tool()
async def get_port_isolation() -> list[dict[str, Any]]:
    """Get port isolation config: which ports each port is allowed to forward to."""
    client = _get_client()
    return _to_dict(await client.get_port_isolation())


@mcp.tool()
async def get_vlan_config() -> dict[str, Any]:
    """Get the 802.1Q VLAN configuration.

    Returns whether 802.1Q is enabled, the max VLAN count, and each VLAN
    with its ID, name, tagged ports, and untagged ports.
    """
    client = _get_client()
    return _to_dict(await client.get_vlan_config())


@mcp.tool()
async def get_pvid_config() -> dict[str, Any]:
    """Get the per-port PVID (default VLAN ID) settings.

    Returns whether 802.1Q is enabled and the PVID assigned to each port.
    Incoming untagged frames on a port are assigned to its PVID.
    """
    client = _get_client()
    return _to_dict(await client.get_pvid_config())


@mcp.tool()
async def search_mac_table(mac_address: str) -> list[Any]:
    """Search the switch's MAC address table for a specific MAC.

    Args:
        mac_address: MAC address to search for (e.g. "AA-BB-CC-DD-EE-FF").
    """
    client = _get_client()
    return await client.search_mac_table(mac_address)


# ===================================================================
# WRITE TOOLS
# ===================================================================

# --- Port ---


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
        return _err(e)
    return f"Port {port} updated: enabled={enabled}, speed={speed}"


# --- LED ---


@mcp.tool()
async def set_led(on: bool) -> str:
    """Turn the switch front-panel LEDs on or off.

    Args:
        on: True to turn LEDs on, False to turn off.
    """
    client = _get_client()
    try:
        await client.set_led(on=on)
    except SwitchError as e:
        return _err(e)
    return f"LEDs {'on' if on else 'off'}"


# --- Cable diagnostics ---


@mcp.tool()
async def run_cable_test(ports: list[int]) -> str:
    """Run cable diagnostics on the specified ports.

    Results can be read afterwards with get_cable_diagnostics.

    Args:
        ports: List of port numbers (1-based) to test.
    """
    client = _get_client()
    try:
        await client.run_cable_test(ports)
    except SwitchError as e:
        return _err(e)
    return f"Cable test started on ports {ports}"


# --- Loop prevention ---


@mcp.tool()
async def set_loop_prevention(enabled: bool) -> str:
    """Enable or disable loop prevention.

    Args:
        enabled: True to enable, False to disable.
    """
    client = _get_client()
    try:
        await client.set_loop_prevention(enabled=enabled)
    except SwitchError as e:
        return _err(e)
    return f"Loop prevention {'enabled' if enabled else 'disabled'}"


# --- IGMP snooping ---


@mcp.tool()
async def set_igmp_snooping(enabled: bool, report_suppression: bool = False) -> str:
    """Enable or disable IGMP snooping.

    Args:
        enabled: True to enable, False to disable.
        report_suppression: True to suppress duplicate IGMP reports.
    """
    client = _get_client()
    try:
        await client.set_igmp_snooping(enabled=enabled, report_suppression=report_suppression)
    except SwitchError as e:
        return _err(e)
    return f"IGMP snooping {'enabled' if enabled else 'disabled'}"


# --- QoS ---


@mcp.tool()
async def set_qos_mode(mode: str) -> str:
    """Set the global QoS scheduling mode.

    Args:
        mode: One of: PORT_BASED, DOT1P_BASED, DSCP_BASED.
    """
    client = _get_client()
    try:
        qos_mode = QosMode[mode.upper()]
    except KeyError:
        return f"Invalid mode '{mode}'. Valid: PORT_BASED, DOT1P_BASED, DSCP_BASED"
    try:
        await client.set_qos_mode(qos_mode)
    except SwitchError as e:
        return _err(e)
    return f"QoS mode set to {mode}"


@mcp.tool()
async def set_port_qos_priority(port: int, priority: str) -> str:
    """Set the QoS priority queue for a port (only effective in PORT_BASED mode).

    Args:
        port: Port number (1-based).
        priority: One of: LOWEST, NORMAL, MEDIUM, HIGHEST.
    """
    client = _get_client()
    try:
        qos_pri = QosPriority[priority.upper()]
    except KeyError:
        return f"Invalid priority '{priority}'. Valid: LOWEST, NORMAL, MEDIUM, HIGHEST"
    try:
        await client.set_port_qos_priority(port, qos_pri)
    except SwitchError as e:
        return _err(e)
    return f"Port {port} QoS priority set to {priority}"


@mcp.tool()
async def set_bandwidth_limit(port: int, ingress_rate: int, egress_rate: int) -> str:
    """Set per-port ingress/egress bandwidth rate limits.

    Args:
        port: Port number (1-based).
        ingress_rate: Ingress rate limit in kbps. 0 for unlimited.
        egress_rate: Egress rate limit in kbps. 0 for unlimited.
    """
    client = _get_client()
    try:
        await client.set_bandwidth_limit(port, ingress_rate=ingress_rate, egress_rate=egress_rate)
    except SwitchError as e:
        return _err(e)
    return f"Port {port} bandwidth: ingress={ingress_rate}kbps, egress={egress_rate}kbps"


@mcp.tool()
async def set_storm_control(
    port: int,
    enabled: bool,
    rate: int,
    broadcast: bool = True,
    multicast: bool = False,
    unknown_unicast: bool = False,
) -> str:
    """Set per-port storm control (rate limit broadcast/multicast/unknown unicast).

    Args:
        port: Port number (1-based).
        enabled: True to enable storm control on this port.
        rate: Rate limit value in kbps.
        broadcast: Control broadcast storms.
        multicast: Control multicast storms.
        unknown_unicast: Control unknown unicast storms.
    """
    client = _get_client()
    try:
        await client.set_storm_control(
            port,
            enabled=enabled,
            rate=rate,
            broadcast=broadcast,
            multicast=multicast,
            unknown_unicast=unknown_unicast,
        )
    except SwitchError as e:
        return _err(e)
    return f"Port {port} storm control {'enabled' if enabled else 'disabled'}"


# --- Port mirroring ---


@mcp.tool()
async def set_port_mirror(
    enabled: bool,
    destination_port: int = 1,
    ingress_ports: list[int] | None = None,
    egress_ports: list[int] | None = None,
) -> str:
    """Configure port mirroring.

    Args:
        enabled: True to enable port mirroring.
        destination_port: The monitoring port that receives mirrored traffic.
        ingress_ports: Source ports to mirror ingress (incoming) traffic from.
        egress_ports: Source ports to mirror egress (outgoing) traffic from.
    """
    client = _get_client()
    try:
        await client.set_port_mirror(
            enabled=enabled,
            destination_port=destination_port,
            ingress_ports=ingress_ports,
            egress_ports=egress_ports,
        )
    except SwitchError as e:
        return _err(e)
    state = "enabled" if enabled else "disabled"
    return f"Port mirroring {state}, destination=port {destination_port}"


# --- Port isolation ---


@mcp.tool()
async def set_port_isolation(port: int, forwarding_ports: list[int]) -> str:
    """Set which ports a given port is allowed to forward traffic to.

    Args:
        port: The port to configure isolation for (1-based).
        forwarding_ports: List of port numbers this port can forward to.
    """
    client = _get_client()
    try:
        await client.set_port_isolation(port, forwarding_ports)
    except SwitchError as e:
        return _err(e)
    return f"Port {port} isolation updated: forwards to {forwarding_ports}"


# --- LAG ---


@mcp.tool()
async def create_lag(group_id: int, ports: list[int]) -> str:
    """Create or modify a link aggregation group (LAG / port trunk).

    Args:
        group_id: LAG group ID (1-8).
        ports: List of member port numbers.
    """
    client = _get_client()
    try:
        await client.create_lag(group_id, ports)
    except SwitchError as e:
        return _err(e)
    return f"LAG group {group_id} created with ports {ports}"


@mcp.tool()
async def delete_lag(group_id: int) -> str:
    """Delete a link aggregation group (LAG / port trunk).

    Args:
        group_id: LAG group ID to delete (1-8).
    """
    client = _get_client()
    try:
        await client.delete_lag(group_id)
    except SwitchError as e:
        return _err(e)
    return f"LAG group {group_id} deleted"


# --- DHCP snooping ---


@mcp.tool()
async def set_dhcp_snooping(enabled: bool) -> str:
    """Enable or disable DHCP snooping globally.

    Args:
        enabled: True to enable, False to disable.
    """
    client = _get_client()
    try:
        await client.set_dhcp_snooping_enabled(enabled=enabled)
    except SwitchError as e:
        return _err(e)
    return f"DHCP snooping {'enabled' if enabled else 'disabled'}"


@mcp.tool()
async def set_dhcp_snooping_port(port: int, trusted: bool) -> str:
    """Set a port as trusted or untrusted for DHCP snooping.

    Trusted ports accept DHCP server responses. Untrusted ports only allow
    DHCP client requests (blocks rogue DHCP servers).

    Args:
        port: Port number (1-based).
        trusted: True for trusted (DHCP server side), False for untrusted.
    """
    client = _get_client()
    try:
        await client.set_dhcp_snooping_port(port, trusted=trusted)
    except SwitchError as e:
        return _err(e)
    return f"Port {port} DHCP snooping: {'trusted' if trusted else 'untrusted'}"


# --- PoE ---


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
        return _err(e)
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
        return _err(e)
    return f"Port {port} PoE updated: enabled={enabled}, priority={priority}"


@mcp.tool()
async def repower_poe_port(port: int) -> str:
    """Restart PoE on a port without changing its configuration.

    Useful for rebooting a PoE-powered device.

    Args:
        port: Port number (1-based).
    """
    client = _get_client()
    try:
        await client.repower_poe_port(port)
    except SwitchError as e:
        return _err(e)
    return f"Port {port} PoE re-powered"


# --- VLAN ---


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
        return _err(e)
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
        return _err(e)
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
        return _err(e)
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
        return _err(e)
    return f"Port {port} PVID set to {pvid}"


# --- System ---


@mcp.tool()
async def set_device_name(name: str) -> str:
    """Set the switch's system name/description.

    Args:
        name: New device name.
    """
    client = _get_client()
    try:
        await client.set_device_name(name)
    except SwitchError as e:
        return _err(e)
    return f"Device name set to '{name}'"


@mcp.tool()
async def set_ip_settings(
    dhcp: bool,
    ip: str = "",
    netmask: str = "",
    gateway: str = "",
) -> str:
    """Change the switch's IP configuration.

    WARNING: Changing IP settings may make the switch unreachable.

    Args:
        dhcp: True to enable DHCP, False for static IP.
        ip: Static IP address (ignored if dhcp=True).
        netmask: Subnet mask (ignored if dhcp=True).
        gateway: Default gateway (ignored if dhcp=True).
    """
    client = _get_client()
    try:
        await client.set_ip_settings(dhcp=dhcp, ip=ip, netmask=netmask, gateway=gateway)
    except SwitchError as e:
        return _err(e)
    if dhcp:
        return "IP settings changed to DHCP"
    return f"IP settings changed to static: {ip}/{netmask} gw {gateway}"


@mcp.tool()
async def reboot_switch() -> str:
    """Reboot the switch. Configuration is saved before rebooting.

    The switch will be unreachable for ~30 seconds during reboot.
    """
    client = _get_client()
    try:
        await client.reboot()
    except SwitchError as e:
        return _err(e)
    return "Switch is rebooting"
