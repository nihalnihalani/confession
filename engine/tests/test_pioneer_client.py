"""Pioneer model-list validation without network calls."""

import asyncio

import pytest

from confession.pioneer_client import (
    PioneerBaseModelUnavailable,
    PioneerClient,
)


def test_base_model_validation_accepts_listed_model():
    client = PioneerClient(api_key="test-key")

    async def listed():
        return ["base-a", "base-b"]

    client.list_base_models = listed
    asyncio.run(client.validate_base_model("base-b"))


def test_base_model_validation_rejects_unlisted_model():
    client = PioneerClient(api_key="test-key")

    async def listed():
        return ["base-a"]

    client.list_base_models = listed
    with pytest.raises(PioneerBaseModelUnavailable):
        asyncio.run(client.validate_base_model("base-missing"))
