"""Lightlink cluster handlers module for Zigbee Home Automation."""

from zigpy.zcl.clusters.lightlink import LightLink

from zha.zigbee.cluster_handlers import ClusterHandler, registries


@registries.CLUSTER_HANDLER_REGISTRY.register(LightLink.cluster_id)
class LightLinkClusterHandler(ClusterHandler):
    """LightLink cluster handler.

    Coordinator group joining lives on the `LightLinkGroupJoin` virtual entity
    now.
    """

    BIND: bool = False
