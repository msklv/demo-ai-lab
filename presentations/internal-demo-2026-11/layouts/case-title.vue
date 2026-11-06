<template>
  <div class="slidev-layout case-title dark-family">
    <LogoBadge />
    <div class="case-title__inner">
      <div class="case-title__numcol">
        <div class="case-title__num">{{ $frontmatter.number }}</div>
        <div class="case-title__rule" />
      </div>
      <div class="case-title__body">
        <div class="case-title__kicker">{{ $frontmatter.kicker }}</div>
        <h1 class="case-title__title">{{ $frontmatter.title }}</h1>
        <p class="case-title__thesis">{{ $frontmatter.thesis }}</p>
        <div v-if="$frontmatter.models" class="case-title__models">На карте: {{ $frontmatter.models }}</div>
      </div>
    </div>
    <DotPattern />
    <PageNumber />
  </div>
</template>
