<script setup>
defineProps({
  label: { type: String, default: 'Итог' },
  text: { type: String, default: '' },
})
</script>

<template>
  <div class="info-callout-row">
    <div class="info-callout-row__label">{{ label }}</div>
    <div class="info-callout-row__text">{{ text }}</div>
  </div>
</template>
