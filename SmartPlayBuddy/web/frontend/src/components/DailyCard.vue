<template>
  <div class="module-card" id="card-daily">
    <div class="module-head">
      <!-- 运行功能图标 + 底下文字，整体 104px：点击即执行每日实训 -->
      <div class="icon-col">
        <button type="button" class="icon-tile" id="btn-run-daily" :disabled="s.busy" @click="run" title="点击执行每日实训">
          <img class="icon-img" src="/assets/img/1.png" alt="每日实训" />
          <span class="icon-badge" aria-hidden="true">{{ s.busy ? '⏳' : '▶' }}</span>
        </button>
        <span class="icon-label">每日实训</span>
      </div>
      <!-- 重要的报错信息：图标右半部分展示 -->
      <div class="head-right">
        <div v-if="s.moduleError" id="daily-error" class="error-msg">❌ {{ s.moduleError }}</div>
      </div>
    </div>
    <!-- 执行过程日志统一输出到「日志」栏目 -->
  </div>
</template>

<script setup>
import { api } from '../js/api.js';
import { activity, targetClientValue } from '../js/settings.js';
import { pushLog } from '../js/log.js';
import { useJobRunner } from '../composables/useJobRunner.js';

const runner = useJobRunner({
  apiCall: () => api.dailyTask(undefined, targetClientValue()),
  // 执行前检查游戏是否已启动（driver game/running）：未启动则提醒用户，不执行
  preCheck: async () => {
    pushLog('info', '🔍 每日实训：正在检查游戏是否已启动…');
    const resp = await api.gameRunning(targetClientValue());
    if (!resp || !resp.running) {
      return '游戏未启动，请先在「启动游戏」中启动《崩坏：星穹铁道》后再执行';
    }
    pushLog('ok', '✅ 游戏已启动');
    return '';
  },
  startLog: '⏳ 开始执行完整日常（观察 → 逐项执行 → 领取奖励）…',
  okLog: '✅ 每日实训执行完成',
  errLabel: '每日实训',
  activityKey: 'daily',
  activity,
});

const { s, run } = runner;
</script>
