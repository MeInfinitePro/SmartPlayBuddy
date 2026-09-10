/**
 * useJobRunner —— 长任务执行器（每日实训 / 清体力共用）。
 * 与原 daily.js / power.js 行为一致：
 *   调用 API 拿 jobId → pollJob 轮询 → 实时进度 + 增量同步到「日志」页。
 *  - moduleError：API 调用失败（显示在卡片上方的 error-msg）
 *  - boxError   ：轮询中断（显示在进度框底部 error 行）
 */
import { reactive } from 'vue';
import { api, pollJob } from '../js/api.js';
import { pushLog } from '../js/log.js';
import { fmtErr } from '../js/utils.js';

/**
 * @param {object} cfg
 * @param {() => Promise<{jobId:string}>} cfg.apiCall  发起任务，返回 jobId
 * @param {string | (() => string)} cfg.startLog  开始日志文案（可为函数，开跑时求值）
 * @param {string} cfg.okLog     完成日志文案
 * @param {string} cfg.errLabel  错误文案前缀（如“每日实训”）
 * @param {'daily'|'power'} cfg.activityKey 对应全局忙碌开关
 * @param {() => void} [cfg.onStart]  开跑前的清理（可选）
 * @param {() => Promise<string>} [cfg.preCheck]  执行前检查（可选）：
 *   返回非空字符串表示未通过（展示给用户并终止，不发起任务）；返回 ''/falsy 表示通过。
 */
export function useJobRunner(cfg) {
  const s = reactive({
    busy: false,
    running: false,   // 轮询中（用于“执行中…”提示行）
    done: false,
    events: [],       // 原始事件列表（升序）
    moduleError: '',  // API 层错误
    boxError: '',     // 轮询层错误
    seenCount: 0,     // 已同步到日志页的事件数
  });

  function setBusy(v) {
    s.busy = v;
    if (cfg.activityKey) cfg.activity[cfg.activityKey] = v;
  }

  /** 将新增事件增量同步到「日志」页 */
  function syncEventsToLog(events) {
    const fresh = events || [];
    for (let i = s.seenCount; i < fresh.length; i++) {
      const ev = fresh[i];
      pushLog('info', `[${ev.flow || '流程'}] ${ev.step || ''}${ev.detail ? `（${ev.detail}）` : ''}`);
    }
    s.seenCount = Math.max(s.seenCount, fresh.length);
  }

  function startPoll(jobId) {
    pollJob(jobId, {
      onEvent: (events) => {
        s.events = events;
        syncEventsToLog(events);
      },
    })
      .then((job) => {
        s.events = job.events || [];
        syncEventsToLog(job.events || []);
        s.running = false;
        s.done = true;
        pushLog('ok', cfg.okLog);
        if (job.result) {
          pushLog('info', `${cfg.errLabel}结果：${JSON.stringify(job.result)}`);
        }
        setBusy(false);
      })
      .catch((e) => {
        s.running = false;
        s.events = [];
        s.boxError = e.message || '任务执行失败';
        pushLog('err', `${cfg.errLabel}任务中断：${e.message || String(e)}`);
        setBusy(false);
      });
  }

  async function run() {
    if (s.busy) return;
    setBusy(true);
    s.moduleError = '';
    s.boxError = '';
    s.done = false;
    s.events = [];
    s.running = true;
    s.seenCount = 0;

    // 前置检查（如：游戏是否已启动）。未通过则提示并终止，不发起任务
    if (cfg.preCheck) {
      try {
        const blocked = await cfg.preCheck();
        if (blocked) {
          s.running = false;
          s.moduleError = blocked;
          pushLog('err', `${cfg.errLabel}未执行：${blocked}`);
          setBusy(false);
          return;
        }
      } catch (e) {
        s.running = false;
        s.moduleError = fmtErr(e);
        pushLog('err', `${cfg.errLabel}前置检查失败：${e.message || String(e)}`);
        setBusy(false);
        return;
      }
    }

    pushLog('info', typeof cfg.startLog === 'function' ? cfg.startLog() : cfg.startLog);
    if (cfg.onStart) cfg.onStart();
    try {
      const resp = await cfg.apiCall();
      if (!resp || !resp.jobId) throw new Error('后端未返回 jobId');
      startPoll(resp.jobId);
    } catch (e) {
      s.running = false;
      s.moduleError = fmtErr(e);
      pushLog('err', `${cfg.errLabel}失败：${e.message || String(e)}`);
      setBusy(false);
    }
  }

  return { s, run };
}
