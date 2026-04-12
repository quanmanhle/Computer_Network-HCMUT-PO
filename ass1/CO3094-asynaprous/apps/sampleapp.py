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

from   daemon import AsynapRous

app = AsynapRous()

TRACKER_PEERS = {}   # Store list active peer (for Tracker ) Format: {"username1": {"ip": "192.168.1.2", "port": 2026}}
CHANNELS = {"general": []}  # Save chat & message broadcast Format: {"general": [{"sender": "A", "msg": "hello"}]}
LOCAL_INBOX = []  # Save inbox for P2P messages

def parse_body(body):
    """Helper function to safely parse JSON from request body"""
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
    return json.dumps(res).encode("utf-8")

@app.route('/submit-info', methods=['POST'])
def submit_info(headers="guest", body="anonymous"):
    data = parse_body(body)
    username = data.get("username")
    ip = data.get("ip")
    port = data.get("port")
    
    if username and ip and port:
        TRACKER_PEERS[username] = {"ip": ip, "port": port}
        print(f"[Tracker] Registered peer: {username} at {ip}:{port}")
        res = {"status": "success", "message": "IP/Port registration successful"}
        return json.dumps(res).encode("utf-8")
        
    res = {"status": "error", "message": "Missing username, IP, or port"}
    return json.dumps(res).encode("utf-8")

@app.route('/get-list', methods=['GET'])
def get_list(headers="guest", body="anonymous"):
    print("[Tracker] A client requested the list of active peers")
    res = {"status": "success", "peers": TRACKER_PEERS}
    return json.dumps(res).encode("utf-8")

@app.route('/add-list', methods=['POST'])
def add_list(headers="guest", body="anonymous"):
    data = parse_body(body)
    channel_name = data.get("channel_name")
    
    if channel_name and channel_name not in CHANNELS:
        CHANNELS[channel_name] = []
        print(f"[Tracker] Created new chat channel: {channel_name}")
        res = {"status": "success", "message": f"Channel {channel_name} created"}
        return json.dumps(res).encode("utf-8")
        
    res = {"status": "error", "message": "Invalid or existing channel name"}
    return json.dumps(res).encode("utf-8")

@app.route('/connect-peer', methods=['POST'])
def connect_peer(headers="guest", body="anonymous"):
    data = parse_body(body)
    sender = data.get("username", "Someone")
    
    print(f"[P2P] Received connection request from: {sender}")
    res = {"status": "success", "message": f"Hi {sender}, I am ready to receive messages!"}
    return json.dumps(res).encode("utf-8")

@app.route('/send-peer', methods=['POST'])
def send_peer(headers="guest", body="anonymous"):
    data = parse_body(body)
    sender = data.get("sender", "Unknown")
    message = data.get("message", "")
    
    print(f"\n[P2P INBOX] Received message from {sender}: {message}\n")
    LOCAL_INBOX.append({"sender": sender, "message": message})
    
    res = {"status": "success", "message": "P2P message received"}
    return json.dumps(res).encode("utf-8")

@app.route('/broadcast-peer', methods=['POST'])
def broadcast_peer(headers="guest", body="anonymous"):
    data = parse_body(body)
    sender = data.get("sender", "Unknown")
    channel = data.get("channel", "general")
    message = data.get("message", "")
    
    if channel in CHANNELS:
        CHANNELS[channel].append({"sender": sender, "message": message})
        print(f"[Broadcast - {channel}] {sender}: {message}")
        res = {"status": "success", "message": "Broadcast message received"}
        return json.dumps(res).encode("utf-8")
        
    res = {"status": "error", "message": "Channel does not exist"}
    return json.dumps(res).encode("utf-8")

def create_sampleapp(ip, port):
    # Prepare and launch the RESTful application
    app.prepare_address(ip, port)
    app.run()

