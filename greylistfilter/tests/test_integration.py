import asyncio

import pytest
from aiosmtplib import SMTP as aioSMTP, SMTPDataError

from ..postgrey_client import greylist_status
from .conftest import (PG_RESPONSE_DEFER, PG_RESPONSE_DUNNO,
                       PG_RESPONSE_PREPEND, PG_RESPONSE_HEADER,
                       PG_RESPONSE_TEXT)


@pytest.mark.asyncio
async def test_expected_responses(real_pg_server):
    pg_port, pg_proto = real_pg_server

    result = await greylist_status('a', 'b', 'c', 'd', port=pg_port)
    vals = result.split(' ', 1)
    assert vals[0] == PG_RESPONSE_DEFER

    await asyncio.sleep(1)

    result = await greylist_status('a', 'b', 'c', 'd', port=pg_port)
    vals = result.split(' ', 1)
    assert vals[0] == PG_RESPONSE_PREPEND

    result = await greylist_status('a', 'b', 'c', 'd', port=pg_port)
    vals = result.split(' ', 1)
    assert vals[0] == PG_RESPONSE_DUNNO


@pytest.mark.asyncio
async def test_greylisting(pf_proxy_server, mail_relay, real_pg_server, data_bytes, event_loop):
    pg_port, pg_proto = real_pg_server

    server = pf_proxy_server(relay='localhost:%d' % mail_relay.port, pgport=pg_port)

    mail_from = 'bob@test.com'
    rcpt_to = 'fred@test.com'
    client_name = 'spike.porcupine.org'
    client_ip = '168.100.189.2'
    xforward_args = b'NAME=%s ADDR=%s PROTO=ESMTP' % (client_name.encode(), client_ip.encode())

    client = aioSMTP(server.hostname, server.port, loop=event_loop)

    await client.connect()

    code, _ = await client.ehlo()
    assert code == 250

    async def send_preamble():
        code, _ = await client.execute_command(b'xforward', xforward_args)
        assert code == 250

        code, _ = await client.mail(mail_from)
        assert code == 250

        code, _ = await client.rcpt(rcpt_to)
        assert code == 250

    async def reset():
        code, _ = await client.rset()
        assert code == 250

    async def send_data():
        return await client.data(data_bytes)

    await send_preamble()

    with pytest.raises(SMTPDataError) as ex:
        await send_data()
    assert ex.value.code == 451
    assert ex.value.message == '4.7.1 %s' % PG_RESPONSE_TEXT
    assert mail_relay.content is None

    await reset()
    await asyncio.sleep(1)

    await send_preamble()

    code, _ = await send_data()
    assert code == 250
    assert mail_relay.content is not None
    header = ('%s\r\n' % PG_RESPONSE_HEADER).encode()
    header_len = len(header)
    assert mail_relay.content[0:header_len] == header
    assert mail_relay.content[header_len:] == data_bytes

    await reset()
    mail_relay.envelope = None
    mail_relay.content = None
    await send_preamble()
    code, _ = await send_data()
    assert code == 250
    assert mail_relay.content is not None
    assert mail_relay.content == data_bytes

    await client.quit()

    # this is testing a bit of the details of how postgrey logs info
    # which shouldn't be strictly relevant, but I think it's important
    # that we're on top of how postgrey works
    actions = pg_proto.get_actions()
    assert len(actions) == 3

    action = actions.pop(0)
    assert action['action'] == 'greylist'
    assert action['reason'] == 'new'
    assert action['client_name'] == client_name
    assert action['client_address'] == client_ip
    assert action['sender'] == mail_from
    assert action['recipient'] == rcpt_to

    action = actions.pop(0)
    assert action['action'] == 'pass'
    assert action['reason'] == 'triplet found'
    assert 1 <= int(action['delay']) <= 3  # somewhere in there, needn't be exact...
    assert action['client_name'] == client_name
    assert action['client_address'] == client_ip
    assert action['sender'] == mail_from
    assert action['recipient'] == rcpt_to

    action = actions.pop(0)
    assert action['action'] == 'pass'
    assert action['reason'] == 'triplet found'
    assert 'delay' not in action
    assert action['client_name'] == client_name
    assert action['client_address'] == client_ip
    assert action['sender'] == mail_from
    assert action['recipient'] == rcpt_to
