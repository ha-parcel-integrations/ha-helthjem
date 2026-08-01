"""Tests for the Helthjem GraphQL API client."""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.helthjem.api import HelthjemApiClient, HelthjemApiError

from .payloads import DELIVERED_CODE, delivered_sample, graphql_response

CODE = DELIVERED_CODE


def _session_returning(status: int, body: object = None) -> MagicMock:
    response = AsyncMock()
    response.status = status
    if isinstance(body, str):
        response.json = AsyncMock(side_effect=json.JSONDecodeError("x", body, 0))
    else:
        response.json = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post = MagicMock(return_value=ctx)
    return session


async def test_get_parcel_returns_parcel_on_success():
    session = _session_returning(200, graphql_response(delivered_sample()))
    client = HelthjemApiClient(session)

    parcel = await client.async_get_parcel(CODE)

    assert parcel["trackingNumber"] == CODE
    # the tracking code is sent as the GraphQL ``ref`` variable
    assert session.post.call_args.kwargs["json"]["variables"] == {"ref": CODE}


async def test_get_parcel_returns_none_when_not_found():
    """``getParcelTrackingDetails: null`` (unknown/not-yet-scanned) is normal."""
    client = HelthjemApiClient(_session_returning(200, graphql_response(None)))
    assert await client.async_get_parcel("TESTHJEM00000000") is None


async def test_get_parcel_returns_none_on_non_object_parcel():
    """A non-object where a parcel is expected is treated as unknown, not a crash."""
    client = HelthjemApiClient(
        _session_returning(200, {"data": {"getParcelTrackingDetails": "??"}})
    )
    assert await client.async_get_parcel(CODE) is None


async def test_get_parcel_raises_on_graphql_errors():
    client = HelthjemApiClient(
        _session_returning(200, {"errors": [{"message": "boom"}]})
    )
    with pytest.raises(HelthjemApiError) as err:
        await client.async_get_parcel(CODE)
    assert "boom" in str(err.value)


async def test_get_parcel_raises_without_data_object():
    client = HelthjemApiClient(_session_returning(200, {"nonsense": True}))
    with pytest.raises(HelthjemApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_error_status():
    client = HelthjemApiClient(_session_returning(500, {}))
    with pytest.raises(HelthjemApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_unparseable_body():
    client = HelthjemApiClient(_session_returning(200, "not json"))
    with pytest.raises(HelthjemApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_non_object_body():
    client = HelthjemApiClient(_session_returning(200, ["not", "a", "dict"]))
    with pytest.raises(HelthjemApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_propagates_network_error():
    """ClientError is left alone — DataUpdateCoordinator already wraps it."""
    session = MagicMock()
    session.post = MagicMock(side_effect=aiohttp.ClientError("boom"))
    client = HelthjemApiClient(session)
    with pytest.raises(aiohttp.ClientError):
        await client.async_get_parcel(CODE)
