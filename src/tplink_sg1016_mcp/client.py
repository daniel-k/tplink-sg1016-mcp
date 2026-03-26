"""HTTP client for the TP-Link SG1016PE Easy Smart switch web interface."""

import asyncio
import logging
from typing import Any

import aiohttp

from .models import (
    CableDiagResult,
    CableStatus,
    DashboardInfo,
    DeviceInfo,
    DhcpSnoopingConfig,
    DhcpSnoopingPort,
    IgmpGroup,
    IgmpSnoopingConfig,
    IpSettings,
    LagConfig,
    LagGroup,
    PoeClass,
    PoeExtendConfig,
    PoeExtendPort,
    PoeGlobalState,
    PoePowerLimit,
    PoePowerStatus,
    PoePriority,
    PoeRecoveryConfig,
    PoeRecoveryPort,
    PortBandwidthLimit,
    PortIsolationEntry,
    PortMirrorConfig,
    PortPoeState,
    PortPvid,
    PortQosPriority,
    PortRate,
    PortSpeed,
    PortState,
    PortStatistics,
    PortStormControl,
    PvidConfig,
    QosConfig,
    QosMode,
    QosPriority,
    Vlan,
    VlanConfig,
    VlanPortMembership,
)
from .parsing import VarType, get_variable, get_variables

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 5.0

_POE_PRIORITY_TO_WIRE: dict[PoePriority, int] = {
    PoePriority.HIGH: 1,
    PoePriority.MIDDLE: 2,
    PoePriority.LOW: 3,
}

_POE_POWER_LIMIT_TO_WIRE: dict[PoePowerLimit, tuple[int, str | None]] = {
    PoePowerLimit.AUTO: (1, None),
    PoePowerLimit.CLASS_1: (2, "(4w)"),
    PoePowerLimit.CLASS_2: (3, "(7w)"),
    PoePowerLimit.CLASS_3: (4, "(15.4w)"),
    PoePowerLimit.CLASS_4: (5, "(30w)"),
}


class SwitchError(Exception):
    pass


class AuthenticationError(SwitchError):
    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class SwitchClient:
    """Async client for the TP-Link SG1016PE web API."""

    def __init__(
        self,
        host: str,
        port: int = 80,
        username: str = "admin",
        password: str = "",
        *,
        use_ssl: bool = False,
        verify_ssl: bool = False,
    ) -> None:
        scheme = "https" if use_ssl else "http"
        self._base_url = f"{scheme}://{host}:{port}"
        self._username = username
        self._password = password
        self._verify_ssl = verify_ssl
        self._session: aiohttp.ClientSession | None = None
        self._lock = asyncio.Lock()
        self._poe_available: bool | None = None

    # --- session lifecycle ---

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            jar = aiohttp.CookieJar(unsafe=True)
            self._session = aiohttp.ClientSession(cookie_jar=jar)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # --- low-level HTTP ---

    async def _get(self, path: str) -> str:
        session = self._ensure_session()
        resp = await session.get(
            f"{self._base_url}/{path}",
            ssl=self._verify_ssl if self._verify_ssl else False,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        )
        return (await resp.content.read()).decode("utf-8")

    async def _post(self, path: str, data: dict[str, Any]) -> str:
        session = self._ensure_session()
        resp = await session.post(
            f"{self._base_url}/{path}",
            data=data,
            ssl=self._verify_ssl if self._verify_ssl else False,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        )
        return (await resp.content.read()).decode("utf-8")

    # --- authentication ---

    async def authenticate(self) -> None:
        """Log in to the switch. Raises AuthenticationError on failure."""
        session = self._ensure_session()
        session.cookie_jar.clear()

        page = await self._post(
            "logon.cgi",
            {
                "username": self._username,
                "password": self._password,
                "cpassword": "",
                "logon": "Login",
            },
        )
        info = get_variable(page, "logonInfo", VarType.LIST)
        if not info:
            raise AuthenticationError("No logon response", "no_response")

        code = info[0]
        if code == "0":
            return

        reasons: dict[str, tuple[str, str]] = {
            "1": ("Invalid username or password", "invalid_credentials"),
            "2": ("User not allowed to login", "user_blocked"),
            "3": ("Too many users logged in", "too_many_users"),
            "4": ("Max concurrent logins (16) exceeded", "too_many_users"),
            "5": ("Session timeout", "session_timeout"),
        }
        msg, reason = reasons.get(code, (f"Unknown logon error: {code}", "unknown"))
        raise AuthenticationError(msg, reason)

    def _is_authorized(self, page: str) -> bool:
        logon_info = get_variable(page, "logonInfo", VarType.STR)
        return logon_info is None

    async def _authed_get(self, path: str) -> str:
        """GET with automatic re-authentication on session expiry."""
        async with self._lock:
            if self._session is None or self._session.closed:
                await self.authenticate()

            page = await self._get(path)
            if not self._is_authorized(page):
                await self.authenticate()
                page = await self._get(path)
                if not self._is_authorized(page):
                    raise SwitchError(f"Unauthorized after re-auth: {path}")
            return page

    async def _authed_post(self, path: str, data: dict[str, Any]) -> str:
        """POST with automatic re-authentication on session expiry."""
        async with self._lock:
            if self._session is None or self._session.closed:
                await self.authenticate()

            page = await self._post(path, data)
            if not self._is_authorized(page):
                await self.authenticate()
                page = await self._post(path, data)
                if not self._is_authorized(page):
                    raise SwitchError(f"Unauthorized after re-auth: {path}")
            return page

    # --- feature detection ---

    async def is_poe_available(self) -> bool:
        if self._poe_available is not None:
            return self._poe_available
        try:
            page = await self._authed_get("PoeConfigRpm.htm")
            data = get_variables(
                page, [("portConfig", VarType.DICT), ("poe_port_num", VarType.INT)]
            )
            poe_port_num = data.get("poe_port_num")
            self._poe_available = (
                data.get("portConfig") is not None and poe_port_num is not None and poe_port_num > 0
            )
        except Exception:
            self._poe_available = False
        return self._poe_available

    # --- helpers ---

    @staticmethod
    def _bitmask_to_ports(mask: int, port_count: int) -> list[int]:
        """Convert a port bitmask to a list of 1-based port numbers."""
        return [i + 1 for i in range(port_count) if mask & (1 << i)]

    # ===================================================================
    # QUERIES
    # ===================================================================

    async def get_device_info(self) -> DeviceInfo:
        page = await self._authed_get("SystemInfoRpm.htm")
        data = get_variable(page, "info_ds", VarType.DICT)

        def val(key: str) -> str | None:
            if data is None:
                return None
            arr = data.get(key, [])
            return arr[0] if len(arr) == 1 else None

        return DeviceInfo(
            name=val("descriStr"),
            mac=val("macStr"),
            ip=val("ipStr"),
            netmask=val("netmaskStr"),
            gateway=val("gatewayStr"),
            firmware=val("firmwareStr"),
            hardware=val("hardwareStr"),
        )

    async def get_dashboard(self) -> DashboardInfo:
        """Get the main dashboard with live port TX/RX rates and uptime."""
        page = await self._authed_get("MainRpm.htm")
        data = get_variables(
            page,
            [
                ("info_ds", VarType.DICT),
                ("port_info", VarType.DICT),
                ("max_port_num", VarType.INT),
            ],
        )

        info_ds = data.get("info_ds") or {}
        port_info = data.get("port_info") or {}
        max_ports = data.get("max_port_num") or 0

        work_time = info_ds.get("workTime", ["0"])[0] if info_ds.get("workTime") else "0"

        states = port_info.get("state", [])
        spd_act = port_info.get("spd_act", [])
        rx_rates = port_info.get("rx_rate", [])
        tx_rates = port_info.get("tx_rate", [])

        ports: list[PortRate] = []
        for i in range(max_ports):
            ports.append(
                PortRate(
                    number=i + 1,
                    enabled=states[i] == 1 if i < len(states) else False,
                    link_speed=PortSpeed(spd_act[i]) if i < len(spd_act) else PortSpeed.LINK_DOWN,
                    tx_rate=tx_rates[i] if i < len(tx_rates) else 0,
                    rx_rate=rx_rates[i] if i < len(rx_rates) else 0,
                )
            )

        return DashboardInfo(uptime=str(work_time), ports=ports)

    async def get_port_statistics(self) -> list[PortStatistics]:
        """Get per-port packet statistics."""
        page = await self._authed_get("PortStatisticsRpm.htm")
        data = get_variables(page, [("all_info", VarType.DICT), ("max_port_num", VarType.INT)])

        all_info = data.get("all_info")
        max_ports = data.get("max_port_num")
        if not all_info or not max_ports:
            return []

        # All arrays have 2 trailing zero-padding elements beyond max_port_num.
        # pkts has 4 values per port (stride 4), so 8 trailing zeros.
        states = all_info.get("state", [])
        link_statuses = all_info.get("link_status", [])
        pkts = all_info.get("pkts", [])

        result: list[PortStatistics] = []
        for i in range(max_ports):
            base = i * 4
            result.append(
                PortStatistics(
                    number=i + 1,
                    enabled=states[i] == 1 if i < len(states) else False,
                    link_status=PortSpeed(link_statuses[i])
                    if i < len(link_statuses)
                    else PortSpeed.LINK_DOWN,
                    tx_good_packets=pkts[base] if base < len(pkts) else 0,
                    tx_bad_packets=pkts[base + 1] if base + 1 < len(pkts) else 0,
                    rx_good_packets=pkts[base + 2] if base + 2 < len(pkts) else 0,
                    rx_bad_packets=pkts[base + 3] if base + 3 < len(pkts) else 0,
                )
            )
        return result

    async def get_port_states(self) -> list[PortState]:
        page = await self._authed_get("PortSettingRpm.htm")
        data = get_variables(page, [("all_info", VarType.DICT), ("max_port_num", VarType.INT)])

        all_info = data.get("all_info")
        max_ports = data.get("max_port_num")
        if not all_info or not max_ports:
            return []

        result: list[PortState] = []
        for i in range(max_ports):
            result.append(
                PortState(
                    number=i + 1,
                    enabled=all_info["state"][i] == 1,
                    speed_config=PortSpeed(all_info["spd_cfg"][i]),
                    speed_actual=PortSpeed(all_info["spd_act"][i]),
                    flow_control_config=all_info["fc_cfg"][i] == 1,
                    flow_control_actual=all_info["fc_act"][i] == 1,
                )
            )
        return result

    async def get_ip_settings(self) -> IpSettings:
        """Get the switch's IP configuration."""
        page = await self._authed_get("IpSettingRpm.htm")
        data = get_variable(page, "ip_ds", VarType.DICT)
        if not data:
            return IpSettings(dhcp_enabled=False, ip="", netmask="", gateway="")
        return IpSettings(
            dhcp_enabled=data.get("state", 0) == 1,
            ip=data.get("ipStr", [""])[0] if data.get("ipStr") else "",
            netmask=data.get("netmaskStr", [""])[0] if data.get("netmaskStr") else "",
            gateway=data.get("gatewayStr", [""])[0] if data.get("gatewayStr") else "",
        )

    async def get_led_status(self) -> bool:
        """Get whether the switch LEDs are on. Returns True if on."""
        page = await self._authed_get("TurnOnLEDRpm.htm")
        led = get_variable(page, "led", VarType.INT)
        return led == 1

    async def get_cable_diagnostics(self) -> list[CableDiagResult]:
        """Get cable diagnostics results (run run_cable_test first)."""
        page = await self._authed_get("CableDiagRpm.htm")
        data = get_variables(
            page,
            [
                ("maxPort", VarType.INT),
                ("cablestate", VarType.LIST),
                ("cablelength", VarType.LIST),
            ],
        )
        max_port = data.get("maxPort") or 0
        states = data.get("cablestate") or []
        lengths = data.get("cablelength") or []

        result: list[CableDiagResult] = []
        for i in range(max_port):
            raw_status = int(states[i]) if i < len(states) else -1
            length = int(lengths[i]) if i < len(lengths) else 0
            result.append(
                CableDiagResult(
                    port=i + 1,
                    status=CableStatus(raw_status),
                    length_m=length,
                )
            )
        return result

    async def get_igmp_snooping(self) -> IgmpSnoopingConfig:
        """Get IGMP snooping configuration and multicast group table."""
        page = await self._authed_get("IgmpSnoopingRpm.htm")
        data = get_variable(page, "igmp_ds", VarType.DICT)
        if not data:
            return IgmpSnoopingConfig(enabled=False, report_suppression=False)

        enabled = data.get("state", 0) == 1
        suppression = data.get("suppressionState", 0) == 1
        count = data.get("count", 0)

        groups: list[IgmpGroup] = []
        ip_list = data.get("ipStr", [])
        vlan_list = data.get("vlanStr", [])
        port_list = data.get("portStr", [])
        for i in range(count):
            groups.append(
                IgmpGroup(
                    ip=ip_list[i] if i < len(ip_list) else "",
                    vlan=vlan_list[i] if i < len(vlan_list) else "",
                    ports=port_list[i] if i < len(port_list) else "",
                )
            )

        return IgmpSnoopingConfig(enabled=enabled, report_suppression=suppression, groups=groups)

    async def get_lag_config(self) -> LagConfig:
        """Get link aggregation group (LAG / port trunk) configuration."""
        page = await self._authed_get("PortTrunkRpm.htm")
        data = get_variable(page, "trunk_conf", VarType.DICT)
        if not data:
            return LagConfig(max_groups=0, port_count=0)

        max_groups = data.get("maxTrunkNum", 8)
        port_count = data.get("portNum", 0)

        groups: list[LagGroup] = []
        for g in range(1, max_groups + 1):
            port_str = data.get(f"portStr_g{g}", [])
            ports = [int(p) for p in port_str if int(p) > 0] if port_str else []
            if ports:
                groups.append(LagGroup(group_id=g, ports=ports))

        return LagConfig(max_groups=max_groups, port_count=port_count, groups=groups)

    async def get_port_mirror_config(self) -> PortMirrorConfig:
        """Get port mirroring configuration."""
        page = await self._authed_get("PortMirrorRpm.htm")
        data = get_variables(
            page,
            [
                ("MirrEn", VarType.INT),
                ("MirrPort", VarType.INT),
                ("mirr_info", VarType.DICT),
                ("max_port_num", VarType.INT),
            ],
        )

        enabled = data.get("MirrEn", 0) == 1
        dest_port = data.get("MirrPort", 0)
        max_ports = data.get("max_port_num", 0)
        mirr_info = data.get("mirr_info") or {}

        ingress = mirr_info.get("ingress", [])
        egress = mirr_info.get("egress", [])

        ingress_ports = [i + 1 for i in range(min(max_ports, len(ingress))) if ingress[i] == 1]
        egress_ports = [i + 1 for i in range(min(max_ports, len(egress))) if egress[i] == 1]

        return PortMirrorConfig(
            enabled=enabled,
            destination_port=dest_port,
            ingress_ports=ingress_ports,
            egress_ports=egress_ports,
        )

    async def get_loop_prevention(self) -> bool:
        """Get loop prevention status. Returns True if enabled."""
        page = await self._authed_get("LoopPreventionRpm.htm")
        return get_variable(page, "lpEn", VarType.INT) == 1

    async def get_qos_config(self) -> QosConfig:
        """Get QoS mode and per-port priority settings."""
        page = await self._authed_get("QosBasicRpm.htm")
        data = get_variables(
            page,
            [
                ("qosMode", VarType.INT),
                ("pPri", VarType.LIST),
                ("portNumber", VarType.INT),
            ],
        )

        mode = QosMode(data.get("qosMode", 0))
        port_count = data.get("portNumber", 0)
        pri_list = data.get("pPri") or []

        priorities: list[PortQosPriority] = []
        for i in range(port_count):
            raw = int(pri_list[i]) if i < len(pri_list) else 0
            priorities.append(PortQosPriority(port=i + 1, priority=QosPriority(raw)))

        return QosConfig(mode=mode, port_priorities=priorities)

    async def get_bandwidth_limits(self) -> list[PortBandwidthLimit]:
        """Get per-port bandwidth rate limiting configuration."""
        page = await self._authed_get("QosBandWidthControlRpm.htm")
        data = get_variables(
            page,
            [("bcInfo", VarType.LIST), ("portNumber", VarType.INT)],
        )

        port_count = data.get("portNumber", 0)
        bc_info = data.get("bcInfo") or []

        result: list[PortBandwidthLimit] = []
        for i in range(port_count):
            base = i * 3
            ingress = int(bc_info[base]) if base < len(bc_info) else 0
            egress = int(bc_info[base + 1]) if base + 1 < len(bc_info) else 0
            result.append(PortBandwidthLimit(port=i + 1, ingress_rate=ingress, egress_rate=egress))
        return result

    async def get_storm_control(self) -> list[PortStormControl]:
        """Get per-port storm control configuration."""
        page = await self._authed_get("QosStormControlRpm.htm")
        data = get_variables(
            page,
            [("scInfo", VarType.LIST), ("portNumber", VarType.INT)],
        )

        port_count = data.get("portNumber", 0)
        sc_info = data.get("scInfo") or []

        result: list[PortStormControl] = []
        for i in range(port_count):
            base = i * 3
            rate = int(sc_info[base]) if base < len(sc_info) else 0
            type_mask = int(sc_info[base + 1]) if base + 1 < len(sc_info) else 0
            result.append(
                PortStormControl(
                    port=i + 1,
                    rate=rate,
                    unknown_unicast=bool(type_mask & 1),
                    multicast=bool(type_mask & 2),
                    broadcast=bool(type_mask & 4),
                )
            )
        return result

    async def get_poe_recovery(self) -> PoeRecoveryConfig:
        """Get PoE auto-recovery (ping watchdog) configuration."""
        if not await self.is_poe_available():
            return PoeRecoveryConfig(enabled=False)

        page = await self._authed_get("poeRecoveryRpm.htm")
        data = get_variables(
            page,
            [
                ("globalRecoveryConfig", VarType.DICT),
                ("portRecoveryConfig", VarType.DICT),
                ("poe_port_num", VarType.INT),
            ],
        )

        global_cfg = data.get("globalRecoveryConfig") or {}
        port_cfg = data.get("portRecoveryConfig") or {}
        num_ports = data.get("poe_port_num") or 0
        enabled = global_cfg.get("global_status", 0) == 1

        ports: list[PoeRecoveryPort] = []
        ips = port_cfg.get("ip", [])
        startups = port_cfg.get("startup", [])
        intervals = port_cfg.get("interval", [])
        retries = port_cfg.get("retry", [])
        reboots = port_cfg.get("reboot", [])
        failures = port_cfg.get("failure", [])
        totals = port_cfg.get("total", [])
        statuses = port_cfg.get("status", [])

        for i in range(num_ports):
            ports.append(
                PoeRecoveryPort(
                    port=i + 1,
                    ip=ips[i] if i < len(ips) else "",
                    startup_interval=startups[i] if i < len(startups) else 0,
                    ping_interval=intervals[i] if i < len(intervals) else 0,
                    max_retries=retries[i] if i < len(retries) else 0,
                    reboot_count=reboots[i] if i < len(reboots) else 0,
                    failure_count=failures[i] if i < len(failures) else 0,
                    total_restarts=totals[i] if i < len(totals) else 0,
                    status=statuses[i] if i < len(statuses) else 0,
                )
            )

        return PoeRecoveryConfig(enabled=enabled, ports=ports)

    async def get_poe_extend(self) -> PoeExtendConfig:
        """Get PoE extend mode status per port."""
        if not await self.is_poe_available():
            return PoeExtendConfig()

        page = await self._authed_get("poeExtendRpm.htm")
        data = get_variables(
            page,
            [("poeExtendConfig", VarType.DICT), ("poe_port_num", VarType.INT)],
        )

        ext_cfg = data.get("poeExtendConfig") or {}
        num_ports = data.get("poe_port_num") or 0
        statuses = ext_cfg.get("status", [])

        ports: list[PoeExtendPort] = []
        for i in range(num_ports):
            ports.append(
                PoeExtendPort(
                    port=i + 1,
                    enabled=statuses[i] == 1 if i < len(statuses) else False,
                )
            )
        return PoeExtendConfig(ports=ports)

    async def get_dhcp_snooping(self) -> DhcpSnoopingConfig:
        """Get DHCP snooping configuration."""
        page = await self._authed_get("DhcpSnoopingRpm.htm")
        data = get_variable(page, "dhcp_ds", VarType.DICT)
        if not data:
            return DhcpSnoopingConfig(enabled=False)

        enabled = data.get("state", 0) == 1
        trust_list = data.get("trust", [])

        ports: list[DhcpSnoopingPort] = []
        for i, trusted in enumerate(trust_list):
            ports.append(DhcpSnoopingPort(port=i + 1, trusted=trusted == 1))

        return DhcpSnoopingConfig(enabled=enabled, ports=ports)

    async def get_port_isolation(self) -> list[PortIsolationEntry]:
        """Get port isolation / forwarding restrictions."""
        page = await self._authed_get("PortIsolationRpm.htm")
        data = get_variable(page, "portIso_conf", VarType.DICT)
        if not data:
            return []

        port_iso = data.get("port_iso", [])
        port_count = len(port_iso)

        result: list[PortIsolationEntry] = []
        for i in range(port_count):
            mask = port_iso[i]
            result.append(
                PortIsolationEntry(
                    port=i + 1,
                    forwarding_ports=self._bitmask_to_ports(mask, port_count),
                )
            )
        return result

    async def search_mac_table(self, mac_address: str) -> list[dict[str, Any]]:
        """Search the MAC address table for a specific MAC."""
        page = await self._authed_get(
            f"mac_address_search.cgi?txt_macAddress_search={mac_address}&apply=Search"
        )
        data = get_variable(page, "mac_ds", VarType.DICT)
        if not data:
            return []
        return data.get("mac_info", [])

    # --- PoE queries ---

    async def get_poe_port_states(self) -> list[PortPoeState]:
        if not await self.is_poe_available():
            return []

        page = await self._authed_get("PoeConfigRpm.htm")
        data = get_variables(page, [("portConfig", VarType.DICT), ("poe_port_num", VarType.INT)])

        port_config = data.get("portConfig")
        num_ports = data.get("poe_port_num")
        if not port_config or not num_ports:
            return []

        # Firmware quirk: PoE read uses 1=enabled, but write uses 2=enabled/1=disabled.
        # Priority read uses 0=HIGH/1=MIDDLE/2=LOW, write uses 1=HIGH/2=MIDDLE/3=LOW.
        result: list[PortPoeState] = []
        for i in range(num_ports):
            raw_limit = port_config["powerlimit"][i]
            power_limit: PoePowerLimit | float
            is_known_limit = raw_limit in PoePowerLimit.__members__.values()
            power_limit = PoePowerLimit(raw_limit) if is_known_limit else raw_limit / 10

            raw_pdclass = port_config["pdclass"][i]
            is_known_class = raw_pdclass in PoeClass.__members__.values()
            pd_class = PoeClass(raw_pdclass) if is_known_class else None

            result.append(
                PortPoeState(
                    number=i + 1,
                    enabled=port_config["state"][i] == 1,
                    priority=PoePriority(port_config["priority"][i]),
                    power_limit=power_limit,
                    power_watts=port_config["power"][i] / 10,
                    current_ma=port_config["current"][i],
                    voltage_v=port_config["voltage"][i] / 10,
                    pd_class=pd_class,
                    power_status=PoePowerStatus(port_config["powerstatus"][i]),
                )
            )
        return result

    async def get_poe_global_state(self) -> PoeGlobalState | None:
        if not await self.is_poe_available():
            return None

        page = await self._authed_get("PoeConfigRpm.htm")
        cfg = get_variable(page, "globalConfig", VarType.DICT)
        if not cfg:
            return None

        return PoeGlobalState(
            power_limit=cfg.get("system_power_limit", 0) / 10,
            power_limit_min=cfg.get("system_power_limit_min", 0) / 10,
            power_limit_max=cfg.get("system_power_limit_max", 0) / 10,
            power_consumption=cfg.get("system_power_consumption", 0) / 10,
            power_remain=cfg.get("system_power_remain", 0) / 10,
        )

    # --- VLAN queries ---

    async def get_vlan_config(self) -> VlanConfig:
        """Get the 802.1Q VLAN configuration."""
        page = await self._authed_get("Vlan8021QRpm.htm")
        data = get_variable(page, "qvlan_ds", VarType.DICT)
        if not data:
            return VlanConfig(enabled=False, port_count=0, max_vlans=0)

        enabled = data.get("state", 0) == 1
        port_count = data.get("portNum", 0)
        max_vlans = data.get("maxVids", 0)
        vids = data.get("vids", [])
        names = data.get("names", [])
        tag_mbrs = data.get("tagMbrs", [])
        untag_mbrs = data.get("untagMbrs", [])

        vlans: list[Vlan] = []
        for i, vid in enumerate(vids):
            tagged_mask = tag_mbrs[i] if i < len(tag_mbrs) else 0
            untagged_mask = untag_mbrs[i] if i < len(untag_mbrs) else 0
            vlans.append(
                Vlan(
                    vid=int(vid),
                    name=names[i] if i < len(names) else "",
                    tagged_ports=self._bitmask_to_ports(tagged_mask, port_count),
                    untagged_ports=self._bitmask_to_ports(untagged_mask, port_count),
                )
            )

        return VlanConfig(
            enabled=enabled,
            port_count=port_count,
            max_vlans=max_vlans,
            vlans=vlans,
        )

    async def get_pvid_config(self) -> PvidConfig:
        """Get the per-port PVID (default VLAN) settings."""
        page = await self._authed_get("Vlan8021QPvidRpm.htm")
        data = get_variable(page, "pvid_ds", VarType.DICT)
        if not data:
            return PvidConfig(enabled=False, port_count=0)

        enabled = data.get("state", 0) == 1
        port_count = data.get("portNum", 0)
        pvid_list = data.get("pvids", [])

        pvids = [
            PortPvid(port=i + 1, pvid=int(pvid_list[i]))
            for i in range(min(port_count, len(pvid_list)))
        ]

        return PvidConfig(enabled=enabled, port_count=port_count, pvids=pvids)

    # ===================================================================
    # MUTATIONS
    # ===================================================================

    # --- VLAN ---

    async def set_vlan_enabled(self, *, enabled: bool) -> None:
        """Enable or disable 802.1Q VLAN mode."""
        query = f"qvlan_en={1 if enabled else 0}&qvlan_mode=Apply"
        await self._authed_get(f"qvlanSet.cgi?{query}")

    async def create_or_update_vlan(
        self,
        vid: int,
        name: str,
        port_memberships: dict[int, VlanPortMembership],
    ) -> None:
        """Create or modify an 802.1Q VLAN."""
        if not (1 <= vid <= 4094):
            raise SwitchError("VLAN ID must be between 1 and 4094")
        # Firmware only accepts alphanumeric VLAN names, max 10 chars
        name = "".join(c for c in name if c.isalnum())[:10]
        if not name:
            raise SwitchError("VLAN name must contain at least one alphanumeric character")

        config = await self.get_vlan_config()
        if not config.enabled:
            raise SwitchError("802.1Q VLAN is not enabled")

        membership_to_wire = {
            VlanPortMembership.UNTAGGED: 0,
            VlanPortMembership.TAGGED: 1,
            VlanPortMembership.NOT_MEMBER: 2,
        }

        params = [f"vid={vid}", f"vname={name}"]
        for port in range(1, config.port_count + 1):
            membership = port_memberships.get(port, VlanPortMembership.NOT_MEMBER)
            params.append(f"selType_{port}={membership_to_wire[membership]}")
        params.append("qvlan_add=Add%2FModify")

        await self._authed_get(f"qvlanSet.cgi?{'&'.join(params)}")

    async def delete_vlan(self, vid: int) -> None:
        """Delete an 802.1Q VLAN."""
        if vid == 1:
            raise SwitchError("Cannot delete the default VLAN (ID 1)")
        query = f"selVlans={vid}&qvlan_del=Delete"
        await self._authed_get(f"qvlanSet.cgi?{query}")

    async def set_port_pvid(self, port: int, pvid: int) -> None:
        """Set the PVID (default VLAN) for a port."""
        if port < 1:
            raise SwitchError("Port number must be >= 1")
        pbm = 1 << (port - 1)
        query = f"pbm={pbm}&pvid={pvid}"
        await self._authed_get(f"vlanPvidSet.cgi?{query}")

    # --- Port state ---

    async def set_port_state(
        self,
        port: int,
        *,
        enabled: bool,
        speed: PortSpeed = PortSpeed.AUTO,
        flow_control: bool = False,
    ) -> None:
        query = (
            f"portid={port}&state={1 if enabled else 0}"
            f"&speed={speed.value}&flowcontrol={1 if flow_control else 0}&apply=Apply"
        )
        await self._authed_get(f"port_setting.cgi?{query}")

    # --- PoE ---

    async def set_poe_limit(self, limit: float) -> None:
        if not await self.is_poe_available():
            raise SwitchError("PoE is not available on this device")

        current = await self.get_poe_global_state()
        if current is None:
            raise SwitchError("Cannot read current PoE state")
        if not (current.power_limit_min <= limit <= current.power_limit_max):
            raise SwitchError(
                f"Limit must be between {current.power_limit_min} and {current.power_limit_max}"
            )

        await self._authed_post(
            "poe_global_config.cgi",
            {
                "name_powerlimit": limit,
                "name_powerconsumption": current.power_consumption,
                "name_powerremain": current.power_remain,
                "applay": "Apply",
            },
        )

    async def set_poe_port_settings(
        self,
        port: int,
        *,
        enabled: bool,
        priority: PoePriority = PoePriority.HIGH,
        power_limit: PoePowerLimit | float = PoePowerLimit.AUTO,
    ) -> None:
        if not await self.is_poe_available():
            raise SwitchError("PoE is not available on this device")
        if port < 1:
            raise SwitchError("Port number must be >= 1")

        page = await self._authed_get("PoeConfigRpm.htm")
        poe_port_num = get_variable(page, "poe_port_num", VarType.INT)
        if poe_port_num is None:
            raise SwitchError("Cannot determine number of PoE ports")
        if port > poe_port_num:
            raise SwitchError(f"Port number must be <= {poe_port_num}")

        # Write API uses inverted convention: 2=enable, 1=disable (read uses 1=enabled)
        pstate = 2 if enabled else 1
        # Write priority: 1=HIGH, 2=MIDDLE, 3=LOW (read uses 0/1/2)
        ppriority = _POE_PRIORITY_TO_WIRE.get(priority)
        if ppriority is None:
            raise SwitchError(f"Invalid PoE priority: {priority}")

        if isinstance(power_limit, PoePowerLimit):
            entry = _POE_POWER_LIMIT_TO_WIRE.get(power_limit)
            if entry is None:
                raise SwitchError(f"Invalid PoE power limit: {power_limit}")
            ppowerlimit, ppowerlimit2 = entry
        elif isinstance(power_limit, (int, float)):
            if not (0.1 <= float(power_limit) <= 30.0):
                raise SwitchError("Custom power limit must be between 0.1 and 30.0 watts")
            ppowerlimit = 6
            ppowerlimit2 = float(power_limit)
        else:
            raise SwitchError(f"Invalid power_limit type: {type(power_limit)}")

        await self._authed_post(
            "poe_port_config.cgi",
            {
                "name_pstate": pstate,
                "name_ppriority": ppriority,
                "name_ppowerlimit": ppowerlimit,
                "name_ppowerlimit2": ppowerlimit2,
                f"sel_{port}": 1,
                "applay": "Apply",
            },
        )

    async def repower_poe_port(self, port: int) -> None:
        """Re-power (restart) a PoE port without changing its configuration."""
        if not await self.is_poe_available():
            raise SwitchError("PoE is not available on this device")
        await self._authed_post("main_poe_port_reset.cgi", {f"reset_{port}": "Re-power"})

    # --- LED ---

    async def set_led(self, *, on: bool) -> None:
        """Turn switch LEDs on or off."""
        query = f"rd_led={1 if on else 0}&led_cfg=Apply"
        await self._authed_get(f"led_on_set.cgi?{query}")

    # --- Cable diagnostics ---

    async def run_cable_test(self, ports: list[int]) -> None:
        """Trigger cable diagnostics on the specified ports."""
        params = [f"chk_{p}={p}" for p in ports]
        params.append("Apply=Apply")
        await self._authed_get(f"cable_diag_get.cgi?{'&'.join(params)}")

    # --- Loop prevention ---

    async def set_loop_prevention(self, *, enabled: bool) -> None:
        query = f"lpEn={1 if enabled else 0}&apply=Apply"
        await self._authed_get(f"loop_prevention_set.cgi?{query}")

    # --- IGMP snooping ---

    async def set_igmp_snooping(self, *, enabled: bool, report_suppression: bool = False) -> None:
        query = (
            f"igmp_mode={1 if enabled else 0}"
            f"&reportSu_mode={1 if report_suppression else 0}&Apply=Apply"
        )
        await self._authed_get(f"igmpSnooping.cgi?{query}")

    # --- QoS ---

    async def set_qos_mode(self, mode: QosMode) -> None:
        await self._authed_post(
            "qos_mode_set.cgi",
            {"rd_qosmode": mode.value, "qosmode": "Apply"},
        )

    async def set_port_qos_priority(self, port: int, priority: QosPriority) -> None:
        await self._authed_post(
            "qos_port_priority_set.cgi",
            {f"sel_{port}": 1, "port_queue": priority.value, "apply": "Apply"},
        )

    async def set_bandwidth_limit(self, port: int, *, ingress_rate: int, egress_rate: int) -> None:
        await self._authed_post(
            "qos_bandwidth_set.cgi",
            {
                f"sel_{port}": 1,
                "igrRate": ingress_rate,
                "egrRate": egress_rate,
                "applay": "Apply",
            },
        )

    async def set_storm_control(
        self,
        port: int,
        *,
        enabled: bool,
        rate: int,
        broadcast: bool = True,
        multicast: bool = False,
        unknown_unicast: bool = False,
    ) -> None:
        type_mask = 0
        if unknown_unicast:
            type_mask |= 1
        if multicast:
            type_mask |= 2
        if broadcast:
            type_mask |= 4
        await self._authed_post(
            "qos_storm_set.cgi",
            {
                f"sel_{port}": 1,
                "rate": rate,
                "stormType": type_mask,
                "state": 1 if enabled else 0,
                "applay": "Apply",
            },
        )

    # --- Port mirroring ---

    async def set_port_mirror(
        self,
        *,
        enabled: bool,
        destination_port: int = 1,
        ingress_ports: list[int] | None = None,
        egress_ports: list[int] | None = None,
    ) -> None:
        """Configure port mirroring: enable/disable and set destination."""
        await self._authed_get(
            f"mirror_enabled_set.cgi?state={1 if enabled else 0}"
            f"&mirroringport={destination_port}&mirrorenable=Apply"
        )
        if enabled and (ingress_ports or egress_ports):
            for port in ingress_ports or []:
                await self._authed_get(
                    f"mirrored_port_set.cgi?mirroredport={port}"
                    f"&ingressState=1&egressState=0&mirrored_submit=Apply"
                )
            for port in egress_ports or []:
                await self._authed_get(
                    f"mirrored_port_set.cgi?mirroredport={port}"
                    f"&ingressState=0&egressState=1&mirrored_submit=Apply"
                )
            # ports in both lists: set both directions
            both = set(ingress_ports or []) & set(egress_ports or [])
            for port in both:
                await self._authed_get(
                    f"mirrored_port_set.cgi?mirroredport={port}"
                    f"&ingressState=1&egressState=1&mirrored_submit=Apply"
                )

    # --- Port isolation ---

    async def set_port_isolation(self, port: int, forwarding_ports: list[int]) -> None:
        """Set which ports a given port is allowed to forward to."""
        params = [f"groupId={port}"]
        for p in forwarding_ports:
            params.append(f"portid={p}")
        params.append("setapply=Apply")
        await self._authed_get(f"port_isolation_set.cgi?{'&'.join(params)}")

    # --- LAG ---

    async def create_lag(self, group_id: int, ports: list[int]) -> None:
        """Create or modify a link aggregation group."""
        if not (1 <= group_id <= 8):
            raise SwitchError("LAG group ID must be between 1 and 8")
        params = [f"groupId={group_id}"]
        for p in ports:
            params.append(f"portid={p}")
        params.append("setapply=Apply")
        await self._authed_get(f"port_trunk_set.cgi?{'&'.join(params)}")

    async def delete_lag(self, group_id: int) -> None:
        """Delete a link aggregation group."""
        query = f"chk_trunk={group_id}&setDelete=Delete"
        await self._authed_get(f"port_trunk_display.cgi?{query}")

    # --- DHCP snooping ---

    async def set_dhcp_snooping_enabled(self, *, enabled: bool) -> None:
        query = f"dhcp_mode={1 if enabled else 0}&Apply=Apply"
        await self._authed_get(f"dhcp_enable_set.cgi?{query}")

    async def set_dhcp_snooping_port(self, port: int, *, trusted: bool) -> None:
        query = (
            f"dhcpport={port}&trustPort={1 if trusted else 0}"
            f"&option82=0&operation=0&dhcp_submit=Apply"
        )
        await self._authed_get(f"dhcp_port_set.cgi?{query}")

    # --- System ---

    async def reboot(self) -> None:
        """Reboot the switch."""
        await self._authed_post(
            "reboot.cgi",
            {"reboot_op": "reboot", "save_op": "true", "apply": "Reboot"},
        )

    async def set_ip_settings(
        self,
        *,
        dhcp: bool,
        ip: str = "",
        netmask: str = "",
        gateway: str = "",
    ) -> None:
        """Change the switch's IP configuration."""
        query = (
            f"dhcpSetting={'enable' if dhcp else 'disable'}"
            f"&ip_address={ip}&ip_netmask={netmask}&ip_gateway={gateway}"
            f"&submit=Apply"
        )
        await self._authed_get(f"ip_setting.cgi?{query}")

    async def set_device_name(self, name: str) -> None:
        """Set the switch's system name/description."""
        await self._authed_get(f"system_name_set.cgi?sysName={name}")
