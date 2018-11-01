import asyncio
import pytest

from ..postgrey_client import greylist_status

RESPONSE = 'action=DEFER_IF_PERMIT'

async def handle_conn(reader, writer):
    while True:
        line = await reader.readline()
        if not line or line == b'\n':
            break

    writer.write(b'%s\n' % RESPONSE.encode())
    await writer.drain()
    writer.write(b'\n')

    writer.close()

@pytest.mark.asyncio
async def test_postgrey_client(unused_tcp_port, event_loop):
    server = await asyncio.start_server(handle_conn, host='localhost',
        port=unused_tcp_port, loop=event_loop)

    result = await greylist_status('a', 'b', 'c', 'd', port=unused_tcp_port)

    assert result == RESPONSE

    server.close()