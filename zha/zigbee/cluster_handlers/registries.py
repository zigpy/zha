"""Mapping registries for zha cluster handlers."""

from zha.decorators import DictRegistry, NestedDictRegistry, SetRegistry
from zha.zigbee.cluster_handlers import ClusterHandler

BINDABLE_CLUSTERS = SetRegistry()
HANDLER_ONLY_CLUSTERS = SetRegistry()
CLIENT_CLUSTER_HANDLER_REGISTRY = DictRegistry()
CLUSTER_HANDLER_REGISTRY: NestedDictRegistry[type[ClusterHandler]] = (
    NestedDictRegistry()
)
