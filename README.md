# GreylistProxyFilter

A Postfix before-queue filter to perform conditional greylisting using
Postgrey.

## Description

The usual approach to greylisting is simply based on a triplet of
`(ip/sender/recipient)`. When used against all mail, this can be
problematic for several reasons:
* legitimate email is initially delayed
* some senders are broken and won't retry, leading to lost mail

This filter allows using more selective criteria based on other checks
which have been performed on the mail. Specifically, the filter expects
to find:
* SpamAssassin headers
* DCC headers

Based on the information in those headers, mail can be conditionally
greylisted.

For example, should the SpamAssassin score exceed a given
threshold (e.g. not enough for it to be definitively marked as spam,
but enough to indicate some doubts), or should certain rules have
been triggered, the mail would additionally be subject to greylisting.

## Installation

This code is currently written against Python 3.5, as that's what ships
with Ubuntu 16.04, where I'm deploying this. It might run on newer
versions, but no guarantees.

1. Install the production requirements.

    `pip install -r requirements/production.txt`

1. Set up a service to run `greylist_proxy_filter.py`.

## Running Tests
Due to changes in asyncio between 3.5 and 3.6+, the testing code will
probably not run anything other than 3.5.

1. Install the testing requirements.

    `pip install -r requirements/development.txt`

1. Run the tests.

    `pytest`

### Running Integration Tests

The integration tests require a Postgrey server with a clean database
that can be freely set up and torn down. If the Postgrey binary is on
your path (`which postgrey`) the tests should run without problem.

If you don't have access to a Postgrey server, you can run the tests
using Docker. Assuming that Docker is installed and running, use the
`pgtype` flag to run with Postgrey in a Docker container. The image
will be built automatically.

    pytest --pgtype=docker
