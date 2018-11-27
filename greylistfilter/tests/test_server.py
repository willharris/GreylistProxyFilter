import pytest

from smtplib import SMTP
from aiosmtplib import SMTP as aioSMTP, SMTPDataError


from ..smtpproxy import XFORWARD_ARGS, OK_REPLY


def test_ehlo(pf_proxy_server):
    server = pf_proxy_server()

    with SMTP(server.hostname, server.port) as client:
        code, resp = client.ehlo()
        assert code == 250
        xfwd_cmd = b'XFORWARD %s' % b' '.join(x.encode() for x in XFORWARD_ARGS)
        assert xfwd_cmd in resp.splitlines()


@pytest.mark.asyncio
async def test_xforward(simple_proxy_server):
    ok = b'%s\r\n' % OK_REPLY.encode()

    await simple_proxy_server.smtp_XFORWARD('NAME=spike.porcupine.org ADDR=168.100.189.2 PROTO=ESMTP')

    assert simple_proxy_server.responses[0] == ok

    fi = simple_proxy_server.session.fwd_info
    assert len(fi) == 3
    assert fi['NAME'] == 'spike.porcupine.org'
    assert fi['ADDR'] == '168.100.189.2'
    assert fi['PROTO'] == 'ESMTP'

    await simple_proxy_server.smtp_XFORWARD('HELO=a.b.c')

    assert simple_proxy_server.responses[1] == ok

    assert len(fi) == 4
    assert fi['HELO'] == 'a.b.c'

    await simple_proxy_server.smtp_XFORWARD('FOO=bar')

    assert len(fi) == 4

    assert simple_proxy_server.responses[2] == b'501 Syntax error\r\n'


def test_no_greylist_server_still_relays(pf_proxy_server, data_bytes, mocker):
    server = pf_proxy_server()

    mock_relay = mocker.patch.object(server.handler, 'relay_mail')

    with SMTP(server.hostname, server.port) as client:
        code, _ = client.ehlo()
        assert code == 250
        code, _ = client.docmd('xforward', 'NAME=spike.porcupine.org ADDR=168.100.189.2 PROTO=ESMTP')
        assert code == 250
        code, _ = client.mail('bob@test.com')
        assert code == 250
        code, _ = client.rcpt('fred@test.com')
        assert code == 250
        code, _ = client.data(data_bytes)
        assert code == 250

    mock_relay.assert_called_once_with(mocker.ANY, None)


def test_relaying_mail(pf_proxy_server, mail_relay, data_bytes):
    server = pf_proxy_server('127.0.0.1:%d' % mail_relay.port)

    mail_from = 'bob@test.com'
    rcpt_to = 'fred@test.com'

    with SMTP(server.hostname, server.port) as client:
        code, _ = client.ehlo()
        assert code == 250
        code, _ = client.docmd('xforward', 'NAME=spike.porcupine.org ADDR=168.100.189.2 PROTO=ESMTP')
        assert code == 250
        code, _ = client.mail(mail_from)
        assert code == 250
        code, _ = client.rcpt(rcpt_to)
        assert code == 250
        code, _ = client.data(data_bytes)
        assert code == 250
        client.quit()
        client.close()

    assert mail_relay.envelope.mail_from == mail_from
    assert mail_relay.envelope.rcpt_tos == [rcpt_to]
    assert mail_relay.content == data_bytes


@pytest.mark.timeout(30)
def test_deferred_mail(pf_proxy_server, mail_relay, pg_server, data_bytes, event_loop):
    server = pf_proxy_server(relay='127.0.0.1:%d' % mail_relay.port, pgport=pg_server.port)

    mail_from = 'bob@test.com'
    rcpt_to = 'fred@test.com'

    client = aioSMTP(server.hostname, server.port, loop=event_loop)
    event_loop.run_until_complete(
        client.connect())

    code, _ = event_loop.run_until_complete(
        client.ehlo())
    assert code == 250

    code, _ = event_loop.run_until_complete(
        client.execute_command(b'xforward',
                               b'NAME=spike.porcupine.org ADDR=168.100.189.2 PROTO=ESMTP')
    )
    assert code == 250

    code, _ = event_loop.run_until_complete(
        client.mail(mail_from))
    assert code == 250

    code, _ = event_loop.run_until_complete(
        client.rcpt(rcpt_to))
    assert code == 250

    with pytest.raises(SMTPDataError) as ex:
        event_loop.run_until_complete(
            client.data(data_bytes))
    assert ex.value.code == 451

    event_loop.run_until_complete(client.quit())

    assert mail_relay.content is None
