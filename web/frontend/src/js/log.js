/**
 * 会话级运行日志（全局响应式 store）。
 * 内存内累积，刷新页面后清空。日志页与主页执行进度共用。
 */
import { reactive } from 'vue';
import { fmtTime } from './utils.js';

const MAX_LINES = 300;

/** line: { kind: '' | 'info' | 'ok' | 'err', text, ts } */
export const logState = reactive({ lines: [] });

/** 追加一行日志 */
export function pushLog(kind, text) {
  logState.lines.push({ kind: kind || '', text: String(text), ts: Date.now() });
  if (logState.lines.length > MAX_LINES) logState.lines.splice(0, logState.lines.length - MAX_LINES);
}

export function clearLog() {
  logState.lines.splice(0);
}

/** 供模板显示日志行时间（内部用） */
export { fmtTime as logTime };
