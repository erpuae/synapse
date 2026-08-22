# Copyright (c) 2026, Dxbitz and contributors
"""Tools exposed over the synapse MCP endpoint.

Importing a module in here is what registers its tools against the MCP instance
in synapse/mcp.py. Nothing is imported at package level on purpose — the
endpoint body does the importing, so a broken tool module cannot take down the
rest of the app at boot.
"""
