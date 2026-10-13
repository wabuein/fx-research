from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from fxresearch.live.config import CTraderConfig

AUTH_URL = "https://openapi.ctrader.com/apps/auth"
TOKEN_URL = "https://openapi.ctrader.com/apps/token"
REDIRECT = "http://localhost:5000/"
SCOPE = "trading"
PORT = 5000


class RedirectHandler(BaseHTTPRequestHandler):

    received: dict = {}

    def do_GET(self) -> None:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        RedirectHandler.received["code"] = params.get("code", [None])[0]
        RedirectHandler.received["error"] = params.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        ok = RedirectHandler.received.get("code") is not None
        self.wfile.write(b"<h2>" + (b"Authorized - you can close this tab." if ok else b"Authorization failed.")
                         + b"</h2>")

    def log_message(self, *args: object) -> None:
        pass


class CTraderAuth:

    def __init__(self, config: CTraderConfig) -> None:
        self.config = config

    def run(self) -> None:
        client_id = self.config.require("client_id")
        client_secret = self.config.require("client_secret")

        code = self._authorize(client_id)
        print("Got authorization code; exchanging for tokens...")
        data = self._exchange(code, client_id, client_secret)

        access = data.get("accessToken") or data.get("access_token")
        refresh = data.get("refreshToken") or data.get("refresh_token")
        if not access: sys.exit("No access token in the token response")

        self.config.save_tokens(access, refresh or "")
        print(f"\nSaved tokens to {self.config.path.name} (expires in "
              f"{data.get('expiresIn', data.get('expires_in', '?'))}s).")
        print("Next: python3 scripts/ctrader_bot.py --list-accounts")

    def _authorize(self, client_id: str) -> str:
        url = AUTH_URL + "?" + urllib.parse.urlencode({"client_id": client_id, "redirect_uri": REDIRECT,
                                                       "scope": SCOPE})
        print("Opening browser to authorize (demo account)...\n")
        webbrowser.open(url)

        print(f"Waiting for the redirect on {REDIRECT} ...")
        server = HTTPServer(("localhost", PORT), RedirectHandler)
        while "code" not in RedirectHandler.received:
            server.handle_request()

        if RedirectHandler.received.get("error") or not RedirectHandler.received.get("code"):
            sys.exit(f"OAuth failed: {RedirectHandler.received.get('error')}")
        return RedirectHandler.received["code"]

    def _exchange(self, code: str, client_id: str, client_secret: str) -> dict:
        url = TOKEN_URL + "?" + urllib.parse.urlencode({
            "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
            "client_id": client_id, "client_secret": client_secret})
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read().decode())

