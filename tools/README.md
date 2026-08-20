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

## Sync constants from Home Assistant

ZHA keeps near 1:1 copies of some Home Assistant enums (unit enums in `zha.units`, and the device-class / mode enums under `zha.application.platforms`). This tool copies them verbatim — including docstrings and comments — from the installed `homeassistant` package, so they stay in sync. Unit enums are added, refreshed, or removed to match HA; the device-class / mode enums are a fixed set that is refreshed in place (a brand-new one in HA has to be added to the tool by hand). Run it from the repo root; it needs `homeassistant` installed but reads ZHA's files as text (it never imports them, so `zha`/`zha-quirks` don't need to be installed).

```console
$ python -m tools.sync_constants          # copy the enums from HA into ZHA
$ python -m tools.sync_constants --check  # dry run, exits 1 if anything is out of sync
$ ruff format zha/                         # normalise whitespace afterwards
```

Only enums are synced. ZHA-only symbols and the hand-maintained backwards-compatibility constants at the end of `zha.units` are left untouched. The `Sync device classes from Home Assistant` GitHub workflow runs this against Home Assistant's `dev` branch on a schedule and opens a pull request with the result.
