#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# AsynapRous release
#

import socket
import threading
import asyncio
import inspect
import selectors

from .httpadapter import HttpAdapter

sel = selectors.DefaultSelector()

# Hotfix để chạy ổn cho phần auth test trước.
# A có thể đổi lại "callback" sau khi hoàn thiện selectors.
mode_async = "threading"
# mode_async = "callback"
# mode_async = "coroutine"


def handle_client(ip, port, conn, addr, routes):
    print("[Backend] Invoke handle_client accepted connection from {}".format(addr))
    daemon = HttpAdapter(ip, port, conn, addr, routes)
    daemon.handle_client(conn, addr, routes)


def handle_client_callback(server, ip, port, conn, addr, routes):
    print("[Backend] Invoke handle_client_callback accepted connection from {}".format(addr))
    daemon = HttpAdapter(ip, port, conn, addr, routes)
    daemon.handle_client(conn, addr, routes)


async def handle_client_coroutine(reader, writer, ip, port, routes):
    addr = writer.get_extra_info("peername")
    print("[Backend] Invoke handle_client_coroutine accepted connection from {}".format(addr))

    daemon = HttpAdapter(ip, port, None, addr, routes)
    await daemon.handle_client_coroutine(reader, writer)


async def async_server(ip="0.0.0.0", port=7000, routes=None):
    if routes is None:
        routes = {}

    print("[Backend] async_server **ASYNC** listening on port {}".format(port))
    if routes != {}:
        print("[Backend] route settings")
        for key, value in routes.items():
            isCoFunc = ""
            if inspect.iscoroutinefunction(value):
                isCoFunc += "**ASYNC** "
            print("   + ('{}', '{}'): {}{}".format(key[0], key[1], isCoFunc, str(value)))

    server = await asyncio.start_server(
        lambda reader, writer: handle_client_coroutine(reader, writer, ip, port, routes),
        ip,
        port
    )

    async with server:
        await server.serve_forever()


def run_backend(ip, port, routes):
    global mode_async

    if routes is None:
        routes = {}

    print("[Backend] run_backend with routes={}".format(routes))

    if mode_async == "coroutine":
        asyncio.run(async_server(ip, port, routes))
        return

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind((ip, port))
        server.listen(50)

        print("[Backend] Listening on port {}".format(port))
        if routes != {}:
            print("[Backend] route settings")
            for key, value in routes.items():
                isCoFunc = ""
                if inspect.iscoroutinefunction(value):
                    isCoFunc += "**ASYNC** "
                print("   + ('{}', '{}'): {}{}".format(key[0], key[1], isCoFunc, str(value)))

        if mode_async == "callback":
            server.setblocking(False)
            sel.register(server, selectors.EVENT_READ, (ip, port, routes))

            while True:
                events = sel.select(timeout=None)
                for key, mask in events:
                    sock = key.fileobj
                    ip_cb, port_cb, routes_cb = key.data

                    conn, addr = sock.accept()
                    conn.setblocking(True)

                    handle_client_callback(sock, ip_cb, port_cb, conn, addr, routes_cb)

        else:
            while True:
                conn, addr = server.accept()

                if mode_async == "threading":
                    client_thread = threading.Thread(
                        target=handle_client,
                        args=(ip, port, conn, addr, routes),
                        daemon=True
                    )
                    client_thread.start()
                else:
                    handle_client(ip, port, conn, addr, routes)

    except socket.error as e:
        print("Socket error: {}".format(e))
    finally:
        try:
            server.close()
        except Exception:
            pass


def create_backend(ip, port, routes={}):
    run_backend(ip, port, routes)