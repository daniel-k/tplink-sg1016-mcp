"""HTTP client for the TP-Link SG1016PE Easy Smart switch web interface."""

import asyncio
import logging
from typing import Any

import aiohttp

from .models import (
    DeviceInfo,
    PoeClass,
    PoeGlobalState,
    PoePowerLimit,
    PoePowerStatus,
    PoePriority,
    PortPoeState,
    PortPvid,
    PortSpeed,
    PortState,
    PortStatistics,
    PvidConfig,
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
            {"username": self._username, "password": self._password, "logon": "Login"},
        )
        info = get_variable(page, "logonInfo", VarType.LIST)
        if info is None:
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

    # --- queries ---

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

    async def get_port_statistics(self) -> list[PortStatistics]:
        """Get per-port packet statistics."""
        page = await self._authed_get("PortStatisticsRpm.htm")
        data = get_variables(page, [("all_info", VarType.DICT), ("max_port_num", VarType.INT)])

        all_info = data.get("all_info")
        max_ports = data.get("max_port_num")
        if not all_info or not max_ports:
            return []

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

    async def get_poe_port_states(self) -> list[PortPoeState]:
        if not await self.is_poe_available():
            return []

        page = await self._authed_get("PoeConfigRpm.htm")
        data = get_variables(page, [("portConfig", VarType.DICT), ("poe_port_num", VarType.INT)])

        port_config = data.get("portConfig")
        num_ports = data.get("poe_port_num")
        if not port_config or not num_ports:
            return []

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

    @staticmethod
    def _bitmask_to_ports(mask: int, port_count: int) -> list[int]:
        """Convert a port bitmask to a list of 1-based port numbers."""
        return [i + 1 for i in range(port_count) if mask & (1 << i)]

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

    # --- mutations ---

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
        """Create or modify an 802.1Q VLAN.

        Args:
            vid: VLAN ID (1-4094).
            name: VLAN name (alphanumeric, max 10 chars).
            port_memberships: Mapping of port number to membership type.
                Ports not in the dict default to NOT_MEMBER.
        """
        if not (1 <= vid <= 4094):
            raise SwitchError("VLAN ID must be between 1 and 4094")
        if len(name) > 10:
            raise SwitchError("VLAN name must be 10 characters or fewer")

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

        pstate = 2 if enabled else 1
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
