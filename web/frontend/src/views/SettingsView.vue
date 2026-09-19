<template>
  <section>
    <!-- 目标设备 -->
    <div class="card">
      <h2>⚙️ 目标设备</h2>
      <p class="desc">client 端 deviceName；留空时使用当前会话默认目标设备。</p>
      <input
        id="target-client"
        v-model="settings.targetClient"
        type="text"
        placeholder="client 端 deviceName（留空用会话默认）"
        style="width: min(420px, 100%)"
        :disabled="busyAny"
      />
    </div>

    <!-- 体力计划 -->
    <div class="card">
      <h2>🕘 体力计划</h2>
      <p class="desc">
        自定义清体力方案：0 表示清完全部开拓力；1-30 表示清理对应次数（每次 10 点，即 10-300 点）。
        超出现有体力时按现有体力清理；启用后备开拓力时会先补足至 300 点。主页的「清体力」图标将按此计划执行。
      </p>

      <h3 class="small muted-text" style="margin: 10px 0 4px">清理次数 / 体力</h3>
      <div class="slider-wrap">
        <div class="row" style="justify-content: space-between">
          <span class="muted small">0（全部清完）</span>
          <span class="slider-val" id="power-num-text">{{ sliderValText(powerPlan.num) }}</span>
          <span class="muted small">300 点</span>
        </div>
        <input
          id="power-num"
          :value="powerPlan.num"
          type="range"
          min="0"
          max="30"
          step="1"
          :disabled="powerBusy"
          @input="powerPlan.num = Number($event.target.value)"
        />
        <p class="muted small" style="margin: 2px 0 10px">计划：<span id="power-plan-text">{{ planText(powerPlan.num) }}</span></p>
      </div>

      <h3 class="small muted-text" style="margin: 10px 0 8px">战利品类型</h3>
      <div class="row" style="margin-bottom: 14px">
        <label v-for="o in LOOT_OPTIONS" :key="o.value" class="check">
          <input v-model="powerPlan.selection" type="radio" name="selection" :value="o.value" :disabled="powerBusy" />
          {{ o.label }}
        </label>
      </div>

      <label class="check">
        <input id="use-reserve" v-model="powerPlan.useReserve" type="checkbox" :disabled="powerBusy" />
        使用后备开拓力（补足至 300 点）
      </label>
    </div>
  </section>
</template>

<script setup>
import { settings, busyAny, powerBusy } from '../js/settings.js';
import { powerPlan, sliderValText, planText } from '../js/powerPlan.js';

const LOOT_OPTIONS = [
  { value: 1, label: '1. 信用点（藏宝之芽）' },
  { value: 2, label: '2. 角色经验（回忆之芽）' },
  { value: 3, label: '3. 光锥经验（虚空之芽）' },
];
</script>
