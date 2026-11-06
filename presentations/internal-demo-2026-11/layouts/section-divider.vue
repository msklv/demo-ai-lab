<template>
  <div class="slidev-layout section-divider dark-family">
    <LogoBadge />
    <div style="margin-top:auto; margin-bottom:auto;">
      <div class="section-divider__kicker">{{ $frontmatter.tag }}</div>
      <h1 class="section-divider__title">{{ $frontmatter.title }}</h1>
      <p class="section-divider__sub">{{ $frontmatter.subtitle }}</p>
    </div>
    <DotPattern />
  </div>
</template>
