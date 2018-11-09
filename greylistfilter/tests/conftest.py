import asyncio
import os
import pytest
import types
import unittest.mock

# Note: this will only work with Python 3.5, which is what is installed
# by default on Ubuntu 16.04.
# TODO make generic for 3.5+
from async_generator import yield_, async_generator

from aiosmtpd.controller import Controller

from ..smtpproxy import PostfixProxyServer, PostfixProxyHandler, PostfixProxyController

PG_RESPONSE_DEFER = 'action=DEFER_IF_PERMIT'


async def handle_conn(reader, writer):
    while True:
        line = await reader.readline()
        if not line or line == b'\n':
            break

    writer.write(b'%s\n' % PG_RESPONSE_DEFER.encode())
    await writer.drain()
    writer.write(b'\n')

    writer.close()

# c.f. pytest-asyncio/tests/async_fixtures/test_async_gen_fixtures_35.py
@pytest.fixture
@async_generator
async def pg_server(unused_tcp_port, event_loop):
    server = await asyncio.start_server(handle_conn, host='localhost',
        port=unused_tcp_port, loop=event_loop)

    server.port = unused_tcp_port

    await yield_(server)

    server.close()


@pytest.fixture
def pf_handler():
    return PostfixProxyHandler(None, 1.0, 1)


# c.f. pytest-asyncio/tests/async_fixtures/test_async_gen_fixtures_35.py
@pytest.fixture
@async_generator
async def simple_proxy_server():
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


@pytest.fixture
def data_bytes():
    thisdir = os.path.dirname(__file__)
    with open(os.path.join(thisdir, 'data', 'testmail.eml'), 'rb') as input:
        data = input.read()

    return data


@pytest.fixture
def pf_proxy_server(request, unused_tcp_port):
    servers = []

    def _server(relay=None, spam=1.0, dcc=2):
        for srv in servers:
            srv.stop()

        handler = PostfixProxyHandler(relay, spam, dcc)
        controller = PostfixProxyController(handler, port=unused_tcp_port)
        servers.append(controller)
        controller.start()
        return controller

    yield _server

    for srv in servers:
        srv.stop()


class DataHandler:
    def __init__(self, port):
        self.envelope = None
        self.content = None
        self.port = port

    async def handle_DATA(self, server, session, envelope):
        self.envelope = envelope
        self.content = envelope.content
        return '250 OK'


@pytest.fixture
def handler(unused_tcp_port):
    handler = DataHandler(unused_tcp_port)
    relay = Controller(handler, hostname='localhost', port=unused_tcp_port)
    relay.start()

    yield handler

    relay.stop()
