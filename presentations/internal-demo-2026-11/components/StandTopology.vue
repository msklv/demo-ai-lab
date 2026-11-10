<template>
  <svg viewBox="0 0 470 292" class="topo" xmlns="http://www.w3.org/2000/svg">
    <defs>
      <marker id="arr" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
        <path d="M0,0 L7,3.5 L0,7 z" fill="#9B7DF9" />
      </marker>
    </defs>

    <!-- внешний край -->
    <rect x="140" y="2" width="190" height="26" rx="7" fill="none" stroke="#9B7DF9" stroke-dasharray="4 3" />
    <text x="235" y="19" text-anchor="middle" class="t10 muted">Cloud.ru VM · haproxy · TLS</text>

    <line x1="235" y1="28" x2="235" y2="44" stroke="#9B7DF9" stroke-width="1.4" marker-end="url(#arr)" />

    <!-- шлюз -->
    <rect x="124" y="46" width="222" height="30" rx="8" fill="#F4EFFF" stroke="#6B3FF7" stroke-width="1.4" />
    <text x="235" y="65" text-anchor="middle" class="t11 bold">MikroTik gw · 192.168.10.1</text>

    <line x1="235" y1="76" x2="235" y2="90" stroke="#9B7DF9" stroke-width="1.4" marker-end="url(#arr)" />

    <!-- коммутатор -->
    <rect x="124" y="92" width="222" height="26" rx="8" fill="#F4EFFF" stroke="#6B3FF7" stroke-width="1.4" />
    <text x="235" y="109" text-anchor="middle" class="t10 bold">L2-коммутатор · LAG 2×1G</text>

    <!-- шина -->
    <line x1="235" y1="118" x2="235" y2="128" stroke="#9B7DF9" stroke-width="1.4" />
    <line x1="60" y1="128" x2="402" y2="128" stroke="#9B7DF9" stroke-width="1.4" />
    <line x1="60" y1="128" x2="60" y2="138" stroke="#9B7DF9" stroke-width="1.4" />
    <line x1="176" y1="128" x2="176" y2="138" stroke="#9B7DF9" stroke-width="1.4" />
    <line x1="288" y1="128" x2="288" y2="138" stroke="#9B7DF9" stroke-width="1.4" />
    <line x1="402" y1="128" x2="402" y2="138" stroke="#9B7DF9" stroke-width="1.4" />

    <!-- узлы -->
    <g>
      <rect x="8" y="140" width="104" height="54" rx="9" fill="#FFF" stroke="rgba(107,63,247,.35)" stroke-width="1.2" />
      <text x="60" y="159" text-anchor="middle" class="t11 bold">k8s-01</text>
      <text x="60" y="172" text-anchor="middle" class="t9 muted">CP #1 · компьют</text>
      <text x="60" y="184" text-anchor="middle" class="t9 muted">780M · bge</text>

      <rect x="124" y="140" width="104" height="54" rx="9" fill="#FFF" stroke="rgba(107,63,247,.35)" stroke-width="1.2" />
      <text x="176" y="159" text-anchor="middle" class="t11 bold">k8s-02</text>
      <text x="176" y="172" text-anchor="middle" class="t9 muted">CP #2 · ingress</text>
      <text x="176" y="184" text-anchor="middle" class="t9 muted">GitOps · hm.</text>

      <rect x="236" y="140" width="104" height="54" rx="9" fill="#FFF" stroke="rgba(107,63,247,.35)" stroke-width="1.2" />
      <text x="288" y="159" text-anchor="middle" class="t11 bold">k8s-03</text>
      <text x="288" y="172" text-anchor="middle" class="t9 muted">CP #3 · ingress</text>
      <text x="288" y="184" text-anchor="middle" class="t9 muted">owu · spk · doc</text>

      <rect x="350" y="140" width="112" height="54" rx="9" fill="#F4EFFF" stroke="#6B3FF7" stroke-width="1.6" />
      <text x="406" y="159" text-anchor="middle" class="t11 bold">k8s-04</text>
      <text x="406" y="172" text-anchor="middle" class="t9 muted">LLM-инференс</text>
      <text x="406" y="184" text-anchor="middle" class="t9 muted">GPUStack · данные</text>
    </g>

    <!-- VIP -->
    <rect x="124" y="202" width="104" height="18" rx="9" fill="#6B3FF7" />
    <text x="176" y="214.5" text-anchor="middle" class="t85 light">.230 ingress VIP</text>
    <rect x="236" y="202" width="104" height="18" rx="9" fill="#6B3FF7" />
    <text x="288" y="214.5" text-anchor="middle" class="t85 light">.240 API VIP</text>

    <!-- GPU -->
    <rect x="350" y="202" width="112" height="34" rx="8" fill="#6B3FF7" />
    <text x="406" y="216" text-anchor="middle" class="t95 lime">RTX 5070 Ti</text>
    <text x="406" y="228" text-anchor="middle" class="t85 light">16 ГБ · модели hostPath</text>

    <!-- консоль и зал -->
    <rect x="8" y="202" width="104" height="18" rx="9" fill="#F4EFFF" stroke="rgba(107,63,247,.3)" />
    <text x="60" y="214.5" text-anchor="middle" class="t85 ink">Wi-Fi зала · LAN</text>
    <rect x="8" y="224" width="104" height="18" rx="9" fill="#F4EFFF" stroke="rgba(107,63,247,.3)" />
    <text x="60" y="236.5" text-anchor="middle" class="t85 ink">Mac-консоль .200</text>

    <text x="124" y="242" class="t9 muted">Longhorn 3×250 ГБ · replica=2 · k8s-01 вне пула</text>
    <text x="124" y="256" class="t9 muted">Вход снаружи и из LAN — одно имя и один TLS</text>

    <line x1="8" y1="270" x2="462" y2="270" stroke="rgba(107,63,247,.2)" />
    <text x="8" y="286" class="t85 muted">Пунктир — внешний край; стрелки — путь до ingress-VIP</text>
  </svg>
</template>

<style scoped>
.topo { display: block; width: 100%; height: auto; font-family: 'Rubik', system-ui, sans-serif; }
.topo text { font-size: 10px; fill: #0F0F14; }
.topo .t11 { font-size: 11px; }
.topo .t10 { font-size: 10px; }
.topo .t95 { font-size: 9.5px; }
.topo .t9 { font-size: 9px; }
.topo .t85 { font-size: 8.5px; }
.topo .bold { font-weight: 700; }
.topo .muted { fill: #6B6680; }
.topo .ink { fill: #0F0F14; }
.topo .light { fill: #FFFFFF; }
.topo .lime { fill: #C6F542; }
</style>
