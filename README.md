# tplink-sg1016-mcp

> **WARNING:** This project is in early development. Many tools are based
> on reverse-engineered API endpoints, **not official documentation**. Not
> all tools have been thoroughly tested against real hardware. Write
> operations (port config, PoE, VLANs, QoS, rebooting, IP changes, etc.)
> can disrupt your network or make the switch unreachable if used
> incorrectly. **Use at your own risk.** Always verify critical changes
> through the switch's web UI.

MCP server for TP-Link SG1016PE Easy Smart switches. Exposes switch management
over the [Model Context Protocol](https://modelcontextprotocol.io/) (stdio
transport), so you can query and configure the switch from Claude Code or any
other MCP client.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- A TP-Link SG1016PE (or compatible Easy Smart) switch reachable over HTTP

## Configuration

The server is configured via environment variables:

| Variable | Default | Description |
|---|---|---|
| `TPLINK_HOST` | `192.168.0.1` | Switch IP address |
| `TPLINK_PORT` | `80` | Web interface port |
| `TPLINK_USERNAME` | `admin` | Login username |
| `TPLINK_PASSWORD` | *(empty)* | Login password |
| `TPLINK_USE_SSL` | `false` | Use HTTPS |
| `TPLINK_VERIFY_SSL` | `false` | Verify SSL certificate |

## Running

### With uv (development)

```sh
uv run tplink-sg1016-mcp
```

### With the PEX executable

Build a self-contained executable:

```sh
uv run tox -e pex
```

This produces `dist/tplink-sg1016-mcp.pex`. Run it directly:

```sh
TPLINK_PASSWORD=secret ./dist/tplink-sg1016-mcp.pex
```

## Claude Code integration

Add to your MCP config (e.g. `~/.claude/settings.json` or `.claude/settings.json`):

```json
{
  "mcpServers": {
    "tplink": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/tplink-sg1016-mcp", "tplink-sg1016-mcp"],
      "env": {
        "TPLINK_HOST": "192.168.0.1",
        "TPLINK_PASSWORD": "your-password"
      }
    }
  }
}
```

Or using the PEX:

```json
{
  "mcpServers": {
    "tplink": {
      "command": "/path/to/dist/tplink-sg1016-mcp.pex",
      "env": {
        "TPLINK_HOST": "192.168.0.1",
        "TPLINK_PASSWORD": "your-password"
      }
    }
  }
}
```

## Available tools

### System

| Tool | Description |
|---|---|
| `get_device_info` | Model name, MAC, IP, firmware, hardware version |
| `get_ip_settings` | Switch management IP config (DHCP/static) |
| `get_led_status` | Front-panel LED on/off state |
| `set_device_name` | Change the switch's system name |
| `set_ip_settings` | Change management IP (DHCP or static) |
| `set_led` | Turn front-panel LEDs on/off |
| `reboot_switch` | Reboot the switch (saves config first) |

### Port management

| Tool | Description |
|---|---|
| `get_port_states` | All 16 ports: admin state, speed, flow control |
| `get_port_statistics` | Per-port TX/RX good/bad packet counters |
| `set_port_state` | Enable/disable a port, set speed and flow control |

### PoE (Power over Ethernet)

| Tool | Description |
|---|---|
| `get_poe_port_states` | Per-port power, voltage, current, PD class, status |
| `get_poe_global_state` | Switch-wide power budget, consumption, remaining |
| `get_poe_recovery` | PoE auto-recovery (ping watchdog) config |
| `set_poe_global_limit` | Set the global PoE power budget (watts) |
| `set_poe_port` | Configure per-port PoE: enable, priority, power limit |
| `repower_poe_port` | Power-cycle a PoE port to reboot connected device |

### 802.1Q VLANs

| Tool | Description |
|---|---|
| `get_vlan_config` | All VLANs with tagged/untagged port membership |
| `get_pvid_config` | Per-port PVID (native VLAN) assignments |
| `set_vlan_enabled` | Enable/disable 802.1Q VLAN mode |
| `create_vlan` | Create a new VLAN with optional initial port memberships |
| `add_vlan_members` | Add ports to an existing VLAN (reads current state first) |
| `remove_vlan_members` | Remove ports from an existing VLAN (reads current state first) |
| `delete_vlan` | Delete a VLAN |
| `set_port_pvid` | Set a port's native VLAN for untagged traffic |

### QoS (Quality of Service)

| Tool | Description |
|---|---|
| `get_qos_config` | QoS mode and per-port priority queues |
| `get_bandwidth_limits` | Per-port ingress/egress rate limits |
| `get_storm_control` | Per-port storm control settings |
| `set_qos_mode` | Set QoS mode (port-based, 802.1p, DSCP) |
| `set_port_qos_priority` | Set a port's priority queue |
| `set_bandwidth_limit` | Set per-port ingress/egress rate limits |
| `set_storm_control` | Configure per-port storm control |

### Security

| Tool | Description |
|---|---|
| `get_igmp_snooping` | IGMP snooping config and multicast groups |
| `get_loop_prevention` | Loop prevention enabled/disabled |
| `set_igmp_snooping` | Enable/disable IGMP snooping |
| `set_loop_prevention` | Enable/disable loop prevention |

### Diagnostics

| Tool | Description |
|---|---|
| `get_cable_diagnostics` | Cable test results (status, length) |
| `run_cable_test` | Start TDR cable test on selected ports |
| `search_mac_table` | Find which port a MAC address is on |

### LAG / Mirroring

| Tool | Description |
|---|---|
| `get_lag_config` | Link aggregation groups and member ports |
| `get_port_mirror_config` | Port mirroring setup (source/destination) |
| `create_lag` | Create/modify a link aggregation group |
| `delete_lag` | Delete a link aggregation group |
| `set_port_mirror` | Configure port mirroring for traffic analysis |

## Development

Install dev dependencies:

```sh
uv sync
```

Run all checks:

```sh
uv run tox
```

Individual tox environments:

```sh
uv run tox -e lint      # ruff linter
uv run tox -e format    # ruff format check
uv run tox -e pex       # build PEX executable
```

Format code:

```sh
uv run ruff format src/
```

Format `tox.ini`:

```sh
uv run tox-ini-fmt tox.ini
```
