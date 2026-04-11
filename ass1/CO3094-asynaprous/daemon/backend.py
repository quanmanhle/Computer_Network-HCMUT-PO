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
daemon.backend
~~~~~~~~~~~~~~~~~

This module provides a backend object to manage and persist backend daemon. 
It implements a basic backend server using Python's socket and threading libraries.
It supports handling multiple client connections concurrently and routing requests using a
custom HTTP adapter.

Requirements:
--------------
- socket: provide socket networking interface.
- threading: Enables concurrent client handling via threads.
- response: response utilities.
- httpadapter: the class for handling HTTP requests.
- CaseInsensitiveDict: provides dictionary for managing headers or routes.


Notes:
------
- The server create daemon threads for client handling.
- The current implementation error handling is minimal, socket errors are printed to the console.
- The actual request processing is delegated to the HttpAdapter class.

Usage Example:
--------------
>>> create_backend("127.0.0.1", 9000, routes={})

"""

import socket
import threading
import argparse

import asyncio
import inspect

from .response import *
from .httpadapter import HttpAdapter
from .dictionary import CaseInsensitiveDict

import selectors

# Use DefaultSelector - automatically picks the best available (epoll on Linux, kqueue on macOS)
sel = selectors.DefaultSelector()

# Select non-blocking mode by uncommenting the desired line.
# The LAST assignment wins (Python evaluates top-to-bottom).
#   "threading"  - one thread per connection (baseline)
#   "callback"   - event-driven via selectors (non-blocking, single-thread accept loop)
#   "coroutine"  - asyncio async/await
#mode_async = "threading"
#mode_async = "coroutine"
mode_async = "callback"


def handle_client(ip, port, conn, addr, routes):
    """
    Initializes an HttpAdapter instance and delegates the client handling logic to it.

    :param ip (str): IP address of the server.
    :param port (int): Port number the server is listening on.
    :param conn (socket.socket): Client connection socket.
    :param addr (tuple): client address (IP, port).
    :param routes (dict): Dictionary of route handlers.
    """
    print("[Backend] Invoke handle_client accepted connection from {}".format(addr))
    daemon = HttpAdapter(ip, port, conn, addr, routes)
    daemon.handle_client(conn, addr, routes)


def handle_client_callback(server, ip, port, conn, addr, routes):
    """
    Callback invoked by the selector event loop when a client connection is ready.
    Spawns a daemon thread so the selector loop is never blocked while the
    HttpAdapter processes the request.

    :param server: The listening server socket (not used directly here).
    :param ip (str): IP address of the server.
    :param port (int): Port number the server is listening on.
    :param conn (socket.socket): Client connection socket.
    :param addr (tuple): client address (IP, port).
    :param routes (dict): Dictionary of route handlers.
    """
    print("[Backend] Invoke handle_client_callback accepted connection from {}".format(addr))

    # Run the blocking HttpAdapter in a daemon thread so the selector loop
    # remains free to accept the next connection immediately.
    t = threading.Thread(
        target=handle_client,
        args=(ip, port, conn, addr, routes),
        daemon=True
    )
    t.start()


async def handle_client_coroutine(reader, writer):
    """
    Coroutine in async communication to initialize connection instance
    then delegates the client handling logic to it.

    :param reader (StreamReader): Stream reader wrapper.
    :param writer (StreamWriter): Stream write wrapper.
    """
    addr = writer.get_extra_info("peername")
    print("[Backend] Invoke handle_client_coroutine accepted connection from {}".format(addr))

    while True:
        daemon = HttpAdapter(None, None, None, None, None)
        await daemon.handle_client_coroutine(reader, writer)


async def async_server(ip="0.0.0.0", port=7000, routes={}):
    """
    Coroutine-based server entry point using asyncio.start_server.

    :param ip (str): IP address to bind.
    :param port (int): Port to listen on.
    :param routes (dict): Route handlers.
    """
    print("[Backend] async_server **ASYNC** listening on port {}".format(port))
    if routes:
        print("[Backend] route settings")
        for key, value in routes.items():
            isCoFunc = "**ASYNC** " if inspect.iscoroutinefunction(value) else ""
            print("   + ('{}', '{}'): {}{}".format(key[0], key[1], isCoFunc, str(value)))

    srv = await asyncio.start_server(handle_client_coroutine, ip, port)
    async with srv:
        await srv.serve_forever()


def _accept_callback(server_sock, mask, ip, port, routes):
    """
    Internal selector callback: called when the server socket is readable,
    meaning a new client is ready to be accepted.

    Accepts the connection, makes the client socket non-blocking, registers
    a per-client read callback, then immediately dispatches to handle_client_callback
    which offloads work to a thread.

    :param server_sock: The listening server socket.
    :param mask: Event mask from the selector (EVENT_READ).
    :param ip (str): Server IP address.
    :param port (int): Server port number.
    :param routes (dict): Route handlers.
    """
    conn, addr = server_sock.accept()
    print("[Backend] Selector accepted connection from {}".format(addr))

    # Set client socket to non-blocking so recv() returns immediately
    conn.setblocking(False)

    # Dispatch to callback (which runs HttpAdapter in a thread)
    handle_client_callback(server_sock, ip, port, conn, addr, routes)


def run_backend(ip, port, routes):
    """
    Starts the backend server, binds to the specified IP and port, and listens for incoming
    connections.

    Supports three non-blocking modes selected by the global ``mode_async``:

    * ``"callback"``  – selector/event-driven: the server socket is registered with
      ``selectors.DefaultSelector``; a single event loop calls ``_accept_callback``
      whenever a new connection arrives.  Each accepted connection is handed off to a
      daemon thread (via ``handle_client_callback``) so the loop never blocks.

    * ``"coroutine"`` – asyncio ``async/await``: delegates to ``async_server``.

    * ``"threading"`` – baseline: one blocking ``threading.Thread`` per accepted
      connection (original behaviour).

    :param ip (str): IP address to bind the server.
    :param port (int): Port number to listen on.
    :param routes (dict): Dictionary of route handlers.
    """
    global mode_async

    print("[Backend] run_backend with mode_async='{}', routes={}".format(mode_async, routes))

    # ------------------------------------------------------------------ coroutine
    if mode_async == "coroutine":
        asyncio.run(async_server(ip, port, routes))
        return

    # ------------------------------------------------------------------ socket setup (shared by callback & threading)
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind((ip, port))
        server.listen(50)

        print("[Backend] Listening on {}:{}".format(ip, port))
        if routes:
            print("[Backend] route settings")
            for key, value in routes.items():
                isCoFunc = "**ASYNC** " if inspect.iscoroutinefunction(value) else ""
                print("   + ('{}', '{}'): {}{}".format(key[0], key[1], isCoFunc, str(value)))

        # ---------------------------------------------------------------- callback / selector mode
        if mode_async == "callback":
            # Make the server socket non-blocking so accept() never stalls
            server.setblocking(False)

            # Register the server socket: when it becomes readable a client is waiting
            sel.register(
                server,
                selectors.EVENT_READ,
                data=(ip, port, routes)   # carry context into the callback
            )

            print("[Backend] Entering selector event loop (callback mode)")
            while True:
                # Block here until at least one socket is ready; timeout=None = wait forever
                events = sel.select(timeout=None)
                for key, mask in events:
                    ip_ctx, port_ctx, routes_ctx = key.data
                    # key.fileobj is the server socket that registered above
                    _accept_callback(key.fileobj, mask, ip_ctx, port_ctx, routes_ctx)

        # ---------------------------------------------------------------- threading mode (baseline)
        else:
            print("[Backend] Entering accept loop (threading mode)")
            while True:
                conn, addr = server.accept()
                client_thread = threading.Thread(
                    target=handle_client,
                    args=(ip, port, conn, addr, routes),
                    daemon=True
                )
                client_thread.start()

    except socket.error as e:
        print("[Backend] Socket error: {}".format(e))
    finally:
        sel.close()
        server.close()


def create_backend(ip, port, routes={}):
    """
    Entry point for creating and running the backend server.

    :param ip (str): IP address to bind the server.
    :param port (int): Port number to listen on.
    :param routes (dict, optional): Dictionary of route handlers. Defaults to empty dict.
    """
    run_backend(ip, port, routes)
