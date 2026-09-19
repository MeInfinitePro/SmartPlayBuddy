from .. import i18n
from .. import log
from ..config import SERVER_HOST

import asyncio
import socket
import webbrowser
import http.server
import urllib.parse
import urllib.request
import json
import base64
import hashlib
import secrets
import time
import keyring
from dataclasses import dataclass, asdict


logger = log.logger.getChild("User").getChild("Login")

SERVICE_NAME = "SmartPlayBuddy"
ACCOUNT_NAME = "UserTokens"

#: access token 剩余有效期低于该值(秒)就提前刷新，避免握手中途过期
TOKEN_REFRESH_MARGIN = 60

#: 服务端 HttpOnly cookie 名（与 common/authtoken.go 的 CookieName / RefreshCookieName 一致）
ACCESS_COOKIE_NAME = "access_token"
REFRESH_COOKIE_NAME = "refresh_token"

@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_in: int


def save_tokens(tokens: Tokens):
    credential = json.dumps(asdict(tokens))
    keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, credential)
    logger.debug(i18n.translate("user.login.tokens_saved"))


def clear_tokens():
    """清除本地保存的令牌（token 被吊销/强制重登时使用）。"""
    try:
        keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
        logger.debug(i18n.translate("user.login.tokens_cleared"))
    except Exception as e:
        logger.warning(i18n.translate("user.login.load_tokens_failed", error=str(e)))


def decode_jwt_payload(access_token: str) -> dict:
    """解析 JWT 的 payload 部分，返回完整 claims dict；解析失败返回空 dict。"""
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def access_token_ttl(access_token: str) -> float | None:
    """解析 JWT 的 exp 声明，返回 access token 剩余有效期(秒)；解析失败返回 None。"""
    try:
        exp = decode_jwt_payload(access_token).get("exp")
    except Exception:
        return None
    if not exp:
        return None
    return float(exp) - time.time()


async def ensure_tokens(tokens: Tokens | None = None, force_login: bool = False) -> Tokens:
    """返回可用的令牌：仍然有效则复用，过期则刷新，刷新失败或 force_login 则重新登录。

    异步接口（浏览器登录为阻塞 IO，经 to_thread 执行以免卡住事件循环）。
    - force_login=True：清空本地令牌并重新走浏览器登录（用于 4001 token 被吊销）；
    - tokens 仍有效（TTL 未知或 > TOKEN_REFRESH_MARGIN）→ 直接复用；
    - 过期 → 尝试 refresh_login；失败 → 清空令牌后重新登录。
    """
    if force_login:
        clear_tokens()
        return await asyncio.to_thread(login)

    if tokens is None:
        tokens = _load_tokens()

    if tokens is not None and tokens.access_token:
        ttl = access_token_ttl(tokens.access_token)
        if ttl is None or ttl > TOKEN_REFRESH_MARGIN:
            return tokens

    refreshed = refresh_login(tokens)
    if refreshed is not None:
        return refreshed

    clear_tokens()
    return await asyncio.to_thread(login)


def _load_tokens() -> Tokens | None:
    try:
        credential = keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
        if credential is None:
            return None
        data = json.loads(credential)
        return Tokens(**data)
    except Exception as e:
        logger.warning(i18n.translate("user.login.load_tokens_failed", error=str(e)))
        return None


def refresh_login(tokens: Tokens | None = None) -> Tokens | None:
    """用 refresh token 换新令牌；tokens 缺省时从系统凭据管理器加载。"""
    tokens = tokens or _load_tokens()
    if tokens is None or not tokens.refresh_token:
        return None
    # 新契约（实测确认）：refresh token 经 Cookie 头传递（JSON body 会 401
    # "missing refresh token"），成功后服务器轮换 refresh_token（Set-Cookie 下发），
    # 必须保存新值，否则旧 token 因轮换被吊销（TOKEN_REVOKED）。
    try:
        req = urllib.request.Request(
            f"{SERVER_HOST}/api/user/auth/refresh",
            headers={"Cookie": f"refresh_token={tokens.refresh_token}"},
            method="POST",
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        cookies = _parse_set_cookies(resp)
        access = (cookies.get("access_token") or data.get("accessToken")
                  or data.get("access_token"))
        if not access:
            raise RuntimeError(f"refresh 接口未返回 accessToken: {data}")
        new_tokens = Tokens(
            access_token=access,
            refresh_token=(cookies.get("refresh_token") or data.get("refreshToken")
                           or tokens.refresh_token),
            expires_in=int(data.get("expiresIn") or data.get("expires_in") or 0),
        )
        save_tokens(new_tokens)
        logger.info(i18n.translate("user.login.auto_login_success", expires_in=new_tokens.expires_in))
        return new_tokens
    except Exception as e:
        logger.warning(i18n.translate("user.login.auto_login_failed", error=str(e)))
        # 旧契约兜底：JSON body 直接带 refreshToken
        try:
            req = urllib.request.Request(
                f"{SERVER_HOST}/api/user/auth/refresh",
                data=json.dumps({"refreshToken": tokens.refresh_token}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req)
            data = json.loads(resp.read())
            cookies = _parse_set_cookies(resp)
            access = (cookies.get("access_token") or data.get("accessToken")
                      or data.get("access_token"))
            if not access:
                raise RuntimeError(f"refresh 接口未返回 accessToken: {data}")
            new_tokens = Tokens(
                access_token=access,
                refresh_token=(cookies.get("refresh_token") or data.get("refreshToken")
                               or tokens.refresh_token),
                expires_in=int(data.get("expiresIn") or data.get("expires_in") or 0),
            )
            save_tokens(new_tokens)
            logger.info(i18n.translate("user.login.auto_login_success", expires_in=new_tokens.expires_in))
            return new_tokens
        except Exception as e2:
            logger.warning(i18n.translate("user.login.auto_login_failed", error=str(e2)))
            return None


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        port = s.getsockname()[1]
    return port


def _generate_pkce() -> tuple[str, str]:
    """生成 PKCE S256 的 verifier / challenge（用于服务器 handoff 流程换取 token）。"""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("utf-8")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _parse_set_cookies(resp) -> dict:
    """从响应头提取 Set-Cookie 键值对（新契约：token 经 Cookie 下发）。"""
    cookies = {}
    for header in resp.headers.get_all("Set-Cookie") or []:
        name, _, rest = header.partition("=")
        cookies[name.strip()] = rest.split(";", 1)[0].strip()
    return cookies


def _exchange_code(code: str, verifier: str) -> Tokens:
    """用回调拿到的 code + 本地 verifier 调 POST /api/user/auth/token 换取 tokens。

    新契约（实测确认）：换取成功返回 200，body 仅 {"expiresIn": N}，
    access_token（JWT）与 refresh_token（opaque）通过 Set-Cookie 响应头下发；
    同时保留旧契约兼容（body 直接带 accessToken）。
    """
    req = urllib.request.Request(
        f"{SERVER_HOST}/api/user/auth/token",
        data=json.dumps({"code": code, "verifier": verifier}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read())
    cookies = _parse_set_cookies(resp)
    access = (cookies.get("access_token") or data.get("accessToken")
              or data.get("access_token"))
    if not access:
        raise RuntimeError(f"token 接口未返回 accessToken: {data}")
    refresh = (cookies.get("refresh_token") or data.get("refreshToken")
               or data.get("refresh_token") or "")
    expires = int(data.get("expiresIn") or data.get("expires_in") or 0)
    return Tokens(access, refresh, expires)


def _is_port_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def login() -> Tokens:
    result: Tokens | None = None
    verifier, challenge = _generate_pkce()

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal result
            logger.info(f"回调收到: {self.path}")
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            access_token = params.get("accessToken", [None])[0]
            refresh_token = params.get("refreshToken", [None])[0]
            expires_in = int(params.get("expiresIn", ["0"])[0])
            code = params.get("code", [None])[0]

            try:
                if access_token:
                    # 旧契约：回调直接携带 token
                    result = Tokens(access_token, refresh_token, expires_in)
                elif code:
                    # 新契约（PKCE handoff）：回调携带 code，本地用 verifier 换取 token
                    logger.info("检测到 code，调用 /api/user/auth/token 换取 token ...")
                    result = _exchange_code(code, verifier)
                if result is not None:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<h1>Login successful! You can close this tab.</h1>")
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Missing token and code")
            except Exception as e:
                logger.warning(f"登录回跳处理失败: {e}")
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"Login handoff failed: {e}".encode("utf-8"))

        def log_message(self, format, *args):
            pass

    port = _find_free_port()
    if not _is_port_available(port):
        raise RuntimeError(i18n.translate("user.login.no_free_port"))

    server = http.server.HTTPServer(("127.0.0.1", port), CallbackHandler)

    frontend_url = urllib.parse.quote(f"http://localhost:{port}", safe="")
    challenge_q = urllib.parse.quote(challenge, safe="")
    resp = urllib.request.urlopen(
        f"{SERVER_HOST}/api/user/auth/authorize?redirectUrl={frontend_url}"
        f"&handoffChallenge={challenge_q}"
    )
    iam_url = json.loads(resp.read())["url"]

    logger.info(i18n.translate("user.login.opening_browser"))
    logger.info(i18n.translate("user.login.manual_login_hint", url=iam_url))
    webbrowser.open(iam_url)

    server.handle_request()
    server.server_close()

    if result is None:
        raise RuntimeError("Login failed")

    logger.info(i18n.translate("user.login.login_success", expires_in=result.expires_in))
    return result
