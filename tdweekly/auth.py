"""腾讯文档开放平台 OAuth2.0 鉴权 + token 缓存。

流程(授权码模式):
  1. 浏览器打开授权页 -> 用户同意 -> 回调到 redirect_uri?code=xxx
  2. 用 code 换 access_token / refresh_token (token 接口)
  3. 用 access_token 调 userinfo 拿 open_id(后续 API 请求头需要)
  4. token 缓存到本地文件; 过期用 refresh_token 自动刷新

⚠️ 端点版本/字段名以官方文档为准, 见 docs/API_NOTES.md。所有 URL 都可在 config.toml 覆盖。
官方文档: https://docs.qq.com/open/document/app/oauth2/
"""

from __future__ import annotations

import json
import time
import urllib.parse
import webbrowser
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

from .config import AppConfig


@dataclass
class Token:
    access_token: str
    refresh_token: str
    open_id: str
    expires_at: float  # epoch 秒

    def is_expired(self, skew: int = 120) -> bool:
        return time.time() >= (self.expires_at - skew)


class _CallbackHandler(BaseHTTPRequestHandler):
    code: str | None = None

    def do_GET(self):  # noqa: N802
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        _CallbackHandler.code = (params.get("code") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = "授权成功, 可以关闭本页面回到终端。" if _CallbackHandler.code else "未拿到 code, 授权失败。"
        self.wfile.write(f"<html><body><h3>{msg}</h3></body></html>".encode("utf-8"))

    def log_message(self, *args):  # 静音
        pass


def _capture_code(redirect_uri: str) -> str:
    """起一个一次性本地 HTTP 服务接收 OAuth 回调里的 code。"""
    parsed = urllib.parse.urlparse(redirect_uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 80
    _CallbackHandler.code = None
    httpd = HTTPServer((host, port), _CallbackHandler)
    print(f"[auth] 已在 {host}:{port} 等待授权回调…")
    while _CallbackHandler.code is None:
        httpd.handle_request()
    return _CallbackHandler.code


def authorize(cfg: AppConfig) -> Token:
    """走完整授权流程, 返回并缓存 Token。"""
    state = "tdweekly"
    params = {
        "client_id": cfg.client_id,
        "redirect_uri": cfg.redirect_uri,
        "response_type": "code",
        "scope": cfg.scope,
        "state": state,
    }
    url = cfg.oauth_authorize_url + "?" + urllib.parse.urlencode(params)
    print("[auth] 请在浏览器中完成授权(若没自动打开请手动复制):")
    print(url)
    try:
        webbrowser.open(url)
    except Exception:
        pass

    code = _capture_code(cfg.redirect_uri)
    print("[auth] 已收到 code, 正在换取 token…")

    resp = requests.post(
        cfg.oauth_token_url,
        data={
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": cfg.redirect_uri,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    token = _token_from_response(cfg, data)
    save_token(cfg, token)
    print("[auth] 授权完成, token 已缓存到", cfg.token_cache)
    return token


def _token_from_response(cfg: AppConfig, data: dict) -> Token:
    access = data["access_token"]
    refresh = data.get("refresh_token", "")
    expires_in = int(data.get("expires_in", 7200))
    open_id = data.get("user_id") or data.get("open_id") or _fetch_open_id(cfg, access)
    return Token(
        access_token=access,
        refresh_token=refresh,
        open_id=open_id,
        expires_at=time.time() + expires_in,
    )


def _fetch_open_id(cfg: AppConfig, access_token: str) -> str:
    """token 响应里没带 open_id 时, 调 userinfo 获取。"""
    try:
        r = requests.get(
            cfg.oauth_userinfo_url,
            params={"client_id": cfg.client_id, "access_token": access_token},
            timeout=30,
        )
        r.raise_for_status()
        d = r.json()
        return d.get("open_id") or d.get("user_id") or (d.get("data", {}) or {}).get("open_id", "")
    except Exception as e:  # pragma: no cover - 联网
        print("[auth] 警告: 获取 open_id 失败:", e)
        return ""


def refresh(cfg: AppConfig, token: Token) -> Token:
    resp = requests.post(
        cfg.oauth_token_url,
        data={
            "client_id": cfg.client_id,
            "client_secret": cfg.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    new = _token_from_response(cfg, data)
    if not new.open_id:
        new.open_id = token.open_id
    save_token(cfg, new)
    return new


def save_token(cfg: AppConfig, token: Token) -> None:
    Path(cfg.token_cache).write_text(json.dumps(asdict(token), ensure_ascii=False, indent=2))


def load_token(cfg: AppConfig) -> Token | None:
    p = Path(cfg.token_cache)
    if not p.exists():
        return None
    return Token(**json.loads(p.read_text()))


def token_from_config(cfg: AppConfig) -> Token:
    """方式一: 直接用 config 里填的 access_token / open_id(无需 OAuth)。"""
    return Token(
        access_token=cfg.access_token,
        refresh_token="",
        open_id=cfg.open_id,
        expires_at=time.time() + 30 * 86400,  # 仅作信息; 真过期时接口会返回鉴权错误
    )


def get_valid_token(cfg: AppConfig) -> Token:
    """返回一个有效 token。

    方式一(推荐): config 里填了 access_token + open_id -> 直接使用。
    方式二(OAuth): 否则走授权码流程的缓存/刷新(需先 `python run.py auth`)。
    """
    if cfg.access_token and cfg.open_id:
        return token_from_config(cfg)
    if cfg.access_token and not cfg.open_id:
        raise RuntimeError("config.toml 里填了 access_token 但缺 open_id, 两个都要填。")

    token = load_token(cfg)
    if token is None:
        raise RuntimeError(
            "尚未配置凭据。请在 config.toml 填 access_token + open_id(推荐), "
            "或走 OAuth 先运行: python run.py auth"
        )
    if token.is_expired():
        print("[auth] token 已过期, 正在刷新…")
        token = refresh(cfg, token)
    return token
