/**
 * platform.js —— 智玩搭档平台「iframe 桥接模式」（基于平台官方 SDK）。
 *
 * 依据《Mod 接入教程》：平台把本前端加载进 sandbox iframe，页面通过
 * SmtplayWSBridge 与平台 WS 双向通信——握手、来源识别（nonce 标记）、
 * Base64 编解码、二进制拆包全部由 SDK 封装，本模块只负责业务层翻译：
 * REST 调用 → mod 指令（requestId 匹配响应，event 消息作为任务进度）。
 *
 * SDK 以 vendored 方式打包进本仓库（smtplay-sdk-message.js / smtplay-sdk-bridge.js，
 * 拷贝自平台 /sdk/，2026-09-15 版本）：教程推荐的远程 import 在 HTTPS 页面里
 * 会被浏览器当混合内容拦截（平台入口是 http://），故本地化。
 *
 * 注意：SDK 必须单例（重复 new 会让前一个实例的标记失效），模块内只创建一次。
 */

import { SmtplayWSBridge } from './smtplay-sdk-bridge.js';
import { Message as SdkMessage } from './smtplay-sdk-message.js';

const qs = new URLSearchParams(location.search);

/** 是否平台桥接模式：处于 iframe 内（平台控制台）或显式 ?platform=1 */
export const isPlatformMode =
  qs.get('platform') === '1' || (window.parent !== window && qs.get('platform') !== '0');

/** userId：只认 ?uid=（显式传入）。
 *  - 内嵌 client 模式：登录后由 whoami（本机桥身份查询）提供真实身份；
 *  - 浏览器直开模式：必须在入口 URL 携带 &uid=，缺失时报错而非静默路由。
 *  2026-09-19：移除 localStorage 兜底——实测换账号后旧缓存导致新账号指令
 *  静默路由到旧账号设备（串号），宁可显式报错。 */
export const uid = qs.get('uid') || '';
let resolvedUid = uid;

/** whoami 成功后由上层写入本机登录身份（优先级高于 URL uid） */
export function setResolvedUid(u) {
  if (u !== null && u !== undefined && u !== '') resolvedUid = String(u);
}

/** 当前生效的 userId（whoami 结果 > URL uid） */
export function getUid() {
  return resolvedUid;
}

/** mod 设备名：?mod= > localStorage > starrail */
export const modName = qs.get('mod') || localStorage.getItem('spb_pf_mod') || 'starrail';

// 清理历史版本可能写入的旧 uid 缓存，避免任何残留影响路由
localStorage.removeItem('spb_pf_uid');
if (qs.get('mod')) localStorage.setItem('spb_pf_mod', modName);

export function modTarget() {
  if (!resolvedUid) return null;
  return `mod:${resolvedUid}:${modName}`;
}

// ---------- SDK 桥（异步初始化；未加载完成的发送会排队等待） ----------
let bridge = null;
let seenInbound = false; // 收到过任何回包 => 控制台 WS 链路活着（仅用于诊断提示）
let bridgeReady; // Promise<SmtplayWSBridge>
const pending = new Map(); // requestId -> {resolve, reject, timer}
let latestJobId = null; // event 消息无法按 requestId 路由（mod 侧自生成），投递给最新任务
const jobListeners = new Map(); // jobId -> onEvent

function initBridge() {
  bridgeReady = (async () => {
    bridge = new SmtplayWSBridge(); // 单例；构造时自动向平台握手
    bridge.recv((msg) => {
      if (!seenInbound) console.info('[spb-pf] 平台桥回包首次到达，中继链路已通');
      seenInbound = true;
      try {
        console.info(
          `[spb-pf] 收到消息 type=${msg.type} requestId=${msg.requestId} data=`,
          typeof msg.data === 'string' ? msg.data.slice(0, 300) : msg.data,
        );
      } catch (_) { /* 日志失败不影响业务 */ }
      handleMessage(msg);
    });
    console.info(
      `[spb-pf] SmtplayWSBridge 就绪（${bridge.is_embedded() ? '已嵌入平台' : '独立运行，消息不会送达后端'}）`,
    );
    return bridge;
  })().catch((e) => {
    console.error('[spb-pf] SDK 加载失败：', e);
    throw e;
  });
}

function handleMessage(msg) {
  // SDK 已把 data 解码（JSON 串→对象）；msg 为 Message 实例

  // 进度事件（mod 的 event 消息不带我们的 requestId，投递给最新任务）
  if (msg.type === 'event' && msg.data && typeof msg.data === 'object') {
    const ev = {
      flow: msg.data.flow,
      step: msg.data.step,
      detail: msg.data.detail,
      state: msg.data.state,
      ts: msg.timestamp,
    };
    if (latestJobId && jobListeners.has(latestJobId)) {
      jobListeners.get(latestJobId)(ev);
    }
    return;
  }

  const entry = pending.get(msg.requestId);
  if (!entry) return;
  clearTimeout(entry.timer);
  pending.delete(msg.requestId);
  if (msg.type === 'error') {
    const detail = typeof msg.data === 'string' ? msg.data : JSON.stringify(msg.data);
    entry.reject(new Error(detail || 'mod 返回错误'));
  } else {
    // mod 的 response.data = {status:'ok', result: X}（与 REST 解包后一致）
    const payload = msg.data && typeof msg.data === 'object' ? msg.data : {};
    if (payload.status === 'error') {
      entry.reject(new Error(payload.message || 'mod 执行失败'));
    } else {
      entry.resolve(payload.result !== undefined ? payload.result : payload);
    }
  }
}

export function modRequest(operate, params = {}, { timeoutS = 60 } = {}) {
  const to = modTarget();
  if (!to) {
    return Promise.reject(
      new Error('缺少 userId：本机桥 whoami 未取到身份且 URL 未携带 &uid=，请先在 client 完成登录'),
    );
  }
  return bridgeReady.then((smtplay) => {
    const msg = new SdkMessage('command', modName, { operate, params }, { to });
    const requestId = msg.requestId;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        if (pending.has(requestId)) {
          pending.delete(requestId);
          if (!seenInbound) {
            reject(new Error(
              `${operate} 无响应且从未收到平台桥回包：控制台页面的 WS 会话可能已过期`
              + '（平台 token 仅 15 分钟有效），请刷新平台控制台页面（F5）后重试',
            ));
          } else {
            reject(new Error(`${operate} ${timeoutS}s 无响应（mod 未连接或指令超时）`));
          }
        }
      }, timeoutS * 1000);
      pending.set(requestId, { resolve, reject, timer });
      try {
        console.info(
          `[spb-pf] 发送指令 operate=${operate} to=${to} requestId=${requestId}`,
        );
      } catch (_) { /* 日志失败不影响业务 */ }
      smtplay.send(msg);
    });
  });
}

/**
 * 本机 system 指令（To=local，桥就地处理、不透传服务端）。
 * 响应经 handleMessage 按 requestId 匹配 resolve。
 */
function bridgeCall(action, { timeoutS = 10 } = {}) {
  return bridgeReady.then((smtplay) => new Promise((resolve, reject) => {
    const msg = new SdkMessage('system', action, null, { to: 'local' });
    const requestId = msg.requestId;
    const timer = setTimeout(() => {
      if (pending.has(requestId)) {
        pending.delete(requestId);
        reject(new Error(`${action} ${timeoutS}s 无响应（本机桥未就绪或已断开）`));
      }
    }, timeoutS * 1000);
    pending.set(requestId, { resolve, reject, timer });
    smtplay.send(msg);
  }));
}

/** 查询本机 client 登录身份：返回 {uid, name?, ...}；uid 为空说明 client 未登录 */
export function whoami(opts) {
  return bridgeCall('whoami', opts);
}

/** 请求本机 client 退出登录（清令牌、断开桥、回到统一 IAM 登录） */
export function bridgeLogout(opts) {
  return bridgeCall('logout', opts);
}

if (isPlatformMode) {
  initBridge();
}

// ---------- Job 抽象（对齐 webapi 的 jobId + events + 轮询接口） ----------
let jobSeq = 0;
const jobs = new Map(); // jobId -> {events, listeners, promise}

export function modStartJob(operate, params = {}, { timeoutS = 3600 } = {}) {
  const jobId = `bridge-${++jobSeq}`;
  const handle = { events: [], listeners: [], promise: null };
  handle.promise = new Promise((resolve, reject) => {
    modRequest(operate, params, { timeoutS }).then(
      (result) => resolve({ status: 'ok', result, events: handle.events }),
      (e) => reject(e),
    );
    // event 消息无法按 requestId 路由（mod 侧自生成），改用 latestJobId 投递
    jobListeners.set(jobId, (ev) => {
      handle.events.push(ev);
      handle.listeners.forEach((f) => f(handle.events));
    });
    latestJobId = jobId;
  });
  jobs.set(jobId, handle);
  return { mode: 'job', jobId };
}

/** 与 js/api.js 的 REST pollJob 同接口：轮询桥接任务直到结束 */
export function modPollJob(jobId, { onEvent } = {}) {
  const h = jobs.get(jobId);
  if (!h) return Promise.reject(new Error('任务不存在或已完成'));
  if (onEvent) {
    h.listeners.push(onEvent);
    onEvent(h.events); // 立即同步已有事件
  }
  return h.promise;
}
