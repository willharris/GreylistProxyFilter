#!/usr/bin/env python3

import argparse
import asyncio
import logging
import logging.handlers
import re
import smtplib
import sys

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, syntax
from postgrey_client import greylist_status

logger = logging.getLogger('SpamFilterProxy')

re_status = re.compile(r'^X-Spam-Status: No, score=(\S+) .*$')
re_dcc = re.compile(r'^X-Spam-DCC: .+? (?:Body=(\d+|many)\s*)?(?:Fuz1=(\d+|many)\s*)?(?:Fuz2=(\d+|many)\s*)?$')


def byte_lines(data):
    """
    Generator to return byte objects line-by-line,
    i.e. separarated by a newline character
    """
    if type(data) is not bytes:
        raise TypeError('requires a <bytes> object')

    start = 0
    pos = 0
    while pos < len(data):
        if data[pos] == 0x0a:  # \n
            pos += 1
            yield data[start:pos]
            start = pos
        pos += 1

    if start > 0 and pos > start:
        yield data[start:pos]


def configure_logging(level=None, config_file=None):
    level = getattr(logging, level, logging.INFO)
    logger.setLevel(level)
    syslog_handler = logging.handlers.SysLogHandler(address='/dev/log', facility=logging.handlers.SysLogHandler.LOG_MAIL)
    syslog_handler.setLevel(level)
    formatter = logging.Formatter('%(name)s[%(process)d]: %(levelname)s - %(message)s')
    syslog_handler.setFormatter(formatter)
    logger.addHandler(syslog_handler)


class PostfixProxyServer(SMTP):

    XF_ARGS = ('NAME', 'ADDR', 'PROTO', 'HELO')

    @syntax('XFORWARD NAME ADDR PROTO HELO')
    async def smtp_XFORWARD(self, args):
        logger.debug('XFORWARD: %s', args)
        kwargs = dict(x.split('=') for x in args.split(' '))
        if not set(kwargs.keys()).issubset(self.XF_ARGS):
            logger.error('Client sent invalid arguments: %s', kwargs.keys())
            await self.push('501 Syntax error')
            return

        if hasattr(self.session, 'fwd_info'):
            logger.debug('Updating fwd_info: %s', kwargs)
            self.session.fwd_info.update(kwargs)
        else:
            logger.debug('Setting fwd_info: %s', kwargs)
            self.session.fwd_info = kwargs

        await self.push('250 Ok')


class PostfixProxyHandler:
    
    def __init__(self, relay, spam, dcc):
        self.relay = relay
        self.spam = spam
        self.dcc = dcc

    async def handle_DATA(self, server, session, envelope):
        logger.debug('Processing message from %s', session.peer)
        
        status = self.get_spam_status(envelope.content)
        logger.debug('status: %s', status)

        if status['score'] >= self.spam and status['dcc'] >= self.dcc:
            logger.debug('Score (%d) and DCC (%d) conditions met, checking greylist',
                         status['score'], status['dcc'])
            do_grey = await self.check_greylist(session, envelope)

        try:
            self.relay_mail(envelope)
            result = '250 Ok'
        except Exception:
            logger.exception('Caught exception trying to relay mail to %s', self.relay)
            result = '500 Could not process your message'

        return result

    async def handle_RSET(self, session, envelope, *args):
        logger.debug('Handle RSET, clearing fwd_info')
        session.fwd_info = {}
        return '250 Ok'

    async def check_greylist(self, session, envelope):
        recipient = envelope.rcpt_tos[0]
        sender = envelope.mail_from
        client_ip = session.fwd_info['ADDR']
        client_name = session.fwd_info['NAME']

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(greylist_status(loop, 
            recipient, sender, client_ip, client_name))
        
        logger.debug('greylist result: %s', result)

        return result

    def get_spam_status(self, data):
        status = {}

        for line in byte_lines(data):
            if line == b'\r\n':
                logger.debug('End of headers')
                break

            line = line.decode('utf8', errors='replace')

            match = re_status.match(line)
            if match:
                logger.debug('Got match for status')
                status['score'] = float(match.group(1))
                continue

            match = re_dcc.match(line)
            if match:
                logger.debug('Got match for dcc')
                for grp in match.groups():
                    if grp is not None:
                        if grp == 'many':
                            status['dcc'] = 999999
                        else:
                            try:
                                val = int(grp)
                                if 'dcc' in status and val > status['dcc']:
                                    status['dcc'] = val
                            except ValueError as ex:
                                logger.error('Unexpected ValueError from %s: %s', grp, ex)
                                status['dcc'] = 1
                        break
            
            if len(status) == 2:
                logger.debug('Status retrieved: %s', status)
                break
        
        return status

    def relay_mail(self, envelope):
        if self.relay == 'None':
            logger.debug('Relay is None, dropping message!')
            return

        mail_from = envelope.mail_from
        rcpt_tos = envelope.rcpt_tos
        data = envelope.content         # type: bytes

        client = smtplib.SMTP(self.relay)

        return client.sendmail(mail_from, rcpt_tos, data)


class PostfixProxyController(Controller):
    def factory(self):
        return PostfixProxyServer(self.handler)


def main(host, port, relay, spam, dcc):
    handler = PostfixProxyHandler(relay, spam, dcc)
    controller = PostfixProxyController(handler, hostname=host, port=port)
    # Run the event loop in a separate thread.
    controller.start()
    # Wait for the user to press Return.
    input('SMTP server running. Press Return to stop server and exit.')
    controller.stop()


def check_dcc_type(value):
    if value == 'many':
        val = 999999
    else:
        try:
            val = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError('value must be either an integer or "many": %s' % value)

    if val < 2:
        raise argparse.ArgumentTypeError('value must be greater than 1: %s' % val)
    
    return val


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Spam-filtering SMTP proxy server.')
    parser.add_argument('-l', '--loglevel', choices=('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'),
                        default='INFO', help='Logging level. Default: %(default)s')
    parser.add_argument('-a', '--address', default='localhost',
                        help='Hostname on which to listen. Default: %(default)s')
    parser.add_argument('-d', '--dcc', type=check_dcc_type, default='2',
                        help='Minimum required DCC score (2-many). Default: %(default)s')
    parser.add_argument('-p', '--port', type=int, default=10025,
                        help='Port on which to listen. Default: %(default)s')
    parser.add_argument('-s', '--spam', default=1.0, type=float, help='Minimum required SpamAssassin score. Default: %(default)s')

    parser.add_argument('-r', '--relay', required=True, help='Relay SMTP server')

    args = parser.parse_args()

    configure_logging(level=args.loglevel)
    logger.info('SpamFilterProxy starting')

    main(args.address, args.port, args.relay, args.spam, args.dcc)