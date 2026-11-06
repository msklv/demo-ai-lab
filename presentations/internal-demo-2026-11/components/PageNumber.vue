<script setup>
import { useSlideContext } from '@slidev/client'

const { $nav } = useSlideContext()
</script>

<template>
  <div class="page-number">{{ String($nav?.currentPage ?? 0).padStart(2, '0') }}</div>
</template>
