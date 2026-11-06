<template>
  <div class="slidev-layout light-family">
    <LogoBadge />
    <SlideTag :label="$frontmatter.tag" />
    <div class="slide-head">
      <h1>{{ $frontmatter.title }}</h1>
      <p v-if="$frontmatter.subtitle">{{ $frontmatter.subtitle }}</p>
    </div>
    <div class="card-grid">
      <slot />
    </div>
    <PageNumber />
  </div>
</template>
