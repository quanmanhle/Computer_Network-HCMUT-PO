#!/usr/bin/env python3
#
# test_e2e_channel.py
# End-to-end test for CO3094 AsynapRous hybrid chat app.
#
# Expected services before running:
#   python start_backend.py --server-ip 127.0.0.1 --server-port 9000
#   python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
#   python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2027
#   python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2028
#   python start_proxy.py --server-ip 127.0.0.1 --server-port 8080
#
# What this test checks:
#   1. Services are listening.
#   2. Proxy can serve chat.html.
#   3. Tracker can register peers and return peer/channel state.
#   4. Direct P2P message 2027 -> 2028 works.
#   5. Channel broadcast from 2027 to 2028 works.
#

import json
import socket
import time

SERVER_IP = "127.0.0.1"
PROXY_PORT = 8080
BACKEND_PORT = 9000
TRACKER_PORT = 2026
PEER1_PORT = 2027
PEER2_PORT = 2028
TIMEOUT = 5

HOST_BACKEND = "127.0.0.1:8080"
HOST_TRACKER = "tracker.local:8080"
HOST_PEER = "peer.local:8080"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

results = []


def _ok(msg):
    print("  {}OK {}{}".format(GREEN, msg, RESET))


def _warn(msg):
    print("  {}WARN {}{}".format(YELLOW, msg, RESET))


def _fail(msg):
    print("  {}FAIL {}{}".format(RED, msg, RESET))


def _info(msg):
    print("  {}- {}{}".format(DIM, msg, RESET))


def _head(msg):
    print("\n{}{}{}{}".format(BOLD, CYAN, msg, RESET))


def _sub(msg):
    print("{}{}{}".format(BOLD, msg, RESET))


def run(name, status, note=""):
    if status == "pass":
        _ok(name)
    elif status == "partial":
        _warn("{} -- {}".format(name, note))
    else:
        _fail("{} -- {}".format(name, note))
    results.append((name, status, note))


def check_port(host, port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def send_http(target_host, target_port, method, path, host_header, body=b"", extra_headers=None):
    """Return (code, headers_dict_lower, response_body_text)."""
    if extra_headers is None:
        extra_headers = {}

    if isinstance(body, str):
        body_bytes = body.encode("utf-8")
    elif body is None:
        body_bytes = b""
    else:
        body_bytes = body

    headers = {
        "Host": host_header,
        "Connection": "close",
        "Content-Length": str(len(body_bytes)),
    }
    headers.update(extra_headers)

    header_str = "\r\n".join("{}: {}".format(k, v) for k, v in headers.items())
    raw = "{} {} HTTP/1.1\r\n{}\r\n\r\n".format(method, path, header_str).encode("utf-8") + body_bytes

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
            except socket.timeout:
                break
        s.close()
    except Exception as exc:
        return -1, {}, str(exc)

    if not resp:
        return 0, {}, ""

    header_part, _, body_part = resp.partition(b"\r\n\r\n")
    lines = header_part.decode("iso-8859-1", errors="replace").splitlines()
    status_line = lines[0] if lines else ""
    parts = status_line.split()
    try:
        code = int(parts[1]) if len(parts) >= 2 else 0
    except Exception:
        code = 0

    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()

    return code, headers, body_part.decode("utf-8", errors="replace")


def send_json(port, path, payload=None, method="POST", host_header="127.0.0.1"):
    if payload is None:
        body = b""
    else:
        body = json.dumps(payload).encode("utf-8")
    code, headers, text = send_http(
        SERVER_IP,
        port,
        method,
        path,
        host_header,
        body=body,
        extra_headers={"Content-Type": "application/json"} if body else {},
    )
    data = None
    try:
        data = json.loads(text) if text.strip() else None
    except Exception:
        data = None
    return code, headers, text, data


def expect_json_ok(label, code, data, status_value="success"):
    if code in (200, 201) and isinstance(data, dict) and data.get("status") == status_value:
        run(label, "pass")
        return True
    run(label, "fail", "HTTP {} body={}".format(code, data))
    return False


def get_last_id(port):
    code, _, _, data = send_json(port, "/send-peer", {"action": "pull", "after_id": 0})
    if code in (200, 201) and isinstance(data, dict):
        return int(data.get("last_id", 0) or 0)
    return 0


def pull_messages(port, after_id):
    code, _, text, data = send_json(port, "/send-peer", {"action": "pull", "after_id": after_id})
    if not isinstance(data, dict):
        return code, [], text, data
    messages = data.get("messages") or data.get("new_messages") or []
    return code, messages, text, data


def contains_message(messages, text, sender=None, channel=None):
    for msg in messages:
        msg_text = str(msg.get("message") or msg.get("msg") or msg.get("text") or "")
        msg_sender = str(msg.get("sender") or msg.get("from") or "")
        msg_channel = str(msg.get("channel") or "")
        if text not in msg_text:
            continue
        if sender is not None and msg_sender != sender:
            continue
        if channel is not None and msg_channel != channel:
            continue
        return True
    return False


_head("== [0] SERVICE BOOT CHECK ==")
services = [
    ("Backend static/auth", BACKEND_PORT),
    ("Tracker sampleapp", TRACKER_PORT),
    ("Peer 1 sampleapp", PEER1_PORT),
    ("Peer 2 sampleapp", PEER2_PORT),
    ("Proxy", PROXY_PORT),
]
for name, port in services:
    alive = check_port(SERVER_IP, port)
    run("Port {} - {}".format(port, name), "pass" if alive else "fail", "not running")


_head("== [1] PROXY + WEB PAGE ==")
code, _, body = send_http(SERVER_IP, PROXY_PORT, "GET", "/chat.html", HOST_BACKEND)
if code == 200 and ("P2P" in body or "Chat" in body or "Dashboard" in body):
    run("Proxy serves /chat.html through backend", "pass")
elif code == 502:
    run("Proxy serves /chat.html through backend", "fail", "502: backend 9000 is not running or proxy.conf points elsewhere")
else:
    run("Proxy serves /chat.html through backend", "partial", "HTTP {} len={}".format(code, len(body)))


_head("== [2] TRACKER REGISTRATION + CHANNEL STATE ==")
user1 = "e2e_viet_{}".format(int(time.time()) % 100000)
user2 = "e2e_viet2_{}".format(int(time.time()) % 100000)
channel = "e2e_lab_{}".format(int(time.time()) % 100000)

expect_json_ok("Tracker login user1", *send_json(TRACKER_PORT, "/login", {"username": user1})[0:4:3])

code, _, _, data = send_json(TRACKER_PORT, "/submit-info", {"username": user1, "ip": SERVER_IP, "port": PEER1_PORT})
expect_json_ok("Tracker register peer1 {}:{}".format(SERVER_IP, PEER1_PORT), code, data)

code, _, _, data = send_json(TRACKER_PORT, "/submit-info", {"username": user2, "ip": SERVER_IP, "port": PEER2_PORT})
expect_json_ok("Tracker register peer2 {}:{}".format(SERVER_IP, PEER2_PORT), code, data)

code, _, _, data = send_json(TRACKER_PORT, "/add-list", {"username": user1, "ip": SERVER_IP, "port": PEER1_PORT, "channel_name": channel})
expect_json_ok("Tracker add peer1 to channel {}".format(channel), code, data)

code, _, _, data = send_json(TRACKER_PORT, "/add-list", {"username": user2, "ip": SERVER_IP, "port": PEER2_PORT, "channel_name": channel})
expect_json_ok("Tracker add peer2 to channel {}".format(channel), code, data)

code, _, _, data = send_json(TRACKER_PORT, "/get-list", None, method="GET", host_header=HOST_TRACKER)
if code == 200 and isinstance(data, dict) and user1 in str(data) and user2 in str(data):
    run("Tracker get-list contains both peers", "pass")
else:
    run("Tracker get-list contains both peers", "fail", "HTTP {} body={}".format(code, data))

if isinstance(data, dict) and "channels" in data and channel in str(data.get("channels")):
    run("Tracker get-list exposes channel membership", "pass")
elif isinstance(data, dict) and "channels" not in data:
    run("Tracker get-list exposes channel membership", "partial", "your sampleapp may not return channels in get-list")
else:
    run("Tracker get-list exposes channel membership", "fail", "channel not found in response")


_head("== [3] DIRECT P2P MESSAGE 2027 -> 2028 ==")
last_2028 = get_last_id(PEER2_PORT)
private_text = "hello_private_{}".format(int(time.time()))
code, _, _, data = send_json(
    PEER1_PORT,
    "/send-peer",
    {
        "sender": user1,
        "from": user1,
        "target": user2,
        "recipient": user2,
        "to": "{}:{}".format(SERVER_IP, PEER2_PORT),
        "channel": "private:{}:{}".format(user1, user2),
        "message": private_text,
        "msg": private_text,
    },
)
if code == 200 and isinstance(data, dict) and data.get("status") == "success":
    run("Peer1 sends private message to peer2", "pass")
else:
    run("Peer1 sends private message to peer2", "fail", "HTTP {} body={}".format(code, data))

time.sleep(0.2)
code, messages, text, data = pull_messages(PEER2_PORT, last_2028)
if code == 200 and contains_message(messages, private_text, sender=user1):
    run("Peer2 inbox receives private message", "pass")
else:
    run("Peer2 inbox receives private message", "fail", "HTTP {} messages={} body={}".format(code, messages, text[:200]))


_head("== [4] CHANNEL BROADCAST 2027 -> 2028 ==")
last_2028 = get_last_id(PEER2_PORT)
broadcast_text = "hello_channel_{}".format(int(time.time()))
code, _, _, data = send_json(
    PEER1_PORT,
    "/broadcast-peer",
    {
        "sender": user1,
        "from": user1,
        "to": "{}:{}".format(SERVER_IP, PEER2_PORT),
        "channel": channel,
        "message": broadcast_text,
        "msg": broadcast_text,
    },
)
if code == 200 and isinstance(data, dict) and data.get("status") == "success":
    run("Peer1 sends broadcast to channel {} via peer2 target".format(channel), "pass")
else:
    run("Peer1 sends broadcast to channel {} via peer2 target".format(channel), "fail", "HTTP {} body={}".format(code, data))

time.sleep(0.2)
code, messages, text, data = pull_messages(PEER2_PORT, last_2028)
if code == 200 and contains_message(messages, broadcast_text, sender=user1, channel=channel):
    run("Peer2 receives channel broadcast in channel {}".format(channel), "pass")
else:
    run("Peer2 receives channel broadcast in channel {}".format(channel), "fail", "HTTP {} messages={} body={}".format(code, messages, text[:200]))


_head("== [5] PROXY ROUTING SMOKE TEST ==")
code, _, body = send_http(SERVER_IP, PROXY_PORT, "GET", "/get-list", HOST_TRACKER)
if code == 200 and "peers" in body:
    run("Proxy routes tracker.local/get-list to tracker", "pass")
else:
    run("Proxy routes tracker.local/get-list to tracker", "partial", "HTTP {} body={}".format(code, body[:120]))

rr_codes = []
for i in range(4):
    c, _, _ = send_http(SERVER_IP, PROXY_PORT, "POST", "/send-peer", HOST_PEER, json.dumps({"action": "pull", "after_id": 0}), {"Content-Type": "application/json"})
    rr_codes.append(c)
if all(c == 200 for c in rr_codes):
    run("Proxy routes peer.local round-robin to peer daemons", "pass")
elif all(c != -1 for c in rr_codes):
    run("Proxy routes peer.local round-robin to peer daemons", "partial", "codes={}".format(rr_codes))
else:
    run("Proxy routes peer.local round-robin to peer daemons", "fail", "codes={}".format(rr_codes))


_head("== SUMMARY ==")
total = len(results)
passed = sum(1 for _, s, _ in results if s == "pass")
partial = sum(1 for _, s, _ in results if s == "partial")
failed = sum(1 for _, s, _ in results if s == "fail")
print("  Total   : {}".format(total))
print("  {}Pass    : {}{}".format(GREEN, passed, RESET))
print("  {}Partial : {}{}".format(YELLOW, partial, RESET))
print("  {}Fail    : {}{}".format(RED, failed, RESET))

if failed:
    print("\n{}Failed checks:{}".format(RED, RESET))
    for name, status, note in results:
        if status == "fail":
            print("  - {} -> {}".format(name, note))

if partial:
    print("\n{}Partial checks:{}".format(YELLOW, RESET))
    for name, status, note in results:
        if status == "partial":
            print("  - {} -> {}".format(name, note))

if failed == 0 and partial == 0:
    print("\n{}{}ALL TESTS PASSED{}".format(BOLD, GREEN, RESET))
elif failed == 0:
    print("\n{}No hard failures, but some checks need review.{}".format(YELLOW, RESET))
else:
    print("\n{}{}Some tests failed. Fix these before demo.{}".format(BOLD, RED, RESET))
