"""Loopback OAuth callback server for browser-based authorization flows.

Binds strictly to loopback interfaces (127.0.0.1 and ::1) on registered explicit ports.
Enforces:
- Exact registered path and constant-time state matching per state/port
- Single execution of on_code callback
- Zero logging of state, code, tokens, query strings, or redirect URLs
- 8 KiB request-line cap
- Overall request-read deadline (10 seconds)
- Connection: close and Cache-Control: no-store on all responses
- Static dark/amber HTML response pages (success, expired, denied, unknown, error)
- Safe error handling without leaking internal details
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import ipaddress
import logging
import secrets
from typing import Awaitable, Callable
import urllib.parse

logger = logging.getLogger("blm.oauth_callback_server")

# Overall request read deadline (request-line plus headers)
REQUEST_READ_TIMEOUT_SECONDS: float = 10.0


class OAuthCallbackError(ValueError):
    """Raised when an OAuth callback server operation fails."""
    pass


def _render_page(
    *,
    title: str,
    badge: str,
    heading: str,
    message: str,
    badge_color: str = "#f59e0b",
) -> str:
    """Render a static terminal-styled dark HTML page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{
    margin: 0;
    padding: 0;
    background-color: #09090b;
    color: #f4f4f5;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, monospace;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
  }}
  .card {{
    background-color: #18181b;
    border: 1px solid #27272a;
    border-radius: 8px;
    padding: 32px;
    max-width: 440px;
    width: 90%;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
    text-align: center;
  }}
  .badge {{
    display: inline-block;
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 16px;
    background-color: rgba(245, 158, 11, 0.1);
    color: {badge_color};
    border: 1px solid rgba(245, 158, 11, 0.2);
  }}
  h1 {{
    font-size: 20px;
    font-weight: 600;
    margin: 0 0 12px 0;
    color: #ffffff;
    letter-spacing: -0.01em;
  }}
  p {{
    font-size: 14px;
    color: #a1a1aa;
    line-height: 1.5;
    margin: 0;
  }}
</style>
</head>
<body>
  <div class="card">
    <div class="badge">{badge}</div>
    <h1>{heading}</h1>
    <p>{message}</p>
  </div>
</body>
</html>"""


HTML_SUCCESS = _render_page(
    title="BLM Terminal - Authorization",
    badge="AUTHORIZATION COMPLETE",
    heading="Authorization Successful",
    message="Your account has been connected. You can safely close this browser tab and return to BLM Terminal.",
    badge_color="#10b981",
)

HTML_DENIED = _render_page(
    title="BLM Terminal - Authorization",
    badge="AUTHORIZATION CANCELLED",
    heading="Authorization Denied",
    message="The authorization request was cancelled or denied. You can safely close this tab and return to BLM Terminal.",
    badge_color="#ef4444",
)

HTML_EXPIRED = _render_page(
    title="BLM Terminal - Authorization",
    badge="SESSION EXPIRED",
    heading="Authorization Expired",
    message="This authorization session has expired. Please return to BLM Terminal and start a new authorization.",
    badge_color="#f59e0b",
)

HTML_UNKNOWN = _render_page(
    title="BLM Terminal - Authorization",
    badge="INVALID REQUEST",
    heading="Invalid Authorization Request",
    message="The authorization state was not recognized or has already been completed. You can safely close this tab.",
    badge_color="#71717a",
)

HTML_ERROR = _render_page(
    title="BLM Terminal - Authorization",
    badge="SERVER ERROR",
    heading="Authorization Error",
    message="An unexpected error occurred while processing the authorization. Please return to BLM Terminal and try again.",
    badge_color="#ef4444",
)

HTML_METHOD_NOT_ALLOWED = _render_page(
    title="BLM Terminal - Authorization",
    badge="METHOD NOT ALLOWED",
    heading="Method Not Allowed",
    message="Only GET requests are supported on this callback listener.",
    badge_color="#71717a",
)

HTML_INVALID = _render_page(
    title="BLM Terminal - Authorization",
    badge="BAD REQUEST",
    heading="Bad Request",
    message="The request could not be processed.",
    badge_color="#71717a",
)

HTML_TIMEOUT = _render_page(
    title="BLM Terminal - Authorization",
    badge="REQUEST TIMEOUT",
    heading="Request Timeout",
    message="The request timed out while waiting for data. Please return to BLM Terminal and try again.",
    badge_color="#71717a",
)


def _build_response(
    status_code: int,
    reason: str,
    html_body: str,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    """Format an HTTP/1.1 response with Connection: close and Cache-Control: no-store."""
    body_bytes = html_body.encode("utf-8")
    headers = [
        f"HTTP/1.1 {status_code} {reason}",
        "Content-Type: text/html; charset=utf-8",
        f"Content-Length: {len(body_bytes)}",
        "Connection: close",
        "Cache-Control: no-store",
    ]
    if extra_headers:
        for k, v in extra_headers.items():
            headers.append(f"{k}: {v}")
    header_bytes = "\r\n".join(headers).encode("latin1") + b"\r\n\r\n"
    return header_bytes + body_bytes


def parse_loopback_redirect(redirect_uri: str) -> tuple[str, int, str]:
    """Parse and validate an HTTP loopback redirect URI with an explicit port.

    Rejects non-HTTP schemes, non-loopback hosts, missing ports, and malformed paths
    while accepting provider-specific callback paths.
    Returns (host, port, path).
    """
    if not redirect_uri or not isinstance(redirect_uri, str):
        raise OAuthCallbackError("redirect_uri must be a non-empty string")

    stripped = redirect_uri.strip()
    try:
        parsed = urllib.parse.urlsplit(stripped)
    except Exception as exc:
        raise OAuthCallbackError(f"Malformed redirect_uri: {type(exc).__name__}") from exc

    if parsed.scheme.lower() != "http":
        raise OAuthCallbackError(
            f"Unsupported scheme '{parsed.scheme}'; only http loopback is allowed"
        )

    if not parsed.hostname:
        raise OAuthCallbackError("Missing host in redirect URI")

    host_lower = parsed.hostname.lower()
    if host_lower != "localhost":
        try:
            ip = ipaddress.ip_address(host_lower)
            if not ip.is_loopback:
                raise OAuthCallbackError(
                    f"Non-loopback IP host '{parsed.hostname}' is not allowed"
                )
        except ValueError:
            raise OAuthCallbackError(
                f"Non-loopback host '{parsed.hostname}' is not allowed"
            )

    try:
        port = parsed.port
    except ValueError as exc:
        raise OAuthCallbackError(f"Invalid port in redirect URI: {exc}") from exc

    if port is None:
        raise OAuthCallbackError("Missing port in loopback redirect URI")

    if not (1 <= port <= 65535):
        raise OAuthCallbackError(f"Invalid port {port}")

    if parsed.fragment:
        raise OAuthCallbackError("Redirect URI must not contain a fragment")

    raw_path = parsed.path
    if not raw_path or not raw_path.startswith("/") or raw_path == "/":
        raise OAuthCallbackError(
            f"Malformed or missing callback path in '{redirect_uri}'"
        )

    if ".." in raw_path:
        raise OAuthCallbackError(
            "Path traversal elements are not allowed in callback path"
        )

    return (host_lower, port, raw_path)


@dataclass
class _Registration:
    state: str
    port: int
    path: str
    on_code: Callable[[str, str], Awaitable[None]]
    on_error: Callable[[str], Awaitable[None]]
    called: bool = False


class OAuthCallbackServer:
    """Manages loopback HTTP listeners for OAuth authorization redirects."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._registrations: dict[str, _Registration] = {}
        self._servers: dict[int, list[asyncio.Server]] = {}
        self._port_states: dict[int, set[str]] = {}

    async def register(
        self,
        *,
        state: str,
        redirect_uri: str,
        on_code: Callable[[str, str], Awaitable[None]],
        on_error: Callable[[str], Awaitable[None]],
    ) -> str:
        """Register a state and redirect URI, starting the loopback listener if needed."""
        host, port, path = parse_loopback_redirect(redirect_uri)

        async with self._lock:
            if port not in self._servers:
                listeners: list[asyncio.Server] = []
                # Bind IPv4 127.0.0.1 first
                try:
                    srv4 = await asyncio.start_server(
                        lambda r, w, p=port: self._handle_client(r, w, p),
                        host="127.0.0.1",
                        port=port,
                    )
                    listeners.append(srv4)
                except OSError as exc:
                    logger.debug("IPv4 port bind failed: %s", type(exc).__name__)
                    raise OAuthCallbackError(
                        f"Port {port} is already in use or cannot be bound"
                    ) from exc

                # Attempt IPv6 ::1 in a separate try/except; failure continues with IPv4 only
                try:
                    srv6 = await asyncio.start_server(
                        lambda r, w, p=port: self._handle_client(r, w, p),
                        host="::1",
                        port=port,
                    )
                    listeners.append(srv6)
                except OSError as exc:
                    logger.debug("IPv6 loopback bind failed on port %s: %s", port, type(exc).__name__)

                self._servers[port] = listeners
                self._port_states[port] = set()
                logger.debug("OAuth callback server started on port %s", port)

            reg = _Registration(
                state=state,
                port=port,
                path=path,
                on_code=on_code,
                on_error=on_error,
            )
            self._registrations[state] = reg
            self._port_states[port].add(state)

        return redirect_uri

    async def unregister(self, state: str) -> None:
        """Unregister a state, closing the underlying port listener if no states remain."""
        servers_to_close: list[asyncio.Server] | None = None
        port_closed: int | None = None

        async with self._lock:
            reg = self._registrations.pop(state, None)
            if reg is not None:
                port = reg.port
                states = self._port_states.get(port)
                if states:
                    states.discard(state)
                    if not states:
                        del self._port_states[port]
                        servers_to_close = self._servers.pop(port, None)
                        port_closed = port

        if servers_to_close:
            for s in servers_to_close:
                s.close()
            await asyncio.gather(
                *(s.wait_closed() for s in servers_to_close), return_exceptions=True
            )
            if port_closed is not None:
                logger.debug("OAuth callback server stopped on port %s", port_closed)

    async def shutdown(self) -> None:
        """Close all active listeners and clear all registrations."""
        async with self._lock:
            self._registrations.clear()
            self._port_states.clear()
            servers_lists = list(self._servers.values())
            self._servers.clear()

        all_servers: list[asyncio.Server] = [s for sublist in servers_lists for s in sublist]
        for s in all_servers:
            s.close()
        if all_servers:
            await asyncio.gather(
                *(s.wait_closed() for s in all_servers), return_exceptions=True
            )
        logger.debug("All OAuth callback servers shut down")

    async def _claim(self, reg: _Registration) -> bool:
        """Atomically claim execution rights for a registration under self._lock."""
        async with self._lock:
            if reg.called:
                return False
            reg.called = True
            return True

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        port: int,
    ) -> None:
        """Handle incoming HTTP request with 8 KiB line cap and exact state/path routing."""
        try:
            raw_data = bytearray()
            async with asyncio.timeout(REQUEST_READ_TIMEOUT_SECONDS):
                # Read request line respecting the 8 KiB cap
                while b"\r\n" not in raw_data and b"\n" not in raw_data:
                    chunk = await reader.read(1024)
                    if not chunk:
                        break
                    raw_data.extend(chunk)
                    if len(raw_data) > 8192 and b"\r\n" not in raw_data and b"\n" not in raw_data:
                        resp = _build_response(414, "URI Too Long", HTML_INVALID)
                        writer.write(resp)
                        await writer.drain()
                        return

                if not raw_data:
                    return

                first_line_end = raw_data.find(b"\r\n")
                if first_line_end == -1:
                    first_line_end = raw_data.find(b"\n")
                if first_line_end == -1 or first_line_end > 8192:
                    resp = _build_response(414, "URI Too Long", HTML_INVALID)
                    writer.write(resp)
                    await writer.drain()
                    return

                # Ingest remaining headers up to 16 KiB total so client request completes
                while b"\r\n\r\n" not in raw_data and len(raw_data) < 16384:
                    chunk = await reader.read(1024)
                    if not chunk:
                        break
                    raw_data.extend(chunk)

            request_line = (
                raw_data[:first_line_end].decode("latin1", errors="replace").strip()
            )
            parts = request_line.split()
            if len(parts) < 2:
                resp = _build_response(400, "Bad Request", HTML_INVALID)
                writer.write(resp)
                await writer.drain()
                return

            method, raw_target = parts[0].upper(), parts[1]
            if method != "GET":
                resp = _build_response(
                    405,
                    "Method Not Allowed",
                    HTML_METHOD_NOT_ALLOWED,
                    extra_headers={"Allow": "GET"},
                )
                writer.write(resp)
                await writer.drain()
                return

            split_res = urllib.parse.urlsplit(raw_target)
            req_path = split_res.path
            query_params = urllib.parse.parse_qs(
                split_res.query, keep_blank_values=True
            )
            req_state = query_params.get("state", [None])[0]

            if not req_state:
                resp = _build_response(400, "Bad Request", HTML_UNKNOWN)
                writer.write(resp)
                await writer.drain()
                return

            # Constant-time state lookup among registrations on this port
            matched_reg: _Registration | None = None
            async with self._lock:
                port_states = list(self._port_states.get(port, ()))
                for st in port_states:
                    if secrets.compare_digest(st, req_state):
                        matched_reg = self._registrations.get(st)
                        break

            if matched_reg is None:
                resp = _build_response(400, "Bad Request", HTML_UNKNOWN)
                writer.write(resp)
                await writer.drain()
                return

            # Exact path matching
            if req_path != matched_reg.path:
                resp = _build_response(404, "Not Found", HTML_UNKNOWN)
                writer.write(resp)
                await writer.drain()
                return

            # Handle provider error redirect
            if "error" in query_params:
                error_code = query_params["error"][0] or "access_denied"
                if await self._claim(matched_reg):
                    try:
                        await matched_reg.on_error(error_code)
                    except Exception as exc:
                        logger.debug("on_error callback raised: %s", type(exc).__name__)
                        resp = _build_response(
                            500, "Internal Server Error", HTML_ERROR
                        )
                        writer.write(resp)
                        await writer.drain()
                        return

                if error_code in ("expired", "expired_token"):
                    html_page = HTML_EXPIRED
                elif error_code == "access_denied":
                    html_page = HTML_DENIED
                else:
                    html_page = HTML_DENIED

                resp = _build_response(200, "OK", html_page)
                writer.write(resp)
                await writer.drain()
                return

            # Handle success redirect
            code_val = query_params.get("code", [None])[0]
            if not code_val:
                resp = _build_response(400, "Bad Request", HTML_UNKNOWN)
                writer.write(resp)
                await writer.drain()
                return

            if await self._claim(matched_reg):
                try:
                    await matched_reg.on_code(matched_reg.state, code_val)
                except Exception as exc:
                    logger.debug("on_code callback raised: %s", type(exc).__name__)
                    resp = _build_response(
                        500, "Internal Server Error", HTML_ERROR
                    )
                    writer.write(resp)
                    await writer.drain()
                    return

            resp = _build_response(200, "OK", HTML_SUCCESS)
            writer.write(resp)
            await writer.drain()

        except (TimeoutError, asyncio.TimeoutError):
            logger.debug("Request read timed out on port %s", port)
            try:
                resp = _build_response(408, "Request Timeout", HTML_TIMEOUT)
                writer.write(resp)
                await asyncio.wait_for(writer.drain(), timeout=1.0)
            except Exception:
                pass
            return
        except Exception as exc:
            logger.debug("Client handler error: %s", type(exc).__name__)
            try:
                resp = _build_response(500, "Internal Server Error", HTML_ERROR)
                writer.write(resp)
                await writer.drain()
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


__all__ = [
    "OAuthCallbackError",
    "OAuthCallbackServer",
    "REQUEST_READ_TIMEOUT_SECONDS",
    "parse_loopback_redirect",
]
