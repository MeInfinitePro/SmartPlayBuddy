<template>
  <div class="card">
    <div class="row" style="justify-content: space-between; margin-bottom: 12px">
      <h2 style="margin: 0">📜 运行日志</h2>
      <button type="button" class="ghost small-btn" id="btn-clear-log" @click="onClear">清空</button>
    </div>
    <p class="desc" style="margin-bottom: 12px">本会话内的任务执行记录（含主页执行进度）。刷新页面后清空。</p>

    <div ref="boxEl" id="log-console" class="log-console">
      <div v-if="logState.lines.length === 0" class="line muted">— 暂无日志，等待任务开始 —</div>
      <div v-for="(l, i) in logState.lines" :key="i" :class="['line', l.kind]">
        <span class="ts">[{{ logTime(l.ts) }}]</span>{{ l.text }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue';
import { logState, pushLog, clearLog, logTime } from '../js/log.js';

const boxEl = ref(null);

watch(
  () => logState.lines.length,
  async () => {
    await nextTick();
    if (boxEl.value) boxEl.value.scrollTop = boxEl.value.scrollHeight;
  },
);

function onClear() {
  clearLog();
  pushLog('info', '日志已清空。');
}
</script>
