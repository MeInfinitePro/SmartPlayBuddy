<template>
  <div class="card">
    <h2>▶️ 启动游戏</h2>
    <p class="desc">通过客户端驱动（game/open）唤起《崩坏：星穹铁道》，等待登录并进入主界面，供后续自动化任务使用。</p>
    <div class="launch-box">
      <div class="launch-game">🎮</div>
      <button type="button" id="btn-launch-game" :disabled="launching" @click="onLaunch">
        {{ launching ? '⏳ 启动中…（等待进入主界面）' : '启动《崩坏：星穹铁道》' }}
      </button>
      <p class="muted small" style="margin: 12px 0 0" v-if="!statusMsg">
        ※ 启动过程由游戏所在电脑的客户端驱动执行；首次启动可能需要搜索游戏路径，耗时较久。
      </p>
      <p class="small" :class="launched ? 'ok-msg' : 'error-msg'" style="margin: 12px 0 0" v-if="statusMsg">
        {{ statusMsg }}
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';
import { api } from '../js/api.js';
import { pushLog } from '../js/log.js';
import { targetClientValue } from '../js/settings.js';
import { fmtErr } from '../js/utils.js';

const launching = ref(false);
const statusMsg = ref('');
const launched = ref(false);

async function onLaunch() {
  if (launching.value) return;
  launching.value = true;
  statusMsg.value = '';
  launched.value = false;
  pushLog('info', '🎮 正在启动《崩坏：星穹铁道》（等待进入主界面，可能耗时较久）…');
  try {
    const resp = await api.gameOpen(targetClientValue());
    if (resp && resp.opened) {
      launched.value = true;
      statusMsg.value = '✅ 游戏已启动并进入主界面，可以执行每日实训 / 清体力了。';
      pushLog('ok', '✅ 启动游戏成功（已进入主界面）');
    } else {
      statusMsg.value = '⚠️ 启动指令已下发，但未能确认进入主界面，请在游戏所在电脑上检查。';
      pushLog('err', '⚠️ 启动游戏：未能确认进入主界面，请检查客户端与游戏窗口。');
    }
  } catch (e) {
    statusMsg.value = `❌ 启动游戏失败：${e.message || String(e)}`;
    pushLog('err', `启动游戏失败：${e.message || String(e)}`);
  } finally {
    launching.value = false;
  }
}
</script>
