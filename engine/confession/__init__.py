"""CONFESSION engine — the lie detector for AI agents.

A Builder agent claims a task is done; the Auditor hands that claim to Replay QA,
which explores the real deployed app and returns a root-cause verdict. The verdict
(never the agent's word) drives the Guild tool-grant tier ratchet, and every caught
false claim becomes a Pioneer fine-tune example.

Public surface is intentionally small; import the submodules directly:
    from confession.auditor import Auditor
    from confession.verdicts import decide_verdict
"""

__version__ = "0.1.0"
