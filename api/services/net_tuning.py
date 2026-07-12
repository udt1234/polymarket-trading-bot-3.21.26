"""Network latency tuning (BUILD_SPEC speed hardening; tweet-thread Part 5).

Nagle's algorithm buffers small outbound packets to coalesce them, which can add
tens of ms to a tiny request/response - exactly the shape of a CLOB order POST or
cancel. On a maker the cancel/re-quote path is latency-sensitive, so disable Nagle
(TCP_NODELAY) on every stream socket. Call once at process start, before any
connection is opened. Idempotent.
"""
import logging
import socket

log = logging.getLogger(__name__)
_patched = False


def enable_tcp_nodelay() -> None:
    """Monkeypatch socket creation so every TCP stream socket sets TCP_NODELAY."""
    global _patched
    if _patched:
        return
    orig_init = socket.socket.__init__

    def init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        try:
            if self.type == socket.SOCK_STREAM:
                self.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (OSError, AttributeError):
            pass  # non-TCP (unix/listening) sockets: option not applicable

    socket.socket.__init__ = init
    _patched = True
    log.info("TCP_NODELAY enabled on all stream sockets (Nagle off)")
