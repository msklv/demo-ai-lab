<script setup>
defineProps({
  steps: { type: Array, default: () => [] },
})
</script>

<template>
  <div class="step-flow">
    <template v-for="(step, i) in steps" :key="step.title">
      <div class="step-card" :class="step.variant === 'accent' ? 'accent' : ''">
        <div class="step-card__label">{{ step.label }}</div>
        <div class="step-circle">{{ i + 1 }}</div>
        <div class="step-card__title">{{ step.title }}</div>
        <div v-if="step.body" class="step-card__body">{{ step.body }}</div>
      </div>
      <div v-if="i < steps.length - 1" class="step-arrow">▶</div>
    </template>
  </div>
</template>
