"""Agent-facing tool for the consent-center "propose" step.

This is the ONLY module in the consent-center feature with a module-body
top-level ``registry.register(...)`` call. It exposes a single tool,
``propose_memory``, which stages connector-derived candidates into the consent
review area. It NEVER writes personal memory — that path is reserved for the
plugin's confirm endpoint (RED LINE #5).

The tool is registered under the ``consent-dev`` toolset, which the hermit
profile does not enable by default; even when enabled, the worst it can do is
write staging proposals.
"""

import json

from tools.registry import registry
from tools import consent_memory

PROPOSE_SCHEMA = {
    "name": "propose_memory",
    "description": (
        "Stage candidate items that were read from a connector and which you "
        "want to sediment into the user's personal memory. This writes the "
        "candidates into a human-confirmation review area ONLY — it does NOT "
        "write personal memory directly. A human must approve each item via "
        "the consent-center before anything is persisted."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "Candidate items to stage for human confirmation.",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The candidate memory content. Required.",
                        },
                        "target": {
                            "type": "string",
                            "description": (
                                "Which store the item would land in once "
                                "confirmed: 'memory' or 'user'. Optional "
                                "(default 'memory')."
                            ),
                        },
                        "kind": {
                            "type": "string",
                            "description": "Optional classification, e.g. 'fact' or 'preference'.",
                        },
                        "id": {
                            "type": "string",
                            "description": "Optional stable id; auto-assigned if omitted.",
                        },
                    },
                    "required": ["content"],
                },
            },
            "source": {
                "type": "string",
                "description": "Connector this candidate came from (default 'google_calendar').",
            },
            "source_ref": {
                "type": "object",
                "description": "Optional reference back to the source record.",
            },
        },
        "required": ["items"],
    },
}


handler = lambda args, **kw: json.dumps(
    consent_memory.propose_memory(
        items=args.get("items", []),
        source=args.get("source", "google_calendar"),
        source_ref=args.get("source_ref"),
    ),
    ensure_ascii=False,
)


registry.register(
    name="propose_memory",
    toolset="consent-dev",
    schema=PROPOSE_SCHEMA,
    handler=handler,
    description=(
        "Stage connector-derived candidates into the consent-center review "
        "area for human confirmation (never writes personal memory directly)."
    ),
    emoji="🗳️",
)
