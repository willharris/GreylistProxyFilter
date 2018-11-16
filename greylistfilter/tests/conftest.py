import asyncio
import getpass
import shutil
import os

from distutils.spawn import find_executable
from io import StringIO
from tempfile import mkdtemp

import grp
import pytest
import unittest.mock

from aiosmtpd.controller import Controller
from async_generator import async_generator, yield_

from ..smtpproxy import PostfixProxyController, PostfixProxyHandler, \
    PostfixProxyServer

PG_RESPONSE_DEFER = 'action=DEFER_IF_PERMIT'
PG_RESPONSE_PREPEND = 'action=PREPEND'
PG_RESPONSE_DUNNO = 'action=DUNNO'
PG_RESPONSE_TEXT = 'Greylisted, see this URL'
PG_RESPONSE_HEADER = 'X-Greylist: The message was greylisted'


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
async def pg_server(unused_tcp_port_factory, event_loop):
    port = unused_tcp_port_factory()
    server = await asyncio.start_server(handle_conn, host='localhost',
                                        port=port, loop=event_loop)

    server.port = port

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
def pf_proxy_server(request, unused_tcp_port_factory):
    port = unused_tcp_port_factory()
    servers = []

    def _server(relay=None, spam=1.0, dcc=2, pghost='localhost', pgport=10023):
        for srv in servers:
            srv.stop()

        handler = PostfixProxyHandler(relay, spam, dcc, pghost, pgport)
        controller = PostfixProxyController(handler, port=port)
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
def mail_relay(unused_tcp_port_factory):
    port = unused_tcp_port_factory()
    handler = DataHandler(port)
    relay = Controller(handler, hostname='localhost', port=port)
    relay.start()

    yield handler

    relay.stop()


#
# Integration test fixtures
#
@pytest.fixture
def temp_dir(request):
    tmp = mkdtemp(prefix='pgproxy-')
    print('Created temp dir: %s' % tmp)

    yield tmp

    try:
        shutil.rmtree(tmp, ignore_errors=True)
        print('Removed temp dir: %s' % tmp)
    except Exception as e:
        print('Failed to remove tmpdir: {}'.format(e))


@pytest.fixture(scope='session')
def username():
    return getpass.getuser()


@pytest.fixture(scope='session')
def groupname():
    g = grp.getgrgid(os.getgid())
    return g.gr_name


@pytest.fixture(scope='session')
def postgrey_binary():
    pg = find_executable('postgrey')
    if len(pg) == 0:
        raise Exception('Cannot find postgrey binary')
    return pg


@pytest.fixture
def postgrey_args(postgrey_binary, temp_dir, username, groupname):
    def _args(port):
        print('Postgrey port: %d' % port)
        return (
            postgrey_binary,
            '--inet', str(port),
            '--delay', '1',
            '--dbdir', temp_dir,
            '--user', username,
            '--group', groupname,
            '--greylist-text', PG_RESPONSE_TEXT,
            '--x-greylist-header', PG_RESPONSE_HEADER,
        )
    return _args


class SubprocessProtocol(asyncio.SubprocessProtocol):

    def __init__(self, future):
        self.exit_future = future
        self.output = StringIO()

    def pipe_data_received(self, fd, data):
        self.output.write(data.decode())

    def connection_lost(self, exc):
        self.exit_future.set_result(True)

    def get_actions(self):
        actions = []
        self.output.seek(0)
        for line in self.output.readlines():
            if line[:6] == 'action':
                kwargs = dict(x.split('=') for x in line.rstrip().split(', '))
                actions.append(kwargs)
        return actions


@pytest.fixture
@async_generator
async def real_pg_server(event_loop, unused_tcp_port_factory, postgrey_args):
    port = unused_tcp_port_factory()
    args = postgrey_args(port)

    exit_future = asyncio.Future(loop=event_loop)

    transport, protocol = await event_loop.subprocess_exec(
        lambda: SubprocessProtocol(exit_future),
        *args
    )

    await yield_((port, protocol))

    transport.terminate()

    await exit_future
