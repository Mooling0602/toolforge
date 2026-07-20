"""Upstream client protocol."""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, Optional, Protocol, Union

from ..config import UpstreamConfig


class UpstreamClient(Protocol):
    config: UpstreamConfig

    async def chat_completions(
        self,
        body: Dict[str, Any],
        *,
        stream: bool = False,
    ) -> Union[Dict[str, Any], AsyncIterator[str]]:
        """Non-stream returns JSON dict; stream returns SSE line iterator."""
        ...

    async def aclose(self) -> None:
        ...
