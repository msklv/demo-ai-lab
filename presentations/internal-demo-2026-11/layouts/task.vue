<template>
  <div class="slidev-layout light-family">
    <LogoBadge />
    <SlideTag :label="$frontmatter.tag" />
    <div class="slide-head">
      <h1>{{ $frontmatter.title }}</h1>
      <p v-if="$frontmatter.subtitle">{{ $frontmatter.subtitle }}</p>
    </div>
    <div class="task-grid">
      <div class="task-steps">
        <slot />
      </div>
      <div class="task-aside">
        <slot name="aside" />
      </div>
    </div>
    <PageNumber />
  </div>
</template>
