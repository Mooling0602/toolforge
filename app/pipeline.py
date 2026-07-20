"""Request pipeline (orchestrator). Single place to execute CanonicalRequest."""

from .engine.orchestrator import handle_canonical

__all__ = ["handle_canonical"]
