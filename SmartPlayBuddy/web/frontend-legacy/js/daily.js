/**
 * 每日实训（主页功能模块）：
 * 主页仅保留「执行完整日常」按钮 —— 服务端完整流程：
 * 观察任务列表 → 逐项执行 → 领取每日实训奖励。
 * 实时进度展示在卡片下方，并同步写入「日志」页。
 */
import { api, pollJob } from './api.js';
import { pushLog } from './log.js';

const $ = (id) => document.getElementById(id);

const el = {
  btn: $('btn-run-daily'),
  progress: $('daily-progress'),
  error: $('daily-error'),
};

let busy = false;
let seenCount = 0; // 已同步到「日志」页的事件数

function targetClient() {
  return ($('target-client') ? $('target-client').value : '').trim() || undefined;
}

function setBusy(v) {
  busy = v;
  el.btn.disabled = v;
  if ($('target-client')) $('target-client').disabled = v;
}

function showError(msg) {
  el.error.textContent = `❌ ${msg}`;
  el.error.style.display = 'block';
}

function clearError() {
  el.error.style.display = 'none';
}

function handleErr(e) {
  showError(e.unauthorized ? '登录已过期，请刷新页面重新通过统一登录。' : (e.message || String(e)));
  pushLog('err', `每日实训失败：${e.message || String(e)}`);
  setBusy(false);
}

function fmtTime(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toTimeString().slice(0, 8);
}

function renderEvents(events, running, done) {
  el.progress.style.display = 'block';
  const lines = [];
  if (running) {
    lines.push('<div class="line"><b>⏳ 执行中…</b> 游戏内自动化操作可能耗时较长，请勿操作该设备。</div>');
  }
  for (const ev of [...events].reverse()) {
    const detail = ev.detail ? `（${ev.detail}）` : '';
    lines.push(`<div class="line">[${fmtTime(ev.ts)}] <b>${ev.flow || '流程'}</b> — ${ev.step || ''} ${detail}</div>`);
  }
  if (done) lines.push('<div class="line result">✅ 执行完成</div>');
  el.progress.innerHTML = lines.join('');
  el.progress.scrollTop = el.progress.scrollHeight;
}

/** 将 job 新增的事件增量同步到「日志」页 */
function syncEventsToLog(events) {
  const fresh = events || [];
  for (let i = seenCount; i < fresh.length; i++) {
    const ev = fresh[i];
    pushLog('info', `[${ev.flow || '流程'}] ${ev.step || ''}${ev.detail ? `（${ev.detail}）` : ''}`);
  }
  seenCount = Math.max(seenCount, fresh.length);
}

function startJob(jobId) {
  setBusy(true);
  seenCount = 0;
  renderEvents([], true, false);
  pushLog('info', '⏳ 开始执行完整日常（观察 → 逐项执行 → 领取奖励）…');
  pollJob(jobId, {
    onEvent: (events) => {
      renderEvents(events, true, false);
      syncEventsToLog(events);
    },
  })
    .then((job) => {
      renderEvents(job.events || [], false, true);
      syncEventsToLog(job.events || []);
      pushLog('ok', '✅ 每日实训执行完成');
      if (job.result) {
        pushLog('info', `每日实训结果：${JSON.stringify(job.result)}`);
      }
      setBusy(false);
    })
    .catch((e) => {
      renderEvents([], false, false);
      el.progress.insertAdjacentHTML(
        'beforeend',
        `<div class="line error">❌ ${e.message || '任务执行失败'}</div>`,
      );
      pushLog('err', `每日实训任务中断：${e.message || String(e)}`);
      setBusy(false);
    });
}

async function runDaily() {
  if (busy) return;
  setBusy(true);
  clearError();
  el.progress.style.display = 'none';
  try {
    const resp = await api.dailyTask(undefined, targetClient());
    startJob(resp.jobId);
  } catch (e) {
    handleErr(e);
  }
}

export function initDaily() {
  el.btn.addEventListener('click', runDaily);
}
