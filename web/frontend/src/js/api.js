/**
 * 后端 API 封装（Vue 版，逻辑与 legacy js/api.js 一致）。
 * 认证依赖后端会话 Cookie（统一登录回跳 /api/auth/callback 建立），前端不含登录页。
 *
 * 平台桥接模式（智玩搭档控制台 iframe 内）：改由 __smtplay__ postMessage 桥
 * 直接指挥 mod 后端（见 js/platform.js），方法签名与返回形状与 REST 版一致。
 */
import {
  isPlatformMode, uid, modName, modRequest, modStartJob, modPollJob,
  whoami, logout as platformLogout,
} from './platform.js';

async function request(method, url, body) {
  const resp = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    credentials: 'same-origin',
  });
  if (resp.status === 401) {
    const err = new Error('UNAUTHORIZED');
    err.unauthorized = true;
    err.data = await resp.json().catch(() => ({}));
    throw err;
  }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const err = new Error(data.detail || `请求失败 (${resp.status})`);
    err.data = data;
    err.status = resp.status;
    throw err;
  }
  return data;
}

const restApi = {
  // ---- 认证 ----
  me: () => request('GET', '/api/auth/me'),
  /**
   * 登出：优先走新认证契约（POST /api/user/auth/logout —— 撤 JTI + 吊销
   * refresh token + 清 HttpOnly cookie，与 SmartBuddy_Web 同款服务端登出）；
   * 服务端未部署新契约（404/405）时回退旧 webapi 会话登出 /api/auth/logout。
   * 探测结果按 origin 记忆（sessionStorage），后续登出直接用对的端点，
   * 不再产生 405 网络报错噪音。平台桥接模式不走这里（见 platformApi.logout）。
   */
  logout: async () => {
    const memKey = 'spb_logout_endpoint';
    const remembered = sessionStorage.getItem(memKey);
    if (remembered === 'legacy') {
      await request('POST', '/api/auth/logout');
      return;
    }
    try {
      await request('POST', '/api/user/auth/logout', {});
      sessionStorage.setItem(memKey, 'new');
    } catch (e) {
      if (e?.status !== 404 && e?.status !== 405) throw e;
      await request('POST', '/api/auth/logout');
      sessionStorage.setItem(memKey, 'legacy');
    }
  },

  // ---- 星穹铁道指令 ----
  gameRunning: (targetClient) =>
    request('GET', `/api/starrail/game/running${targetClient ? `?targetClient=${encodeURIComponent(targetClient)}` : ''}`),
  gameOpen: (targetClient) =>
    request('POST', '/api/starrail/game/open', { targetClient }),
  dailyTask: (taskIds, targetClient) =>
    request('POST', '/api/starrail/daily-task', { taskIds, targetClient }),
  clearPower: (powerNum, selection, useReserve, targetClient) =>
    request('POST', '/api/starrail/clear-power', {
      powerNum, selection, useReserve, targetClient,
    }),
  job: (jobId) => request('GET', `/api/jobs/${jobId}`),
};

/** 平台桥接模式实现：返回形状与 restApi 一致，但直接指挥 mod 后端 */
const platformApi = {
  // 身份来源按运行环境分流（platform.whoami）：client 内嵌=本机桥登录令牌；
  // 控制台挂载=服务端 /ws session/status。URL uid 仅作兜底展示
  me: async () => {
    try {
      const info = await whoami();
      const display = info.name || info.nickname || info.username
        || (info.uid != null && info.uid !== '' ? String(info.uid) : '');
      return { authenticated: !!display, userId: display || uid || '平台用户' };
    } catch {
      return { authenticated: true, userId: uid || '平台用户' };
    }
  },
  // 退出按运行环境分流：client 内嵌=本机桥清 keyring；控制台挂载=服务端吊销会话
  logout: async () => {
    await platformLogout();
  },
  gameRunning: async () => ({
    running: !!(await modRequest('game/running', {}, { timeoutS: 30 })).running,
  }),
  gameOpen: async () => ({
    opened: !!(await modRequest('game/open', {}, { timeoutS: 900 })).opened,
  }),
  dailyTask: (taskIds) =>
    modStartJob('daily_task', taskIds && taskIds.length ? { task_ids: taskIds } : {}),
  clearPower: (powerNum, selection, useReserve) =>
    modStartJob('clear_power', { power_num: powerNum, selection, use_reserve: useReserve }),
};

export const api = isPlatformMode ? platformApi : restApi;

/**
 * 轮询 Job 直到结束（长操作：daily_task / clear_power 等）。
 * onEvent(events) 在每次轮询时回调最新进度列表。
 * 平台桥接模式下改由 modStartJob 创建的句柄直接交付事件与结果。
 */
function restPollJob(jobId, { onEvent, intervalMs = 2000 } = {}) {  return new Promise((resolve, reject) => {
    const timer = setInterval(async () => {
      try {
        const job = await api.job(jobId);
        if (onEvent) onEvent(job.events || []);
        if (job.status === 'ok') {
          clearInterval(timer);
          resolve(job);
        } else if (job.status === 'error') {
          clearInterval(timer);
          reject(new Error(job.error || '任务执行失败'));
        }
      } catch (e) {
        if (e.unauthorized || e.status === 404) {
          // 登录失效 / 任务已被清理（如后端重启丢内存 Job）：立即结束，避免永久卡“执行中”
          clearInterval(timer);
          reject(e);
        }
        // 其它（网络抖动等）单次失败不中断，继续重试
      }
    }, intervalMs);
  });
}

/** 平台桥接模式：pollJob 直接对接 mod 指令句柄 */
export const pollJob = isPlatformMode ? modPollJob : restPollJob;
