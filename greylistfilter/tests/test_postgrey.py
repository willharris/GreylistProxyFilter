import asyncio
import pytest

from ..postgrey_client import greylist_status

from .conftest import PG_RESPONSE_DEFER


@pytest.mark.asyncio
async def test_postgrey_client(pg_server):
    result = await greylist_status('a', 'b', 'c', 'd', port=pg_server.port)

    assert result == PG_RESPONSE_DEFER
