/**
 * 会话级运行日志（供「日志」页与控制台展示）。
 * 内存内累积，刷新页面后清空。
 */
const MAX_LINES = 300;

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function fmtClock(ts) {
  if (!ts) return '';
  const d = ts instanceof Date ? ts : new Date(ts * 1000);
  if (Number.isNaN(d.getTime())) return '';
  return d.toTimeString().slice(0, 8);
}

/** 追加一行日志。kind: '' | 'info' | 'ok' | 'err' */
export function pushLog(kind, text) {
  const box = document.getElementById('log-console');
  if (!box) return;
  // 移除初始占位
  const placeholder = box.querySelector('.line.muted');
  if (placeholder && /暂无日志/.test(placeholder.textContent)) placeholder.remove();

  const line = document.createElement('div');
  line.className = 'line' + (kind ? ` ${kind}` : '');
  const ts = document.createElement('span');
  ts.className = 'ts';
  ts.textContent = `[${fmtClock(Date.now())}]`;
  line.appendChild(ts);
  line.appendChild(document.createTextNode(esc(text)));
  box.appendChild(line);

  while (box.children.length > MAX_LINES) box.firstElementChild.remove();
  box.scrollTop = box.scrollHeight;
}

export function clearLog() {
  const box = document.getElementById('log-console');
  if (!box) return;
  box.innerHTML = '';
  const empty = document.createElement('div');
  empty.className = 'line muted';
  empty.textContent = '— 暂无日志，等待任务开始 —';
  box.appendChild(empty);
}

/** Unix 秒 → HH:MM:SS */
export function fmtTime(ts) {
  return fmtClock(ts);
}
