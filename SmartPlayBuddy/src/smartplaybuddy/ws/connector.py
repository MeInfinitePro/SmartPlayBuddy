"""
WebSocket 连接器基类。
处理 text + binary 双帧协议：当 text 帧标记 __binary__=true 时，
等待紧随其后的 binary 帧完成配对，再派发到 main()。

移植自上游 SmartBuddy 的健壮性改进（保留本仓库"外层续期循环"架构，
不引入内层自动重连，避免与 client/mod 已有的外层循环双循环打架）：
  - 握手被拒(InvalidStatus)识别：记录 close_code，token 过期/吊销时便于外层循环决策；
  - CLOSE_CODE_TOKEN_REVOKED(4001)：access token 被吊销(他处登出)时外层应 force_login；
  - claim 被拒快速断开：连接建立后 CLAIM_WINDOW 内收到"无 from 的 error"
    即判定 claim 失败，主动断开触发外层重连（否则要等服务端 PongWait 60s）；
  - send/send_pair 原子发送：保证 text(binary=true) 与 binary 帧成对写出。
"""
import asyncio
import time
import websockets
import json
from abc import ABC, abstractmethod
from .. import i18n
from .. import log
from ..config import WS_URL as _DEFAULT_WS_URL
from . import logic
from . import message

try:  # websockets >= 14 抛 InvalidStatus，旧版本抛 InvalidStatusCode
    from websockets.exceptions import InvalidStatus as _InvalidStatus
except ImportError:  # pragma: no cover
    from websockets.exceptions import InvalidStatusCode as _InvalidStatus

logger = log.logger.getChild("Connector")

# 服务端在 access token 被吊销(他处登出)时使用的关闭码，见 claimlogic.go closeCodeTokenRevoked。
# 此时 refresh token 通常一并被吊销，外层重连循环应走 force_login 重新走浏览器登录。
CLOSE_CODE_TOKEN_REVOKED = 4001

#: claim 生效观察窗口(秒)。窗口内收到"无 from 的 error"即判定 claim 被拒。
CLAIM_WINDOW = 10.0


class Connector(ABC):
    """WebSocket 连接器抽象基类，子类需实现 main() 处理业务消息。"""
    conn: websockets.ClientConnection

    System: "SystemCls"
    Session: "SessionCls"
    Error: "ErrorCls"

    def __init__(self, **config):
        self.url = config.get("url", _DEFAULT_WS_URL)
        self.close_code: int | None = None
        self._claim_pending = False
        self._connected_at = 0.0
        # 连接关闭信号：on_close 时置位，供外层重连/续期循环观察（client/mod 同款）
        self._closed = asyncio.Event()
        # text(binary=true) 与其后的 binary 帧必须成对写出：
        # 服务端 ReadLoop 用 lastText* 缓存做配对，中间插入任何其他文本帧都会错配。
        self._send_lock = asyncio.Lock()
        try:
            self.connection = asyncio.create_task(self.connect(config))
        except Exception as e:
            logger.error(i18n.translate("connector.task_create_failed", error=e))

    async def send(self, payload: str | bytes):
        """原子发送单帧（text 或 binary），避免与 send_pair 交叉错配。"""
        async with self._send_lock:
            await self.conn.send(payload)

    async def send_pair(self, meta: "message.Message", binary: bytes):
        """原子发送元数据帧 + 二进制帧。"""
        async with self._send_lock:
            await self.conn.send(meta.to_json())
            await self.conn.send(binary)

    async def connect(self, config):
        logger.debug(i18n.translate("message.connecting"))
        try:
            self.conn = await websockets.connect(
                self.url,
                additional_headers=config.get("headers"),
                max_size=None,
                compression=None,
            )
            self._connected_at = time.monotonic()
            logger.debug(i18n.translate("message.connect_success"))

            self.System = self.SystemCls(self.conn)
            self.Session = self.SessionCls(self.conn)
            self.Error = self.ErrorCls(self.conn)

            # 向服务端声明设备状态
            self._claim_pending = True
            await self.Session.claims(config.get("status"))

            await self.loop()
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            logger.error(i18n.translate("message.connect_timeout"))
        except _InvalidStatus as e:
            # 握手被拒：missing / invalid / revoked token。
            # 记录状态码供外层循环判断：401→刷新令牌，4001→force_login。
            status = getattr(getattr(e, "response", None), "status_code", None)
            self.close_code = status
            logger.warning(i18n.translate("connector.handshake_rejected", code=status, error=e))
        except websockets.exceptions.ConnectionClosed as e:
            if e.rcvd is not None:
                self.close_code = e.rcvd.code
                if e.rcvd.code == CLOSE_CODE_TOKEN_REVOKED:
                    logger.warning(i18n.translate("connector.token_revoked", code=e.rcvd.code))
                elif e.rcvd.code != 1000:
                    logger.error(i18n.translate("connector.connect_closed_error", code=e.rcvd.code, reason=e.rcvd.reason))
            logger.warning(i18n.translate("message.connect_closed"))
        except ConnectionRefusedError:
            logger.error(i18n.translate("message.connect_server_failed"))
        except Exception as e:
            logger.error(i18n.translate("connector.loop_exception", error=e), exc_info=True)
        finally:
            self._claim_pending = False
            self.on_close()

    def on_close(self):
        # 默认：置位关闭信号，供外层重连/续期循环观察。
        # 子类 override 时应自行置位 _closed 或调用 super().on_close()。
        closed = getattr(self, "_closed", None)
        if closed is not None:
            closed.set()

    async def loop(self):
        """消息主循环：接收 text/binary 帧，配对后派发到 main()。"""
        pending = None
        while True:
            try:
                raw = await self.conn.recv()

                # 二进制帧：与前置 pending 的 text 帧配对
                if isinstance(raw, bytes):
                    logger.debug(i18n.translate("connector.binary_received", size=len(raw)))
                    if pending is not None:
                        pending.BinaryData = raw
                        msg = pending
                        pending = None
                        logger.debug(i18n.translate("connector.binary_paired", type=msg.Type, action=msg.Action))
                    else:
                        logger.error(i18n.translate("connector.binary_without_text"))
                        continue
                # 文本帧：解析 JSON 并检查是否需要等待后续二进制帧
                else:
                    try:
                        d = json.loads(raw)
                        msg = self.Message.from_json(d)
                        logger.debug(i18n.translate("connector.msg_received", msg=msg))
                    except json.decoder.JSONDecodeError:
                        logger.error(i18n.translate("connector.msg_parse_failed", msg=raw))
                        continue
                    except KeyError as e:
                        logger.error(i18n.translate("connector.msg_field_missing", field=e.args[0], msg=raw))
                        await self.Error.error(d, To=d.get("from"), RequestID=d.get("requestId"))
                        continue

                    # Data 为 Base64 编码的 JSON，尝试解码
                    if isinstance(msg.Data, str):
                        import base64 as _b64
                        try:
                            decoded = json.loads(_b64.b64decode(msg.Data).decode("utf-8"))
                            msg.Data = decoded
                        except Exception:
                            try:
                                msg.Data = json.loads(msg.Data)
                            except (json.JSONDecodeError, ValueError):
                                pass

                    # 标记 __binary__ 的消息需要等待后续二进制帧
                    if isinstance(msg.Data, dict) and msg.Data.pop("__binary__", False):
                        pending = msg
                        logger.debug(i18n.translate("connector.pending_set"))
                        continue

                # 服务端自身产生的 error 没有 from(claim 被拒 / 未知消息类型 / 路由失败)。
                if msg.Type == "error" and not msg.From:
                    if self._claim_pending and time.monotonic() - self._connected_at <= CLAIM_WINDOW:
                        # claim 被拒时连接依然"健康"，但本连接没有任何设备身份，
                        # 之后所有消息都会被服务端以 "device not found in connection status" 拒绝。
                        # 必须主动断开触发外层重连：服务端要等 PongWait(60s) 才回收残留会话，
                        # 重连一轮即可 claim 成功。
                        self._claim_pending = False
                        logger.error(i18n.translate("connector.claim_rejected", reason=msg.Data))
                        await self._drop_connection()
                        break

                # 收到任何带 from 的消息说明服务端已按本设备地址完成路由，claim 必然已生效
                if msg.From:
                    self._claim_pending = False

                # 系统消息走内部逻辑，其余派发到子类
                if msg.Type == "system":
                    logic.system(self, msg)
                await self.main(msg)
            except websockets.exceptions.ConnectionClosed:
                break
            except Exception as e:
                logger.error(i18n.translate("connector.loop_exception", error=e), exc_info=True)
                break
        logger.debug(i18n.translate("connector.loop_exited"))

    async def _drop_connection(self):
        conn = getattr(self, "conn", None)
        if conn is None:
            return
        try:
            await conn.close()
        except Exception:
            pass

    @abstractmethod
    async def main(self, msg: "Message") -> None:
        """子类实现：处理接收到的业务消息。"""
        logger.debug(i18n.translate("connector.msg_received", msg=msg))


    Message = message.Message


    class SystemCls:
        def __init__(self, conn: websockets.ClientConnection):
            self.conn = conn

        async def ping(self):
            await self.conn.send(message.system.ping())


    class SessionCls:
        def __init__(self, conn: websockets.ClientConnection):
            self.conn = conn

        async def claims(self, status: dict):
            await self.conn.send(message.session.claim(status))


    class ErrorCls:
        def __init__(self, conn: websockets.ClientConnection):
            self.conn = conn

        async def error(self, data, To: str | None = None, RequestID: str | None = None):
            if not To:
                # 无 to 的消息一般由服务端自行处理，本地无处可回，静默丢弃(不再告警刷屏)
                return
            await self.conn.send(message.error.error(data, To=To, RequestID=RequestID))
