/**
 * serverSession.js —— 服务端会话身份（对齐 SmartBuddy_Web 认证契约）。
 *
 * 适用场景：本前端被 SmartBuddy_Web 的 mod 控制台（/mods/:mod）以 iframe 挂载、
 * 或独立部署在认证服务同域下。此时「本机桥」（To=local）不存在，
 * 身份与登出只能直接使用服务端提供的服务（HttpOnly cookie 同域自动携带）：
 *
 *   WS   /ws                          连接后 session/claim + session/status → { userId, device }
 *   POST /api/user/auth/logout  {}    撤 JTI + 吊销 refresh token + 清 cookie
 *
 * 注意：跨域 iframe（页面与认证服务不同源）时 cookie 不会随请求携带，
 * 身份获取与登出都会失败——本前端必须与认证服务同域部署才能走通此模块。
 */

/** base64（UTF-8 安全，deviceName 可能含非 ASCII） */
function b64utf8(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = '';
  bytes.forEach((b) => { bin += String.fromCharCode(b); });
  return btoa(bin);
}

/** 解码服务端 wire.data（base64 → JSON 对象/字符串；兼容直接给对象的情况） */
function decodeData(data) {
  if (data == null) return null;
  if (typeof data !== 'string') return data;
  try {
    const text = new TextDecoder().decode(
      Uint8Array.from(atob(data), (c) => c.charCodeAt(0)),
    );
    try { return JSON.parse(text); } catch { return text; }
  } catch {
    return data;
  }
}

/**
 * 连接服务端 /ws 并取回当前会话身份。
 * @returns {Promise<{userId: string, device: object|null}>}
 */
export function fetchServerIdentity({ timeoutMs = 8000 } = {}) {
  return new Promise((resolve, reject) => {
    let ws = null;
    let done = false;
    const finish = (fn, arg) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      try { ws && ws.close(); } catch { /* 已关闭 */ }
      fn(arg);
    };
    const timer = setTimeout(
      () => finish(reject, new Error('服务端会话身份获取超时（未登录或跨域部署）')),
      timeoutMs,
    );

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    try {
      ws = new WebSocket(`${proto}//${location.host}/ws`);
    } catch (e) {
      clearTimeout(timer);
      reject(e);
      return;
    }

    ws.onopen = () => {
      // deviceName 加随机后缀：同一浏览器多个控制台标签页各挂一个 iframe 时避免 claim 冲突
      const device = {
        type: 'web',
        deviceName: `starrail-web-${Math.random().toString(36).slice(2, 7)}`,
        platform: navigator.platform,
        appVersion: '1.0.0',
        screenResolution: `${screen.width}x${screen.height}`,
      };
      ws.send(JSON.stringify({
        type: 'session', action: 'claim', timestamp: Date.now(),
        data: b64utf8(JSON.stringify({ device })),
      }));
      ws.send(JSON.stringify({ type: 'session', action: 'status', timestamp: Date.now() }));
    };

    ws.onmessage = (ev) => {
      try {
        const wire = JSON.parse(ev.data);
        if (wire.type !== 'session' || wire.action !== 'status') return;
        const data = decodeData(wire.data);
        if (data && data.userId != null && data.userId !== '') {
          finish(resolve, { userId: String(data.userId), device: data.device || null });
        } else {
          finish(reject, new Error('服务端会话未认证（userId 为空），请先在控制台登录'));
        }
      } catch { /* 非 JSON 帧，忽略 */ }
    };
    ws.onerror = () => finish(reject, new Error('服务端 /ws 连接失败（跨域部署或网络不可达）'));
    ws.onclose = () => finish(reject, new Error('服务端 /ws 连接已关闭（会话过期）'));
  });
}

/**
 * 服务端登出（与 SmartBuddy_Web 完全同款）：撤 JTI + 吊销 refresh + 清 cookie。
 * 登出后挂载我们的控制台页会话随之失效（其 WS 断开、路由回登录页）。
 */
export async function serverLogout({ timeoutMs = 8000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch('/api/user/auth/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
      credentials: 'same-origin',
      signal: ctrl.signal,
    });
    // 404/405：服务端未部署新契约——不算失败，交由上层决定是否回退
    if (!res.ok && res.status !== 404 && res.status !== 405) {
      throw new Error(`登出失败（HTTP ${res.status}）`);
    }
    return res.ok;
  } finally {
    clearTimeout(timer);
  }
}
