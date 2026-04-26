"""dormy.memory — agent's evolving observations about each founder.

`observations` — async CRUD over the user_observations Postgres table.
`extractor`    — Sonnet 4.6 batch extraction pipeline producing observations
                 from conversation history.

Read by engine modules (find_investors / draft_intro / watch_vcs / ...)
pre-LLM-call to inject per-founder context. Written by extractor post-
conversation as a fire-and-forget hook from skill / MCP tool handlers.

Replaces nanobot's built-in Dream long-term memory in the Dormy stack
(Dream is global-per-instance and would leak across founders in our
multi-tenant SaaS deployment). See DESIGN.md "Long-term memory design".
"""

from dormy.memory import extractor, observations

__all__ = ["extractor", "observations"]
