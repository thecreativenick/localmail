import smtplib
import socket
from email.message import EmailMessage
from email import message_from_bytes, policy

import pytest

from localmail import SMTPServer


@pytest.fixture
def server():
    with SMTPServer() as srv:
        yield srv


def test_smtplib_send_message(server):
    msg = EmailMessage()
    msg["From"] = "alice@example.test"
    msg["To"] = "bob@example.test, carol@example.test"
    msg["Subject"] = "Lunch?"
    msg.set_content("Noon at the usual place.\n.\n..starts with dots\n")

    with smtplib.SMTP(server.host, server.port) as s:
        refused = s.send_message(msg)
    assert refused == {}

    [stored] = server.store.messages
    assert stored.sender == "alice@example.test"
    assert stored.recipients == ["bob@example.test", "carol@example.test"]
    parsed = message_from_bytes(stored.data, policy=policy.default)
    assert parsed["Subject"] == "Lunch?"
    # dot-stuffing round-trips (stored with CRLF line endings, as on the wire)
    body = parsed.get_content().replace("\r\n", "\n")
    assert body == "Noon at the usual place.\n.\n..starts with dots\n"
    assert len(server.store.for_recipient("BOB@example.test")) == 1


def test_several_messages_one_connection(server):
    with smtplib.SMTP(server.host, server.port) as s:
        for i in range(5):
            s.sendmail("a@x.test", ["b@x.test"], f"Subject: n{i}\r\n\r\nbody {i}\r\n")
    assert [message_from_bytes(m.data)["Subject"] for m in server.store.messages] == [
        f"n{i}" for i in range(5)
    ]


def test_command_sequence_errors(server):
    with socket.create_connection((server.host, server.port)) as sock:
        f = sock.makefile("rwb")

        def cmd(line):
            f.write(line.encode() + b"\r\n")
            f.flush()
            return f.readline().decode()

        assert f.readline().decode().startswith("220")
        assert cmd("MAIL FROM:<a@x.test>").startswith("503")  # no EHLO yet
        assert cmd("HELO me").startswith("250")
        assert cmd("RCPT TO:<b@x.test>").startswith("503")  # no MAIL yet
        assert cmd("MAIL FROM:<a@x.test>").startswith("250")
        assert cmd("DATA").startswith("503")  # no RCPT yet
        assert cmd("RCPT TO:<>").startswith("501")
        assert cmd("BOGUS").startswith("500")
        assert cmd("RSET").startswith("250")
        assert cmd("QUIT").startswith("221")
        f.close()
    assert server.store.messages == []
