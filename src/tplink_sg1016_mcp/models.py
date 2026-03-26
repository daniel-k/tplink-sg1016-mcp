"""Data models for the TP-Link SG1016PE switch."""

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum


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


class CableStatus(IntEnum):
    NOT_TESTED = -1
    NO_CABLE = 0
    NORMAL = 1
    OPEN = 2
    SHORT = 3
    OPEN_SHORT = 4
    CROSSTALK = 5


class QosMode(IntEnum):
    PORT_BASED = 0
    DOT1P_BASED = 1
    DSCP_BASED = 2


class QosPriority(IntEnum):
    LOWEST = 0
    NORMAL = 1
    MEDIUM = 2
    HIGHEST = 3


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


# --- Port statistics ---


@dataclass
class PortStatistics:
    number: int
    enabled: bool
    link_status: PortSpeed
    tx_good_packets: int
    tx_bad_packets: int
    rx_good_packets: int
    rx_bad_packets: int


# --- Live port rates (MainRpm) ---


@dataclass
class PortRate:
    number: int
    enabled: bool
    link_speed: PortSpeed
    tx_rate: int
    rx_rate: int


@dataclass
class DashboardInfo:
    uptime: str
    ports: list[PortRate] = field(default_factory=list)


# --- IP settings ---


@dataclass
class IpSettings:
    dhcp_enabled: bool
    ip: str
    netmask: str
    gateway: str


# --- Cable diagnostics ---


@dataclass
class CableDiagResult:
    port: int
    status: CableStatus
    length_m: int


# --- IGMP snooping ---


@dataclass
class IgmpGroup:
    ip: str
    vlan: str
    ports: str


@dataclass
class IgmpSnoopingConfig:
    enabled: bool
    report_suppression: bool
    groups: list[IgmpGroup] = field(default_factory=list)


# --- LAG (port trunk) ---


@dataclass
class LagGroup:
    group_id: int
    ports: list[int] = field(default_factory=list)


@dataclass
class LagConfig:
    max_groups: int
    port_count: int
    groups: list[LagGroup] = field(default_factory=list)


# --- Port mirroring ---


@dataclass
class PortMirrorConfig:
    enabled: bool
    destination_port: int
    ingress_ports: list[int] = field(default_factory=list)
    egress_ports: list[int] = field(default_factory=list)


# --- QoS ---


@dataclass
class PortQosPriority:
    port: int
    priority: QosPriority


@dataclass
class QosConfig:
    mode: QosMode
    port_priorities: list[PortQosPriority] = field(default_factory=list)


# --- Bandwidth control ---


@dataclass
class PortBandwidthLimit:
    port: int
    ingress_rate: int
    egress_rate: int


# --- Storm control ---


@dataclass
class PortStormControl:
    port: int
    broadcast: bool
    multicast: bool
    unknown_unicast: bool
    rate: int


# --- PoE recovery ---


@dataclass
class PoeRecoveryPort:
    port: int
    ip: str
    startup_interval: int
    ping_interval: int
    max_retries: int
    reboot_count: int
    failure_count: int
    total_restarts: int
    status: int


@dataclass
class PoeRecoveryConfig:
    enabled: bool
    ports: list[PoeRecoveryPort] = field(default_factory=list)


# --- PoE extend ---


@dataclass
class PoeExtendPort:
    port: int
    enabled: bool


@dataclass
class PoeExtendConfig:
    ports: list[PoeExtendPort] = field(default_factory=list)


# --- DHCP snooping ---


@dataclass
class DhcpSnoopingPort:
    port: int
    trusted: bool


@dataclass
class DhcpSnoopingConfig:
    enabled: bool
    ports: list[DhcpSnoopingPort] = field(default_factory=list)


# --- Port isolation ---


@dataclass
class PortIsolationEntry:
    port: int
    forwarding_ports: list[int] = field(default_factory=list)


# --- VLAN models ---


class VlanPortMembership(StrEnum):
    TAGGED = "tagged"
    UNTAGGED = "untagged"
    NOT_MEMBER = "not_member"


@dataclass
class Vlan:
    vid: int
    name: str
    tagged_ports: list[int] = field(default_factory=list)
    untagged_ports: list[int] = field(default_factory=list)


@dataclass
class VlanConfig:
    enabled: bool
    port_count: int
    max_vlans: int
    vlans: list[Vlan] = field(default_factory=list)


@dataclass
class PortPvid:
    port: int
    pvid: int


@dataclass
class PvidConfig:
    enabled: bool
    port_count: int
    pvids: list[PortPvid] = field(default_factory=list)
