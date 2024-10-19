"""Main module for zhawss."""

from websockets.__main__ import main as websockets_cli

if __name__ == "__main__":
    # "Importing this module enables command line editing using GNU readline."
    import readline  # noqa: F401

    websockets_cli()
