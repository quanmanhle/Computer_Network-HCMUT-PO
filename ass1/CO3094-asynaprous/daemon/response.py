#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# AsynApRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#

"""
daemon.response
~~~~~~~~~~~~~~~~~

This module provides a :class: `Response <Response>` object to manage and persist
response settings (cookies, auth, proxies), and to construct HTTP responses
based on incoming requests.
"""

import datetime
import json
import os
import mimetypes
from .dictionary import CaseInsensitiveDict

BASE_DIR = ""


class Response():
    __attrs__ = [
        "_content",
        "_header",
        "status_code",
        "method",
        "headers",
        "url",
        "history",
        "encoding",
        "reason",
        "cookies",
        "elapsed",
        "request",
        "body",
        "reason",
    ]

    def __init__(self, request=None):
        self._content = b""
        self._content_consumed = False
        self._next = None

        self.status_code = None
        self.headers = CaseInsensitiveDict()
        self.url = None
        self.encoding = None
        self.history = []
        self.reason = None
        self.cookies = CaseInsensitiveDict()
        self.elapsed = datetime.timedelta(0)
        self.request = request

    def get_mime_type(self, path):
        try:
            mime_type, _ = mimetypes.guess_type(path)
        except Exception:
            return 'application/octet-stream'
        return mime_type or 'application/octet-stream'

    def prepare_content_type(self, mime_type='text/html'):
        base_dir = ""

        if not hasattr(self, "headers") or self.headers is None:
            self.headers = CaseInsensitiveDict()

        main_type, sub_type = mime_type.split('/', 1)
        print("[Response] Processing main_type={} sub_type={}".format(main_type, sub_type))

        if main_type == 'text':
            if sub_type == 'plain':
                self.headers['Content-Type'] = 'text/plain; charset=utf-8'
                base_dir = BASE_DIR + "static/"
            elif sub_type == 'css':
                self.headers['Content-Type'] = 'text/css; charset=utf-8'
                base_dir = BASE_DIR + "static/"
            elif sub_type == 'html':
                self.headers['Content-Type'] = 'text/html; charset=utf-8'
                base_dir = BASE_DIR + "www/"
            elif sub_type == 'javascript':
                self.headers['Content-Type'] = 'text/javascript; charset=utf-8'
                base_dir = BASE_DIR + "static/"
            else:
                self.headers['Content-Type'] = 'text/{}; charset=utf-8'.format(sub_type)
                base_dir = BASE_DIR + "static/"

        elif main_type == 'image':
            base_dir = BASE_DIR + "static/"
            self.headers['Content-Type'] = 'image/{}'.format(sub_type)

        elif main_type == 'application':
            if sub_type == 'json':
                base_dir = BASE_DIR + "apps/"
                self.headers['Content-Type'] = 'application/json; charset=utf-8'
            elif sub_type == 'xml':
                base_dir = BASE_DIR + "static/"
                self.headers['Content-Type'] = 'application/xml; charset=utf-8'
            elif sub_type == 'zip':
                base_dir = BASE_DIR + "static/"
                self.headers['Content-Type'] = 'application/zip'
            elif sub_type == 'octet-stream':
                base_dir = BASE_DIR + "static/"
                self.headers['Content-Type'] = 'application/octet-stream'
            else:
                base_dir = BASE_DIR + "static/"
                self.headers['Content-Type'] = 'application/{}'.format(sub_type)
        else:
            self.headers['Content-Type'] = 'application/octet-stream'
            base_dir = BASE_DIR + "static/"

        return base_dir

    def build_content(self, path, base_dir):
        filepath = os.path.join(base_dir, path.lstrip('/'))
        print("[Response] Serving the object at location {}".format(filepath))

        try:
            with open(filepath, "rb") as f:
                content = f.read()
        except Exception as e:
            print("[Response] build_content exception: {}".format(e))
            return -1, b""

        return len(content), content

    def _status_text(self, code):
        mapping = {
            200: "OK",
            201: "Created",
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            500: "Internal Server Error",
        }
        return mapping.get(code, "OK")

    def build_response_header(self, request):
        reqhdr = request.headers if request and getattr(request, "headers", None) else CaseInsensitiveDict()
        rsphdr = CaseInsensitiveDict()
        rsphdr.update(self.headers or {})

        if "content-type" not in rsphdr:
            rsphdr["Content-Type"] = "text/plain; charset=utf-8"

        if "content-length" not in rsphdr:
            rsphdr["Content-Length"] = str(len(self._content or b""))

        if "date" not in rsphdr:
            rsphdr["Date"] = datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")

        if "connection" not in rsphdr:
            rsphdr["Connection"] = "close"

        # optional passthrough if browser sent Host
        if "server" not in rsphdr:
            rsphdr["Server"] = "AsynapRous/1.0"

        status_code = self.status_code or 200
        reason = self.reason or self._status_text(status_code)

        lines = ["HTTP/1.1 {} {}".format(status_code, reason)]

        for k, v in rsphdr.items():
            header_name = "-".join([part.capitalize() for part in k.split("-")])
            lines.append("{}: {}".format(header_name, v))

        lines.append("")
        lines.append("")

        fmt_header = "\r\n".join(lines)
        return fmt_header.encode('utf-8')

    def build_notfound(self):
        self.status_code = 404
        self.reason = "Not Found"
        self._content = b"404 Not Found"
        self.headers = CaseInsensitiveDict({
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Length": str(len(self._content)),
            "Cache-Control": "no-cache",
            "Connection": "close",
        })
        dummy_req = type("DummyReq", (), {"headers": CaseInsensitiveDict()})()
        self._header = self.build_response_header(dummy_req)
        return self._header + self._content

    def build_unauthorized(self, realm="CO3094 Chat"):
        self.status_code = 401
        self.reason = "Unauthorized"
        self._content = b"401 Unauthorized"
        self.headers = CaseInsensitiveDict({
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Length": str(len(self._content)),
            "WWW-Authenticate": 'Basic realm="{}"'.format(realm),
            "Cache-Control": "no-cache",
            "Connection": "close",
        })
        dummy_req = type("DummyReq", (), {"headers": CaseInsensitiveDict()})()
        self._header = self.build_response_header(dummy_req)
        return self._header + self._content

    def build_server_error(self, message="Internal Server Error"):
        body = "500 Internal Server Error\n{}".format(message)
        self.status_code = 500
        self.reason = "Internal Server Error"
        self._content = body.encode("utf-8")
        self.headers = CaseInsensitiveDict({
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Length": str(len(self._content)),
            "Cache-Control": "no-cache",
            "Connection": "close",
        })
        dummy_req = type("DummyReq", (), {"headers": CaseInsensitiveDict()})()
        self._header = self.build_response_header(dummy_req)
        return self._header + self._content

    def build_response(self, request, envelop_content=None, set_cookie=None, content_type=None):
        print("[Response] Start build response with req {}".format(request))

        self.headers = CaseInsensitiveDict()
        self.status_code = 200
        self.reason = "OK"

        if envelop_content is not None:
            if isinstance(envelop_content, bytes):
                self._content = envelop_content
            elif isinstance(envelop_content, str):
                self._content = envelop_content.encode("utf-8")
            elif isinstance(envelop_content, (dict, list)):
                self._content = json.dumps(envelop_content).encode("utf-8")
            else:
                self._content = str(envelop_content).encode("utf-8")

            self.headers["Content-Type"] = content_type or "application/json; charset=utf-8"

            if set_cookie:
                self.headers["Set-Cookie"] = (
                    "session_id={}; Path=/; HttpOnly; Max-Age=3600; SameSite=Lax"
                ).format(set_cookie)

            self.headers["Content-Length"] = str(len(self._content))
            self._header = self.build_response_header(request)
            return self._header + self._content

        path = request.path
        mime_type = self.get_mime_type(path)
        print("[Response] {} path {} mime_type {}".format(request.method, request.path, mime_type))

        if path.endswith('.html') or mime_type == 'text/html':
            base_dir = self.prepare_content_type(mime_type='text/html')
        elif mime_type == 'text/css':
            base_dir = self.prepare_content_type(mime_type='text/css')
        elif mime_type == 'text/javascript':
            base_dir = self.prepare_content_type(mime_type='text/javascript')
        elif mime_type.startswith('image/'):
            base_dir = self.prepare_content_type(mime_type=mime_type)
        elif mime_type == 'application/json' or mime_type == 'application/octet-stream':
            base_dir = self.prepare_content_type(mime_type='application/json')
        else:
            return self.build_notfound()

        content_length, content = self.build_content(path, base_dir)
        if content_length < 0:
            return self.build_notfound()

        self._content = content
        self.headers["Content-Length"] = str(content_length)

        if set_cookie:
            self.headers["Set-Cookie"] = (
                "session_id={}; Path=/; HttpOnly; Max-Age=3600; SameSite=Lax"
            ).format(set_cookie)

        self._header = self.build_response_header(request)
        return self._header + self._content