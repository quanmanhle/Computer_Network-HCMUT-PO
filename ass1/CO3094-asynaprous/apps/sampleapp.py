#
# Copyright (C) 2026 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#

"""
apps.sampleapp
~~~~~~~~~~~~~~~~~

Tracker + peer REST API for the hybrid P2P chat assignment.

This version keeps the working P2P flow and adds channel-aware broadcast:
- Tracker keeps peer metadata and channel memberships.
- Peers send direct/private messages and broadcast messages through their own
  local Python daemon; that daemon forwards by TCP socket to the target peer.
- Browser JavaScript does not send peer-to-peer traffic directly to remote peers.
"""

import json
import socket
import time

from daemon import AsynapRous

app = AsynapRous()

TRACKER_PEERS = {}
CHANNELS = {
    "general": {
        "members": {},
        "messages": [],
    }
}
LOCAL_INBOX = []
PEER_CONNECTIONS = {}
INBOX_SEQ = 0
CURRENT_IP = "127.0.0.1"
CURRENT_PORT = 0


def now_ts():
    return int(time.time())


def next_inbox_id():
    global INBOX_SEQ
    INBOX_SEQ += 1
    return INBOX_SEQ


def json_response(payload, status_code=200):
    body = json.dumps(payload).encode("utf-8")
    reason = "OK" if status_code == 200 else "Error"
    headers = (
        "HTTP/1.1 {} {}\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: {}\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "Access-Control-Allow-Methods: POST, GET, OPTIONS\r\n"
        "Access-Control-Allow-Headers: Content-Type, Authorization\r\n"
        "Access-Control-Allow-Private-Network: true\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).format(status_code, reason, len(body))
    return headers.encode("utf-8") + body


def parse_body(body):
    if isinstance(body, dict):
        return body
    if not body or body == "anonymous":
        return {}
    try:
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        return json.loads(body)
    except Exception as exc:
        print("[sampleapp] JSON parsing error: {}".format(exc))
        return {}


def split_host_port(value):
    """Accept '127.0.0.1:2028', {'ip':..., 'port':...}, or None."""
    if not value:
        return None, None
    if isinstance(value, dict):
        host = value.get("ip") or value.get("host")
        port = value.get("port")
        return host, int(port) if port else None
    text = str(value).strip()
    if text.startswith("http://"):
        text = text[len("http://"):]
    text = text.split("/", 1)[0]
    if ":" not in text:
        return text, None
    host, port = text.rsplit(":", 1)
    try:
        return host, int(port)
    except ValueError:
        return host, None


def is_local_target(host, port):
    if not port:
        return True
    local_hosts = {"127.0.0.1", "localhost", "0.0.0.0", CURRENT_IP}
    return int(port) == int(CURRENT_PORT) and (not host or host in local_hosts)


def ensure_channel(channel):
    """Return normalized channel record: {'members': {}, 'messages': []}."""
    channel = channel or "general"
    current = CHANNELS.get(channel)
    if isinstance(current, dict) and "members" in current and "messages" in current:
        return current

    old_messages = current if isinstance(current, list) else []
    CHANNELS[channel] = {
        "members": {},
        "messages": old_messages,
    }
    return CHANNELS[channel]


def add_channel_member(channel, username, ip=None, port=None):
    record = ensure_channel(channel)
    if not username:
        return
    record["members"][username] = {
        "ip": ip or "127.0.0.1",
        "port": int(port) if port else None,
        "last_seen": now_ts(),
    }


def append_channel_message(channel, message_obj):
    record = ensure_channel(channel)
    record["messages"].append(message_obj)


def channel_summary():
    summary = {}
    for name in list(CHANNELS.keys()):
        record = ensure_channel(name)
        summary[name] = {
            "count": len(record["members"]),
            "members": record["members"],
        }
    return summary


def append_local_inbox(sender, message, channel="general", target=None, kind="p2p"):
    msg = {
        "id": next_inbox_id(),
        "from": sender,
        "sender": sender,
        "target": target,
        "channel": channel,
        "message": message,
        "msg": message,
        "kind": kind,
        "timestamp": now_ts(),
    }
    LOCAL_INBOX.append(msg)
    return msg


def http_post_json(host, port, path, payload, timeout=5):
    body = json.dumps(payload).encode("utf-8")
    request = (
        "POST {} HTTP/1.1\r\n"
        "Host: {}:{}\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).format(path, host, port, len(body)).encode("utf-8") + body

    response = b""
    with socket.create_connection((host, int(port)), timeout=timeout) as sock:
        sock.sendall(request)
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk

    _, _, body_part = response.partition(b"\r\n\r\n")
    text = body_part.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text}


def forward_to_peer(path, payload):
    host, port = split_host_port(payload.get("to") or payload.get("peer") or payload.get("target_addr"))
    if not host or not port:
        return None, "Missing target address"

    if is_local_target(host, port):
        return None, None

    try:
        forwarded = dict(payload)
        forwarded["forwarded_by"] = "{}:{}".format(CURRENT_IP, CURRENT_PORT)
        result = http_post_json(host, port, path, forwarded)
        return result, None
    except Exception as exc:
        return None, str(exc)


@app.route('/login', methods=['POST'])
def login(headers="guest", body="anonymous"):
    data = parse_body(body)
    username = data.get("username", "Unknown")
    print("[Tracker] User logged in successfully: {}".format(username))
    return json_response({
        "status": "success",
        "message": "Welcome {}".format(username),
        "token": "dummy_token",
    })


@app.route('/submit-info', methods=['POST'])
def submit_info(headers="guest", body="anonymous"):
    data = parse_body(body)
    ip = data.get("ip") or data.get("host") or "127.0.0.1"
    port = data.get("port")
    username = data.get("username") or ("{}:{}".format(ip, port) if port else None)

    if username and port:
        TRACKER_PEERS[username] = {
            "ip": ip,
            "port": int(port),
            "last_seen": now_ts(),
        }
        add_channel_member("general", username, ip, port)
        return json_response({
            "status": "success",
            "message": "Peer registered",
            "peers": TRACKER_PEERS,
            "channels": channel_summary(),
        })

    return json_response({"status": "error", "message": "Missing info"}, status_code=400)


@app.route('/get-list', methods=['GET'])
def get_list(headers="guest", body="anonymous"):
    print("[Tracker] A client requested the list of active peers")
    return json_response({
        "status": "success",
        "peers": TRACKER_PEERS,
        "channels": channel_summary(),
    })


@app.route('/add-list', methods=['POST'])
def add_list(headers="guest", body="anonymous"):
    data = parse_body(body)
    channel_name = data.get("channel_name") or data.get("channel") or "general"
    username = data.get("username") or data.get("sender")
    ip = data.get("ip") or "127.0.0.1"
    port = data.get("port")

    ensure_channel(channel_name)
    if username:
        add_channel_member(channel_name, username, ip, port)
        if port:
            TRACKER_PEERS[username] = {
                "ip": ip,
                "port": int(port),
                "last_seen": now_ts(),
            }

    print("[Tracker] {} joined channel {}".format(username, channel_name))
    return json_response({
        "status": "success",
        "message": "Joined channel {}".format(channel_name),
        "channel": channel_name,
        "peers": TRACKER_PEERS,
        "channels": channel_summary(),
    })


@app.route('/connect-peer', methods=['POST'])
def connect_peer(headers="guest", body="anonymous"):
    data = parse_body(body)

    forwarded_result, err = forward_to_peer('/connect-peer', data)
    if err:
        return json_response({"status": "error", "message": "Forward connect failed", "error": err}, status_code=500)
    if forwarded_result is not None:
        return json_response({"status": "success", "mode": "forward", "peer_response": forwarded_result})

    sender = data.get("username") or data.get("sender") or data.get("from") or "Someone"
    sender_ip = data.get("ip") or data.get("sender_ip")
    sender_port = data.get("port") or data.get("sender_port")

    if sender_ip and sender_port:
        PEER_CONNECTIONS[sender] = {
            "ip": sender_ip,
            "port": int(sender_port),
            "connected_at": now_ts(),
        }

    print("[P2P] Received connection request from: {}".format(sender))
    return json_response({
        "status": "success",
        "message": "Hi {}, peer {}:{} is ready".format(sender, CURRENT_IP, CURRENT_PORT),
        "connected_peers": len(PEER_CONNECTIONS),
    })


@app.route('/connect-peer', methods=['GET'])
def get_peer_connections(headers="guest", body="anonymous"):
    return json_response({
        "status": "success",
        "connections": PEER_CONNECTIONS,
        "count": len(PEER_CONNECTIONS),
    })


@app.route('/send-peer', methods=['POST'])
def send_peer(headers="guest", body="anonymous"):
    data = parse_body(body)

    if data.get("action") == "pull":
        try:
            after_id = int(data.get("after_id", 0))
        except Exception:
            after_id = 0
        messages = [msg for msg in LOCAL_INBOX if int(msg.get("id", 0)) > after_id]
        last_id = LOCAL_INBOX[-1]["id"] if LOCAL_INBOX else 0
        return json_response({
            "status": "success",
            "mode": "pull",
            "messages": messages,
            "last_id": last_id,
            "immutable": True,
            "peer": "{}:{}".format(CURRENT_IP, CURRENT_PORT),
        })

    forwarded_result, err = forward_to_peer('/send-peer', data)
    if err:
        return json_response({"status": "error", "message": "Forward message failed", "error": err}, status_code=500)
    if forwarded_result is not None:
        return json_response({"status": "success", "mode": "forward", "peer_response": forwarded_result})

    sender = data.get("sender") or data.get("from") or "Unknown"
    target = data.get("target") or data.get("recipient") or data.get("to")
    channel = data.get("channel") or "private"
    message = data.get("message") or data.get("msg") or data.get("text") or ""

    msg = append_local_inbox(sender, message, channel, target, kind="p2p")
    append_channel_message(channel, {
        "sender": sender,
        "target": target,
        "message": message,
        "timestamp": msg["timestamp"],
        "kind": "p2p",
    })

    print("[P2P INBOX {}:{}] {}: {}".format(CURRENT_IP, CURRENT_PORT, sender, message))
    return json_response({
        "status": "success",
        "message": "P2P message received",
        "mode": "push",
        "inbox_id": msg["id"],
        "peer": "{}:{}".format(CURRENT_IP, CURRENT_PORT),
    })


@app.route('/broadcast-peer', methods=['POST'])
def broadcast_peer(headers="guest", body="anonymous"):
    data = parse_body(body)

    forwarded_result, err = forward_to_peer('/broadcast-peer', data)
    if err:
        return json_response({"status": "error", "message": "Forward broadcast failed", "error": err}, status_code=500)
    if forwarded_result is not None:
        return json_response({"status": "success", "mode": "forward", "peer_response": forwarded_result})

    sender = data.get("sender") or data.get("from") or "Unknown"
    channel = data.get("channel") or "general"
    message = data.get("message") or data.get("msg") or data.get("text") or ""

    msg = append_local_inbox(sender, message, channel, target="ALL", kind="broadcast")
    append_channel_message(channel, {
        "sender": sender,
        "message": message,
        "timestamp": msg["timestamp"],
        "kind": "broadcast",
    })

    print("[Broadcast - {} on {}:{}] {}: {}".format(channel, CURRENT_IP, CURRENT_PORT, sender, message))
    return json_response({
        "status": "success",
        "message": "Broadcast message received",
        "channel": channel,
        "inbox_id": msg["id"],
        "peer": "{}:{}".format(CURRENT_IP, CURRENT_PORT),
    })


@app.route('/submit-info', methods=['OPTIONS'])
@app.route('/add-list', methods=['OPTIONS'])
@app.route('/connect-peer', methods=['OPTIONS'])
@app.route('/send-peer', methods=['OPTIONS'])
@app.route('/broadcast-peer', methods=['OPTIONS'])
def global_preflight_handler(headers=None, body=None):
    return (
        "HTTP/1.1 204 No Content\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "Access-Control-Allow-Methods: POST, GET, OPTIONS\r\n"
        "Access-Control-Allow-Headers: Content-Type, Authorization\r\n"
        "Access-Control-Allow-Private-Network: true\r\n"
        "Access-Control-Max-Age: 86400\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("utf-8")


def create_sampleapp(ip, port):
    global CURRENT_IP, CURRENT_PORT
    CURRENT_IP = ip if ip not in ("0.0.0.0", "") else "127.0.0.1"
    CURRENT_PORT = int(port)
    print("[sampleapp] Starting node at {}:{}".format(CURRENT_IP, CURRENT_PORT))
    app.prepare_address(ip, port)
    app.run()
