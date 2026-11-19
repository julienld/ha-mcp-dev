"""Finite flow ports for testing shared algorithms without transport ownership."""

from typing import Any
from unittest.mock import AsyncMock


class FlowClient(AsyncMock):
    async def read_flow(self, kind: str, flow_id: str) -> dict[str, Any]:
        resource = {
            "config": "flow",
            "setup": "flow",
            "reconfigure": "flow",
            "options": "options/flow",
            "config_subentries": "subentries/flow",
        }[kind]
        return await self._request(
            "GET", f"/config/config_entries/{resource}/{flow_id}"
        )

    async def read_flow_translations(
        self, domain: str, category: str
    ) -> dict[str, Any]:
        return await self.send_websocket_message(
            {
                "type": "frontend/get_translations",
                "language": "en",
                "category": category,
                "integration": [domain],
            }
        )
