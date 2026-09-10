/**
 * 体力计划（全局响应式 store）。
 * 「设置 → 体力计划」编辑，主页「清理开拓力」卡片实时读取同步。
 */
import { reactive } from 'vue';

export const LOOT = { 1: '信用点', 2: '角色经验', 3: '光锥经验' };

export const powerPlan = reactive({
  num: 0,             // 清理次数 0-30（0=全部清完；每次 10 点，上限 300）
  selection: 1,       // 战利品类型 1 信用点 / 2 角色经验 / 3 光锥经验
  useReserve: false,   // 是否使用后备开拓力
});

/** 滑杆右侧数值：0 → “全部清完”，N → “N*10 点” */
export function sliderValText(n) {
  return n === 0 ? '全部清完' : `${n * 10} 点`;
}

/** 滑杆下方计划描述：0 → “全部清完”，N → “N 次（N*10 点开拓力）” */
export function planText(n) {
  return n === 0 ? '全部清完' : `${n} 次（${n * 10} 点开拓力）`;
}

/** 完整当前计划文案（主页卡片实时提示 + 开跑前日志） */
export function currentPlan() {
  const n = powerPlan.num;
  const base = n === 0 ? '全部清完' : `清理 ${n} 次（${n * 10} 点）`;
  const loot = LOOT[powerPlan.selection] || '信用点';
  const reserve = powerPlan.useReserve ? ' · 使用后备开拓力' : '';
  return `${base} · ${loot}${reserve}`;
}
