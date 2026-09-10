/**
 * 应用入口（纯 JS，无框架）：
 * 登录态探测 → 进入应用壳（左侧导航 主页/帮助/启动游戏/日志/设置）→ 初始化功能模块。
 */
import { api } from './api.js';
import { initDaily } from './daily.js';
import { initPower } from './power.js';
import { pushLog, clearLog } from './log.js';

const $ = (id) => document.getElementById(id);

const PAGES = ['home', 'help', 'launch', 'log', 'settings'];

let auth = null;

function switchPage(name) {
  if (!PAGES.includes(name)) name = 'home';
  PAGES.forEach((p) => {
    const sec = $(`page-${p}`);
    const nav = document.querySelector(`.nav-item[data-page="${p}"]`);
    if (sec) sec.classList.toggle('active', p === name);
    if (nav) nav.classList.toggle('active', p === name);
  });
  if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
  window.scrollTo(0, 0);
}

function initNav() {
  document.querySelectorAll('.nav-item').forEach((btn) => {
    btn.addEventListener('click', () => switchPage(btn.dataset.page));
  });
  // 支持 #hash 直达
  window.addEventListener('hashchange', () => {
    switchPage(location.hash.replace('#', ''));
  });
  switchPage(location.hash.replace('#', '') || 'home');
}

/**
 * 致命错误展示：优先复用登录兜底卡；若连兜底卡都不存在（极端旧缓存），
 * 直接往页面注入一条全屏提示，避免“白屏 + 无从下手”。
 */
function showFatal(title, detail) {
  const loading = $('auth-loading');
  if (loading) loading.style.display = 'none';
  const gate = $('auth-gate');
  if (gate) {
    gate.style.display = 'block';
    const h2 = gate.querySelector('h2');
    if (h2) h2.textContent = title;
    const err = $('auth-error');
    if (err) {
      err.textContent = detail ? `⚠️ ${detail}` : '';
      err.style.display = detail ? 'block' : 'none';
    }
    const link = $('login-link');
    if (link) link.style.display = 'none';
    const fail = $('login-fail');
    if (fail) fail.style.display = 'none';
    return;
  }
  console.error(`[app] ${title}`, detail);
  let box = document.getElementById('fatal-banner');
  if (!box) {
    box = document.createElement('div');
    box.id = 'fatal-banner';
    box.style.cssText =
      'position:fixed;inset:0;display:flex;align-items:center;justify-content:center;' +
      'background:#fff;z-index:9999;padding:24px;text-align:center;font:14px/1.8 sans-serif;color:#000;';
    document.body.appendChild(box);
  }
  box.innerHTML = `<div><b>${title}</b><br>${String(detail || '').replace(/</g, '&lt;')}<br><br>请强制刷新：Ctrl+F5（Mac：Cmd+Shift+R）</div>`;
}

/** 登录失败兜底展示（正常未登录会直接跳统一登录，不会走到这里） */
function showAuthFail(errText, loginUrl) {
  const gate = $('auth-gate');
  if (!gate) {
    showFatal('无法进入控制台', fmtErrText('页面缺少登录兜底节点，请强制刷新'));
    return;
  }
  gate.style.display = 'block';
  if (errText) {
    const err = $('auth-error');
    if (err) {
      err.textContent = `⚠️ ${errText}`;
      err.style.display = 'block';
    }
  }
  const link = $('login-link');
  if (loginUrl && link) {
    link.href = loginUrl;
    link.style.display = 'inline-block';
  }
}

async function boot() {
  // 回调失败提示（?authError=...）
  const params = new URLSearchParams(location.search);
  if (params.get('authError')) {
    sessionStorage.setItem('spb_auth_error',
      `登录回跳未携带有效 token（${params.get('authError')}）。` +
      '请点击下方按钮重新前往统一登录。');
    history.replaceState(null, '', '/');
  }

  try {
    auth = await api.me();
  } catch {
    auth = { authenticated: false };
  }

  const loading = $('auth-loading');
  if (loading) loading.style.display = 'none';

  if (!auth.authenticated) {
    const savedErr = sessionStorage.getItem('spb_auth_error');
    sessionStorage.removeItem('spb_auth_error');
    // 登录回跳失败（?authError=...）：展示错误，避免与统一登录来回死循环
    if (savedErr) {
      showAuthFail(savedErr, auth.loginUrl);
      return;
    }
    // 未登录：直接跳转统一登录（无需中间提示页）
    if (auth.loginUrl) {
      location.replace(auth.loginUrl);
      return;
    }
    // 拿不到登录地址：展示兜底错误
    showAuthFail('', null);
    const fail = $('login-fail');
    if (fail) {
      fail.textContent = fmtErrText(auth.error);
      fail.style.display = 'block';
    }
    return;
  }

  // 已登录：先校验应用壳关键 DOM。
  // 若命中缺失，多半是浏览器缓存了旧版 index.html/app.js 造成结构不匹配，
  // 此时给出明确提示而非在访问 .style 时抛错导致“白屏/停在加载页”。
  const required = [
    'shell', 'nav', 'user-id', 'btn-logout',
    'btn-run-daily', 'btn-clear-power', 'power-num',
    'log-console', 'btn-clear-log', 'btn-launch-game',
  ];
  const missing = required.filter((id) => !$(id));
  if (missing.length) {
    showFatal('页面版本不一致，无法初始化',
      `浏览器缓存了旧版页面资源（缺失元素：${missing.join('、')}）。` +
      '请按 Ctrl+F5（Mac 为 Cmd+Shift+R）强制刷新；若仍出现，请清空浏览器缓存后重试。');
    return;
  }

  // 进入应用壳
  $('shell').style.display = 'flex';
  $('user-id').textContent = auth.userId || '未知';
  if (auth.targetClient && $('target-client')) {
    $('target-client').value = auth.targetClient;
  }

  initNav();
  initDaily();
  initPower();
  initActions();

  pushLog('ok', `✅ 欢迎，${auth.userId || '开拓者'}！三月七小助手已就绪。`);
}

function on(id, fn) {
  const el = $(id);
  if (el) el.addEventListener('click', fn);
}

function initActions() {
  // 退出登录
  on('btn-logout', async () => {
    try { await api.logout(); } catch { /* 忽略 */ }
    location.reload();
  });

  // 日志页：清空
  on('btn-clear-log', () => {
    clearLog();
    pushLog('info', '日志已清空。');
  });

  // 启动游戏（Web 端暂未接入远程启动，记录尝试）
  on('btn-launch-game', () => {
    pushLog('err', '⚠️ 启动游戏：Web 端尚未接入远程启动能力，请在 SmartPlayBuddy 客户端侧启动游戏。');
  });
}

function fmtErrText(err) {
  return `无法获取统一登录地址${err ? '：' + err : '，请确认后端服务已启动并可访问。'}`;
}

boot().catch((e) => {
  console.error('[app] boot 异常：', e);
  showFatal('页面初始化失败', String((e && e.message) || e));
});
