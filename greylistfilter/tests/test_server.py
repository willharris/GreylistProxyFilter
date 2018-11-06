import asyncio
import pytest


@pytest.mark.asyncio
async def test_xforward(simple_proxy_server):

    await simple_proxy_server.smtp_XFORWARD('NAME=spike.porcupine.org ADDR=168.100.189.2 PROTO=ESMTP')

    assert simple_proxy_server.responses[0] == b'250 Ok\r\n'

    fi = simple_proxy_server.session.fwd_info
    assert len(fi) == 3
    assert fi['NAME'] == 'spike.porcupine.org'
    assert fi['ADDR'] == '168.100.189.2'
    assert fi['PROTO'] == 'ESMTP'

    await simple_proxy_server.smtp_XFORWARD('HELO=a.b.c')

    assert simple_proxy_server.responses[1] == b'250 Ok\r\n'

    assert len(fi) == 4
    assert fi['HELO'] == 'a.b.c'

    await simple_proxy_server.smtp_XFORWARD('FOO=bar')

    assert len(fi) == 4

    assert simple_proxy_server.responses[2] == b'501 Syntax error\r\n'


def test_d(pf_proxy_server, data_bytes):
    # print(data_bytes)

    server = pf_proxy_server()

    print('port: %d' % server.port)

    assert len(data_bytes)