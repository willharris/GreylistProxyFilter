import asyncio
import logging
import logging.handlers
import re
import smtplib
import sys

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, syntax

from .postgrey_client import greylist_status

logger = logging.getLogger('SpamFilterProxy')

re_status = re.compile(r'^X-Spam-Status: No, score=(\S+) .*$')
re_dcc = re.compile(r'^X-Spam-DCC: .+?(?:Body=(?:(\d+|many)|\S+?))?\s*(?:Fuz1=(?:(\d+|many)|\S+?))?\s*(?:Fuz2=(?:(\d+|many)|\S+?))?$')


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


class PostfixProxyServer(SMTP):

    XF_ARGS = ('NAME', 'ADDR', 'PROTO', 'HELO')

    @syntax('XFORWARD NAME ADDR PROTO HELO')
    async def smtp_XFORWARD(self, args):
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
    
    DEFAULT_SPAM_SCORE = -999999
    DEFAULT_DCC_SCORE = 0

    def __init__(self, relay, spam, dcc):
        self.relay = relay
        self.spam = spam
        self.dcc = dcc

    async def handle_DATA(self, server, session, envelope):
        logger.debug('Processing message from %s', session.peer)
        
        status = self.get_spam_status(envelope.content)

        if status['spam'] >= self.spam and status['dcc'] >= self.dcc:
            logger.debug('Spam score (%f) and DCC score (%d) conditions met, checking greylist',
                         status['spam'], status['dcc'])
            try:
                response = await self.check_greylist(session, envelope)
                do_grey = response.split(' ', 1)
            except Exception as ex:
                logger.error('Problem while checking with greylisting server: %s', ex)
                do_grey = []

        add_header = None
        result = None

        if do_grey:
            if do_grey[0].endswith('DEFER_IF_PERMIT'):
                result = '450 4.7.1 %s' % do_grey[1] if len(do_grey) > 1 else 'greylisted'
            elif do_grey[0].endswith('PREPEND'):
                add_header = do_grey[1]

        if not result:
            try:
                self.relay_mail(envelope, add_header)
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

        result = await greylist_status(recipient, sender, client_ip, client_name)
        
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
                status['spam'] = float(match.group(1))
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
                                elif 'dcc' not in status:
                                    status['dcc'] = val
                            except ValueError as ex:
                                logger.error('Unexpected ValueError from %s: %s', grp, ex)
                                status['dcc'] = 1
            
            if len(status) == 2:
                logger.debug('Status fully retrieved: %s', status)
                break
        
        # If for some reason no matches were found, set some sane defaults
        if 'spam' not in status:
            status['spam'] = self.DEFAULT_SPAM_SCORE

        if 'dcc' not in status:
            status['dcc'] = self.DEFAULT_DCC_SCORE

        return status

    def relay_mail(self, envelope, add_header):
        if self.relay == 'None':
            logger.debug('Relay is None, dropping message!')
            return

        mail_from = envelope.mail_from
        rcpt_tos = envelope.rcpt_tos
        if add_header:
            data = add_header.encode() + b'\r\n' + envelope.content
        else:
            data = envelope.content

        client = smtplib.SMTP(self.relay)

        return client.sendmail(mail_from, rcpt_tos, data)


class PostfixProxyController(Controller):
    def factory(self):
        return PostfixProxyServer(self.handler)
