/**
 * 清理开拓力（主页功能模块 + 设置页的「体力计划」）：
 * - 主页仅保留「开始清体力」执行按钮，按设置页方案执行
 * - 设置页：体力计划（0-30 滑杆）、战利品类型、是否使用后备开拓力、查询当前开拓力
 * - 主页卡片实时同步当前计划文案
 */
import { api, pollJob } from './api.js';
import { pushLog } from './log.js';

const $ = (id) => document.getElementById(id);

const el = {
  // 主页
  btnClear: $('btn-clear-power'),
  progress: $('power-progress'),
  error: $('power-error'),
  planHint: $('power-plan-hint'),
  // 设置页
  btnQuery: $('btn-query-power'),
  queryError: $('power-query-error'),
  info: $('power-info'),
  current: $('power-current'),
  reserve: $('power-reserve'),
  slider: $('power-num'),
  sliderText: $('power-num-text'),
  planText: $('power-plan-text'),
  useReserve: $('use-reserve'),
};

const LOOT_NAMES = { 1: '信用点', 2: '角色经验', 3: '光锥经验' };

let busy = false;
let seenCount = 0;

function targetClient() {
  return ($('target-client') ? $('target-client').value : '').trim() || undefined;
}

function setBusy(v) {
  busy = v;
  el.btnClear.disabled = v;
  el.btnQuery.disabled = v;
  el.slider.disabled = v;
  el.useReserve.disabled = v;
  document.querySelectorAll('input[name="selection"]').forEach((r) => (r.disabled = v));
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
  pushLog('err', `清体力失败：${e.message || String(e)}`);
  setBusy(false);
}

// ---- 体力计划文案 ----
function planText(n) {
  return n === 0 ? '全部清完' : `${n} 次（${n * 10} 点开拓力）`;
}

function selectionValue() {
  const checked = document.querySelector('input[name="selection"]:checked');
  return checked ? Number(checked.value) : 1;
}

function currentPlanText() {
  const n = Number(el.slider.value);
  const base = n === 0 ? '全部清完' : `清理 ${n} 次（${n * 10} 点）`;
  const loot = LOOT_NAMES[selectionValue()] || '信用点';
  const reserve = el.useReserve.checked ? ' · 使用后备开拓力' : '';
  return `${base} · ${loot}${reserve}`;
}

function syncSlider() {
  const n = Number(el.slider.value);
  el.sliderText.textContent = n === 0 ? '全部清完' : `${n * 10} 点`;
  el.planText.textContent = planText(n);
  if (el.planHint) el.planHint.textContent = `当前计划：${currentPlanText()}`;
}

// ---- 查询当前开拓力 ----
async function queryPower() {
  setBusy(true);
  clearError();
  el.queryError.style.display = 'none';
  try {
    const resp = await api.powerQuery(targetClient());
    const data = (resp.result && resp.result.data) || {};
    el.current.textContent = data.current_power ?? '未知';
    el.reserve.textContent = data.reserve_power ?? '未知';
    el.info.style.display = 'flex';
    pushLog('info', `查询开拓力：当前 ${data.current_power ?? '未知'} / 后备 ${data.reserve_power ?? '未知'}`);
  } catch (e) {
    const msg = e.unauthorized ? '登录已过期，请刷新页面重新通过统一登录。' : (e.message || String(e));
    el.queryError.textContent = `❌ ${msg}`;
    el.queryError.style.display = 'block';
    pushLog('err', `查询开拓力失败：${msg}`);
  } finally {
    setBusy(false);
  }
}

// ---- 开始清理 ----
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
  pushLog('info', `⏳ 开始清体力（${currentPlanText()}）…`);
  pollJob(jobId, {
    onEvent: (events) => {
      renderEvents(events, true, false);
      syncEventsToLog(events);
    },
  })
    .then((job) => {
      renderEvents(job.events || [], false, true);
      syncEventsToLog(job.events || []);
      pushLog('ok', '✅ 清体力执行完成');
      if (job.result) {
        pushLog('info', `清体力结果：${JSON.stringify(job.result)}`);
      }
      setBusy(false);
    })
    .catch((e) => {
      renderEvents([], false, false);
      el.progress.insertAdjacentHTML(
        'beforeend',
        `<div class="line error">❌ ${e.message || '任务执行失败'}</div>`,
      );
      pushLog('err', `清体力任务中断：${e.message || String(e)}`);
      setBusy(false);
    });
}

async function startClear() {
  if (busy) return;
  setBusy(true);
  clearError();
  el.progress.style.display = 'none';
  try {
    const resp = await api.clearPower(
      Number(el.slider.value),
      selectionValue(),
      el.useReserve.checked,
      targetClient(),
    );
    startJob(resp.jobId);
  } catch (e) {
    handleErr(e);
  }
}

export function initPower() {
  el.btnClear.addEventListener('click', startClear);
  el.btnQuery.addEventListener('click', queryPower);
  el.slider.addEventListener('input', syncSlider);
  document.querySelectorAll('input[name="selection"]').forEach((r) => r.addEventListener('change', syncSlider));
  el.useReserve.addEventListener('change', syncSlider);
  syncSlider();
}
