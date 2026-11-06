<template>
  <div class="slidev-layout split-light light-family">
    <LogoBadge />
    <SlideTag :label="$frontmatter.tag" />
    <div class="split-grid split-grid--light-left">
      <div class="split-col">
        <slot name="left" />
      </div>
      <div class="split-right">
        <ScreenshotFrame :label="$frontmatter.frameLabel || 'Схема'">
          <slot name="right" />
        </ScreenshotFrame>
      </div>
    </div>
    <PageNumber />
  </div>
</template>
