<template>
  <div class="stack">
    <div v-for="row in rows" :key="row.layer" class="stack__row">
      <div class="stack__layer">{{ row.layer }}</div>
      <div class="stack__items">
        <span v-for="item in row.items" :key="item" class="stack__chip">{{ item }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
const rows = [
  { layer: 'Агентский', items: ['Hermes Agent · hm.', 'qm (в плане)'] },
  { layer: 'Сервисы', items: ['Open WebUI · owu.', 'Speakr · spk.', 'Docling · doc.', 'RAG в OWU'] },
  { layer: 'MCP', items: ['doc. /mcp', 'ysrch. /mcp', 'каталог mcp.'] },
  { layer: 'Инференс', items: ['GPUStack 2.2.3 · vLLM', 'RTX 5070 Ti 16 ГБ', '780M k8s-01'] },
  { layer: 'Guardrail', items: ['Higress', 'DLP ai-data-masking', 'Qwen3Guard 4B', 'fail-closed'] },
  { layer: 'Данные · Ops', items: ['Keycloak SSO', 'Longhorn r=2', 'PostgreSQL · MinIO', 'Argo CD'] },
]
</script>

<style scoped>
.stack { display: flex; flex-direction: column; gap: 7px; width: 100%; }
.stack__row {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 10px;
  align-items: center;
  border-radius: 9px;
  border: 1px solid rgba(107, 63, 247, .16);
  background: #F4EFFF;
  padding: 7px 10px;
}
:global(.dark-family) .stack__row {
  background: rgba(255, 255, 255, .07);
  border-color: rgba(231, 221, 255, .16);
}
.stack__layer {
  font-size: 9.5px; letter-spacing: .08em; text-transform: uppercase;
  font-weight: 700; color: #6B3FF7; line-height: 1.2;
}
:global(.dark-family) .stack__layer { color: #C6F542; }
.stack__items { display: flex; flex-wrap: wrap; gap: 5px; }
.stack__chip {
  font-size: 11px; line-height: 1;
  padding: 4px 7px; border-radius: 9999px;
  background: #FFF; border: 1px solid rgba(107, 63, 247, .16);
  color: #0F0F14; white-space: nowrap;
}
:global(.dark-family) .stack__chip {
  background: rgba(42, 39, 53, .55);
  border-color: rgba(231, 221, 255, .16);
  color: #FFF;
}
</style>
