<template>
  <div id="app">
    <!-- 加载中 -->
    <div v-if="phase === 'loading'" class="card center-card">
      <p>正在检查登录状态…</p>
    </div>

    <!-- 未登录兜底 / 致命错误（正常未登录会直接跳统一登录） -->
    <div v-else-if="phase === 'gate'" class="card center-card">
      <div class="gate-logo">⚠️</div>
      <h2>{{ gate.title }}</h2>
      <div v-if="gate.err" class="error-msg">{{ gate.err }}</div>
      <a v-if="gate.loginUrl" :href="gate.loginUrl" style="display: inline-block">
        <button type="button">重新前往统一登录</button>
      </a>
      <p v-if="gate.failText" class="red-text">{{ gate.failText }}</p>
    </div>

    <!-- 已登录：应用壳（左侧导航 + 内容区，页面 v-show 保活避免任务状态丢失） -->
    <div v-else id="shell">
      <aside id="sidebar">
        <div class="brand">
          <div class="brand-logo"><img src="../public/assets/img/favicon.png"></div>
          <div>
            <div class="brand-name">星穹铁道助手</div>
            <div class="brand-sub">StarRailAssistant</div>
          </div>
        </div>

        <nav id="nav">
          <button v-for="p in PAGES" :key="p.key" type="button" class="nav-item" :class="{ active: page === p.key }"
            :data-page="p.key" @click="go(p.key)">
            <span class="nav-ico iconfont" :class="p.ico"></span>{{ p.label }}
          </button>
        </nav>

        <div class="side-foot">
          <div class="muted small" style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
            开拓者：<span id="user-id">{{ userId }}</span>
          </div>
          <button type="button" class="ghost btn-logout" id="btn-logout" @click="logout">退出登录</button>
        </div>
      </aside>

      <main id="content">
        <HomeView v-show="page === 'home'" />
        <HelpView v-show="page === 'help'" />
        <LaunchView v-show="page === 'launch'" />
        <LogView v-show="page === 'log'" />
        <SettingsView v-show="page === 'settings'" />
      </main>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue';
import { api } from './js/api.js';
import { pushLog } from './js/log.js';
import { settings } from './js/settings.js';
import HomeView from './views/HomeView.vue';
import HelpView from './views/HelpView.vue';
import LaunchView from './views/LaunchView.vue';
import LogView from './views/LogView.vue';
import SettingsView from './views/SettingsView.vue';
import '../public/assets/icon/side_icon/iconfont.css'
const PAGES = [
  { key: 'home', label: '主页', ico: 'icon-home-g' },
  { key: 'help', label: '帮助', ico: 'icon-bangzhu' },
  { key: 'launch', label: '启动游戏', ico: 'icon-start' },
  { key: 'log', label: '日志', ico: 'icon-rizhi' },
  { key: 'settings', label: '设置', ico: 'icon-shezhi' },
];

const phase = ref('loading'); // loading | gate | shell
const gate = reactive({ title: '无法进入控制台', err: '', loginUrl: '', failText: '' });
const userId = ref('未知');
const page = ref(normalizePage());

function normalizePage() {
  const h = location.hash.replace('#', '');
  return PAGES.some((p) => p.key === h) ? h : 'home';
}

function go(key) {
  page.value = key;
  if (location.hash !== `#${key}`) history.replaceState(null, '', `#${key}`);
  window.scrollTo(0, 0);
}

/** 登录失败兜底展示（正常未登录会直接跳统一登录，不会走到这里） */
function showAuthFail(errText, loginUrl) {
  gate.title = '无法进入控制台';
  gate.err = errText ? `⚠️ ${errText}` : '';
  gate.loginUrl = loginUrl || '';
  gate.failText = '';
  phase.value = 'gate';
}

/** 致命错误展示（初始化异常等） */
function showFatal(title, detail) {
  gate.title = title;
  gate.err = detail ? `⚠️ ${detail}` : '';
  gate.loginUrl = '';
  gate.failText = '';
  phase.value = 'gate';
}

function fmtErrText(err) {
  return `无法获取统一登录地址${err ? '：' + err : '，请确认后端服务已启动并可访问。'}`;
}

async function logout() {
  try {
    await api.logout();
  } catch {
    /* 忽略 */
  }
  location.reload();
}

// ===== 【调试开关】跳过登录验证：true = 不校验登录直接进入应用壳 =====
// 调试完改回 false 并重新 npm run build 即可恢复统一登录流程。
const SKIP_AUTH = false;

async function boot() {
  // 【调试】登录验证已注释：直接进入应用壳（原验证逻辑保留在下方，改回 SKIP_AUTH=false 恢复）
  if (SKIP_AUTH) {
    userId.value = '本地调试';
    phase.value = 'shell';
    pushLog('ok', '✅ 欢迎开拓者（登录验证已跳过）！三月七小助手已就绪。');
    return;
  }

  // 回调失败提示（?authError=...）
  const params = new URLSearchParams(location.search);
  if (params.get('authError')) {
    sessionStorage.setItem(
      'spb_auth_error',
      `登录回跳未携带有效 token（${params.get('authError')}）。` + '请点击下方按钮重新前往统一登录。',
    );
    history.replaceState(null, '', '/');
  }

  let auth;
  try {
    auth = await api.me();
  } catch {
    auth = { authenticated: false };
  }

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
    showAuthFail('', '');
    gate.failText = fmtErrText(auth.error);
    phase.value = 'gate';
    return;
  }

  // 已登录：进入应用壳
  userId.value = auth.userId || '未知';
  if (auth.targetClient) settings.targetClient = auth.targetClient;
  phase.value = 'shell';
  pushLog('ok', `✅ 欢迎，${userId.value}！三月七小助手已就绪。`);
}

onMounted(() => {
  window.addEventListener('hashchange', () => {
    page.value = normalizePage();
    window.scrollTo(0, 0);
  });
  boot().catch((e) => {
    console.error('[app] boot 异常：', e);
    showFatal('页面初始化失败', String((e && e.message) || e));
  });
});
</script>
