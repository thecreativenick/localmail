# localmail

SMTP and IMAP servers plus a browser mail client, all on localhost. Send with Python's
`smtplib` and the message threads into a conversation in the web client. All mail is
generated test data; nothing talks to real mail servers or accounts.

## Status

Early scaffold. Done so far:

- An asyncio SMTP server (RFC 5321 subset): EHLO/HELO, MAIL, RCPT, DATA with dot-unstuffing,
  RSET, NOOP, QUIT, and correct 5xx replies for bad command order.
- An in-memory mail store. Tests drive the server with the standard library's `smtplib` and
  raw sockets.

Run it: `python -m localmail.smtp` (listens on 127.0.0.1:2525).

## Planned milestones

1. Persistent store (SQLite) with per-user mailboxes, UIDs and flags.
2. MIME parser: multipart, quoted-printable/base64, RFC 2047 encoded words, broken charsets.
3. IMAP4rev1 server: LOGIN (test users), SELECT, FETCH, STORE, SEARCH, UID commands, IDLE.
4. Conversation threading (JWZ algorithm) and a full-text search index.
5. Web client: thread list, reader, compose/drafts, filters, offline sync.
6. A generator for 100,000 tangled, mixed-encoding test emails, plus a load test.

## Success bar

Scripted `imaplib` and `smtplib` sessions pass, and 100,000 generated messages sync to the
client and search in under 100 ms.

## Development

```bash
pip install -e .[dev]
pytest
```
