import asyncio
import unittest.mock
import pytest

# Note: this will only work with Python 3.5, which is what is installed
# by default on Ubuntu 16.04.
# TODO make generic for 3.5+
from async_generator import yield_, async_generator

from ..smtpproxy import PostfixProxyServer


# c.f. pytest-asyncio/tests/async_fixtures/test_async_gen_fixtures_35.py
@pytest.fixture
@async_generator
async def server():
    server = PostfixProxyServer(handler=None)
    server.responses = []

    def _write(data):
        server.responses.append(data)

    transport = unittest.mock.Mock()
    transport.write = _write
    server.connection_made(transport)

    # allow the server to write the greeting, then reset
    await asyncio.sleep(0.0001)
    assert len(server.responses) == 1
    server.responses = []

    await yield_(server)

    server.connection_lost(None)


@pytest.mark.asyncio
async def test_xforward(server):

    await server.smtp_XFORWARD('NAME=spike.porcupine.org ADDR=168.100.189.2 PROTO=ESMTP')

    assert server.responses[0] == b'250 Ok\r\n'

    fi = server.session.fwd_info
    assert len(fi) == 3
    assert fi['NAME'] == 'spike.porcupine.org'
    assert fi['ADDR'] == '168.100.189.2'
    assert fi['PROTO'] == 'ESMTP'

    await server.smtp_XFORWARD('HELO=a.b.c')

    assert server.responses[1] == b'250 Ok\r\n'

    assert len(fi) == 4
    assert fi['HELO'] == 'a.b.c'

    await server.smtp_XFORWARD('FOO=bar')

    assert len(fi) == 4

    assert server.responses[2] == b'501 Syntax error\r\n'
