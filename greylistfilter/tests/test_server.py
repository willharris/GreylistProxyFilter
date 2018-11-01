import asyncio
import pytest

from ..smtpproxy import PostfixProxyServer


@pytest.mark.asyncio
async def test_xforward(mocker):
    server = PostfixProxyServer(handler=None)

    responses = []
    def _write(data):
        responses.append(data)

    transport = mocker.Mock()
    transport.write = _write
    server.connection_made(transport)

    # allow the server to write the greeting
    await asyncio.sleep(0.0001)

    assert len(responses) == 1

    await server.smtp_XFORWARD('NAME=spike.porcupine.org ADDR=168.100.189.2 PROTO=ESMTP')

    assert responses[1] == b'250 Ok\r\n'

    fi = server.session.fwd_info
    assert len(fi) == 3
    assert fi['NAME'] == 'spike.porcupine.org'
    assert fi['ADDR'] == '168.100.189.2'
    assert fi['PROTO'] == 'ESMTP'

    await server.smtp_XFORWARD('HELO=a.b.c')

    assert responses[2] == b'250 Ok\r\n'

    assert len(fi) == 4
    assert fi['HELO'] == 'a.b.c'

    await server.smtp_XFORWARD('FOO=bar')

    assert len(fi) == 4

    assert responses[3] == b'501 Syntax error\r\n'

    server.connection_lost(None)
