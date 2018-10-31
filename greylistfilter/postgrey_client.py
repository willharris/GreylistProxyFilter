#!/usr/bin/env python3
import argparse
import asyncio


async def greylist_status(recipient, sender, client_ip, client_name):
    reader, writer = await asyncio.open_connection('127.0.0.1', 10023)

    writer.write(b'request=smtpd_access_policy\n')
    writer.write(b'recipient=%s\n' % recipient.encode())
    writer.write(b'sender=%s\n' % sender.encode())
    writer.write(b'client_address=%s\n' % client_ip.encode())
    writer.write(b'client_name=%s\n' % client_name.encode())
    writer.write(b'\n')

    reply = await reader.read(1024)

    writer.close()

    return reply.decode().rstrip()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Postgrey client.')
    parser.add_argument('-s', '--server', default='localhost',
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
        args.recipient, args.sender, args.address, args.hostname))
    loop.close()

    print(result)