import argparse
import os

import pytest


def pgtype_check(value):
    types = ('native', 'docker')
    if value not in types:
        raise argparse.ArgumentTypeError('Must be one of %s' % str(types))

    if value == 'docker':
        try:
            import docker
            client = docker.from_env()
            client.version()
        except:
            raise argparse.ArgumentTypeError('Docker is not running')

    return value


def pytest_addoption(parser):
    parser.addoption(
        '--pgtype', type=pgtype_check, action='store', default='native',
        help='Postgrey server type: native or docker. Default: %(default)s'
    )


@pytest.fixture
def pgtype(request):
    return request.config.getoption('--pgtype')


@pytest.fixture
def dockerfile():
    return os.path.join(os.path.dirname(__file__), 'docker', 'postgrey')
