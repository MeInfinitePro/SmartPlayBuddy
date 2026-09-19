/**
 * 全局 UI 状态：目标设备名 + 各任务忙碌开关。
 * 供 主页卡片 / 设置页 共享，保证 busy 期间相关控件统一禁用。
 */
import { reactive, computed } from 'vue';

export const settings = reactive({
  /** client 端 deviceName；留空时使用会话默认目标设备 */
  targetClient: '',
});

export const activity = reactive({
  daily: false, // 每日实训执行中
  power: false, // 清体力执行中
});

/** 任一任务忙碌 → 目标设备输入框禁用 */
export const busyAny = computed(() => activity.daily || activity.power);

/** 清体力相关控件（滑杆/单选/复选）仅在清体力执行中禁用 */
export const powerBusy = computed(() => activity.power);

export function targetClientValue() {
  return settings.targetClient.trim() || undefined;
}
