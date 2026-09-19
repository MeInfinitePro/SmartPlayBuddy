/** 通用小工具 */

/** Unix 秒 / Date → HH:MM:SS */
export function fmtTime(ts) {
  if (ts === null || ts === undefined) return '';
  const d = ts instanceof Date ? ts : new Date(ts * 1000);
  if (Number.isNaN(d.getTime())) return '';
  return d.toTimeString().slice(0, 8);
}

/** 错误 → 用户可读文案（登录过期特殊提示） */
export function fmtErr(e, fallback = '') {
  if (e && e.unauthorized) return '登录已过期，请刷新页面重新通过统一登录。';
  if (e && e.message) return e.message;
  return fallback || String(e || '未知错误');
}
