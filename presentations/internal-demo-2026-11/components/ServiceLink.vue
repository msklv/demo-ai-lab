<script setup>
const props = defineProps({
  name: { type: String, required: true },
  url: { type: String, required: true },
  note: { type: String, default: '' },
  auth: { type: String, default: 'SSO' },
})

const isOpen = props.auth.toLowerCase().includes('без')
</script>

<template>
  <div class="service-link">
    <div>
      <div class="service-link__name">{{ name }}</div>
      <div class="service-link__meta">
        <span class="service-link__badge" :class="isOpen ? 'service-link__badge--open' : ''">{{ auth }}</span>
      </div>
    </div>
    <div>
      <a :href="url" target="_blank" class="service-link__url">{{ url.replace('https://', '') }}</a>
      <div v-if="note" class="service-link__note">{{ note }}</div>
    </div>
  </div>
</template>
