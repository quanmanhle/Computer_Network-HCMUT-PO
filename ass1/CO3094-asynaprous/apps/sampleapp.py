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
app.sampleapp
~~~~~~~~~~~~~~~~~

"""

import sys
import os
import importlib.util
import json
import time

from   daemon import AsynapRous

app = AsynapRous()

TRACKER_PEERS = {}   # Store list active peer (for Tracker ) Format: {"username1": {"ip": "192.168.1.2", "port": 2026}}
CHANNELS = {"general": []}  # Save chat & message broadcast Format: {"general": [{"sender": "A", "msg": "hello"}]}
LOCAL_INBOX = []  # Save inbox for P2P messages
PEER_CONNECTIONS = {}
INBOX_SEQ = 0


def json_response(payload):
    return json.dumps(payload).encode("utf-8")


def now_ts():
    return int(time.time())


def next_inbox_id():
    global INBOX_SEQ
    INBOX_SEQ += 1
    return INBOX_SEQ


def append_local_inbox(sender, message, channel="general", target=None):
    msg = {
        "id": next_inbox_id(),
        "sender": sender,
        "target": target,
        "channel": channel,
        "message": message,
        "timestamp": now_ts()
    }
    LOCAL_INBOX.append(msg)
    return msg


def ensure_channel(channel):
    if channel not in CHANNELS:
        CHANNELS[channel] = []

def parse_body(body):
    """Helper function to safely parse JSON from request body"""
    if isinstance(body, dict):
        return body

    if not body or body == "anonymous":
        return {}
    try:
        if isinstance(body, bytes):
            body = body.decode('utf-8')
        return json.loads(body)
    except Exception as e:
        print(f"[Error] JSON parsing error: {e}")
        return {}

@app.route('/login', methods=['POST'])
def login(headers="guest", body="anonymous"):
    data = parse_body(body)
    username = data.get("username", "Unknown")
    
    print(f"[Tracker] User logged in successfully: {username}")
    res = {"status": "success", "message": f"Welcome {username}", "token": "dummy_token"}
    return json_response(res)

@app.route('/submit-info', methods=['POST'])
def submit_info(headers="guest", body="anonymous"):
    data = parse_body(body)
    username = data.get("username")
    ip = data.get("ip")
    port = data.get("port")
    
    if username and ip and port:
        TRACKER_PEERS[username] = {"ip": ip, "port": int(port), "last_seen": now_ts()}
        print(f"[Tracker] Registered peer: {username} at {ip}:{port}")
        res = {"status": "success", "message": "IP/Port registration successful"}
        return json_response(res)
        
    res = {"status": "error", "message": "Missing username, IP, or port"}
    return json_response(res)

@app.route('/get-list', methods=['GET'])
def get_list(headers="guest", body="anonymous"):
    print("[Tracker] A client requested the list of active peers")
    res = {"status": "success", "peers": TRACKER_PEERS}
    return json_response(res)

@app.route('/add-list', methods=['POST'])
def add_list(headers="guest", body="anonymous"):
    data = parse_body(body)
    channel_name = data.get("channel_name")
    
    if channel_name and channel_name not in CHANNELS:
        CHANNELS[channel_name] = []
        print(f"[Tracker] Created new chat channel: {channel_name}")
        res = {"status": "success", "message": f"Channel {channel_name} created"}
        return json_response(res)
        
    res = {"status": "error", "message": "Invalid or existing channel name"}
    return json_response(res)

@app.route('/connect-peer', methods=['POST'])
def connect_peer(headers="guest", body="anonymous"):
    data = parse_body(body)
    sender = data.get("username", "Someone")
    sender_ip = data.get("ip")
    sender_port = data.get("port")

    if sender_ip and sender_port:
        PEER_CONNECTIONS[sender] = {
            "ip": sender_ip,
            "port": int(sender_port),
            "connected_at": now_ts()
        }
    
    print(f"[P2P] Received connection request from: {sender}")
    res = {
        "status": "success",
        "message": f"Hi {sender}, I am ready to receive messages!",
        "connected_peers": len(PEER_CONNECTIONS)
    }
    return json_response(res)


@app.route('/connect-peer', methods=['GET'])
def get_peer_connections(headers="guest", body="anonymous"):
    return json_response({
        "status": "success",
        "connections": PEER_CONNECTIONS,
        "count": len(PEER_CONNECTIONS)
    })

@app.route('/send-peer', methods=['POST'])
def send_peer(headers="guest", body="anonymous"):
    data = parse_body(body)

    # Pull mode is kept on the same public endpoint so Postman testing stays simple.
    action = data.get("action")
    if action == "pull":
        try:
            after_id = int(data.get("after_id", 0))
        except Exception:
            after_id = 0

        new_messages = [msg for msg in LOCAL_INBOX if msg.get("id", 0) > after_id]
        last_id = LOCAL_INBOX[-1]["id"] if LOCAL_INBOX else 0

        return json_response({
            "status": "success",
            "mode": "pull",
            "messages": new_messages,
            "last_id": last_id,
            "immutable": True
        })

    sender = data.get("sender", "Unknown")
    target = data.get("target")
    channel = data.get("channel", "general")
    message = data.get("message", "")

    ensure_channel(channel)
    
    print(f"\n[P2P INBOX] Received message from {sender}: {message}\n")
    msg = append_local_inbox(sender, message, channel, target)
    CHANNELS[channel].append({
        "sender": sender,
        "target": target,
        "message": message,
        "timestamp": msg["timestamp"],
        "kind": "p2p"
    })
    
    res = {
        "status": "success",
        "message": "P2P message received",
        "mode": "push",
        "inbox_id": msg["id"]
    }
    return json_response(res)

@app.route('/broadcast-peer', methods=['POST'])
def broadcast_peer(headers="guest", body="anonymous"):
    data = parse_body(body)
    sender = data.get("sender", "Unknown")
    channel = data.get("channel", "general")
    message = data.get("message", "")

    ensure_channel(channel)
    CHANNELS[channel].append({
        "sender": sender,
        "message": message,
        "timestamp": now_ts(),
        "kind": "broadcast"
    })
    append_local_inbox(sender, message, channel, target="ALL")

    print(f"[Broadcast - {channel}] {sender}: {message}")
    res = {"status": "success", "message": "Broadcast message received"}
    return json_response(res)

def create_sampleapp(ip, port):
    # Prepare and launch the RESTful application
    app.prepare_address(ip, port)
    app.run()

