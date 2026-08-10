# chat — Chat app backend (Phase 3)

FastAPI service on port 8010. Proxies to Ollama for streaming chat responses.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /health | Service health check |
| GET | /models | List available Ollama models |
| POST | /chat | Streaming chat response (SSE) |

## Local dev

```bash
cd platform/chat
python3 -m venv venv
source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn main:app --reload --port 8010
```

## Deploy (mini PC)

```bash
sudo cp systemd/platform-chat.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable platform-chat
sudo systemctl start platform-chat
```

## Caddy config (add to /etc/caddy/Caddyfile)

```
handle /chat/api/* {
    uri strip_prefix /chat/api
    reverse_proxy localhost:8010
}
handle /chat* {
    root * /opt/platform/frontend/chat/dist
    file_server
    try_files {path} /chat/index.html
}
```

Note: API handle must appear before the static file handle. Reload after editing:
`sudo systemctl reload caddy`
