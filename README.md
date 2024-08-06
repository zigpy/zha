# zha

ZHA is a high-level Zigbee Gateway library written in Python and depends on the [zigpy](https://github.com/zigpy/zigpy) project + all of its libraries.

The zha library is meant to be used by application-level implementations such as the [Zigbee Home Automation integration)](https://www.home-assistant.io/integrations/zha/) in Home Assistant.

Others could potentially also use it to create stand-alone Zigbee Gateway applications or externally by other types of Zigbee host applications.  

For more development documentation/information and discussion between developers please see the main zigpy repository: 

- https://github.com/zigpy/zigpy
  - https://github.com/zigpy/zigpy/blob/dev/CONTRIBUTING.md
  - https://github.com/zigpy/zigpy/discussions
  - https://github.com/zigpy/zigpy/wiki

# zha release packages available via PyPI

New packages of tagged versions are also released via the "zigpy" project on PyPI
  - https://pypi.org/project/zha/
    - https://pypi.org/project/zha/#history
    - https://pypi.org/project/zha/#files

# Related projects

The Zigpy organization and its associated libraries implement a complete Zigbee framework written in Python, allowing you to create your own Zigbee gateway applications. It encompasses a standard Zigbee stack, radio libraries, basic device communication libraries, and application-level code to communicate and control off-the-shelf Zigbee devices.

- https://github.com/zigpy

zigpy organization's projects/libraries that are extra important for developers that are new to ZHA:

  - https://github.com/zigpy/zha-device-handlers/ (high-level custom Zigbee device handlers, also referred to as "quirks" for ZHA).
  - https://github.com/zigpy/zigpy (low-level hardware independent standard Zigbee protocol stack implemented as a Python library).
  - https://github.com/zigpy/zigpy-cli (a unified low-level command line interface for all zigpy compatible radio libraries).




