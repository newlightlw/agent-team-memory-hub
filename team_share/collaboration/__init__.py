"""Opt-in, authenticated small-team collaboration gateway.

The existing local CLI and MCP keep their original behavior. Deploy this gateway
with a separate service-owned data directory, never an existing personal repo.
"""

import logging

# MCP initializes INFO logging. Keep private search terms and provider URLs out
# of transport logs; the worker records only job kinds and exception classes.
for _logger in ("httpx", "httpcore"):
    logging.getLogger(_logger).setLevel(logging.WARNING)
