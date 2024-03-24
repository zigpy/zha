"""Helpers for Zigbee Home Automation.

For more details about this component, please refer to the documentation at
https://home-assistant.io/integrations/zha/
"""

from __future__ import annotations

import binascii
import collections
import dataclasses
from dataclasses import dataclass
import enum
import logging
import re
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

import voluptuous as vol
import zigpy.exceptions
import zigpy.types
import zigpy.util
import zigpy.zcl
from zigpy.zcl.foundation import CommandSchema
import zigpy.zdo.types as zdo_types

from zha.application import Platform
from zha.application.const import (
    CLUSTER_TYPE_IN,
    CLUSTER_TYPE_OUT,
    CUSTOM_CONFIGURATION,
)
from zha.decorators import SetRegistry

# from zha.zigbee.cluster_handlers.registries import BINDABLE_CLUSTERS
BINDABLE_CLUSTERS = SetRegistry()

if TYPE_CHECKING:
    from zha.application.gateway import ZHAGateway
    from zha.zigbee.cluster_handlers import ClusterHandler
    from zha.zigbee.device import Device

_ClusterHandlerT = TypeVar("_ClusterHandlerT", bound="ClusterHandler")
_T = TypeVar("_T")
_R = TypeVar("_R")
_P = ParamSpec("_P")
_LOGGER = logging.getLogger(__name__)


@dataclass
class BindingPair:
    """Information for binding."""

    source_cluster: zigpy.zcl.Cluster
    target_ieee: zigpy.types.EUI64
    target_ep_id: int

    @property
    def destination_address(self) -> zdo_types.MultiAddress:
        """Return a ZDO multi address instance."""
        return zdo_types.MultiAddress(
            addrmode=3, ieee=self.target_ieee, endpoint=self.target_ep_id
        )


async def safe_read(
    cluster, attributes, allow_cache=True, only_cache=False, manufacturer=None
):
    """Swallow all exceptions from network read.

    If we throw during initialization, setup fails. Rather have an entity that
    exists, but is in a maybe wrong state, than no entity. This method should
    probably only be used during initialization.
    """
    try:
        result, _ = await cluster.read_attributes(
            attributes,
            allow_cache=allow_cache,
            only_cache=only_cache,
            manufacturer=manufacturer,
        )
        return result
    except Exception:  # pylint: disable=broad-except
        return {}


async def get_matched_clusters(
    source_zha_device: Device, target_zha_device: Device
) -> list[BindingPair]:
    """Get matched input/output cluster pairs for 2 devices."""
    source_clusters = source_zha_device.async_get_std_clusters()
    target_clusters = target_zha_device.async_get_std_clusters()
    clusters_to_bind = []

    for endpoint_id in source_clusters:
        for cluster_id in source_clusters[endpoint_id][CLUSTER_TYPE_OUT]:
            if cluster_id not in BINDABLE_CLUSTERS:
                continue
            if target_zha_device.nwk == 0x0000:
                cluster_pair = BindingPair(
                    source_cluster=source_clusters[endpoint_id][CLUSTER_TYPE_OUT][
                        cluster_id
                    ],
                    target_ieee=target_zha_device.ieee,
                    target_ep_id=target_zha_device.device.application.get_endpoint_id(
                        cluster_id, is_server_cluster=True
                    ),
                )
                clusters_to_bind.append(cluster_pair)
                continue
            for t_endpoint_id in target_clusters:
                if cluster_id in target_clusters[t_endpoint_id][CLUSTER_TYPE_IN]:
                    cluster_pair = BindingPair(
                        source_cluster=source_clusters[endpoint_id][CLUSTER_TYPE_OUT][
                            cluster_id
                        ],
                        target_ieee=target_zha_device.ieee,
                        target_ep_id=t_endpoint_id,
                    )
                    clusters_to_bind.append(cluster_pair)
    return clusters_to_bind


def convert_to_zcl_values(
    fields: dict[str, Any], schema: CommandSchema
) -> dict[str, Any]:
    """Convert user input to ZCL values."""
    converted_fields: dict[str, Any] = {}
    for field in schema.fields:
        if field.name not in fields:
            continue
        value = fields[field.name]
        if issubclass(field.type, enum.Flag) and isinstance(value, list):
            new_value = 0

            for flag in value:
                if isinstance(flag, str):
                    new_value |= field.type[flag.replace(" ", "_")]
                else:
                    new_value |= flag

            value = field.type(new_value)
        elif issubclass(field.type, enum.Enum):
            value = (
                field.type[value.replace(" ", "_")]
                if isinstance(value, str)
                else field.type(value)
            )
        else:
            value = field.type(value)
        _LOGGER.debug(
            "Converted ZCL schema field(%s) value from: %s to: %s",
            field.name,
            fields[field.name],
            value,
        )
        converted_fields[field.name] = value
    return converted_fields


def async_is_bindable_target(source_zha_device, target_zha_device):
    """Determine if target is bindable to source."""
    if target_zha_device.nwk == 0x0000:
        return True

    source_clusters = source_zha_device.async_get_std_clusters()
    target_clusters = target_zha_device.async_get_std_clusters()

    for endpoint_id in source_clusters:
        for t_endpoint_id in target_clusters:
            matches = set(
                source_clusters[endpoint_id][CLUSTER_TYPE_OUT].keys()
            ).intersection(target_clusters[t_endpoint_id][CLUSTER_TYPE_IN].keys())
            if any(bindable in BINDABLE_CLUSTERS for bindable in matches):
                return True
    return False


def async_get_zha_config_value(
    zha_data: ZHAData, section: str, config_key: str, default: _T
) -> _T:
    """Get the value for the specified configuration from the ZHA config entry."""
    return (
        zha_data.config_entry_data.get("options", {})
        .get(CUSTOM_CONFIGURATION, {})
        .get(section, {})
        .get(config_key, default)
    )


def convert_install_code(value: str) -> zigpy.types.KeyData:
    """Convert string to install code bytes and validate length."""

    try:
        code = binascii.unhexlify(value.replace("-", "").lower())
    except binascii.Error as exc:
        raise vol.Invalid(f"invalid hex string: {value}") from exc

    if len(code) != 18:  # 16 byte code + 2 crc bytes
        raise vol.Invalid("invalid length of the install code")

    link_key = zigpy.util.convert_install_code(code)
    if link_key is None:
        raise vol.Invalid("invalid install code")

    return link_key


QR_CODES = (
    # Consciot
    r"^([\da-fA-F]{16})\|([\da-fA-F]{36})$",
    # Enbrighten
    r"""
        ^Z:
        ([0-9a-fA-F]{16})  # IEEE address
        \$I:
        ([0-9a-fA-F]{36})  # install code
        $
    """,
    # Aqara
    r"""
        \$A:
        ([0-9a-fA-F]{16})  # IEEE address
        \$I:
        ([0-9a-fA-F]{36})  # install code
        $
    """,
    # Bosch
    r"""
        ^RB01SG
        [0-9a-fA-F]{34}
        ([0-9a-fA-F]{16}) # IEEE address
        DLK
        ([0-9a-fA-F]{36}|[0-9a-fA-F]{32}) # install code / link key
        $
    """,
)


def qr_to_install_code(qr_code: str) -> tuple[zigpy.types.EUI64, zigpy.types.KeyData]:
    """Try to parse the QR code.

    if successful, return a tuple of a EUI64 address and install code.
    """

    for code_pattern in QR_CODES:
        match = re.search(code_pattern, qr_code, re.VERBOSE)
        if match is None:
            continue

        ieee_hex = binascii.unhexlify(match[1])
        ieee = zigpy.types.EUI64(ieee_hex[::-1])

        # Bosch supplies (A) device specific link key (DSLK) or (A) install code + crc
        if "RB01SG" in code_pattern and len(match[2]) == 32:
            link_key_hex = binascii.unhexlify(match[2])
            link_key = zigpy.types.KeyData(link_key_hex)
            return ieee, link_key
        install_code = match[2]
        # install_code sanity check
        link_key = convert_install_code(install_code)
        return ieee, link_key

    raise vol.Invalid(f"couldn't convert qr code: {qr_code}")


@dataclasses.dataclass(kw_only=True, slots=True)
class ZHAData:
    """ZHA data stored in `gateway.data`."""

    yaml_config: dict[str, Any] = dataclasses.field(default_factory=dict)
    config_entry_data: dict[str, Any] = dataclasses.field(default_factory=dict)
    platforms: collections.defaultdict[Platform, list] = dataclasses.field(
        default_factory=lambda: collections.defaultdict(list)
    )
    gateway: ZHAGateway | None = dataclasses.field(default=None)
    device_trigger_cache: dict[str, tuple[str, dict]] = dataclasses.field(
        default_factory=dict
    )
    allow_polling: bool = dataclasses.field(default=False)
