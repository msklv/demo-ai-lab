<script setup>
defineProps({ lines: { type: Array, default: () => [] } })
</script>

<template>
  <div class="accent-callout">
    <p v-for="line in lines" :key="line">{{ line }}</p>
  </div>
</template>
