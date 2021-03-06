#!/usr/bin/env python3

import argparse
import logging

from logging.handlers import SysLogHandler

from greylistfilter.smtpproxy import PostfixProxyController, PostfixProxyHandler

logger = logging.getLogger('SpamFilterProxy')


def configure_logging(level=None, config_file=None):
    level = getattr(logging, level, logging.INFO)
    logger.setLevel(level)
    syslog_handler = SysLogHandler(address='/dev/log', facility=SysLogHandler.LOG_MAIL)
    syslog_handler.setLevel(level)
    formatter = logging.Formatter('%(name)s[%(process)d]: %(levelname)s - %(message)s')
    syslog_handler.setFormatter(formatter)
    logger.addHandler(syslog_handler)


def main(host, port, relay, spam, dcc, pghost, pgport):
    handler = PostfixProxyHandler(relay, spam, dcc, pghost, pgport)
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


def check_relay_type(value):
    if value == 'None':
        return None
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Spam-filtering SMTP proxy server.')
    parser.add_argument('-l', '--loglevel', choices=('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'),
                        default='INFO', help='Logging level. Default: %(default)s')
    parser.add_argument('-a', '--address', default='127.0.0.1',
                        help='Hostname on which to listen. Default: %(default)s')
    parser.add_argument('-d', '--dcc', type=check_dcc_type, default='2',
                        help='Minimum required DCC score (2-many). Default: %(default)s')
    parser.add_argument('-p', '--port', type=int, default=10025,
                        help='Port on which to listen. Default: %(default)s')
    parser.add_argument('-s', '--spam', default=1.0, type=float,
                        help='Minimum required SpamAssassin score. Default: %(default)s')

    parser.add_argument('-r', '--relay', type=check_relay_type, required=True, help='Relay SMTP server')
    parser.add_argument('--pghost', default='127.0.0.1', help='Postgrey server host. Default: %(default)s')
    parser.add_argument('--pgport', type=int, default=10023, help='Postgrey server port. Default: %(default)s')

    args = parser.parse_args()

    configure_logging(level=args.loglevel)
    logger.info('SpamFilterProxy starting')

    main(args.address, args.port, args.relay, args.spam, args.dcc,
         args.pghost, args.pgport)
