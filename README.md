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

| Tool | Description |
|---|---|
| `get_device_info` | Device name, MAC, IP, firmware, hardware version |
| `get_port_states` | All ports: enabled, speed, flow control |
| `get_poe_port_states` | PoE ports: power, voltage, current, PD class, status |
| `get_poe_global_state` | Global PoE power budget, consumption, remaining |
| `set_port_state` | Enable/disable a port, set speed and flow control |
| `set_poe_limit` | Set the global PoE power budget (watts) |
| `set_poe_port` | Configure per-port PoE: enable, priority, power limit |

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
