"""localmail: SMTP and IMAP servers on localhost, with a browser mail client."""

from .smtp import MailStore, Message, SMTPServer

__all__ = ["MailStore", "Message", "SMTPServer"]
