#!/usr/bin/env python3
import argparse
import asyncio


async def greylist_status(recipient, sender, client_ip, client_name, host='127.0.0.1', port=10023):
    reader, writer = await asyncio.open_connection(host, port)

    data = (b'request=smtpd_access_policy\n'
            b'recipient=%s\n'
            b'sender=%s\n'
            b'client_address=%s\n'
            b'client_name=%s\n'
            b'\n') % (recipient.encode(), sender.encode(), client_ip.encode(), client_name.encode())

    writer.write(data)
    await writer.drain()

    reply = b''
    while True:
        line = await reader.readline()
        if line == b'\n':
            break
        reply = line

    writer.close()
    print(reply)
    return reply.decode().rstrip()


if __name__ == '__main__':  # pragma: no cover
    parser = argparse.ArgumentParser(description='Postgrey client.')
    parser.add_argument('-s', '--server', default='127.0.0.1',
                        help='Name or IP of the Postgrey server. Default: %(default)s')
    parser.add_argument('-p', '--port', type=int, default=10023,
                        help='Port of the Postgrey server. Default: %(default)s')
    parser.add_argument('recipient', help='Recipient email address')
    parser.add_argument('sender', help='Sender email address')
    parser.add_argument('address', help='Client IP address')
    parser.add_argument('hostname', help='Client hostname')

    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    result = loop.run_until_complete(greylist_status(
        args.recipient, args.sender, args.address, args.hostname, args.server, args.port))
    loop.close()

    print(result)
