# README — End-to-End Test for Proxy, P2P Chat, and Channel Broadcast

This README describes how to run the local end-to-end test for the current assignment implementation. The test checks the HTTP backend, tracker, peer-to-peer messaging, proxy routing, and channel-based broadcast.

## Port mapping

| Port | Process | Purpose |
|---:|---|---|
| 8080 | `start_proxy.py` | Public proxy entry point |
| 9000 | `start_backend.py` | Static files and authentication backend |
| 2026 | `start_sampleapp.py` | Tracker / centralized peer-discovery service |
| 2027 | `start_sampleapp.py` | Peer instance 1 |
| 2028 | `start_sampleapp.py` | Peer instance 2 |

Important: ports `2027` and `2028` must run `start_sampleapp.py`, not `start_backend.py`, because each peer needs the REST API routes such as `/send-peer`, `/connect-peer`, and `/broadcast-peer`.

## Host to service mapping

The proxy uses the `Host` header to decide where to forward requests.

| Host header | Routed service | Notes |
|---|---|---|
| `127.0.0.1:8080` or your configured backend host | `127.0.0.1:9000` | Static pages and authentication backend |
| `tracker.local` / `tracker.local:8080` | `127.0.0.1:2026` | Tracker APIs such as login, submit-info, get-list, add-list |
| `peer.local` / `peer.local:8080` | `127.0.0.1:2027` or `127.0.0.1:2028` | Peer route, usually round-robin in `proxy.conf` |

For browser testing with `tracker.local` and `peer.local`, add these lines to your Windows hosts file:

```text
127.0.0.1 tracker.local
127.0.0.1 peer.local
```

The hosts file is usually located at:

```text
C:\Windows\System32\drivers\etc\hosts
```

After editing it, run:

```powershell
ipconfig /flushdns
```

## Start the services

Open five terminals in the project root directory and run the commands below.

```powershell
# Terminal 1 — Backend for static files and authentication
python start_backend.py --server-ip 127.0.0.1 --server-port 9000
```

```powershell
# Terminal 2 — Tracker / peer discovery service
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2026
```

```powershell
# Terminal 3 — Peer 1
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2027
```

```powershell
# Terminal 4 — Peer 2
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2028
```

```powershell
# Terminal 5 — Proxy, start this last
python start_proxy.py --server-ip 127.0.0.1 --server-port 8080
```

When the peer services start correctly, the terminals for ports `2027` and `2028` should show route settings that include:

```text
+ ('POST', '/send-peer'): ...
+ ('POST', '/connect-peer'): ...
+ ('POST', '/broadcast-peer'): ...
```

If these routes are missing, the peer is not running the sample application correctly.

## Run the E2E test

Use the channel-aware E2E test file:

```powershell
python test_e2e_channel.py
```

The test reports each check as:

| Status | Meaning |
|---|---|
| `PASS` | The feature works as expected |
| `PARTIAL` | The service responded, but the response or behavior is incomplete |
| `FAIL` | The service is not reachable, the route is wrong, or the behavior is incorrect |

## What the test checks

```text
[0] Service boot check
    - Backend :9000
    - Tracker :2026
    - Peer 1  :2027
    - Peer 2  :2028
    - Proxy   :8080

[1] Static / proxy sanity checks
    - Proxy can serve /chat.html
    - Backend static routing is available

[2] Tracker flow
    - POST /login
    - POST /submit-info for peer 2027 and peer 2028
    - GET /get-list returns the submitted peers

[3] Channel management
    - POST /add-list creates or joins a channel
    - Both peers can join the same channel
    - GET /get-list returns channel metadata, if implemented

[4] Direct P2P messaging
    - Peer 2027 sends a private message to peer 2028
    - Peer 2028 receives the message through /send-peer pull mode

[5] Channel broadcast
    - Peer 2027 broadcasts to a selected channel
    - Peer 2028 receives the broadcast only if it joined that channel

[6] Proxy routing
    - tracker.local routes to tracker :2026
    - peer.local routes to peer services
    - Unknown host does not crash the proxy
```

## Browser test flow

Open two browser tabs:

```text
http://127.0.0.1:8080/chat.html
```

or, if your hosts file is configured:

```text
http://peer.local:8080/chat.html
```

### Tab 1 — Peer 2027

```text
Username: viet
Local Port: 2027
```

Click:

```text
Login
Submit Peer Info
Channel name: lab1
Join / Create Channel
Refresh List
```

### Tab 2 — Peer 2028

```text
Username: viet2
Local Port: 2028
```

Click:

```text
Login
Submit Peer Info
Channel name: lab1
Join / Create Channel
Refresh List
```

### Private P2P test

In tab 1:

```text
Select viet2
Connect to Selected
Type a private message
Send P2P
```

Expected result: tab 2 opens the direct P2P section and displays the private message.

### Channel broadcast test

In both tabs, make sure the selected channel is `lab1`.

In tab 1:

```text
Type a broadcast message
Broadcast to Channel
```

Expected result: tab 2 receives the message in the broadcast area, shown as:

```text
[viet @ lab1]: message text
```

If a peer has not joined the selected channel, it should not receive broadcasts for that channel.

## Manual API checks

### Pull messages from peer 2028

```powershell
$body = @{ action = "pull"; after_id = 0 } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:2028/send-peer' -ContentType 'application/json' -Body $body
```

Expected result:

```text
status : success
mode   : pull
peer   : 127.0.0.1:2028
```

### Send a private P2P message from 2027 to 2028

```powershell
$body = @{
  sender = "viet"
  to = "127.0.0.1:2028"
  target = "viet2"
  message = "hello from 2027"
} | ConvertTo-Json -Compress

Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:2027/send-peer' -ContentType 'application/json' -Body $body
```

Then pull from 2028 again:

```powershell
$body = @{ action = "pull"; after_id = 0 } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:2028/send-peer' -ContentType 'application/json' -Body $body | ConvertTo-Json -Depth 10
```

The returned messages should include `hello from 2027`.

## Common errors

### `502 Bad Gateway` when opening `127.0.0.1:8080/chat.html`

The proxy is running, but it cannot connect to the backend route. Start the static backend:

```powershell
python start_backend.py --server-ip 127.0.0.1 --server-port 9000
```

### `Serving the object at location apps/send-peer`

The peer process does not have the `/send-peer` route mounted. Make sure ports `2027` and `2028` are started with:

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2027
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2028
```

Do not use `start_backend.py` for peer ports.

### `Missing target address`

The request body was parsed, but it does not contain a destination such as:

```json
{"to":"127.0.0.1:2028"}
```

For pull mode, the body must contain:

```json
{"action":"pull","after_id":0}
```

If pull mode still fails, check that `daemon/httpadapter.py` reads the complete HTTP request body using `Content-Length`.

### A peer does not receive channel broadcast

Check these items:

```text
1. The peer process is running on its Local Port.
2. The peer clicked Submit Peer Info.
3. The peer joined the same channel.
4. The sender clicked Refresh List or the UI refreshed channel membership before broadcasting.
5. The browser loaded the latest chat.html. Use Ctrl + F5 or Incognito mode.
```

## Notes about extra peers

Ports `2027` and `2028` are not fixed by the assignment. They are only the default demo peer ports. You can add more peers, such as `2029`, as long as you start another peer process:

```powershell
python start_sampleapp.py --server-ip 127.0.0.1 --server-port 2029
```

Then open another browser tab with:

```text
Username: viet3
Local Port: 2029
```

The new peer must submit its info and join the target channel before it can receive channel broadcasts.
