"""Lightlink cluster handlers module for Zigbee Home Automation."""

import zigpy.exceptions
from zigpy.zcl.clusters.lightlink import LightLink
from zigpy.zcl.foundation import GENERAL_COMMANDS, GeneralCommand

from .. import registries
from . import ClusterHandler, ClusterHandlerStatus


@registries.CLUSTER_HANDLER_ONLY_CLUSTERS.register(LightLink.cluster_id)
@registries.ZIGBEE_CLUSTER_HANDLER_REGISTRY.register(LightLink.cluster_id)
class LightLinkClusterHandler(ClusterHandler):
    """Lightlink cluster handler."""

    BIND: bool = False

    async def async_configure(self) -> None:
        """Add Coordinator to LightLink group."""

        if self._endpoint.device.skip_configuration:
            self._status = ClusterHandlerStatus.CONFIGURED
            return

        application = self._endpoint.zigpy_endpoint.device.application
        try:
            coordinator = application.get_device(application.state.node_info.ieee)
        except KeyError:
            self.warning("Aborting - unable to locate required coordinator device.")
            return

        try:
            rsp = await self.cluster.get_group_identifiers(0)
        except (zigpy.exceptions.ZigbeeException, TimeoutError) as exc:
            self.warning("Couldn't get list of groups: %s", str(exc))
            return

        if isinstance(rsp, GENERAL_COMMANDS[GeneralCommand.Default_Response].schema):
            groups = []
        else:
            groups = rsp.group_info_records

        if groups:
            for group in groups:
                self.debug("Adding coordinator to 0x%04x group id", group.group_id)
                await coordinator.add_to_group(group.group_id)
        else:
            await coordinator.add_to_group(0x0000, name="Default Lightlink Group")
