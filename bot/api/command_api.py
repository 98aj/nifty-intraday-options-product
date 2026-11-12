"""FastAPI command webhook + read-only state endpoint.

- GET  /state    -> latest StateStore snapshot (read-only; used by the UI).
- GET  /health   -> liveness.
- POST /command  -> {"command": "pause|resume|flatten|kill|status"}; requires
                    Authorization: Bearer <COMMAND_API_TOKEN>. Submits to the
                    CommandQueue; the engine control loop executes it. The API can
                    never touch engine internals directly, so it can't block trading.

Runs uvicorn on its own thread (127.0.0.1 by default).
"""
from __future__ import annotations

import threading
from typing import Optional

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from bot.core.commands import CommandQueue, CommandType, VALID_COMMANDS
from bot.core.state_store import StateStore


class CommandBody(BaseModel):
    command: str


class ConfigBody(BaseModel):
    updates: dict


def build_app(state: StateStore, cq: CommandQueue, token: str,
              get_config=None, set_config=None) -> FastAPI:
    app = FastAPI(title="NIFTY bot command API", version="0.1.0")

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/state")
    def get_state():
        return state.snapshot()

    @app.get("/config")
    def read_config():
        from bot.user_config import EDITABLE
        values = get_config() if get_config else {}
        return {"schema": EDITABLE, "values": values}

    @app.post("/config")
    def write_config(body: ConfigBody,
                     authorization: Optional[str] = Header(default=None)):
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="bad or missing token")
        if set_config is None:
            raise HTTPException(status_code=503, detail="config updates unavailable")
        applied = set_config(body.updates or {})
        if not applied:
            raise HTTPException(status_code=400, detail="no valid fields to update")
        return {"applied": applied}

    @app.post("/command")
    def post_command(body: CommandBody,
                     authorization: Optional[str] = Header(default=None)):
        expected = f"Bearer {token}"
        if authorization != expected:
            raise HTTPException(status_code=401, detail="bad or missing token")
        cmd = body.command.strip().lower()
        if cmd not in VALID_COMMANDS:
            raise HTTPException(status_code=400,
                                detail=f"invalid command; valid: {sorted(VALID_COMMANDS)}")
        cq.submit(CommandType(cmd), source="api")
        return {"accepted": cmd}

    return app


class CommandApiServer:
    def __init__(self, cfg, state: StateStore, cq: CommandQueue,
                 get_config=None, set_config=None) -> None:
        self.cfg = cfg
        self.app = build_app(state, cq, cfg.secrets.command_api_token,
                             get_config=get_config, set_config=set_config)
        self._server: Optional[uvicorn.Server] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        config = uvicorn.Config(self.app, host=self.cfg.api.host,
                                port=self.cfg.api.port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run,
                                        name="CommandAPI", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
