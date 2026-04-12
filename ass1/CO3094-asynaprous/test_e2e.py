#!/usr/bin/env python3
#
# test_e2e.py
#
# End-to-end test theo spec — 2 tầng:
#   Tầng 1: test DIRECT từng service (không qua proxy)
#   Tầng 2: test QUA PROXY (client → proxy → service)
#
# Port mapping:
#   9000 = backend  (static + auth)
#   2026 = tracker  (sampleapp)
#   2027 = peer 1
#   2028 = peer 2
#   8080 = proxy
#
# Cách chạy:
#   python test_e2e.py
#
# Khởi động trước khi chạy test (xem README_e2e.md)
#

import socket
import json
import sys
import time

# ───────────────────────────────────────────
# Config — đổi IP nếu chạy trên VM khác
# ───────────────────────────────────────────
SERVER_IP    = "127.0.0.1"
PROXY_PORT   = 8080
BACKEND_PORT = 9000
TRACKER_PORT = 2026
PEER1_PORT   = 2027
PEER2_PORT   = 2028
TIMEOUT      = 5

# Host headers khớp với proxy.conf
HOST_BACKEND = "192.168.56.114:8080"
HOST_TRACKER = "tracker.local"
HOST_PEER    = "peer.local"

# ───────────────────────────────────────────
# Màu terminal
# ───────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def _ok(msg):    print("  {}✓  {}{}".format(GREEN,  msg, RESET))
def _fail(msg):  print("  {}✗  {}{}".format(RED,    msg, RESET))
def _info(msg):  print("  {}·  {}{}".format(DIM,    msg, RESET))
def _warn(msg):  print("  {}!  {}{}".format(YELLOW, msg, RESET))
def _head(msg):  print("\n{}{}{}{}".format(BOLD, CYAN, msg, RESET))
def _sub(msg):   print("{}{}{}".format(BOLD, msg, RESET))

results = []  # [(name, passed, note)]

# ───────────────────────────────────────────
# Hàm gửi HTTP request thô
# ───────────────────────────────────────────
def send_http(target_host, target_port, method, path,
              host_header, body="", extra_headers=None):
    """
    Gửi 1 HTTP/1.1 request tới target_host:target_port.
    Trả về (status_code: int, headers: dict, body: str).
    status_code = -1 nếu không kết nối được.
    """
    if extra_headers is None:
        extra_headers = {}

    body_bytes = body.encode() if isinstance(body, str) else body
    headers = {
        "Host": host_header,
        "Connection": "close",
        "Content-Length": str(len(body_bytes)) if body_bytes else "0",
    }
    headers.update(extra_headers)

    header_str = "\r\n".join("{}: {}".format(k, v) for k, v in headers.items())
    raw = "{} {} HTTP/1.1\r\n{}\r\n\r\n".format(method, path, header_str)
    if body_bytes:
        raw = raw.encode() + body_bytes
    else:
        raw = raw.encode()

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        s.connect((target_host, target_port))
        s.sendall(raw)

        resp = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
        s.close()
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        return -1, {}, str(e)

    # Parse response
    try:
        header_part, _, body_part = resp.partition(b"\r\n\r\n")
        lines = header_part.decode(errors="replace").splitlines()
        status_line = lines[0] if lines else ""
        status_code = int(status_line.split()[1]) if len(status_line.split()) >= 2 else 0
        resp_headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, _, v = line.partition(":")
                resp_headers[k.strip().lower()] = v.strip()
        return status_code, resp_headers, body_part.decode(errors="replace")
    except Exception as e:
        return 0, {}, str(e)


def is_json(text):
    """Kiểm tra chuỗi có phải JSON hợp lệ không."""
    try:
        json.loads(text)
        return True
    except Exception:
        return False


def check_port_open(host, port):
    """Trả về True nếu host:port đang lắng nghe."""
    try:
        s = socket.socket()
        s.settimeout(2)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def run(name, passed, note="", detail=""):
    """Ghi kết quả 1 test."""
    if passed:
        _ok(name)
    else:
        _fail("{} — {}".format(name, note))
    if detail:
        _info(detail)
    results.append((name, passed, note))


# ═══════════════════════════════════════════════════════
# KIỂM TRA BOOT — tất cả service có đang chạy không
# ═══════════════════════════════════════════════════════
_head("══ [0] SERVICE BOOT CHECK ══")

services = [
    ("Backend  (static + auth)", BACKEND_PORT),
    ("Tracker  (sampleapp)     ", TRACKER_PORT),
    ("Peer 1                   ", PEER1_PORT),
    ("Peer 2                   ", PEER2_PORT),
    ("Proxy                    ", PROXY_PORT),
]

all_up = True
for name, port in services:
    alive = check_port_open(SERVER_IP, port)
    run("Port {:4d} – {}".format(port, name.strip()), alive,
        note="Chưa khởi động — xem README_e2e.md")
    if not alive:
        all_up = False

if not all_up:
    _warn("Một số service chưa chạy — kết quả test bên dưới sẽ FAIL.")
    _warn("Khởi động đủ 5 process rồi chạy lại test.")


# ═══════════════════════════════════════════════════════
# TẦNG 1 — TEST DIRECT (không qua proxy)
# ═══════════════════════════════════════════════════════
_head("══ TẦNG 1: DIRECT (không qua proxy) ══")


# ───────────────────────────────────────────
# 1A. Backend :9000 — static + auth
# ───────────────────────────────────────────
_sub("\n[1A] Backend :9000 — public routes (static)")

for path in ["/", "/index.html", "/login.html"]:
    code, hdrs, body = send_http(SERVER_IP, BACKEND_PORT, "GET", path, HOST_BACKEND)
    ok = code in (200, 301, 302)
    run("GET {} → {}".format(path, code), ok,
        note="Không phải 2xx/3xx (code={})".format(code))

_sub("\n[1B] Backend :9000 — /login của chat app (public, phải trả JSON)")

code, hdrs, body = send_http(
    SERVER_IP, BACKEND_PORT, "POST", "/login", HOST_BACKEND,
    body=json.dumps({"username": "test", "password": "test"}),
    extra_headers={"Content-Type": "application/json"}
)
run("POST /login → HTTP {}".format(code), code in (200, 401, 403),
    note="code={}, body={}".format(code, body[:80]))
run("POST /login → body là JSON", is_json(body),
    note="Nhận HTML thay vì JSON — /login PHẢI trả JSON",
    detail="body preview: {}".format(body[:120]))


# ───────────────────────────────────────────
# 1C. Tracker :2026 — 7 routes, tất cả trả JSON
# ───────────────────────────────────────────
_sub("\n[1C] Tracker :2026 — 7 API routes (tất cả phải trả JSON)")

TRACKER_ROUTES = [
    ("POST", "/login",          json.dumps({"username": "u1", "password": "p1"})),
    ("POST", "/submit-info",    json.dumps({"ip": "127.0.0.1", "port": 2027})),
    ("GET",  "/get-list",       ""),
    ("POST", "/add-list",       json.dumps({"peer": "127.0.0.1:2027"})),
    ("POST", "/connect-peer",   json.dumps({"peer": "127.0.0.1:2027"})),
    ("POST", "/send-peer",      json.dumps({"to": "127.0.0.1:2027", "msg": "hello"})),
    ("POST", "/broadcast-peer", json.dumps({"msg": "broadcast test"})),
]

# Đăng nhập trước để lấy cookie/token dùng cho protected routes
login_code, login_hdrs, login_body = send_http(
    SERVER_IP, TRACKER_PORT, "POST", "/login", HOST_TRACKER,
    body=json.dumps({"username": "u1", "password": "p1"}),
    extra_headers={"Content-Type": "application/json"}
)
auth_cookie = login_hdrs.get("set-cookie", "")
auth_header = {}
if auth_cookie:
    auth_header = {"Cookie": auth_cookie}
    _info("Lấy được cookie: {}".format(auth_cookie[:60]))

for method, path, body in TRACKER_ROUTES:
    extra = {"Content-Type": "application/json"} if body else {}
    extra.update(auth_header)
    code, hdrs, resp_body = send_http(
        SERVER_IP, TRACKER_PORT, method, path, HOST_TRACKER,
        body=body, extra_headers=extra
    )

    # /send-peer đặc biệt: phải qua auth → trả JSON
    if path == "/send-peer":
        json_ok = is_json(resp_body)
        run("{} {} → JSON (auth flow)".format(method, path), json_ok,
            note="body: {}".format(resp_body[:80]),
            detail="HTTP {} | body: {}".format(code, resp_body[:100]))
    else:
        json_ok = is_json(resp_body) or code in (200, 201)
        run("{} {} → HTTP {}".format(method, path, code), code not in (-1,),
            note="Service không trả lời",
            detail="JSON={} | body: {}".format(is_json(resp_body), resp_body[:80]))


# ───────────────────────────────────────────
# 1D. Tracker state — kiểm tra dữ liệu có lưu không
# ───────────────────────────────────────────
_sub("\n[1D] Tracker state — submit-info rồi get-list phải thấy peer")

# Submit peer info
send_http(SERVER_IP, TRACKER_PORT, "POST", "/submit-info", HOST_TRACKER,
          body=json.dumps({"ip": "127.0.0.1", "port": 9999}),
          extra_headers={"Content-Type": "application/json", **auth_header})

# Get list
code, _, list_body = send_http(
    SERVER_IP, TRACKER_PORT, "GET", "/get-list", HOST_TRACKER,
    extra_headers=auth_header
)

if is_json(list_body):
    try:
        data = json.loads(list_body)
        peers = data if isinstance(data, list) else data.get("peers", data.get("list", []))
        found = any(str(p).find("9999") != -1 for p in peers) if peers else False
        run("Tracker state: submit-info → get-list thấy peer", found,
            note="Peer 9999 không có trong list: {}".format(list_body[:120]),
            detail="Peer list: {}".format(list_body[:200]))
    except Exception:
        run("Tracker state: parse JSON get-list", False,
            note="Không parse được: {}".format(list_body[:80]))
else:
    run("Tracker state: get-list trả JSON", False,
        note="Trả về: {}".format(list_body[:80]))


# ───────────────────────────────────────────
# 1E. Peer instances :2027 / :2028
# ───────────────────────────────────────────
_sub("\n[1E] Peer instances :2027 / :2028 — boot và response")

for peer_port in [PEER1_PORT, PEER2_PORT]:
    code, _, body = send_http(SERVER_IP, peer_port, "GET", "/", "peer.local")
    run("Peer :{} → HTTP {}".format(peer_port, code), code != -1,
        note="Peer :{} không trả lời".format(peer_port))


# ═══════════════════════════════════════════════════════
# TẦNG 2 — TEST QUA PROXY
# ═══════════════════════════════════════════════════════
_head("══ TẦNG 2: QUA PROXY :8080 ══")


# ───────────────────────────────────────────
# 2A. Proxy → Backend :9000
# ───────────────────────────────────────────
_sub("\n[2A] Proxy → Backend :9000 (Host: {})".format(HOST_BACKEND))

for path in ["/", "/index.html", "/login.html"]:
    code, _, body = send_http(SERVER_IP, PROXY_PORT, "GET", path, HOST_BACKEND)
    run("Proxy: GET {} → HTTP {}".format(path, code), code not in (-1, 502),
        note="code={} — proxy không route đến backend".format(code))

# /login qua proxy phải trả JSON
code, _, body = send_http(
    SERVER_IP, PROXY_PORT, "POST", "/login", HOST_BACKEND,
    body=json.dumps({"username": "test", "password": "test"}),
    extra_headers={"Content-Type": "application/json"}
)
run("Proxy: POST /login → JSON".format(code), is_json(body),
    note="Nhận HTML thay vì JSON (code={})".format(code),
    detail="body: {}".format(body[:120]))


# ───────────────────────────────────────────
# 2B. Proxy → Tracker :2026
# ───────────────────────────────────────────
_sub("\n[2B] Proxy → Tracker :2026 (Host: {})".format(HOST_TRACKER))

proxy_routes = [
    ("POST", "/login",          json.dumps({"username": "u1", "password": "p1"})),
    ("POST", "/submit-info",    json.dumps({"ip": "127.0.0.1", "port": 2027})),
    ("GET",  "/get-list",       ""),
    ("POST", "/add-list",       json.dumps({"peer": "127.0.0.1:2027"})),
    ("POST", "/connect-peer",   json.dumps({"peer": "127.0.0.1:2027"})),
    ("POST", "/send-peer",      json.dumps({"to": "127.0.0.1:2027", "msg": "hi"})),
    ("POST", "/broadcast-peer", json.dumps({"msg": "broadcast"})),
]

for method, path, body in proxy_routes:
    extra = {"Content-Type": "application/json"} if body else {}
    extra.update(auth_header)
    code, _, resp_body = send_http(
        SERVER_IP, PROXY_PORT, method, path, HOST_TRACKER,
        body=body, extra_headers=extra
    )
    run("Proxy: {} {} → HTTP {}".format(method, path, code), code not in (-1,),
        note="Proxy không route đến tracker",
        detail="JSON={} | body: {}".format(is_json(resp_body), resp_body[:60]))


# ───────────────────────────────────────────
# 2C. Proxy → Peer round-robin :2027 / :2028
# ───────────────────────────────────────────
_sub("\n[2C] Proxy → Peer round-robin (Host: {})".format(HOST_PEER))

_info("Gửi 4 request qua proxy, phải xoay vòng 2027↔2028")
rr_codes = []
for i in range(4):
    code, _, _ = send_http(SERVER_IP, PROXY_PORT, "GET", "/", HOST_PEER)
    rr_codes.append(code)
    _info("Request {} → HTTP {}".format(i + 1, code))

all_ok = all(c not in (-1,) for c in rr_codes)
run("Proxy round-robin: 4 requests đều được xử lý", all_ok,
    note="Có request bị từ chối — peer 2027/2028 chạy chưa?",
    detail="Codes: {}".format(rr_codes))


# ───────────────────────────────────────────
# 2D. Host không trong proxy.conf — không crash
# ───────────────────────────────────────────
_sub("\n[2D] Unknown host — proxy không được crash")

code, _, body = send_http(SERVER_IP, PROXY_PORT, "GET", "/", "unknown.local")
run("Host không có → proxy vẫn sống (trả {}xx)".format(code // 100 if code > 0 else "?"),
    code not in (-1,),
    note="Proxy crash hoặc không trả lời")


# ───────────────────────────────────────────
# 2E. Full flow: client → proxy → auth → tracker → P2P
# ───────────────────────────────────────────
_sub("\n[2E] Full flow: login → submit-info → get-list → send-peer")

# Step 1: login qua proxy lấy session
f_code, f_hdrs, f_body = send_http(
    SERVER_IP, PROXY_PORT, "POST", "/login", HOST_TRACKER,
    body=json.dumps({"username": "u1", "password": "p1"}),
    extra_headers={"Content-Type": "application/json"}
)
flow_cookie = f_hdrs.get("set-cookie", "")
flow_auth = {"Cookie": flow_cookie} if flow_cookie else {}
run("Flow 1/4: POST /login qua proxy → JSON", is_json(f_body),
    note="body: {}".format(f_body[:80]))

# Step 2: submit-info
f_code, _, f_body = send_http(
    SERVER_IP, PROXY_PORT, "POST", "/submit-info", HOST_TRACKER,
    body=json.dumps({"ip": "127.0.0.1", "port": 2027}),
    extra_headers={"Content-Type": "application/json", **flow_auth}
)
run("Flow 2/4: POST /submit-info → HTTP {}".format(f_code), f_code not in (-1,),
    note="code={}".format(f_code))

# Step 3: get-list
f_code, _, f_body = send_http(
    SERVER_IP, PROXY_PORT, "GET", "/get-list", HOST_TRACKER,
    extra_headers=flow_auth
)
run("Flow 3/4: GET /get-list → JSON".format(f_code), is_json(f_body),
    note="body: {}".format(f_body[:80]))

# Step 4: send-peer qua auth → JSON
f_code, _, f_body = send_http(
    SERVER_IP, PROXY_PORT, "POST", "/send-peer", HOST_TRACKER,
    body=json.dumps({"to": "127.0.0.1:2027", "msg": "test message"}),
    extra_headers={"Content-Type": "application/json", **flow_auth}
)
run("Flow 4/4: POST /send-peer → JSON (auth flow)", is_json(f_body),
    note="/send-peer phải trả JSON, nhận: {}".format(f_body[:80]))


# ═══════════════════════════════════════════════════════
# TỔNG KẾT
# ═══════════════════════════════════════════════════════
_head("══ KẾT QUẢ ══\n")

total  = len(results)
passed = sum(1 for _, p, _ in results if p)
failed = total - passed

print("  Tổng  : {}".format(total))
print("  {}Passed: {}{}".format(GREEN, passed, RESET))
print("  {}Failed: {}{}".format(RED if failed else GREEN, failed, RESET))

if failed:
    print("\n{}Chi tiết FAILED:{}".format(RED, RESET))
    for name, p, note in results:
        if not p:
            print("  ✗ {}  →  {}".format(name, note))

print()
if failed == 0:
    print("{}{}Tất cả tests PASSED ✓{}".format(BOLD, GREEN, RESET))
else:
    pct = int(passed / total * 100)
    print("{}{}% tests passed ({}/{}){}".format(YELLOW, pct, passed, total, RESET))
print()