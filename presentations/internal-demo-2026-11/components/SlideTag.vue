<script setup>
defineProps({ label: { type: String, default: '' } })
</script>

<template>
  <div v-if="label" class="slide-tag">{{ label }}</div>
</template>
