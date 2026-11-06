<template>
  <div class="slidev-layout cover dark-family">
    <LogoBadge />
    <h1 class="cover__display">{{ $frontmatter.title }}</h1>
    <div class="cover__rule" />
    <p class="cover__sub">{{ $frontmatter.subtitle }}</p>
    <div class="cover__body">
      <slot />
    </div>
    <DotPattern />
    <PageNumber />
  </div>
</template>
