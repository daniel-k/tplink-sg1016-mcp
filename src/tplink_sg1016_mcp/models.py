"""Data models for the TP-Link SG1016PE switch."""

from dataclasses import dataclass
from enum import IntEnum


class PortSpeed(IntEnum):
    LINK_DOWN = 0
    AUTO = 1
    HALF_10M = 2
    FULL_10M = 3
    HALF_100M = 4
    FULL_100M = 5
    FULL_1000M = 6
    UNKNOWN = 7


class PoePriority(IntEnum):
    HIGH = 0
    MIDDLE = 1
    LOW = 2


class PoePowerLimit(IntEnum):
    AUTO = 330
    CLASS_1 = 40
    CLASS_2 = 70
    CLASS_3 = 154
    CLASS_4 = 300


class PoeClass(IntEnum):
    CLASS_0 = 330
    CLASS_1 = 40
    CLASS_2 = 70
    CLASS_3 = 154
    CLASS_4 = 300


class PoePowerStatus(IntEnum):
    OFF = 0
    TURNING_ON = 1
    ON = 2
    OVERLOAD = 3
    SHORT = 4
    NONSTANDARD_PD = 5
    VOLTAGE_HIGH = 6
    VOLTAGE_LOW = 7
    HARDWARE_FAULT = 8
    OVERTEMPERATURE = 9


@dataclass
class DeviceInfo:
    name: str | None = None
    mac: str | None = None
    ip: str | None = None
    netmask: str | None = None
    gateway: str | None = None
    firmware: str | None = None
    hardware: str | None = None


@dataclass
class PortState:
    number: int
    enabled: bool
    speed_config: PortSpeed
    speed_actual: PortSpeed
    flow_control_config: bool
    flow_control_actual: bool


@dataclass
class PortPoeState:
    number: int
    enabled: bool
    priority: PoePriority
    power_limit: PoePowerLimit | float
    power_watts: float
    current_ma: float
    voltage_v: float
    pd_class: PoeClass | None
    power_status: PoePowerStatus


@dataclass
class PoeGlobalState:
    power_limit: float
    power_limit_min: float
    power_limit_max: float
    power_consumption: float
    power_remain: float
