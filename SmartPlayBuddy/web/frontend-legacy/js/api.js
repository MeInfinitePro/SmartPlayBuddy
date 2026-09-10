/**
 * 后端 API 封装（纯 JS，无框架）。
 * 认证依赖后端会话 Cookie（统一登录回跳 /api/auth/callback 建立），
 * 前端自身不含任何登录页面。
 */

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

export const api = {
  // ---- 认证 ----
  me: () => request('GET', '/api/auth/me'),
  logout: () => request('POST', '/api/auth/logout'),

  // ---- 星穹铁道指令 ----
  powerQuery: (targetClient) =>
    request('GET', `/api/starrail/power${targetClient ? `?targetClient=${encodeURIComponent(targetClient)}` : ''}`),
  dailyObserve: (targetClient) =>
    request('GET', `/api/starrail/daily-task/observe${targetClient ? `?targetClient=${encodeURIComponent(targetClient)}` : ''}`),
  dailyTask: (taskIds, targetClient) =>
    request('POST', '/api/starrail/daily-task', { taskIds, targetClient }),
  dailyReward: (targetClient) =>
    request('POST', '/api/starrail/daily-task/reward', { targetClient }),
  clearPower: (powerNum, selection, useReserve, targetClient) =>
    request('POST', '/api/starrail/clear-power', {
      powerNum, selection, useReserve, targetClient,
    }),
  job: (jobId) => request('GET', `/api/jobs/${jobId}`),
};

/**
 * 轮询 Job 直到结束（长操作：daily_task / clear_power 等）。
 * onEvent(events) 在每次轮询时回调最新进度列表。
 */
export function pollJob(jobId, { onEvent, intervalMs = 2000 } = {}) {
  return new Promise((resolve, reject) => {
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
          // 登录失效 / 任务已被清理（如后端重启丢内存 Job）：
          // 继续轮询没有意义，立即结束，避免页面永久卡在“执行中”、按钮无法恢复
          clearInterval(timer);
          reject(e);
        }
        // 其它（网络抖动等）单次失败不中断，继续重试
      }
    }, intervalMs);
  });
}
