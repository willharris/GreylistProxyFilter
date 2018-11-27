import asyncio
import getpass
import os
import shutil
import time

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
    server = await asyncio.start_server(handle_conn, host='127.0.0.1',
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

    def _server(relay=None, spam=1.0, dcc=2, pghost='127.0.0.1', pgport=10023):
        for srv in servers:
            srv.stop()

        handler = PostfixProxyHandler(relay, spam, dcc, pghost, pgport)
        controller = PostfixProxyController(handler, hostname='127.0.0.1', port=port)
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
    relay = Controller(handler, hostname='127.0.0.1', port=port)
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
    return find_executable('postgrey')


@pytest.fixture
def postgrey_args(postgrey_binary, temp_dir, username, groupname):
    def _args(port):
        if postgrey_binary is None:
            raise Exception('Cannot find native Postgrey binary to run')

        print('Postgrey port: %d' % port)

        return (
            postgrey_binary,
            '--inet', '127.0.0.1:%d' % port,
            '--delay', '1',
            '--dbdir', temp_dir,
            '--user', username,
            '--group', groupname,
            '--greylist-text', PG_RESPONSE_TEXT,
            '--x-greylist-header', PG_RESPONSE_HEADER,
        )

    return _args


@pytest.fixture
def postgrey_docker_cmd():
    return (
        '/usr/sbin/postgrey',
        '--inet', '0.0.0.0:10023',
        '--delay', '1',
        '--greylist-text', PG_RESPONSE_TEXT,
        '--x-greylist-header', PG_RESPONSE_HEADER,
    )


class ActionsMixin(object):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output = StringIO()

    def collect_logs(self):
        pass

    def get_actions(self):
        self.collect_logs()
        actions = []
        self.output.seek(0)
        for line in self.output.readlines():
            if line[:6] == 'action':
                kwargs = dict(x.split('=') for x in line.rstrip().split(', '))
                actions.append(kwargs)
        return actions


class DockerProtocol(ActionsMixin):

    def __init__(self, container, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.container = container

    def collect_logs(self):
        self.output.seek(0)
        self.output.truncate()
        self.output.write(self.container.logs().decode())

    def wait_for_start(self, username):
        needle = b'Setting %s to' % (b'gid' if username == 'root' else b'uid')
        while needle not in self.container.logs():
            time.sleep(0.5)


class SubprocessProtocol(ActionsMixin, asyncio.SubprocessProtocol):

    def __init__(self, future, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.exit_future = future

    def pipe_data_received(self, fd, data):
        self.output.write(data.decode())

    def connection_lost(self, exc):
        self.exit_future.set_result(True)

    async def wait_for_start(self, username):
        needle = 'Setting %s to' % ('gid' if username == 'root' else 'uid')
        haystack = ''
        while needle not in haystack:
            self.output.seek(0)
            haystack = self.output.read()
            await asyncio.sleep(0.5)


@pytest.fixture
def _docker_pg_server(request, pgtype, postgrey_docker_cmd, unused_tcp_port_factory, dockerfile, username):
    if pgtype == 'native':
        return tuple()

    import docker

    client = docker.from_env()
    client.images.build(path=dockerfile, tag='postgrey')

    port = unused_tcp_port_factory()

    container = client.containers.run('postgrey:latest',
                                      command=postgrey_docker_cmd,
                                      detach=True,
                                      name='postgrey',
                                      ports={10023: port})

    protocol = DockerProtocol(container)
    protocol.wait_for_start(username)

    def cleanup():
        container.stop()
        container.remove()

    request.addfinalizer(cleanup)

    return port, protocol


@pytest.fixture
@async_generator
async def _native_pg_server(pgtype, event_loop, unused_tcp_port_factory, postgrey_args, username):
    if pgtype == 'docker':
        await yield_(tuple())
        return

    port = unused_tcp_port_factory()
    args = postgrey_args(port)
    print('Args:', ' '.join(args))

    exit_future = asyncio.Future(loop=event_loop)

    transport, protocol = await event_loop.subprocess_exec(
        lambda: SubprocessProtocol(exit_future),
        *args
    )

    await protocol.wait_for_start(username)

    await yield_((port, protocol))

    transport.terminate()

    await exit_future


@pytest.fixture
def real_pg_server(_native_pg_server, _docker_pg_server):
    choice = _docker_pg_server or _native_pg_server
    return choice
