<template>
  <div class="vram">
    <div v-for="item in items" :key="item.label" class="vram__row">
      <div class="vram__label">{{ item.label }}</div>
      <div class="vram__track">
        <div
          class="vram__fill"
          :class="item.variant === 'accent' ? 'vram__fill--accent' : ''"
          :style="{ width: pct(item.value) + '%' }"
        />
        <div class="vram__hint" :style="{ left: pct(max) + '%' }" />
      </div>
      <div class="vram__value">{{ item.value.toFixed(1).replace('.', ',') }} ГБ</div>
    </div>
    <div class="vram__axis">
      <span>0</span>
      <span>{{ Number.isInteger(max) ? max : max.toFixed(2).replace('.', ',') }} ГБ — вся карта</span>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  items: { type: Array, default: () => [] },
  max: { type: Number, default: 16 },
})

function pct(v) {
  return Math.min(100, (v / props.max) * 100)
}
</script>

<style scoped>
.vram { display: flex; flex-direction: column; gap: 11px; width: 100%; }
.vram__row {
  display: grid;
  grid-template-columns: 116px 1fr 62px;
  align-items: center;
  gap: 10px;
}
.vram__label { font-size: 11.5px; font-weight: 700; color: #0F0F14; line-height: 1.2; }
:global(.dark-family) .vram__label { color: #FFF; }
.vram__track {
  position: relative;
  height: 12px;
  border-radius: 6px;
  background: rgba(107, 63, 247, .1);
  overflow: hidden;
}
:global(.dark-family) .vram__track { background: rgba(255, 255, 255, .12); }
.vram__fill {
  height: 100%;
  border-radius: 6px;
  background: linear-gradient(90deg, #9B7DF9, #6B3FF7);
}
.vram__fill--accent { background: #C6F542; }
.vram__value { font-size: 11.5px; font-weight: 700; color: #6B3FF7; text-align: right; font-variant-numeric: tabular-nums; }
:global(.dark-family) .vram__value { color: #C6F542; }
.vram__axis {
  display: flex; justify-content: space-between;
  font-size: 9.5px; color: #6B6680; padding-left: 126px; padding-right: 72px;
}
:global(.dark-family) .vram__axis { color: #E7DDFF; opacity: .7; }
</style>
