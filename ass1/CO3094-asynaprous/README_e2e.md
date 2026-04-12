# README — End-to-End Proxy Test

## Port mapping (theo spec)

| Port | Process | Mục đích |
|------|---------|---------|
| 8080 | `start_proxy.py` | Entry point  |
| 9000 | `start_backend.py` | Static files + auth |
| 2026 | `start_sampleapp.py` | Tracker / chat app (7 API routes) |
| 2027 | `start_backend.py` | Peer instance 1 |
| 2028 | `start_backend.py` | Peer instance 2 |

## Host → Service mapping (proxy.conf)

| Host header | Proxy route đến | Notes |
|---|---|---|
| `192.168.56.114:8080` | `:9000` | Static + auth |
| `tracker.local` | `:2026` | Tất cả 7 API trả JSON |
| `peer.local` | `:2027` hoặc `:2028` | Round-robin |

---

## Khởi động (5 terminal, theo thứ tự)

```bash
# Terminal 1 — Backend static + auth
python start_backend.py --server-port 9000

# Terminal 2 — Tracker / SampleApp
python start_sampleapp.py --server-port 2026

# Terminal 3 — Peer instance 1
python start_backend.py --server-port 2027

# Terminal 4 — Peer instance 2
python start_backend.py --server-port 2028

# Terminal 5 — Proxy (SAU CÙNG)
python start_proxy.py --server-port 8080
```

## Chạy test

```bash
python test_e2e.py
```

---

## Cấu trúc test (2 tầng)

```
[0] Boot check      — 5 service đều đang chạy?

TẦNG 1: DIRECT (không qua proxy)
  [1A] Backend :9000 — GET /  /index.html  /login.html
  [1B] Backend :9000 — POST /login  →  phải trả JSON
  [1C] Tracker :2026 — 7 routes đều phải trả JSON
         POST /login
         POST /submit-info
         GET  /get-list
         POST /add-list
         POST /connect-peer
         POST /send-peer       ← qua auth, trả JSON
         POST /broadcast-peer
  [1D] Tracker state — submit-info lưu peer, get-list thấy lại
  [1E] Peer :2027 / :2028 — boot và response

TẦNG 2: QUA PROXY :8080
  [2A] Proxy → Backend :9000  (static + /login JSON)
  [2B] Proxy → Tracker :2026  (7 routes)
  [2C] Proxy → Peer round-robin  (4 requests xoay vòng)
  [2D] Unknown host  →  proxy không crash
  [2E] Full flow: login → submit-info → get-list → send-peer
```

---

## Điều kiện pass

| Route | Điều kiện |
|---|---|
| `GET /` `GET /index.html` `GET /login.html` | HTTP 200/301/302 |
| `POST /login` | **Phải trả JSON** (không phải HTML) |
| `POST /submit-info` | HTTP 200/201, lưu peer vào state |
| `GET /get-list` | JSON chứa danh sách peer đã submit |
| `POST /add-list` | HTTP 200/201 |
| `POST /connect-peer` | HTTP 200/201 |
| `POST /send-peer` | **Phải trả JSON** (qua auth flow) |
| `POST /broadcast-peer` | HTTP 200/201 |

---

## Lỗi thường gặp

**Boot check FAIL**
```
✗  Port 2026 – Tracker — Chưa khởi động
```
→ Chạy `python start_sampleapp.py --server-port 2026`

**`/login` trả HTML thay vì JSON**
```
✗  POST /login → body là JSON — Nhận HTML thay vì JSON
```
→ `sampleapp.py` chưa set `Content-Type: application/json` trong response

**Tracker state FAIL**
```
✗  Tracker state: submit-info → get-list thấy peer
```
→ Tracker chưa lưu state — kiểm tra `submit-info` handler có append vào list không

**Round-robin FAIL**
```
✗  Proxy round-robin: 4 requests đều được xử lý
```
→ Peer 2027 hoặc 2028 chưa chạy

**Chạy local (không có VM)**

Đổi trong `proxy.conf`:
```
192.168.56.114  →  127.0.0.1
```

Đổi trong `test_e2e.py` dòng đầu:
```python
SERVER_IP = "127.0.0.1"   # đã đúng rồi, giữ nguyên
HOST_BACKEND = "127.0.0.1:8080"   # đổi dòng này
```
