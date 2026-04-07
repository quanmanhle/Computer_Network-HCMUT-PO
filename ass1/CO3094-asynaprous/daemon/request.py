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
daemon.request
~~~~~~~~~~~~~~~~~

This module provides a Request object to manage and persist
request settings (cookies, auth, proxies).
"""

import base64
from .dictionary import CaseInsensitiveDict


class Request():
    """The fully mutable "class" `Request <Request>` object."""

    __attrs__ = [
        "method",
        "url",
        "path",
        "version",
        "headers",
        "body",
        "_raw_headers",
        "_raw_body",
        "reason",
        "cookies",
        "auth",
        "routes",
        "hook",
    ]

    def __init__(self):
        #: HTTP verb to send to the server.
        self.method = None
        #: HTTP URL to send to the server.
        self.url = None
        #: HTTP path
        self.path = None
        #: HTTP version
        self.version = None
        #: dictionary of HTTP headers
        self.headers = CaseInsensitiveDict()
        #: request body to send to the server
        self.body = ""
        #: raw header
        self._raw_headers = ""
        #: raw body
        self._raw_body = ""
        #: cookies
        self.cookies = {}
        #: parsed authorization
        self.auth = None
        #: routes
        self.routes = {}
        #: mapped routed hook
        self.hook = None
        #: optional reason
        self.reason = None

    def extract_request_line(self, request):
        try:
            lines = request.splitlines()
            first_line = lines[0]
            method, path, version = first_line.split()

            if path == '/':
                path = '/index.html'
        except Exception:
            return None, None, None

        return method, path, version

    def prepare_headers(self, request):
        """Prepares the given HTTP headers."""
        header_text, _ = self.fetch_headers_body(request)
        lines = header_text.split('\r\n')
        headers = CaseInsensitiveDict()
        for line in lines[1:]:
            if ': ' in line:
                key, val = line.split(': ', 1)
                headers[key] = val
        return headers

    def fetch_headers_body(self, request):
        """Split request into header section and body section."""
        parts = request.split("\r\n\r\n", 1)
        _headers = parts[0] if len(parts) > 0 else ""
        _body = parts[1] if len(parts) > 1 else ""
        return _headers, _body

    def prepare(self, request, routes=None):
        """Prepares the entire request with the given parameters."""
        print("[Request] prepare request msg {}".format(request))

        self.method, self.path, self.version = self.extract_request_line(request)
        self.url = self.path

        print("[Request] {} path {} version {}".format(
            self.method, self.path, self.version)
        )

        self._raw_headers, self._raw_body = self.fetch_headers_body(request)
        self.headers = self.prepare_headers(request)
        self.body = self._raw_body

        if routes:
            self.routes = routes
            print("[Request] Routing METHOD {} path {}".format(self.method, self.path))
            self.hook = routes.get((self.method, self.path))
            print("[Request] Hook {}".format(self.hook))

        cookie_header = self.headers.get('cookie', '')
        self.cookies = self.prepare_cookies(cookie_header)

        auth_header = self.headers.get('authorization', '')
        self.auth = self.prepare_auth(auth_header, url=self.path)

        return self

    def prepare_body(self, data=None, files=None, json=None):
        """
        Minimal helper to keep scaffold compatible.
        """
        body = b""
        if json is not None:
            if isinstance(json, bytes):
                body = json
            else:
                body = str(json).encode("utf-8")
        elif data is not None:
            if isinstance(data, bytes):
                body = data
            else:
                body = str(data).encode("utf-8")

        self.body = body
        self.prepare_content_length(self.body)
        return self.body

    def prepare_content_length(self, body):
        if body is None:
            length = 0
        elif isinstance(body, bytes):
            length = len(body)
        else:
            length = len(str(body).encode("utf-8"))

        self.headers["Content-Length"] = str(length)
        return length

    def prepare_auth(self, auth, url=""):
        """
        Parse HTTP Authorization header.
        Expected format: Authorization: Basic base64(username:password)
        """
        if not auth:
            self.auth = None
            return None

        if not isinstance(auth, str):
            self.auth = None
            return None

        auth = auth.strip()
        if not auth.lower().startswith("basic "):
            self.auth = None
            return None

        try:
            token = auth.split(" ", 1)[1].strip()
            decoded = base64.b64decode(token).decode("utf-8")
            username, password = decoded.split(":", 1)
            self.auth = {
                "scheme": "Basic",
                "username": username,
                "password": password,
                "url": url,
            }
            return self.auth
        except Exception as e:
            print("[Request] prepare_auth exception: {}".format(e))
            self.auth = None
            return None

    def prepare_cookies(self, cookies):
        """
        Parse Cookie header string into dict.
        If a dict is passed, build Cookie header from it.
        """
        if cookies is None:
            self.cookies = {}
            return self.cookies

        if isinstance(cookies, dict):
            cookie_text = "; ".join(
                ["{}={}".format(k, v) for k, v in cookies.items()]
            )
            self.headers["Cookie"] = cookie_text
            self.cookies = cookies
            return self.cookies

        parsed = {}
        if isinstance(cookies, str) and cookies.strip() != "":
            for pair in cookies.split(";"):
                pair = pair.strip()
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    parsed[k.strip()] = v.strip()

        self.cookies = parsed
        return self.cookies