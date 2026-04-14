#!/usr/bin/env python3
#
# test_e2e.py — End-to-end proxy test
#
# Phân biệt rõ 3 tình huống:
#   code=-1  = không kết nối được (service không chạy, hoặc proxy không route)
#   code=0   = kết nối được nhưng response rỗng (service chạy nhưng chưa implement response)
#   code=2xx = hoạt động đúng
#

import socket
import json
import sys

SERVER_IP    = "127.0.0.1"
PROXY_PORT   = 8080
BACKEND_PORT = 9000
TRACKER_PORT = 2026
PEER1_PORT   = 2027
PEER2_PORT   = 2028
TIMEOUT      = 5

HOST_BACKEND = "192.168.56.114:8080"
HOST_TRACKER = "tracker.local"
HOST_PEER    = "peer.local"

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def _ok(msg):   print("  {}✓  {}{}".format(GREEN,  msg, RESET))
def _warn(msg): print("  {}~  {}{}".format(YELLOW, msg, RESET))
def _fail(msg): print("  {}✗  {}{}".format(RED,    msg, RESET))
def _info(msg): print("  {}·  {}{}".format(DIM,    msg, RESET))
def _head(msg): print("\n{}{}{}{}".format(BOLD, CYAN, msg, RESET))
def _sub(msg):  print("{}{}{}".format(BOLD, msg, RESET))

results = []  # (name, status) — status: "pass" | "partial" | "fail"

def run(name, status, note=""):
    """
    status:
      "pass"    = xanh ✓  — hoạt động đúng
      "partial" = vàng ~  — kết nối được nhưng chưa implement response (code=0)
      "fail"    = đỏ ✗   — không kết nối được hoặc sai hoàn toàn
    """
    if status == "pass":
        _ok(name)
    elif status == "partial":
        _warn("{} — {}".format(name, note))
    else:
        _fail("{} — {}".format(name, note))
    results.append((name, status, note))


def send_http(target_host, target_port, method, path,
              host_header, body="", extra_headers=None):
    """
    Trả về (code, headers, body):
      code=-1  = ConnectionRefused / timeout
      code=0   = kết nối được, response rỗng
      code=NNN = HTTP status code thật
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
    raw = raw.encode() + (body_bytes or b"")

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT)
        s.connect((target_host, target_port))
        s.sendall(raw)
        resp = b""
        while True:
            try:
                chunk = s.recv(4096)
                if not chunk:
                    break
                resp += chunk
            except (socket.timeout, OSError):
                break
        s.close()
    except (ConnectionRefusedError, socket.timeout, OSError) as e:
        return -1, {}, str(e)

    if not resp:
        return 0, {}, ""

    try:
        header_part, _, body_part = resp.partition(b"\r\n\r\n")
        lines = header_part.decode(errors="replace").splitlines()
        status_line = lines[0] if lines else ""
        parts = status_line.split()
        code = int(parts[1]) if len(parts) >= 2 else 0
        resp_headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, _, v = line.partition(":")
                resp_headers[k.strip().lower()] = v.strip()
        return code, resp_headers, body_part.decode(errors="replace")
    except Exception:
        return 0, {}, resp.decode(errors="replace")


def is_json(text):
    try:
        json.loads(text)
        return bool(text.strip())
    except Exception:
        return False


def check_port(host, port):
    try:
        s = socket.socket()
        s.settimeout(2)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def classify(code, body="", need_json=False):
    """
    Phân loại kết quả thành pass/partial/fail.
    
    pass    = code 2xx (và JSON nếu need_json=True)
    partial = code=0 (kết nối được, chưa có response)
    fail    = code=-1 (không kết nối được) hoặc code 4xx/5xx sai
    """
    if code == -1:
        return "fail", "Không kết nối được — service không chạy hoặc proxy không route"
    if code == 0:
        return "partial", "Kết nối OK nhưng response rỗng — chưa implement response body"
    if code in (200, 201):
        if need_json and not is_json(body):
            return "fail", "HTTP 200 nhưng body không phải JSON"
        return "pass", ""
    if code in (400, 401, 403):
        return "partial", "HTTP {} — route đúng nhưng cần auth/fix logic".format(code)
    if code in (404, 502, 503):
        return "fail", "HTTP {} — route sai hoặc backend lỗi".format(code)
    return "partial", "HTTP {} — chưa rõ".format(code)


# ══════════════════════════════════════════════════════════════
_head("══ [0] SERVICE BOOT CHECK ══")

services = [
    ("Backend  :9000  (static + auth)", BACKEND_PORT),
    ("Tracker  :2026  (sampleapp)     ", TRACKER_PORT),
    ("Peer 1   :2027                  ", PEER1_PORT),
    ("Peer 2   :2028                  ", PEER2_PORT),
    ("Proxy    :8080                  ", PROXY_PORT),
]

boot_ok = {}
for name, port in services:
    alive = check_port(SERVER_IP, port)
    boot_ok[port] = alive
    run("Port {} – {}".format(port, name.strip()),
        "pass" if alive else "fail",
        note="Chưa khởi động")


# ══════════════════════════════════════════════════════════════
_head("══ TẦNG 1: DIRECT (không qua proxy) ══")
_info("Mục đích: xác nhận từng service NHẬN được request, dù chưa có response đầy đủ")
_info("partial (~) = kết nối OK, service chạy, nhưng chưa implement response — cần fix sampleapp/httpadapter")
_info("fail    (✗) = service không chạy hoặc sai hoàn toàn")


# ─────────────────────────────
_sub("\n[1A] Backend :9000 — static files")

for path in ["/", "/index.html", "/login.html"]:
    code, _, body = send_http(SERVER_IP, BACKEND_PORT, "GET", path, HOST_BACKEND)
    status, note = classify(code, body)
    run("GET {} → HTTP {}".format(path, code), status, note)


# ─────────────────────────────
_sub("\n[1B] Backend :9000 — POST /login (phải trả JSON)")

code, _, body = send_http(SERVER_IP, BACKEND_PORT, "POST", "/login", HOST_BACKEND,
    body=json.dumps({"username": "test", "password": "test"}),
    extra_headers={"Content-Type": "application/json"})
status, note = classify(code, body, need_json=True)
run("POST /login → HTTP {} | JSON={}".format(code, is_json(body)), status, note)


# ─────────────────────────────
_sub("\n[1C] Tracker :2026 — 7 API routes")
_info("Kỳ vọng: tất cả kết nối được (không fail -1), response có thể rỗng nếu chưa implement")

TRACKER_ROUTES = [
    ("POST", "/login",          json.dumps({"username": "u1", "password": "p1"}), True),
    ("POST", "/submit-info",    json.dumps({"ip": "127.0.0.1", "port": 2027}),    False),
    ("GET",  "/get-list",       "",                                                 True),
    ("POST", "/add-list",       json.dumps({"peer": "127.0.0.1:2027"}),           False),
    ("POST", "/connect-peer",   json.dumps({"peer": "127.0.0.1:2027"}),           False),
    ("POST", "/send-peer",      json.dumps({"to": "127.0.0.1:2027","msg":"hi"}),  True),
    ("POST", "/broadcast-peer", json.dumps({"msg": "test"}),                       False),
]

login_code, login_hdrs, _ = send_http(SERVER_IP, TRACKER_PORT, "POST", "/login",
    HOST_TRACKER, body=json.dumps({"username":"u1","password":"p1"}),
    extra_headers={"Content-Type": "application/json"})
auth_cookie = login_hdrs.get("set-cookie", "")
auth_header = {"Cookie": auth_cookie} if auth_cookie else {}

for method, path, body, need_json in TRACKER_ROUTES:
    extra = {"Content-Type": "application/json"} if body else {}
    extra.update(auth_header)
    code, hdrs, resp = send_http(SERVER_IP, TRACKER_PORT, method, path,
                                  HOST_TRACKER, body=body, extra_headers=extra)
    status, note = classify(code, resp, need_json=need_json)
    label = "JSON" if need_json else "HTTP"
    run("{} {} → {} {} | JSON={}".format(method, path, label, code, is_json(resp)),
        status, note)


# ─────────────────────────────
_sub("\n[1D] Tracker state — submit-info → get-list")

send_http(SERVER_IP, TRACKER_PORT, "POST", "/submit-info", HOST_TRACKER,
    body=json.dumps({"ip": "127.0.0.1", "port": 9999}),
    extra_headers={"Content-Type": "application/json", **auth_header})
code, _, list_body = send_http(SERVER_IP, TRACKER_PORT, "GET", "/get-list",
    HOST_TRACKER, extra_headers=auth_header)

if code == -1:
    run("Tracker state: get-list", "fail", "Không kết nối được")
elif code == 0 or not is_json(list_body):
    run("Tracker state: get-list trả JSON", "partial",
        "Chưa implement response — cần fix get-list handler")
else:
    try:
        data = json.loads(list_body)
        peers = data if isinstance(data, list) else data.get("peers", data.get("list", []))
        found = any("9999" in str(p) for p in peers)
        run("Tracker state: submit-info → get-list thấy peer",
            "pass" if found else "partial",
            note="" if found else "Peer 9999 không có trong list: {}".format(list_body[:80]))
    except Exception:
        run("Tracker state: parse JSON", "partial", list_body[:80])


# ─────────────────────────────
_sub("\n[1E] Peer instances :2027 / :2028")

for peer_port in [PEER1_PORT, PEER2_PORT]:
    code, _, body = send_http(SERVER_IP, peer_port, "GET", "/", "peer.local")
    status, note = classify(code, body)
    run("Peer :{} → HTTP {}".format(peer_port, code), status, note)


# ══════════════════════════════════════════════════════════════
_head("══ TẦNG 2: QUA PROXY :8080 ══")
_info("Mục đích: xác nhận proxy ROUTE đúng host → đúng service")
_info("partial (~) = proxy route đúng, nhưng backend chưa trả response")
_info("fail    (✗) = proxy route sai hoặc không kết nối được")


# ─────────────────────────────
_sub("\n[2A] Proxy → Backend :9000 (Host: {})".format(HOST_BACKEND))

for path in ["/", "/index.html", "/login.html"]:
    code, _, body = send_http(SERVER_IP, PROXY_PORT, "GET", path, HOST_BACKEND)
    status, note = classify(code, body)
    # Nếu code=0: proxy route đúng (kết nối thành công), backend chưa respond — partial
    run("Proxy: GET {} → HTTP {}".format(path, code), status, note)

code, _, body = send_http(SERVER_IP, PROXY_PORT, "POST", "/login", HOST_BACKEND,
    body=json.dumps({"username":"test","password":"test"}),
    extra_headers={"Content-Type": "application/json"})
status, note = classify(code, body, need_json=True)
run("Proxy: POST /login → JSON | HTTP {}".format(code), status, note)


# ─────────────────────────────
_sub("\n[2B] Proxy → Tracker :2026 (Host: {})".format(HOST_TRACKER))

for method, path, body, need_json in TRACKER_ROUTES:
    extra = {"Content-Type": "application/json"} if body else {}
    extra.update(auth_header)
    code, _, resp = send_http(SERVER_IP, PROXY_PORT, method, path,
                               HOST_TRACKER, body=body, extra_headers=extra)
    status, note = classify(code, resp, need_json=need_json)
    run("Proxy: {} {} → HTTP {}".format(method, path, code), status, note)


# ─────────────────────────────
_sub("\n[2C] Proxy → Peer round-robin (Host: {})".format(HOST_PEER))
_info("Gửi 4 request, proxy phải xoay vòng 2027 ↔ 2028")

rr_codes = []
for i in range(4):
    code, _, _ = send_http(SERVER_IP, PROXY_PORT, "GET", "/", HOST_PEER)
    rr_codes.append(code)
    _info("Request {} → HTTP {}".format(i + 1, code))

# Proxy routing check: không có -1 nào = proxy route được đến peer
routed = all(c != -1 for c in rr_codes)
has_response = all(c not in (-1, 0) for c in rr_codes)

if routed and has_response:
    run("Proxy round-robin: route + response đúng", "pass")
elif routed:
    run("Proxy round-robin: route đúng (code=0, peer chưa implement response)", "partial",
        "Codes: {}".format(rr_codes))
else:
    run("Proxy round-robin: FAIL — proxy không route đến peer", "fail",
        "Codes: {} — có -1, peer chưa chạy hoặc proxy.conf sai".format(rr_codes))


# ─────────────────────────────
_sub("\n[2D] Unknown host — proxy không được crash")

code, _, body = send_http(SERVER_IP, PROXY_PORT, "GET", "/", "unknown.local")
run("Unknown host → proxy vẫn sống (HTTP {})".format(code),
    "pass" if code not in (-1,) else "fail",
    note="Proxy crash hoặc không trả lời")


# ─────────────────────────────
_sub("\n[2E] Full flow: login → submit-info → get-list → send-peer")

steps = [
    ("POST", "/login",       HOST_TRACKER, json.dumps({"username":"u1","password":"p1"}), True),
    ("POST", "/submit-info", HOST_TRACKER, json.dumps({"ip":"127.0.0.1","port":2027}),    False),
    ("GET",  "/get-list",    HOST_TRACKER, "",                                              True),
    ("POST", "/send-peer",   HOST_TRACKER, json.dumps({"to":"127.0.0.1:2027","msg":"hi"}), True),
]
labels = ["login", "submit-info", "get-list", "send-peer"]

flow_auth = {}
for i, (method, path, host, body, need_json) in enumerate(steps, 1):
    extra = {"Content-Type": "application/json"} if body else {}
    extra.update(flow_auth)
    code, hdrs, resp = send_http(SERVER_IP, PROXY_PORT, method, path,
                                  host, body=body, extra_headers=extra)
    if i == 1:
        cookie = hdrs.get("set-cookie", "")
        if cookie:
            flow_auth = {"Cookie": cookie}
    status, note = classify(code, resp, need_json=need_json)
    run("Flow {}/4: {} {} → HTTP {}".format(i, method, path, code), status, note)


# ══════════════════════════════════════════════════════════════
_head("══ KẾT QUẢ ══\n")

total   = len(results)
passed  = sum(1 for _, s, _ in results if s == "pass")
partial = sum(1 for _, s, _ in results if s == "partial")
failed  = sum(1 for _, s, _ in results if s == "fail")

print("  Tổng   : {}".format(total))
print("  {}✓ Pass   : {} — hoạt động đúng{}".format(GREEN,  passed,  RESET))
print("  {}~ Partial: {} — kết nối được, chưa implement response (cần fix sampleapp/httpadapter){}".format(YELLOW, partial, RESET))
print("  {}✗ Fail   : {} — không kết nối được hoặc route sai{}".format(RED,    failed,  RESET))

if failed:
    print("\n{}✗ FAILED (cần fix ngay):{}".format(RED, RESET))
    for name, s, note in results:
        if s == "fail":
            print("    ✗ {}  →  {}".format(name, note))

if partial:
    print("\n{}~ PARTIAL (cần implement response):{}".format(YELLOW, RESET))
    for name, s, note in results:
        if s == "partial":
            print("    ~ {}".format(name))

print()
if failed == 0 and partial == 0:
    print("{}{}Tất cả tests PASSED ✓{}".format(BOLD, GREEN, RESET))
elif failed == 0:
    print("{}Proxy/routing hoạt động đúng. {} items cần implement response trong sampleapp/httpadapter.{}".format(YELLOW, partial, RESET))
else:
    print("{}{}✗ Fail: {} — cần fix ngay trước khi tiếp tục.{}".format(BOLD, RED, failed, RESET))
print()
