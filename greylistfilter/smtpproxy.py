import logging.handlers
import re
import smtplib

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import SMTP, syntax

from .postgrey_client import greylist_status

logger = logging.getLogger('SpamFilterProxy')

RE_STATUS = re.compile(r'^X-Spam-Status: No, score=(\S+) .*$')
RE_DCC = re.compile(r'^X-Spam-DCC: .+?(?:Body=(?:(\d+|many)|\S+?))?\s*(?:Fuz1=(?:(\d+|many)|\S+?))?\s*(?:Fuz2=(?:(\d+|many)|\S+?))?$')  # noqa

XFORWARD_ARGS = ('NAME', 'ADDR', 'PROTO', 'HELO')

OK_REPLY = '250 OK'
ERROR_REPLY = '450 Exception'


def byte_lines(data):
    """
    Generator to return byte objects line-by-line,
    i.e. separated by a newline character
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

    if 0 < start < pos:
        yield data[start:pos]


class PostfixProxyServer(SMTP):

    @syntax('XFORWARD %s' % ' '.join(XFORWARD_ARGS))
    async def smtp_XFORWARD(self, args):
        kwargs = dict(x.split('=') for x in args.split(' '))
        if not set(kwargs.keys()).issubset(XFORWARD_ARGS):
            logger.error('Client sent invalid arguments: %s', kwargs.keys())
            await self.push('501 Syntax error')
            return

        if hasattr(self.session, 'fwd_info'):
            logger.debug('Updating fwd_info: %s', kwargs)
            self.session.fwd_info.update(kwargs)
        else:
            logger.debug('Setting fwd_info: %s', kwargs)
            self.session.fwd_info = kwargs

        await self.push(OK_REPLY)


class PostfixProxyHandler:

    DEFAULT_SPAM_SCORE = -999999
    DEFAULT_DCC_SCORE = 0

    def __init__(self, relay, spam, dcc, pghost='127.0.0.1', pgport=10023):
        self.relay = relay
        self.spam = spam
        self.dcc = dcc
        self.pghost = pghost
        self.pgport = pgport

    async def handle_DATA(self, server, session, envelope):
        logger.debug('Processing message from %s', session.peer)

        do_grey = await self.process_data(session, envelope)

        add_header = None
        result = None

        if do_grey:
            if do_grey[0].endswith('DEFER_IF_PERMIT'):
                result = '451 4.7.1 %s' % (do_grey[1] if len(do_grey) > 1 else 'greylisted')
            elif do_grey[0].endswith('PREPEND'):
                add_header = do_grey[1]

        if not result:
            try:
                self.relay_mail(envelope, add_header)
                result = OK_REPLY
            except smtplib.SMTPResponseException as ex:
                logger.warning('Message could not be relayed: %s', ex)
                result = '%d %s' % (ex.smtp_code, ex.smtp_error.decode())
            except Exception as ex:
                logger.exception('Caught exception trying to relay mail to %s', self.relay)
                result = ERROR_REPLY + ': %s' % ex

        return result

    async def handle_EHLO(self, server, session, envelope, hostname):
        session.host_name = hostname
        await server.push('250-XFORWARD %s' % ' '.join(XFORWARD_ARGS))
        return '250 HELP'

    async def handle_RSET(self, session, envelope, *args):
        logger.debug('Handle RSET, clearing fwd_info')
        session.fwd_info = {}
        return OK_REPLY

    async def check_greylist(self, session, envelope):
        recipient = envelope.rcpt_tos[0]
        sender = envelope.mail_from
        client_ip = session.fwd_info['ADDR']
        client_name = session.fwd_info['NAME']

        result = await greylist_status(recipient, sender, client_ip, client_name,
                                       self.pghost, self.pgport)

        logger.debug('greylist result: %s', result)

        return result

    async def process_data(self, session, envelope):

        do_grey = []

        if self.greylist_conditions_met(envelope.content):
            try:
                response = await self.check_greylist(session, envelope)
                do_grey = response.split(' ', 1)
            except Exception as ex:
                logger.error('Problem while checking with greylisting server: %s', ex)

        return do_grey

    def greylist_conditions_met(self, data):
        status = self.get_spam_status(data)

        conditions_met = False

        if status['spam'] >= self.spam and status['dcc'] >= self.dcc:
            logger.debug('Spam score (%f) and DCC score (%d) conditions met, checking greylist',
                         status['spam'], status['dcc'])
            conditions_met = True

        return conditions_met

    def get_spam_status(self, data):
        status = {}

        for line in byte_lines(data):
            if line == b'\r\n':
                logger.debug('End of headers')
                break

            line = line.decode('utf8', errors='replace')

            match = RE_STATUS.match(line)
            if match:
                logger.debug('Got match for status')
                status['spam'] = float(match.group(1))
                continue

            match = RE_DCC.match(line)
            if match:
                logger.debug('Got match for dcc')
                for grp in match.groups():
                    if grp is not None:
                        if grp == 'many':
                            status['dcc'] = 999999
                        else:
                            val = int(grp)
                            if 'dcc' in status and val > status['dcc']:
                                status['dcc'] = val
                            elif 'dcc' not in status:
                                status['dcc'] = val

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
        if self.relay is None:  # pragma: no cover
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
