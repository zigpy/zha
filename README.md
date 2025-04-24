# Zigbee Home Automation (ZHA)

[![CI](https://github.com/zigpy/zha/actions/workflows/ci.yml/badge.svg)](https://github.com/zigpy/zha/actions/workflows/ci.yml)
[![Coverage Status](https://codecov.io/gh/zigpy/zha/branch/dev/graph/badge.svg)](https://app.codecov.io/gh/zigpy/zha/tree/dev)
[![python](https://img.shields.io/badge/Python-3.12-3776AB.svg?logo=python)](https://www.python.org)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![PyPI version](https://badge.fury.io/py/zha.svg)](https://badge.fury.io/py/zha)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-yellow.svg)](https://opensource.org/license/apache-2-0)


ZHA is a versatile and hardware-independent Zigbee gateway implementation, designed to replace proprietary Zigbee gateways, bridges, hubs, and controllers. With ZHA, you can create a unified Zigbee network, allowing you to easily pair and connect a wide range of Zigbee-based devices for home automation and lighting.

## Key Features

- **Hardware Independence:** ZHA is not tied to any specific hardware, giving you the freedom to choose the Zigbee radio that best suits your needs.
- **Compatibility:** ZHA supports a vast array of Zigbee-based devices, ensuring seamless integration with popular home automation and lighting solutions.
- **Unified Zigbee Network:** By utilizing ZHA, you can establish a single Zigbee network, simplifying device management and enhancing interoperability.
- **Low-Bandwidth Communication:** Zigbee operates on a low-bandwidth communication protocol, utilizing small, low-power digital radios to connect devices within local Zigbee wireless private area networks.

## Getting Started With Development

To bootstrap a development environment for ZHA, follow these steps:

1. Clone the project from the [zigpy](https://github.com/zigpy) organization:

    ```shell
    git clone https://github.com/zigpy/zha.git
    ```

2. Navigate to the `script` directory:

    ```shell
    cd zha/script
    ```

3. Run the setup script to install the necessary dependencies:

    ```shell
    ./setup
    ```

    The `setup` script sets up a virtual environment, installs necessary packages and dependencies, and configures pre-commit hooks for the project. It helps ensure a consistent and controlled development environment for the project, saving you time and effort.
    <details>
    <summary>Script Overview</summary>

    The `setup` script in the `zha/script` directory performs the following actions:

    - `curl -LsSf https://astral.sh/uv/install.sh | sh`: This command uses curl to download a shell script from the specified URL (https://astral.sh/uv/install.sh) and then pipes it to the sh command to execute it. This script is responsible for installing a tool called "uv" (short for "universal virtualenv") which helps manage Python virtual environments.

    - `uv venv venv`: This command uses the "uv" tool to create a new Python virtual environment named "venv" in the current directory. A virtual environment is an isolated Python environment that allows you to install packages and dependencies specific to your project without affecting the global Python installation.

    - `. venv/bin/activate`: This command activates the newly created virtual environment. When a virtual environment is activated, any subsequent Python-related commands will use the Python interpreter and packages installed within that environment.

    - `uv pip install -U pip setuptools pre-commit`: This command uses the "uv" tool to upgrade the "pip" package manager, as well as install or upgrade the "setuptools" and "pre-commit" packages. "pip" is the default package manager for Python, "setuptools" is a library that facilitates packaging Python projects, and "pre-commit" is a tool for managing and enforcing pre-commit hooks in a Git repository.

    - `uv pip install -r requirements_test.txt`: This command uses the "uv" tool to install the Python packages listed in the "requirements_test.txt" file. This file typically contains a list of dependencies required for running tests in the project.

    - `uv pip install -e .`: This command uses the "uv" tool to install the project itself in editable mode. The dot (.) represents the current directory, so this command installs the project as a package in the virtual environment.

    - `pre-commit install`: This command installs Git pre-commit hooks for the project. Pre-commit hooks are scripts that run before each commit is made in a Git repository, allowing you to enforce certain checks or actions before committing changes.
    </details>

4. If creating new entities or modifying existing ones, unit tests that use device diagnostic files will fail. You can regenerate existing device diagnostic JSON files to incorporate the new entities:

    ```shell
    python -m tools.regenerate_diagnostics
    ```

## License

ZHA is released under the [Apache 2.0 License](https://opensource.org/license/apache-2-0). Please refer to the LICENSE file for more details
