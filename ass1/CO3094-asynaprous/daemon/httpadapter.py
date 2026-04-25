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
import socket
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
    "/chat.html",
    "/login",
    "/submit-info",
    "/get-list",
    "/connect-peer",
    "/send-peer",
    "/add-list",
    "/broadcast-peer",
    "/static/css/styles.css",
    "/favicon.ico",
}

def read_full_http_request(conn, max_bytes=1024 * 1024):
    """
    Read HTTP header first, then continue reading until Content-Length bytes
    of body are received.
    """
    conn.setblocking(True)
    data = b""

    while b"\r\n\r\n" not in data and len(data) < max_bytes:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk

    if b"\r\n\r\n" not in data:
        return data

    header_part, sep, body_part = data.partition(b"\r\n\r\n")

    content_length = 0
    header_text = header_part.decode("iso-8859-1", errors="replace")
    for line in header_text.split("\r\n"):
        if line.lower().startswith("content-length:"):
            try:
                content_length = int(line.split(":", 1)[1].strip())
            except Exception:
                content_length = 0
            break

    while len(body_part) < content_length and len(data) < max_bytes:
        chunk = conn.recv(4096)
        if not chunk:
            break
        body_part += chunk
        data += chunk

    return header_part + sep + body_part

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

    def _read_http_request(self, conn):
        """
        Read one complete HTTP/1.x request from a TCP socket.
        TCP is a byte stream, so headers and JSON body may arrive separately.
        """
        conn.setblocking(True)
        conn.settimeout(3)
        data = b""
        try:
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if len(data) > 1024 * 1024:
                    break
            header_part, sep, body_part = data.partition(b"\r\n\r\n")
            content_length = 0
            try:
                header_text = header_part.decode("iso-8859-1", errors="replace")
                for line in header_text.split("\r\n")[1:]:
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":", 1)[1].strip())
                        break
            except Exception:
                content_length = 0
            while content_length and len(body_part) < content_length:
                chunk = conn.recv(content_length - len(body_part))
                if not chunk:
                    break
                body_part += chunk
            return (header_part + sep + body_part).decode("utf-8", errors="ignore")
        except socket.timeout:
            return data.decode("utf-8", errors="ignore")
        finally:
            conn.settimeout(None)

    def handle_client(self, conn, addr, routes):
        self.conn = conn
        self.connaddr = addr
        req = self.request
        resp = self.response

        try:
            msg = self._read_http_request(conn)
            if not msg:
                conn.close()
                return

            req.prepare(msg, routes)

            # --- CORS INTERCEPTION ---
            if req.method == 'OPTIONS':
                cors_headers = (
                    "HTTP/1.1 204 No Content\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
                    "Access-Control-Allow-Headers: Content-Type, Authorization\r\n"
                    "Access-Control-Max-Age: 86400\r\n\r\n"
                )
                conn.sendall(cors_headers.encode("utf-8"))
                return # finally block will handle close

            print("[HttpAdapter] Invoke handle_client connection {}".format(addr))

            authorized, new_session_id = self._authorize(req)
            if not authorized:
                response = resp.build_unauthorized(realm="CO3094 Chat")
                conn.sendall(response)
                return

            if req.hook:
                payload = self._call_hook(req)
                
                # FIX: Check if payload is already a full HTTP response (bytes starting with HTTP)
                if isinstance(payload, bytes) and payload.startswith(b"HTTP/1.1"):
                    response = payload
                else:
                    # Only build the response if the hook returned raw data/dict
                    response = resp.build_response(
                        req,
                        envelop_content=payload,
                        set_cookie=new_session_id,
                        content_type="application/json; charset=utf-8",
                    )
            else:
                response = resp.build_response(req, set_cookie=new_session_id)

            # --- THE WINERROR 10035 FIX ---
            conn.setblocking(True) # FIX 1: Force blocking mode for the send
            conn.sendall(response)
            time.sleep(0.02)       # FIX 2: Give Windows 20ms to flush the buffer

        except Exception as e:
            # FIX 3: Ignore the 10035 warning if it still happens during close
            if "10035" not in str(e):
                print("[HttpAdapter] handle_client exception: {}".format(e))
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
            
            if req.method == 'OPTIONS':
                cors_headers = (
                    "HTTP/1.1 204 No Content\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
                    "Access-Control-Allow-Headers: Content-Type, Authorization\r\n"
                    "Access-Control-Max-Age: 86400\r\n"
                    "\r\n"
                )
                writer.write(cors_headers.encode("utf-8"))
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return

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
