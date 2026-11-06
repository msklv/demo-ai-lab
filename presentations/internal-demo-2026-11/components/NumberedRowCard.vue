<script setup>
defineProps({
  n: { type: [String, Number], required: true },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  variant: { type: String, default: 'default' },
})
</script>

<template>
  <div class="numbered-row-card" :class="variant === 'accent' ? 'accent' : ''">
    <div class="numbered-row-card__num">{{ n }}</div>
    <div class="numbered-row-card__divider" />
    <div>
      <div class="numbered-row-card__title">{{ title }}</div>
      <div v-if="description" class="numbered-row-card__desc">{{ description }}</div>
    </div>
  </div>
</template>
