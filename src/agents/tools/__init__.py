"""src.agents.tools package.

Importing this package registers all built-in tools (the tool modules
register themselves via the @register_tool decorator) and re-exports the
registry API. Without these imports the registry stays empty and every
execute_tool call raises "Unknown tool" - which is exactly what happened
before: nothing imported the tool modules in the app path.
"""

from __future__ import annotations

from src.agents.tools.get_document_versions import get_document_versions as _gmv  # noqa: F401
from src.agents.tools.memory_search import memory_search as _ms  # noqa: F401

# Registry re-exports (canonical import site for the rest of the codebase)
from src.agents.tools.registry import (  # noqa: F401
    ToolResult,
    execute_tool,
    get_tool,
    list_tools,
    register_tool,
)
from src.agents.tools.search_by_date import search_by_date as _sbd  # noqa: F401
from src.agents.tools.search_documents import search_documents as _sd  # noqa: F401
