<script setup>
defineProps({ label: { type: String, default: 'Интерфейс' } })
</script>

<template>
  <div class="screenshot-frame">
    <div class="screenshot-frame__label">{{ label }}</div>
    <slot />
  </div>
</template>
