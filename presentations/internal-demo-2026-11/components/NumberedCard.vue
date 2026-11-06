<script setup>
defineProps({
  n: { type: [String, Number], required: true },
  title: { type: String, required: true },
  body: { type: String, default: '' },
  unit: { type: String, default: '' },
  variant: { type: String, default: 'default' },
})
</script>

<template>
  <div class="numbered-card" :class="variant === 'accent' ? 'accent' : ''">
    <div class="numbered-card__num">{{ n }}<small v-if="unit">{{ unit }}</small></div>
    <div class="numbered-card__sep" />
    <div class="numbered-card__title">{{ title }}</div>
    <div v-if="body" class="numbered-card__body">{{ body }}</div>
  </div>
</template>
