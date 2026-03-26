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
        "MCP server for managing a TP-Link SG1016PE Easy Smart managed switch. "
        "All port numbers are 1-based (1-16). The switch has 16 Gigabit Ethernet "
        "ports, the first 8 of which support PoE+. Tools are grouped into: "
        "system info, port management, PoE, 802.1Q VLANs, QoS, security "
        "(IGMP/DHCP snooping, loop prevention), diagnostics, and LAG/mirroring."
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
# SYSTEM
# ===================================================================


@mcp.tool()
async def get_device_info() -> dict[str, Any]:
    """Get basic switch identity: model name, MAC, IP, firmware and hardware version."""
    client = _get_client()
    return _to_dict(await client.get_device_info())


@mcp.tool()
async def get_ip_settings() -> dict[str, Any]:
    """Get the switch management IP config: DHCP/static mode, IP, subnet mask, gateway."""
    client = _get_client()
    return _to_dict(await client.get_ip_settings())


@mcp.tool()
async def get_led_status() -> dict[str, bool]:
    """Check whether the switch's front-panel port LEDs are turned on or off."""
    client = _get_client()
    return {"led_on": await client.get_led_status()}


@mcp.tool()
async def set_device_name(name: str) -> str:
    """Change the switch's system name (shown in the web UI and device info).

    Args:
        name: New device name/description.
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
    """Change the switch management IP configuration.

    WARNING: This may make the switch unreachable if misconfigured.

    Args:
        dhcp: True for DHCP (auto), False for static IP.
        ip: Static IP address (only used when dhcp=False).
        netmask: Subnet mask (only used when dhcp=False).
        gateway: Default gateway (only used when dhcp=False).
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
async def set_led(on: bool) -> str:
    """Turn the switch's front-panel port LEDs on or off.

    Args:
        on: True to turn LEDs on, False to turn them off.
    """
    client = _get_client()
    try:
        await client.set_led(on=on)
    except SwitchError as e:
        return _err(e)
    return f"LEDs {'on' if on else 'off'}"


@mcp.tool()
async def reboot_switch() -> str:
    """Reboot the switch. Running configuration is saved to flash before rebooting.

    The switch will be unreachable for approximately 30 seconds.
    """
    client = _get_client()
    try:
        await client.reboot()
    except SwitchError as e:
        return _err(e)
    return "Switch is rebooting"


# ===================================================================
# PORT MANAGEMENT
# ===================================================================


@mcp.tool()
async def get_port_states() -> list[dict[str, Any]]:
    """Get configuration and link status for all 16 switch ports.

    Per port: enabled (admin state), speed_config (configured speed),
    speed_actual (negotiated link speed, LINK_DOWN if no link),
    flow_control_config/actual. Speed values: LINK_DOWN, AUTO,
    HALF_10M, FULL_10M, HALF_100M, FULL_100M, FULL_1000M.
    """
    client = _get_client()
    return _to_dict(await client.get_port_states())


@mcp.tool()
async def get_port_statistics() -> list[dict[str, Any]]:
    """Get per-port packet counters (TX/RX good and bad packets).

    Counters are cumulative since last reboot and wrap at 2^32 (4 billion).
    Also includes each port's enabled state and link_status (negotiated speed).
    """
    client = _get_client()
    return _to_dict(await client.get_port_statistics())


@mcp.tool()
async def set_port_state(
    port: int,
    enabled: bool,
    speed: str = "AUTO",
    flow_control: bool = False,
) -> str:
    """Enable or disable a switch port, and optionally set its speed and flow control.

    Args:
        port: Port number (1-16).
        enabled: True to enable the port, False to administratively shut it down.
        speed: Link speed. One of: AUTO, HALF_10M, FULL_10M, HALF_100M, FULL_100M, FULL_1000M.
        flow_control: True to enable 802.3x flow control (pause frames).
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


# ===================================================================
# PoE (POWER OVER ETHERNET)
# ===================================================================


@mcp.tool()
async def get_poe_port_states() -> list[dict[str, Any]]:
    """Get PoE status for all PoE-capable ports (ports 1-8 on the SG1016PE).

    Per port: enabled, priority (HIGH/MIDDLE/LOW), power_limit (AUTO or CLASS_1-4),
    power_watts (current draw), current_ma, voltage_v, pd_class (detected device class,
    NO_PD if nothing connected), power_status (OFF/TURNING_ON/ON/OVERLOAD/SHORT/etc).
    """
    client = _get_client()
    return _to_dict(await client.get_poe_port_states())


@mcp.tool()
async def get_poe_global_state() -> dict[str, Any] | str:
    """Get the switch-wide PoE power budget in watts: limit, consumption, remaining."""
    client = _get_client()
    state = await client.get_poe_global_state()
    if state is None:
        return "PoE is not available on this device"
    return _to_dict(state)


@mcp.tool()
async def get_poe_recovery() -> dict[str, Any]:
    """Get PoE auto-recovery (ping watchdog) configuration.

    When enabled, the switch periodically pings the IP of a PoE-powered device
    and automatically power-cycles the port if the device stops responding.
    """
    client = _get_client()
    return _to_dict(await client.get_poe_recovery())


@mcp.tool()
async def set_poe_global_limit(limit: float) -> str:
    """Set the switch-wide PoE power budget limit in watts.

    The switch enforces a maximum total power draw across all PoE ports.

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
    """Configure PoE on a specific port.

    Args:
        port: Port number (1-8 on the SG1016PE).
        enabled: True to supply power, False to cut PoE power.
        priority: Power allocation priority when budget is constrained. HIGH, MIDDLE, or LOW.
        power_limit: Max power class. AUTO (negotiated), CLASS_1 (4W), CLASS_2 (7W),
            CLASS_3 (15.4W), CLASS_4 (30W), or a float 0.1-30.0 for custom wattage.
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
    """Power-cycle a PoE port: briefly cuts and restores power without changing config.

    Useful for remotely rebooting a PoE-powered device (AP, camera, etc).

    Args:
        port: Port number (1-8 on the SG1016PE).
    """
    client = _get_client()
    try:
        await client.repower_poe_port(port)
    except SwitchError as e:
        return _err(e)
    return f"Port {port} PoE re-powered"


# ===================================================================
# 802.1Q VLANs
# ===================================================================


@mcp.tool()
async def get_vlan_config() -> dict[str, Any]:
    """Get the full 802.1Q VLAN configuration.

    Returns: enabled (whether 802.1Q mode is active), max_vlans (device limit, typically 32),
    and a list of VLANs each with vid, name, tagged_ports, and untagged_ports.
    VLAN 1 ('Default') always exists with all ports as untagged members by default.
    """
    client = _get_client()
    return _to_dict(await client.get_vlan_config())


@mcp.tool()
async def get_pvid_config() -> dict[str, Any]:
    """Get the per-port PVID (Port VLAN ID / native VLAN) assignments.

    Each port has a PVID that determines which VLAN incoming untagged frames
    are classified into. Defaults to VLAN 1 for all ports.
    """
    client = _get_client()
    return _to_dict(await client.get_pvid_config())


@mcp.tool()
async def set_vlan_enabled(enabled: bool) -> str:
    """Enable or disable 802.1Q VLAN mode on the switch.

    WARNING: Disabling 802.1Q removes all VLAN separation. Only one VLAN
    mode (802.1Q, MTU, or port-based) can be active at a time.

    Args:
        enabled: True to enable 802.1Q VLANs, False to disable.
    """
    client = _get_client()
    try:
        await client.set_vlan_enabled(enabled=enabled)
    except SwitchError as e:
        return _err(e)
    return f"802.1Q VLAN {'enabled' if enabled else 'disabled'}"


@mcp.tool()
async def create_vlan(
    vid: int,
    name: str,
    tagged_ports: list[int] | None = None,
    untagged_ports: list[int] | None = None,
) -> str:
    """Create a new 802.1Q VLAN with optional initial port memberships.

    Ports not listed become non-members. Use add_vlan_members / remove_vlan_members
    to modify port memberships on existing VLANs.

    Args:
        vid: VLAN ID (2-4094). VLAN 1 already exists as the default.
        name: VLAN name (alphanumeric only, max 10 characters).
        tagged_ports: Ports that send/receive frames with an 802.1Q VLAN tag.
        untagged_ports: Ports that send frames without a VLAN tag (access ports).
    """
    client = _get_client()
    config = await client.get_vlan_config()
    if any(v.vid == vid for v in config.vlans):
        return (
            f"Error: VLAN {vid} already exists."
            " Use add_vlan_members / remove_vlan_members to modify it."
        )
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
    return f"VLAN {vid} ('{name}') created"


@mcp.tool()
async def add_vlan_members(
    vid: int,
    tagged_ports: list[int] | None = None,
    untagged_ports: list[int] | None = None,
) -> str:
    """Add ports to an existing 802.1Q VLAN.

    Reads the current VLAN state and adds the specified ports without affecting
    other existing members. A port can be changed from tagged to untagged (or
    vice versa) by including it in the desired list.

    Args:
        vid: VLAN ID of the existing VLAN to modify.
        tagged_ports: Ports to add as tagged members.
        untagged_ports: Ports to add as untagged (access) members.
    """
    client = _get_client()
    tagged_ports = tagged_ports or []
    untagged_ports = untagged_ports or []
    overlap = set(tagged_ports) & set(untagged_ports)
    if overlap:
        return f"Error: port(s) {sorted(overlap)} listed in both tagged and untagged"
    if not tagged_ports and not untagged_ports:
        return "Error: no ports specified to add"
    config = await client.get_vlan_config()
    vlan = next((v for v in config.vlans if v.vid == vid), None)
    if vlan is None:
        return f"Error: VLAN {vid} does not exist"
    memberships: dict[int, VlanPortMembership] = {}
    for p in vlan.tagged_ports:
        memberships[p] = VlanPortMembership.TAGGED
    for p in vlan.untagged_ports:
        memberships[p] = VlanPortMembership.UNTAGGED
    for p in tagged_ports:
        memberships[p] = VlanPortMembership.TAGGED
    for p in untagged_ports:
        memberships[p] = VlanPortMembership.UNTAGGED
    try:
        await client.create_or_update_vlan(vid, vlan.name, memberships)
    except SwitchError as e:
        return _err(e)
    added = sorted(set(tagged_ports + untagged_ports))
    return f"Added port(s) {added} to VLAN {vid}"


@mcp.tool()
async def remove_vlan_members(
    vid: int,
    ports: list[int],
) -> str:
    """Remove ports from an existing 802.1Q VLAN.

    Reads the current VLAN state and removes the specified ports (sets them to
    non-member) without affecting other existing members.

    Args:
        vid: VLAN ID of the existing VLAN to modify.
        ports: Port numbers to remove from the VLAN.
    """
    client = _get_client()
    if not ports:
        return "Error: no ports specified to remove"
    config = await client.get_vlan_config()
    vlan = next((v for v in config.vlans if v.vid == vid), None)
    if vlan is None:
        return f"Error: VLAN {vid} does not exist"
    current_members = set(vlan.tagged_ports + vlan.untagged_ports)
    not_members = set(ports) - current_members
    if not_members:
        return f"Error: port(s) {sorted(not_members)} are not members of VLAN {vid}"
    memberships: dict[int, VlanPortMembership] = {}
    for p in vlan.tagged_ports:
        memberships[p] = VlanPortMembership.TAGGED
    for p in vlan.untagged_ports:
        memberships[p] = VlanPortMembership.UNTAGGED
    for p in ports:
        memberships[p] = VlanPortMembership.NOT_MEMBER
    try:
        await client.create_or_update_vlan(vid, vlan.name, memberships)
    except SwitchError as e:
        return _err(e)
    return f"Removed port(s) {sorted(ports)} from VLAN {vid}"


@mcp.tool()
async def delete_vlan(vid: int) -> str:
    """Delete an 802.1Q VLAN. VLAN 1 (Default) cannot be deleted.

    Args:
        vid: VLAN ID to delete (2-4094).
    """
    client = _get_client()
    try:
        await client.delete_vlan(vid)
    except SwitchError as e:
        return _err(e)
    return f"VLAN {vid} deleted"


@mcp.tool()
async def set_port_pvid(port: int, pvid: int) -> str:
    """Set a port's PVID (native VLAN for untagged ingress traffic).

    All untagged frames arriving on this port will be assigned to this VLAN.
    The port must be an untagged or tagged member of the target VLAN.

    Args:
        port: Port number (1-16).
        pvid: VLAN ID to assign as the port's native VLAN.
    """
    client = _get_client()
    try:
        await client.set_port_pvid(port, pvid)
    except SwitchError as e:
        return _err(e)
    return f"Port {port} PVID set to {pvid}"


# ===================================================================
# QoS (QUALITY OF SERVICE)
# ===================================================================


@mcp.tool()
async def get_qos_config() -> dict[str, Any]:
    """Get the QoS configuration: scheduling mode and per-port priority queues.

    mode: PORT_BASED (priority set per port), DOT1P_BASED (from 802.1p VLAN tag),
    or DSCP_BASED (from IP header DSCP field).
    Per-port priority (PORT_BASED only): LOWEST, NORMAL, MEDIUM, HIGHEST.
    """
    client = _get_client()
    return _to_dict(await client.get_qos_config())


@mcp.tool()
async def get_bandwidth_limits() -> list[dict[str, Any]]:
    """Get per-port ingress and egress bandwidth rate limits in kbps.

    A value of 0 means no rate limit (unlimited).
    """
    client = _get_client()
    return _to_dict(await client.get_bandwidth_limits())


@mcp.tool()
async def get_storm_control() -> list[dict[str, Any]]:
    """Get per-port storm control settings.

    Storm control rate-limits broadcast, multicast, and/or unknown unicast
    traffic to prevent network flooding. Shows rate (kbps) and which
    traffic types are controlled per port.
    """
    client = _get_client()
    return _to_dict(await client.get_storm_control())


@mcp.tool()
async def set_qos_mode(mode: str) -> str:
    """Set the global QoS scheduling mode.

    Args:
        mode: PORT_BASED (manual per-port priority), DOT1P_BASED (from 802.1p tag),
            or DSCP_BASED (from IP header).
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
    """Set a port's QoS priority queue. Only effective when QoS mode is PORT_BASED.

    Args:
        port: Port number (1-16).
        priority: LOWEST (queue 0), NORMAL (queue 1), MEDIUM (queue 2), or HIGHEST (queue 3).
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
    """Set per-port ingress and egress bandwidth rate limits.

    Args:
        port: Port number (1-16).
        ingress_rate: Max incoming traffic rate in kbps. 0 for unlimited.
        egress_rate: Max outgoing traffic rate in kbps. 0 for unlimited.
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
    """Configure storm control on a port to rate-limit flooding traffic.

    Args:
        port: Port number (1-16).
        enabled: True to activate storm control on this port.
        rate: Maximum allowed rate in kbps for controlled traffic types.
        broadcast: Rate-limit broadcast traffic (e.g. ARP storms).
        multicast: Rate-limit multicast traffic.
        unknown_unicast: Rate-limit unknown unicast traffic (flooded frames).
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


# ===================================================================
# SECURITY
# ===================================================================


@mcp.tool()
async def get_igmp_snooping() -> dict[str, Any]:
    """Get IGMP snooping configuration and the current multicast group table.

    IGMP snooping constrains multicast traffic to only the ports with interested
    receivers, instead of flooding it to all ports.
    """
    client = _get_client()
    return _to_dict(await client.get_igmp_snooping())


@mcp.tool()
async def get_loop_prevention() -> dict[str, bool]:
    """Check whether loop prevention is enabled.

    Loop prevention detects and blocks Layer 2 loops caused by
    incorrect cabling or misconfiguration.
    """
    client = _get_client()
    return {"enabled": await client.get_loop_prevention()}


@mcp.tool()
async def set_igmp_snooping(enabled: bool, report_suppression: bool = False) -> str:
    """Enable or disable IGMP snooping.

    Args:
        enabled: True to enable IGMP snooping.
        report_suppression: True to suppress duplicate IGMP membership reports
            (reduces multicast control traffic on the uplink).
    """
    client = _get_client()
    try:
        await client.set_igmp_snooping(enabled=enabled, report_suppression=report_suppression)
    except SwitchError as e:
        return _err(e)
    return f"IGMP snooping {'enabled' if enabled else 'disabled'}"


@mcp.tool()
async def set_loop_prevention(enabled: bool) -> str:
    """Enable or disable loop prevention.

    Args:
        enabled: True to enable loop detection and blocking.
    """
    client = _get_client()
    try:
        await client.set_loop_prevention(enabled=enabled)
    except SwitchError as e:
        return _err(e)
    return f"Loop prevention {'enabled' if enabled else 'disabled'}"


# ===================================================================
# DIAGNOSTICS
# ===================================================================


@mcp.tool()
async def get_cable_diagnostics() -> list[dict[str, Any]]:
    """Get cable diagnostics results (must call run_cable_test first).

    Per-port: status (NOT_TESTED, NO_CABLE, NORMAL, OPEN, SHORT, OPEN_SHORT,
    CROSSTALK) and length_m (estimated cable length in meters).
    """
    client = _get_client()
    return _to_dict(await client.get_cable_diagnostics())


@mcp.tool()
async def run_cable_test(ports: list[int]) -> str:
    """Start cable diagnostics (TDR test) on specified ports.

    Tests cable quality and estimates length. Results are available via
    get_cable_diagnostics after the test completes (~2 seconds).

    Args:
        ports: Port numbers to test (1-16).
    """
    client = _get_client()
    try:
        await client.run_cable_test(ports)
    except SwitchError as e:
        return _err(e)
    return f"Cable test started on ports {ports}"


@mcp.tool()
async def search_mac_table(mac_address: str) -> list[Any]:
    """Search the switch's MAC address table for a specific MAC address.

    Useful for finding which port a device is connected to.

    Args:
        mac_address: MAC address in dash-separated format (e.g. "AA-BB-CC-DD-EE-FF").
    """
    client = _get_client()
    return await client.search_mac_table(mac_address)


# ===================================================================
# LAG / PORT MIRRORING / PORT ISOLATION
# ===================================================================


@mcp.tool()
async def get_lag_config() -> dict[str, Any]:
    """Get link aggregation (LAG / port trunking) configuration.

    LAGs bond multiple physical ports into a single logical link for
    increased bandwidth and redundancy. Up to 8 groups supported.
    """
    client = _get_client()
    return _to_dict(await client.get_lag_config())


@mcp.tool()
async def get_port_mirror_config() -> dict[str, Any]:
    """Get port mirroring configuration.

    Port mirroring copies traffic from source ports to a destination
    (monitoring) port for packet capture or analysis. Shows which ports
    are mirrored for ingress (incoming) and/or egress (outgoing) traffic.
    """
    client = _get_client()
    return _to_dict(await client.get_port_mirror_config())


@mcp.tool()
async def create_lag(group_id: int, ports: list[int]) -> str:
    """Create or modify a link aggregation group (LAG / port trunk).

    Member ports are bonded into a single logical link. Ports in a LAG
    must have identical speed and duplex settings.

    Args:
        group_id: LAG group ID (1-8).
        ports: Member port numbers to bond together.
    """
    client = _get_client()
    try:
        await client.create_lag(group_id, ports)
    except SwitchError as e:
        return _err(e)
    return f"LAG group {group_id} created with ports {ports}"


@mcp.tool()
async def delete_lag(group_id: int) -> str:
    """Delete a link aggregation group, releasing its member ports.

    Args:
        group_id: LAG group ID to delete (1-8).
    """
    client = _get_client()
    try:
        await client.delete_lag(group_id)
    except SwitchError as e:
        return _err(e)
    return f"LAG group {group_id} deleted"


@mcp.tool()
async def set_port_mirror(
    enabled: bool,
    destination_port: int = 1,
    ingress_ports: list[int] | None = None,
    egress_ports: list[int] | None = None,
) -> str:
    """Configure port mirroring for traffic analysis.

    Copies traffic from source ports to a destination port where a
    packet sniffer or analyzer can be connected.

    Args:
        enabled: True to enable mirroring.
        destination_port: The monitoring port that receives copied traffic.
        ingress_ports: Source ports to mirror incoming traffic from.
        egress_ports: Source ports to mirror outgoing traffic from.
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
