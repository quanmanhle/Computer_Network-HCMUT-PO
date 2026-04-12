#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course,
# and is released under the "MIT License Agreement". Please see the LICENSE
# file that should have been included as part of this package.
#
# AsynapRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#

"""
daemon.proxy
~~~~~~~~~~~~~~~~~

This module implements a simple proxy server using Python's socket and threading libraries.
It routes incoming HTTP requests to backend services based on hostname mappings (loaded from
proxy.conf) and returns the corresponding responses to clients.

Round-robin state is kept in a module-level dict so it is shared across all threads and
persists for the lifetime of the process.

Requirement:
-----------------
- socket: provides socket networking interface.
- threading: enables concurrent client handling via threads.
- response: customized :class: `Response <Response>` utilities.
- httpadapter: :class: `HttpAdapter <HttpAdapter>` adapter for HTTP request processing.
- dictionary: :class: `CaseInsensitiveDict <CaseInsensitiveDict>` for managing headers.
"""

import socket
import threading

from .response import *
from .httpadapter import HttpAdapter
from .dictionary import CaseInsensitiveDict

# ---------------------------------------------------------------------------
# Round-robin counters  {hostname: current_index}
# Protected by a lock so concurrent threads don't race on the counter.
# ---------------------------------------------------------------------------
_rr_counters = {}
_rr_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Default PROXY_PASS fallback (used only when no routes dict is supplied)
# ---------------------------------------------------------------------------
PROXY_PASS = {
    "192.168.56.103:8080": ('192.168.56.103', 9000),
    "app1.local":          ('192.168.56.103', 9001),
    "app2.local":          ('192.168.56.103', 9002),
}


def forward_request(host, port, request):
    """
    Forwards an HTTP request to a backend server and retrieves the response.

    Opens a fresh TCP connection for every request (HTTP/1.0-style).  If the
    connection or data transfer fails a ``404 Not Found`` response is returned
    so the caller always receives a valid HTTP response.

    :param host (str): IP address of the backend server.
    :param port (int): Port number of the backend server.
    :param request (str|bytes): Raw HTTP request to forward.
    :rtype bytes: Raw HTTP response from the backend.
    """
    backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    backend.settimeout(10)   # avoid hanging forever on a dead backend

    # Accept both str and bytes so callers don't have to care
    if isinstance(request, str):
        request = request.encode('utf-8', errors='replace')

    try:
        backend.connect((host, port))
        backend.sendall(request)

        response = b""
        while True:
            chunk = backend.recv(4096)
            if not chunk:
                break
            response += chunk
        return response

    except socket.error as e:
        print("[Proxy] forward_request error to {}:{} – {}".format(host, port, e))
        return (
            "HTTP/1.1 502 Bad Gateway\r\n"
            "Content-Type: text/plain\r\n"
            "Content-Length: 15\r\n"
            "Connection: close\r\n"
            "\r\n"
            "502 Bad Gateway"
        ).encode('utf-8')
    finally:
        backend.close()


def _pick_round_robin(hostname, backends):
    """
    Selects the next backend from *backends* using a round-robin policy.

    The counter for *hostname* is incremented atomically under ``_rr_lock``
    so concurrent threads always get distinct backends.

    :param hostname (str): Virtual-host key (used to namespace the counter).
    :param backends (list[str]): List of ``"host:port"`` strings.
    :rtype str: The chosen ``"host:port"`` entry.
    """
    with _rr_lock:
        idx = _rr_counters.get(hostname, 0)
        chosen = backends[idx % len(backends)]
        _rr_counters[hostname] = idx + 1
    return chosen


def resolve_routing_policy(hostname, routes):
    """
    Resolves the backend ``(host, port)`` tuple for *hostname* using the
    routing table built from ``proxy.conf``.

    Routes entry format (produced by ``start_proxy.parse_virtual_hosts``):

    .. code-block:: python

        routes = {
            "192.168.56.114:8080": ("192.168.56.114:9000", "round-robin"),
            "app1.local":          ("192.168.56.114:9001", "round-robin"),
            "app2.local":          (["192.168.56.114:9002",
                                     "192.168.56.114:9002"], "round-robin"),
        }

    Policy handling:
    - **Single backend** – use it directly.
    - **Multiple backends + round-robin** – advance the per-host counter and
      pick the backend at ``counter % len(backends)``.
    - **Unknown host** – fall back to ``127.0.0.1:9000`` and log a warning.

    :param hostname (str): Value of the ``Host`` HTTP header from the client.
    :param routes (dict): Routing table from ``parse_virtual_hosts``.
    :rtype tuple: ``(proxy_host: str, proxy_port: int)``
    """
    print("[Proxy] resolve_routing_policy for hostname='{}'".format(hostname))

    if hostname not in routes:
        print("[Proxy] WARNING – hostname '{}' not found in routes, using fallback".format(hostname))
        return '127.0.0.1', 9000

    proxy_map, policy = routes[hostname]
    print("[Proxy]   proxy_map={!r}  policy={!r}".format(proxy_map, policy))

    # ------------------------------------------------------------------ single backend
    if isinstance(proxy_map, str):
        parts = proxy_map.rsplit(':', 1)
        proxy_host = parts[0]
        proxy_port = int(parts[1]) if len(parts) == 2 else 9000
        return proxy_host, proxy_port

    # ------------------------------------------------------------------ list of backends
    if isinstance(proxy_map, list):
        if len(proxy_map) == 0:
            print("[Proxy] Empty backend list for '{}', using fallback".format(hostname))
            return '127.0.0.1', 9000

        if len(proxy_map) == 1:
            chosen = proxy_map[0]
        else:
            # Apply the distribution policy
            if policy == 'round-robin':
                chosen = _pick_round_robin(hostname, proxy_map)
            else:
                # Unknown policy: fall back to first backend
                print("[Proxy] Unknown policy '{}', defaulting to first backend".format(policy))
                chosen = proxy_map[0]

        print("[Proxy]   chosen backend='{}'".format(chosen))
        parts = chosen.rsplit(':', 1)
        proxy_host = parts[0]
        proxy_port = int(parts[1]) if len(parts) == 2 else 9000
        return proxy_host, proxy_port

    # ------------------------------------------------------------------ unexpected type
    print("[Proxy] Unexpected proxy_map type {}, using fallback".format(type(proxy_map)))
    return '127.0.0.1', 9000


def handle_client(ip, port, conn, addr, routes):
    """
    Handles an individual client connection by parsing the HTTP request,
    resolving the target backend via ``resolve_routing_policy``, forwarding
    the request with ``forward_request``, and writing the backend response
    back to the client.

    If the ``Host`` header is absent or the hostname cannot be resolved the
    client receives a ``400 Bad Request`` or ``404 Not Found`` respectively.

    :param ip (str): IP address of the proxy server.
    :param port (int): Port number of the proxy server.
    :param conn (socket.socket): Accepted client connection socket.
    :param addr (tuple): Client address ``(ip, port)``.
    :param routes (dict): Routing table from ``parse_virtual_hosts``.
    """
    try:
        request = conn.recv(4096).decode('utf-8', errors='replace')
        if not request:
            conn.close()
            return

        # -------------------------------------------------------------- extract Host header
        hostname = None
        for line in request.splitlines():
            if line.lower().startswith('host:'):
                hostname = line.split(':', 1)[1].strip()
                break

        if not hostname:
            print("[Proxy] {} – missing Host header".format(addr))
            response = (
                "HTTP/1.1 400 Bad Request\r\n"
                "Content-Type: text/plain\r\n"
                "Content-Length: 15\r\n"
                "Connection: close\r\n"
                "\r\n"
                "400 Bad Request"
            ).encode('utf-8')
            conn.sendall(response)
            conn.close()
            return

        print("[Proxy] {} → Host: {}".format(addr, hostname))

        # -------------------------------------------------------------- resolve backend
        resolved_host, resolved_port = resolve_routing_policy(hostname, routes)

        print("[Proxy] Forwarding '{}' → {}:{}".format(hostname, resolved_host, resolved_port))
        response = forward_request(resolved_host, resolved_port, request)
        conn.sendall(response)

    except socket.error as e:
        print("[Proxy] Socket error handling {}: {}".format(addr, e))
    finally:
        conn.close()


def run_proxy(ip, port, routes):
    """
    Starts the proxy server, binds to *ip*:*port*, and enters an accept loop.

    Each accepted connection is handed off to a **daemon thread** running
    ``handle_client`` so the accept loop is never blocked by slow clients or
    backends, and the process exits cleanly when the main thread finishes.

    :param ip (str): IP address to bind the proxy server.
    :param port (int): Port number to listen on.
    :param routes (dict): Routing table from ``parse_virtual_hosts``.
    """
    proxy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        proxy.bind((ip, port))
        proxy.listen(50)
        print("[Proxy] Listening on {}:{}".format(ip, port))
        print("[Proxy] Loaded routes:")
        for host, (backend, policy) in routes.items():
            print("   '{}' → {}  [{}]".format(host, backend, policy))

        while True:
            conn, addr = proxy.accept()
            # Spawn a daemon thread per client – keeps the accept loop responsive
            t = threading.Thread(
                target=handle_client,
                args=(ip, port, conn, addr, routes),
                daemon=True
            )
            t.start()

    except socket.error as e:
        print("[Proxy] Socket error: {}".format(e))
    finally:
        proxy.close()


def create_proxy(ip, port, routes):
    """
    Entry point for launching the proxy server.

    :param ip (str): IP address to bind the proxy server.
    :param port (int): Port number to listen on.
    :param routes (dict): Routing table from ``parse_virtual_hosts``.
    """
    run_proxy(ip, port, routes)
