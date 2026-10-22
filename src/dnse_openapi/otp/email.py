"""Read DNSE Email OTP codes over IMAP.

This is opt-in: the core client works with a passcode supplied by the caller.
Email OTP is the only DNSE 2FA method that can be fully automated, so this
helper exists for unattended strategies. It logs in with an app password; never
commit that password.
"""

from __future__ import annotations

import imaplib
import re
import time
from datetime import timezone
from email import message_from_bytes
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime

from ..errors import DNSEError

_OTP_NEAR_LABEL = re.compile(
    r"(?:otp|m[aã]\s*x[aá]c\s*th[uự]c|passcode|code)[^0-9]{0,40}(\d{4,8})",
    re.IGNORECASE,
)
# Word boundaries keep six digits inside account/order IDs out of the match.
_OTP_GENERIC = re.compile(r"\b(\d{6})\b")


class OTPTimeout(DNSEError):
    """No OTP email arrived before the deadline."""


def extract_otp(text: str) -> str | None:
    """Extract an OTP from an email body.

    Prefers a code that follows a label such as ``OTP`` or ``mã xác thực`` and
    falls back to the first standalone six-digit number.
    """
    if not text:
        return None
    labelled = _OTP_NEAR_LABEL.search(text)
    if labelled:
        return labelled.group(1)
    generic = _OTP_GENERIC.search(text)
    return generic.group(1) if generic else None


def _message_text(message: Message) -> str:
    plain: list[str] = []
    html: list[str] = []
    for part in message.walk():
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes) or not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            decoded = payload.decode(charset, errors="replace")
        except LookupError:
            decoded = payload.decode("utf-8", errors="replace")
        (plain if content_type == "text/plain" else html).append(decoded)
    if plain:
        return "\n".join(plain)
    # Strip tags so a code split by markup is still readable.
    return re.sub(r"<[^>]+>", " ", "\n".join(html))


def _message_time(message: Message) -> float | None:
    """Return the message's ``Date`` header as an epoch, or ``None``."""
    raw = message.get("Date")
    if not raw:
        return None
    try:
        value = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


class EmailOTPReader:
    """Poll an IMAP mailbox for the newest unread DNSE OTP email."""

    def __init__(
        self,
        user: str,
        password: str,
        *,
        host: str = "imap.gmail.com",
        port: int = 993,
        sender: str | None = "dnse",
        subject: str | None = "Email OTP",
        mailbox: str = "INBOX",
    ) -> None:
        if not user or not password:
            raise ValueError("IMAP user and password are required")
        self._user = user
        self._password = password
        self._host = host
        self._port = port
        self._sender = sender
        self._subject = subject
        self._mailbox = mailbox

    def wait_for_otp(
        self,
        *,
        timeout: float = 180.0,
        poll_interval: float = 2.0,
        mark_seen: bool = True,
        after: float | None = None,
    ) -> str:
        """Block until an OTP email is found, then return the code.

        Fetching with ``RFC822`` (``mark_seen=True``) marks the message as read so
        the same code is not returned twice. Use ``BODY.PEEK[]`` semantics by
        passing ``mark_seen=False`` only if you manage read state yourself.

        ``after`` is an epoch timestamp (captured just before requesting the
        OTP). Messages dated more than two minutes before it are ignored, which
        prevents an old unread code from being reused.
        """
        deadline = time.monotonic() + timeout
        cutoff = None if after is None else after - 120.0
        with imaplib.IMAP4_SSL(self._host, self._port) as mail:
            mail.login(self._user, self._password)
            mail.select(self._mailbox)

            while time.monotonic() < deadline:
                message_ids = self._search(mail)
                for message_id in reversed(message_ids):
                    message = self._fetch(mail, message_id, mark_seen=mark_seen)
                    if message is None:
                        continue
                    if cutoff is not None:
                        sent_at = _message_time(message)
                        if sent_at is not None and sent_at < cutoff:
                            continue
                    otp = extract_otp(_message_text(message))
                    if otp:
                        return otp
                time.sleep(poll_interval)

        raise OTPTimeout(
            f"no OTP email from {self._sender or 'any sender'} within {timeout:.0f}s"
        )

    def _search(self, mail: imaplib.IMAP4_SSL) -> list[bytes]:
        criteria: list[str] = ["UNSEEN"]
        if self._sender:
            address = parseaddr(self._sender)[1] or self._sender
            criteria.append(f'FROM "{address}"')
        if self._subject:
            subject = self._subject.replace('"', r"\"")
            criteria.append(f'SUBJECT "{subject}"')

        status, data = mail.search(None, *criteria)
        if status != "OK" or not data or not data[0]:
            return []
        ids = data[0]
        if not isinstance(ids, bytes):
            return []
        return list(ids.split())

    @staticmethod
    def _fetch(
        mail: imaplib.IMAP4_SSL, message_id: bytes, *, mark_seen: bool
    ) -> Message | None:
        item = "RFC822" if mark_seen else "(BODY.PEEK[])"
        status, data = mail.fetch(message_id.decode("ascii"), item)
        if status != "OK" or not data:
            return None
        for entry in data:
            if isinstance(entry, tuple) and len(entry) >= 2 and isinstance(entry[1], bytes):
                return message_from_bytes(entry[1])
        return None
