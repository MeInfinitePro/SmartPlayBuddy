<template>
  <!-- 主页：三月七小助手风格，上大背景横幅 + 下功能图标卡片 -->
  <section class="home-page">
    <!-- 顶部大幅背景横幅（big.png，占绝大部分） -->
    <div class="home-banner">
      <div class="home-hero">
        <p class="home-hero-sub">点击下方角色图标，立即开始任务~</p>
      </div>
    </div>

    <div class="module-grid home-grid">
      <DailyCard />
      <PowerCard />
    </div>
  </section>
</template>

<script setup>
import DailyCard from '../components/DailyCard.vue';
import PowerCard from '../components/PowerCard.vue';
</script>
