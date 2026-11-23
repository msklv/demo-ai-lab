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
        @deepseek-ai/dsh@0.2.2-rc.1 \
 && dsh --version

USER node
WORKDIR /opt/data
EXPOSE 3080

ENTRYPOINT ["/usr/bin/tini", "--", "dsh"]
CMD ["--profile", "web"]
