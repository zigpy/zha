"""Mapping registries for zha cluster handlers."""

from zha.decorators import DictRegistry, NestedDictRegistry, SetRegistry
from zha.zigbee.cluster_handlers import ClientClusterHandler, ClusterHandler

BINDABLE_CLUSTERS = SetRegistry()
CLUSTER_HANDLER_ONLY_CLUSTERS = SetRegistry()
CLIENT_CLUSTER_HANDLER_REGISTRY: DictRegistry[type[ClientClusterHandler]] = (
    DictRegistry()
)
CLUSTER_HANDLER_REGISTRY: NestedDictRegistry[type[ClusterHandler]] = (
    NestedDictRegistry()
)
