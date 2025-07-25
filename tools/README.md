# ZHA development tools

This module contains development tools for ZHA.

## Import diagnostics JSON

ZHA relies on device diagnostics files to allow us to test entity creation with "real" devices as part of our CI. For this, we collect device diagnostics data from Home Assistant. You can create these JSON files by navigating to individual devices, clicking the three dot dropdown menu, and then selecting "Download diagnostics". These files can then be imported into the database.

```console
$ python -m tools.import_diagnostics /path/to/diagnostics1.json /path/to/diagnostics2.json ...
```

## Regenerate diagnostics JSON

If entities change, the current diagnostics JSON will no longer be valid and CI will fail. This is normal. If you are changing entities on existing devices, the diagnostics JSON will need to be regenerated. Our diagnostics loading/serialization is idempotent so just regenerate all of them:

```console
$ python -m tools.regenerate_diagnostics
```
