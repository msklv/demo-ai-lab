<template>
  <div class="slidev-layout closing dark-family">
    <LogoBadge />
    <SlideTag :label="$frontmatter.tag" />
    <div style="margin-top:auto; margin-bottom:auto;">
      <slot />
    </div>
    <slot name="footer" />
    <PageNumber />
  </div>
</template>
