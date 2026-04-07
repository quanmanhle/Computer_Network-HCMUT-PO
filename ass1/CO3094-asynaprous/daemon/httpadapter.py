#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# AsynapRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#

"""
daemon.httpadapter
~~~~~~~~~~~~~~~~~

This module provides a http adapter object to manage and persist
http settings (headers, bodies). The adapter supports both
raw URL paths and RESTful route definitions, and integrates with
Request and Response objects to handle client-server communication.
"""

from .request import Request
from .response import Response
from .dictionary import CaseInsensitiveDict

import asyncio
import inspect
import secrets
import time


USERS = {
    "admin": "123456",
    "user1": "password",
    "b": "123456",
}

SESSIONS = {}
SESSION_TTL = 3600

PUBLIC_PATHS = {
    "/",
    "/index.html",
    "/login.html",
    "/static/css/styles.css",
    "/favicon.ico",
}


class HttpAdapter:
    __attrs__ = [
        "ip",
        "port",
        "conn",
        "connaddr",
        "routes",
        "request",
        "response",
    ]

    def __init__(self, ip, port, conn, connaddr, routes):
        self.ip = ip
        self.port = port
        self.conn = conn
        self.connaddr = connaddr
        self.routes = routes
        self.request = Request()
        self.response = Response()

    def is_public_path(self, path):
        if not path:
            return False

        if path in PUBLIC_PATHS:
            return True

        if path.startswith("/static/"):
            return True

        if path.startswith("/images/"):
            return True

        return False

    def validate_session(self, req):
        sid = req.cookies.get("session_id")
        if not sid:
            return None

        session = SESSIONS.get(sid)
        if not session:
            return None

        if session.get("expires_at", 0) < time.time():
            try:
                del SESSIONS[sid]
            except KeyError:
                pass
            return None

        return session

    def validate_basic_auth(self, req):
        if not req.auth:
            return None

        username = req.auth.get("username")
        password = req.auth.get("password")
        if username in USERS and USERS[username] == password:
            return username

        return None

    def create_session(self, username):
        sid = secrets.token_hex(16)
        SESSIONS[sid] = {
            "username": username,
            "expires_at": time.time() + SESSION_TTL,
        }
        return sid

    def _call_hook(self, req):
        """
        Execute routed webapp handler and normalize result to bytes.
        """
        result = req.hook(headers=req.headers, body=req.body)

        if inspect.iscoroutine(result):
            result = asyncio.run(result)

        if isinstance(result, bytes):
            return result

        if isinstance(result, str):
            return result.encode("utf-8")

        return str(result).encode("utf-8")

    def _authorize(self, req):
        """
        Returns (authorized: bool, new_session_id: str|None)
        """
        if self.is_public_path(req.path):
            return True, None

        session = self.validate_session(req)
        if session:
            return True, None

        username = self.validate_basic_auth(req)
        if not username:
            return False, None

        sid = self.create_session(username)
        return True, sid

    def handle_client(self, conn, addr, routes):
        self.conn = conn
        self.connaddr = addr
        req = self.request
        resp = self.response

        try:
            msg = conn.recv(4096).decode("utf-8", errors="ignore")
            if not msg:
                conn.close()
                return

            req.prepare(msg, routes)
            print("[HttpAdapter] Invoke handle_client connection {}".format(addr))

            authorized, new_session_id = self._authorize(req)
            if not authorized:
                response = resp.build_unauthorized(realm="CO3094 Chat")
                conn.sendall(response)
                conn.close()
                return

            if req.hook:
                payload = self._call_hook(req)
                response = resp.build_response(
                    req,
                    envelop_content=payload,
                    set_cookie=new_session_id,
                    content_type="application/json; charset=utf-8",
                )
            else:
                response = resp.build_response(
                    req,
                    set_cookie=new_session_id,
                )

            conn.sendall(response)
        except Exception as e:
            print("[HttpAdapter] handle_client exception: {}".format(e))
            try:
                response = resp.build_server_error(str(e))
                conn.sendall(response)
            except Exception:
                pass
        finally:
            conn.close()

    async def handle_client_coroutine(self, reader, writer):
        req = self.request
        resp = self.response
        addr = writer.get_extra_info("peername")

        print("[HttpAdapter] Invoke handle_client_coroutine connection {}".format(addr))

        try:
            msg = await reader.read(4096)
            if not msg:
                writer.close()
                await writer.wait_closed()
                return

            req.prepare(msg.decode("utf-8", errors="ignore"), self.routes or {})

            authorized, new_session_id = self._authorize(req)
            if not authorized:
                response = resp.build_unauthorized(realm="CO3094 Chat")
                writer.write(response)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return

            if req.hook:
                result = req.hook(headers=req.headers, body=req.body)
                if inspect.iscoroutine(result):
                    result = await result

                if isinstance(result, str):
                    result = result.encode("utf-8")
                elif not isinstance(result, bytes):
                    result = str(result).encode("utf-8")

                response = resp.build_response(
                    req,
                    envelop_content=result,
                    set_cookie=new_session_id,
                    content_type="application/json; charset=utf-8",
                )
            else:
                response = resp.build_response(
                    req,
                    set_cookie=new_session_id,
                )

            writer.write(response)
            await writer.drain()

        except Exception as e:
            print("[HttpAdapter] handle_client_coroutine exception: {}".format(e))
            try:
                writer.write(resp.build_server_error(str(e)))
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            await writer.wait_closed()

    def extract_cookies(self, req):
        """
        Build cookies from Request headers.
        """
        if not req:
            return {}
        return req.cookies or {}

    def add_headers(self, request):
        pass

    def build_proxy_headers(self, proxy):
        headers = {}
        username, password = ("user1", "password")

        if username:
            headers["Proxy-Authorization"] = (username, password)

        return headers