<script setup>
defineProps({
  steps: { type: Array, default: () => [] },
  direction: { type: String, default: 'row' },
})
</script>

<template>
  <div class="chain" :class="direction === 'col' ? 'chain--col' : ''">
    <template v-for="(step, i) in steps" :key="step.title">
      <div class="chain__node" :class="step.variant === 'accent' ? 'chain__node--accent' : ''">
        <div class="chain__label">{{ step.label }}</div>
        <div class="chain__title">{{ step.title }}</div>
        <div v-if="step.note" class="chain__note">{{ step.note }}</div>
      </div>
      <div v-if="i < steps.length - 1" class="chain__arrow">{{ direction === 'col' ? '↓' : '→' }}</div>
    </template>
  </div>
</template>

<style scoped>
.chain { display: flex; align-items: stretch; gap: 0; width: 100%; }
.chain--col { flex-direction: column; }
.chain__node {
  flex: 1; min-width: 0;
  border-radius: 10px;
  border: 1px solid rgba(107, 63, 247, .22);
  background: #F4EFFF;
  padding: 10px 11px;
  display: flex; flex-direction: column; gap: 3px;
  justify-content: center;
}
:global(.dark-family) .chain__node {
  background: rgba(255, 255, 255, .07);
  border-color: rgba(231, 221, 255, .18);
}
.chain__node--accent { background: #6B3FF7; border-color: transparent; }
.chain__label {
  font-size: 9px; letter-spacing: .08em; text-transform: uppercase;
  color: #6B6680; font-weight: 700;
}
:global(.dark-family) .chain__label { color: #C6F542; }
.chain__node--accent .chain__label { color: #C6F542; }
.chain__title { font-size: 12.5px; font-weight: 700; color: #0F0F14; line-height: 1.22; }
:global(.dark-family) .chain__title { color: #FFF; }
.chain__node--accent .chain__title { color: #FFF; }
.chain__note { font-size: 10.5px; line-height: 1.35; color: #6B6680; }
:global(.dark-family) .chain__note { color: #E7DDFF; }
.chain__node--accent .chain__note { color: rgba(255, 255, 255, .82); }
.chain__arrow {
  flex: 0 0 auto; display: flex; align-items: center; padding: 0 5px;
  color: #6B3FF7; font-size: 13px;
}
.chain--col .chain__arrow { padding: 1px 0; justify-content: center; }
:global(.dark-family) .chain__arrow { color: #C6F542; }
</style>
