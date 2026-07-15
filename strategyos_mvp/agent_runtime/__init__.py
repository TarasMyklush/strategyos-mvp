"""Durable, governed agents layer (PR 1: domain contracts + Postgres foundation).

See docs/agent-layer/agents-layer-design.md for the full target architecture.
This package currently ships domain contracts, the versioned agent registry,
the Postgres repository, and the append-only event/outbox log. It does not
yet wire task execution, tool dispatch, or UI projections -- those land in
later PRs per the design doc's migration sequence.
"""

from __future__ import annotations
