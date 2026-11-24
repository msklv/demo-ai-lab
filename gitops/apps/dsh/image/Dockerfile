# Образ dsh (DeepSeek Harness) — официального нет, собираем сами (dsh-spec §1, §7).
#
# Пакет ставится глобально на node:24-slim (`engines: node >= 24.9.0`), в образ добавляется git:
# им initContainer клонирует каталог скиллов (`msklv/skills-demo-ai-lab`) по пину коммита.
# Версия пакета ЗАФИКСИРОВАНА вместе с integrity (dsh-spec §0/§1): обновление — новый тег и дигест,
# «на месте» не обновляем.
FROM node:24-slim

ENV NODE_ENV=production \
    npm_config_update_notifier=false \
    npm_config_fund=false

RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates curl tini \
 && rm -rf /var/lib/apt/lists/*

RUN npm i -g --allow-scripts=@deepseek-ai/dsh-subprocess-local,koffi,node-pty,@google/genai,protobufjs \
        @deepseek-ai/dsh@0.2.2-rc.5 \
 && dsh --version

# Официальные плагины сверх бандла (dsh-spec §6.1): ставятся во временный префикс и копируются в
# node_modules пакета dsh — именно оттуда загрузчик профиля резолвит имена (профиль на PVC для этого
# не годится: `dsh plugin add` писал бы в том, а не в git). `npm i --prefix <dsh>` проверено — не
# ставит (peer-дерево считается «up to date»), поэтому копирование.
RUN mkdir -p /tmp/plugins && cd /tmp/plugins && npm init -y >/dev/null 2>&1 \
 && npm i --no-audit --no-fund --loglevel=error \
        @deepseek-ai/dsh-hook-protocol@0.2.2-rc.5 \
        @deepseek-ai/dsh-hooks-codex@0.2.2-rc.5 \
        @deepseek-ai/dsh-webhook@0.2.2-rc.5 \
        @deepseek-ai/dsh-webhook-github@0.2.2-rc.5 \
 && cp -a node_modules/@deepseek-ai/dsh-hook-protocol node_modules/@deepseek-ai/dsh-hooks-codex \
          node_modules/@deepseek-ai/dsh-webhook node_modules/@deepseek-ai/dsh-webhook-github \
          /usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/ \
 && rm -rf /tmp/plugins \
 && node -e "console.log(require.resolve('@deepseek-ai/dsh-hooks-codex', {paths:['/usr/local/lib/node_modules/@deepseek-ai/dsh/node_modules/@deepseek-ai/dsh-app-boot']}))"

USER node
WORKDIR /opt/data
EXPOSE 3080

ENTRYPOINT ["/usr/bin/tini", "--", "dsh"]
CMD ["--profile", "web"]
