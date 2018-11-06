import pytest

from ..smtpproxy import PostfixProxyHandler

header_tpl = b'''
To: Will Harris <host@domain.com>
X-Spam-Status: No, score=%(spam_score)s required=5.0 tests=BAYES_00,FREEMAIL_FROM,
	KAM_LAZY_DOMAIN_SECURITY,RCVD_IN_DNSWL_LOW autolearn=no autolearn_force=no
	version=3.4.1
X-Spam-Checker-Version: SpamAssassin 3.4.1 (2015-04-28) on my.mailhost.com
X-Spam-Relay-Countries: CH ** ** ** AT
X-Spam-DCC: URT:bloggs 1060; %(dcc_scores)s

Danke Will
'''

@pytest.mark.parametrize('spam_score', (
    None, -9999.99, -1.0, -1, 0, 0.1, 0.555, 1.5, 1.555
))
def test_status_spam(pf_handler, spam_score):
    header_params = {
        b'spam_score': b'%f' % spam_score if spam_score is not None else b'',
        b'dcc_scores': b'Body=many Fuz1=1 Fuz2=1'
    }
    headers = header_tpl % header_params
    
    status = pf_handler.get_spam_status(headers)

    assert len(status) == 2

    if spam_score is not None:
        assert status['spam'] == spam_score
    else:
        assert status['spam'] == PostfixProxyHandler.DEFAULT_SPAM_SCORE


@pytest.mark.parametrize('vals,groups', (
    ((1, 2, 3), ('1', '2', '3')),
    ((None, 2, 3), (None, '2', '3')),
    ((1, None, 3), ('1', None, '3')),
    ((1, 2, None), ('1', '2', None)),
    ((-1, 2, 3), (None, '2', '3')),
    ((1, -2, 3), ('1', None, '3')),
    ((1, 2, -3), ('1', '2', None)),
))
def test_dcc_regex(vals, groups):
    from ..smtpproxy import re_dcc

    comps = ['X-Spam-DCC: URT:bloggs 1060;']
    if vals[0]:
        comps.append('Body=%s' % vals[0])
    if vals[1]:
        comps.append('Fuz1=%s' % vals[1])
    if vals[2]:
        comps.append('Fuz2=%s' % vals[2])

    string = ' '.join(comps)
    print('"%s"' % string)

    match = re_dcc.match(string)

    assert match
    assert match.groups() == groups


@pytest.mark.parametrize('body,fuz1,fuz2,result', (
    (None, None, None, PostfixProxyHandler.DEFAULT_DCC_SCORE),
    ('10', None, None, 10),
    (None, '5', None, 5),
    (None, None, '3', 3),
    (None, '5', '3', 5),
    ('7', '3', None, 7),
    ('0', '1', '0', 1),
    ('2', '1', '-1', 2),
    ('many', '0', '0', 999999),
    ('0', 'many', '0', 999999),
    ('0', '0', 'many', 999999),
    ('many', '1', '1', 999999),
    ('10', 'many', '999998', 999999),
    ('-2', '999998', 'many', 999999),
    ('10', '20', '30', 30),
    ('30', '20', '10', 30),
    ('10', '30', '20', 30),
))
def test_status_dcc(pf_handler, body, fuz1, fuz2, result):
    if body or fuz1 or fuz2:
        vals = []
        if body:
            vals.append(b'Body=%s' % body.encode())
        if fuz1:
            vals.append(b'Fuz1=%s' % fuz1.encode())
        if fuz2:
            vals.append(b'Fuz2=%s' % fuz2.encode())
        dcc = b' '.join(vals)
    else:
        dcc = b''

    header_params = {
        b'spam_score': b'1.0',
        b'dcc_scores': dcc
    }
    headers = header_tpl % header_params

    status = pf_handler.get_spam_status(headers)

    assert len(status) == 2
    assert status['dcc'] == result
