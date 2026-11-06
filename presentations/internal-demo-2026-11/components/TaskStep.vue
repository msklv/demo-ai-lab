<script setup>
defineProps({
  n: { type: [String, Number], required: true },
  title: { type: String, required: true },
  body: { type: String, default: '' },
  variant: { type: String, default: 'default' },
})
</script>

<template>
  <div class="task-step" :class="variant === 'accent' ? 'accent' : ''">
    <div class="task-step__num">{{ n }}</div>
    <div>
      <div class="task-step__title">{{ title }}</div>
      <div v-if="body" class="task-step__body">{{ body }}</div>
    </div>
  </div>
</template>
