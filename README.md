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
