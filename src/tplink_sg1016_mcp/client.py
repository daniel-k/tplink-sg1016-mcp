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
    PortSpeed,
    PortState,
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

    # --- mutations ---

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
