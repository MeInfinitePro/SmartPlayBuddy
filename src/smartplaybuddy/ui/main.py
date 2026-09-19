"""
主窗口模块。
内嵌 Web 应用作为主界面，通过 cookie 拦截同步令牌到 keyring。
keyring 为唯一令牌源，cookie 仅作为传输层。
认证状态变化通过 auth_changed 信号通知外部。
"""
import time
import asyncio
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage, QWebEngineScript
from PyQt6.QtCore import QUrl, QTimer, QDateTime, pyqtSignal
from PyQt6.QtNetwork import QNetworkCookie
from .config import Config
from ..user.login import (
    Tokens, save_tokens, clear_tokens, _load_tokens,
    access_token_ttl, decode_jwt_payload, refresh_login,
    ACCESS_COOKIE_NAME, REFRESH_COOKIE_NAME, TOKEN_REFRESH_MARGIN,
)
from .. import i18n


class MainWindow(QMainWindow):
    auth_changed = pyqtSignal(bool)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle(i18n.translate("app.name"))

        self._profile = QWebEngineProfile(self)
        self._profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self._profile.cookieStore().cookieAdded.connect(self._on_cookie)
        self._profile.cookieStore().cookieRemoved.connect(self._on_cookie_removed)

        self._web_view = QWebEngineView(self)
        self._web_view.setPage(QWebEnginePage(self._profile, self._web_view))
        self.setCentralWidget(self._web_view)
        self.resize(1280, 800)

        self._access_token = ""
        self._refresh_token = ""
        self._last_saved_token = ""
        self._last_cookie_activity = 0.0
        self._authenticated = False

        self._web_view.loadFinished.connect(self._on_load_finished)
        QTimer.singleShot(0, self._init_auth)

        self._logout_timer = QTimer(self)
        self._logout_timer.setInterval(2000)
        self._logout_timer.timeout.connect(self._check_logout)
        self._logout_timer.start()

    @property
    def web_url(self) -> str:
        """内嵌窗口实际加载的 Web 应用地址（单一来源：Config.web_url）。

        加载时把登录账号的 uid 动态注入查询参数，避免 URL 硬编码账号导致
        多账号下指令路由到错误设备：
          - 外层带 url= 参数（平台 mod 控制台包裹内层页面）→ 注入/覆盖内层 URL 的 uid；
          - 否则直接注入/覆盖外层 URL 的 uid。
        uid 未就绪（未登录）时原样返回，登录成功后 _inject_cookies 会用
        带 uid 的地址重新加载页面。"""
        uid = self._local_uid()
        if not uid:
            return Config.web_url
        return self._inject_uid(Config.web_url, uid)

    @staticmethod
    def _local_uid() -> str:
        """从登录令牌解析出的 Config.user 里取用户 id（与桥侧 _resolve_uid 同源）。"""
        user = getattr(Config, "user", None)
        if isinstance(user, dict) and user.get("uid") is not None:
            return str(user["uid"])
        return ""

    @staticmethod
    def _inject_uid(url: str, uid: str) -> str:
        """把 uid 注入/覆盖到 URL 查询参数；若外层带 url= 参数则注入其内层 URL。"""
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True)
        inner = next((v for k, v in query if k == "url"), None)
        if inner is None:
            new_query = [(k, v) for k, v in query if k != "uid"]
            new_query.append(("uid", uid))
            return urlunsplit(
                (parts.scheme, parts.netloc, parts.path, urlencode(new_query), parts.fragment)
            )
        inner_parts = urlsplit(inner)
        inner_query = [(k, v) for k, v in parse_qsl(inner_parts.query, keep_blank_values=True) if k != "uid"]
        inner_query.append(("uid", uid))
        new_inner = urlunsplit(
            (inner_parts.scheme, inner_parts.netloc, inner_parts.path,
             urlencode(inner_query), inner_parts.fragment)
        )
        outer_query = [(k, v) for k, v in query if k != "url"]
        outer_query.append(("url", new_inner))
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(outer_query), parts.fragment)
        )

    def _init_auth(self):
        """从 keyring 加载令牌：有效则注入 cookie；access token 过期但 refresh token
        仍可用时后台静默刷新（不阻塞 Qt 主线程）；都失败才加载 Web 应用并弹出登录对话框。"""
        tokens = _load_tokens()
        web_url = self.web_url
        if tokens and tokens.access_token:
            ttl = access_token_ttl(tokens.access_token)
            if ttl is None or ttl > TOKEN_REFRESH_MARGIN:
                self._apply_tokens(tokens)
                return
            # access token 已过期/临近过期：先展示窗口，再在后台线程刷新，避免阻塞 UI
            self._web_view.load(QUrl(web_url))
            self.show()
            asyncio.ensure_future(self._refresh_tokens(tokens))
            return
        self._web_view.load(QUrl(web_url))
        self.show()
        QTimer.singleShot(300, self._show_login_dialog)

    async def _refresh_tokens(self, tokens: Tokens):
        """在线程池中执行同步的 refresh_login，避免阻塞 Qt 主线程；失败则弹登录框。"""
        loop = asyncio.get_running_loop()
        refreshed = await loop.run_in_executor(None, refresh_login, tokens)
        if refreshed is not None:
            self._apply_tokens(refreshed)
        else:
            QTimer.singleShot(0, self._show_login_dialog)

    def _apply_tokens(self, tokens: Tokens):
        """令牌可用：写入 Config.user、注入 cookie 并置为已认证。"""
        Config.user = decode_jwt_payload(tokens.access_token)
        self._inject_cookies(tokens)
        self._set_authenticated(True)

    def _show_login_dialog(self):
        """弹出登录对话框，成功后刷新主窗口；取消则保留当前状态。"""
        from .login import gui_login
        try:
            tokens = gui_login(self.config.server_host)
        except RuntimeError:
            return
        self._apply_tokens(tokens)

    def request_logout(self):
        """前端经本地桥发起的退出登录：清空本机凭据并回到统一登录态。

        _set_authenticated(False) 触发 auth_changed 信号，外部会把 client
        连接与本地桥一并停掉；随后重载页面并弹出统一 IAM 浏览器登录。"""
        from ..user.login import clear_tokens
        clear_tokens()
        Config.user = {}  # 清空登录身份：避免重载页面时注入旧 uid / whoami 返回旧账号
        self._access_token = ""
        self._refresh_token = ""
        self._last_saved_token = ""
        self._set_authenticated(False)
        self._web_view.load(QUrl(self.web_url))
        QTimer.singleShot(300, self._show_login_dialog)

    def _inject_cookies(self, tokens: Tokens):
        """从 keyring 读取令牌，注入 cookie 和 localStorage 到 Web 视图。"""
        target_url = QUrl(self.web_url)
        store = self._profile.cookieStore()

        self._last_saved_token = tokens.access_token
        self._last_cookie_activity = time.monotonic()

        for name, value, path in [
            (ACCESS_COOKIE_NAME, tokens.access_token, "/"),
            (REFRESH_COOKIE_NAME, tokens.refresh_token, "/api/user/auth"),
        ]:
            if not value:
                continue
            cookie = QNetworkCookie(name.encode(), value.encode())
            cookie.setPath(path)
            cookie.setHttpOnly(True)
            cookie.setExpirationDate(QDateTime.currentDateTime().addSecs(86400))
            store.setCookie(cookie, target_url)

        js = QWebEngineScript()
        js.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        js.setWorldId(0)
        js.setName("__smtplay_auth")
        js.setSourceCode(
            'localStorage.setItem("smtplay_authenticated", "1");'
            'localStorage.setItem("smtplay_token_expires_at", String(Date.now() + 86400000));'
        )
        self._profile.scripts().insert(js)

        self._web_view.load(target_url)

    def _on_load_finished(self, ok):
        """页面加载完成后清理注入脚本。"""
        if not ok:
            return
        if not self.isVisible():
            self.show()
        for s in self._profile.scripts().find("__smtplay_auth"):
            self._profile.scripts().remove(s)

    def _on_cookie_removed(self, cookie: QNetworkCookie):
        """cookie 被删除时，若距上次 cookie 活动不足 2 秒则视为启动注入，跳过。"""
        name = bytes(cookie.name()).decode("utf-8", errors="ignore")
        if name == ACCESS_COOKIE_NAME:
            if time.monotonic() - self._last_cookie_activity < 2.0:
                return
            clear_tokens()
            self._set_authenticated(False)

    def _on_cookie(self, cookie: QNetworkCookie):
        """拦截服务端 cookie，同步写入 keyring。"""
        name = bytes(cookie.name()).decode("utf-8", errors="ignore")
        value = bytes(cookie.value()).decode("utf-8")

        if name == ACCESS_COOKIE_NAME and not value:
            clear_tokens()
            self._set_authenticated(False)
            return

        if name == ACCESS_COOKIE_NAME:
            self._access_token = value
        elif name == REFRESH_COOKIE_NAME:
            self._refresh_token = value
        else:
            return

        self._last_cookie_activity = time.monotonic()
        QTimer.singleShot(200, self._flush_tokens)

    def _flush_tokens(self):
        """合并写入 keyring（去重：令牌未变化时跳过）。"""
        if not self._access_token:
            return
        if self._access_token == self._last_saved_token:
            return
        tokens = Tokens(
            access_token=self._access_token,
            refresh_token=self._refresh_token,
            expires_in=0,
        )
        save_tokens(tokens)
        self._last_saved_token = self._access_token
        Config.user = decode_jwt_payload(tokens.access_token)
        self._set_authenticated(True)

    def _check_logout(self):
        """轮询 localStorage 检测退出登录（后备机制）。"""
        if not self._authenticated:
            return
        self._web_view.page().runJavaScript(
            "localStorage.getItem('smtplay_authenticated')",
            self._on_logout_check
        )

    def _on_logout_check(self, result):
        if result is None and self._authenticated:
            clear_tokens()
            self._set_authenticated(False)

    def _set_authenticated(self, value: bool):
        if self._authenticated == value:
            return
        self._authenticated = value
        self.auth_changed.emit(value)

    def set_native_bridge(self, ws_url: str, token: str):
        """把本地 WS 桥地址与一次性会话 token 注入顶层页面。

        安全要点：setRunsOnSubFrames(False) 确保只注入平台页，
        绝不注入第三方 mod iframe——mod 只能通过 postMessage 与平台页通信，
        拿不到控制本机键鼠的本地桥凭据。
        """
        source = (
            f'window.__smtplay_native = {{wsUrl: "{ws_url}", token: "{token}"}};'
            'window.dispatchEvent(new Event("smtplay-native-ready"));'
        )
        for s in self._profile.scripts().find("__smtplay_native"):
            self._profile.scripts().remove(s)

        js = QWebEngineScript()
        js.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        js.setWorldId(0)
        js.setRunsOnSubFrames(False)
        js.setName("__smtplay_native")
        js.setSourceCode(source)
        self._profile.scripts().insert(js)

        # 页面可能已加载完成，立即补设一次并派发事件，避免竞态
        self._web_view.page().runJavaScript(source)

    def clear_native_bridge(self):
        """退出登录/桥停止后清除注入，避免网页连向已失效的本地端口。"""
        for s in self._profile.scripts().find("__smtplay_native"):
            self._profile.scripts().remove(s)
        self._web_view.page().runJavaScript(
            'delete window.__smtplay_native;'
            'window.dispatchEvent(new Event("smtplay-native-gone"));'
        )

    def on_close(self):
        self._logout_timer.stop()
        page = self._web_view.page()
        self._web_view.setPage(None)
        if page:
            page.deleteLater()
        self._profile.deleteLater()
