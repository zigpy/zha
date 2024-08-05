# zha

ZHA is a high-level Zigbee Gateway library written in Python and depends on the [zigpy](https://github.com/zigpy/zigpy) project + all of its libraries.

This zha library is meant to be used by application-level implementsions such as the [Zigbee Home Automation integration)](https://www.home-assistant.io/integrations/zha/) in Home Assistant.

### Back-story

This class library started as an initial migration of the core logic from [ZHA integration](https://www.home-assistant.io/integrations/zha) to breakout and move the Zigbee Gateway part away from the [zha inetgration component inside Home Assistant's core repository](https://github.com/home-assistant/core/tree/dev/homeassistant/components/zha) into a self-contained external library. 

The end result of this split (and other further changes to come) should be a huge improvement in terms of code quality in both the Home Assistant half and the library half of zha.

The ultimate goal of having zha as a separate library is to eventually make ZHA reusable outside of Home Assistant, easier to understand, and pave the path to a more streamlined model for contributing device support code to ZHA and Home Assistant (when necessary).

Note that this is an initial pass where the aim was to modify as little as possible in this split. Future changes will hopefully enable zha to work with other stand-alone applications as well.

You will notice that the terminology currently in use within the library (and thus the rewritten integration) mirrors that of Core. This is intentional and will diverge as we see fit.

For more information please see https://github.com/zigpy/zigpy

# zha release packages available via PyPI

New packages of tagged versions are also released via the "zigpy" project on PyPI
  - https://pypi.org/project/zha/
    - https://pypi.org/project/zha/#history
    - https://pypi.org/project/zha/#files

# Related projects

The Zigpy organization and its associated libraries implement a complete Zigbee framework written in Python, allowing you to create your own Zigbee gateway applications. It encompasses a standard Zigbee stack, radio libraries, basic device communication libraries, and application-level code to communicate and control off-the-shelf Zigbee devices.

- https://github.com/zigpy

zigpy organization projects/libraires that are extra important for developers that are new to ZHA:

  - https://github.com/zigpy/zha-device-handlers/ (high-level custom Zigbee device handlers, also referred to as "quirks" for ZHA).
  - https://github.com/zigpy/zigpy (low-level hardware independent standard Zigbee protocol stack implement as a Python library).
  - https://github.com/zigpy/zigpy-cli (a unified low-level command line interface for all zigpy compatible radio libraries).




