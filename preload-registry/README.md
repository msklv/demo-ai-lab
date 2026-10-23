# preload-registry — локальный реестр образов для демо-стенда

`registry:2`, поднимается одной командой на консоли. Нужен, чтобы ноды забирали образы
из LAN, а не из интернета (канал площадки 4–6 МБ/с, `registry.k8s.io` и `public.ecr.aws`
с неё вообще недоступны).

```bash
docker compose -f preload-registry/docker-compose.yml up -d
docker compose -f preload-registry/docker-compose.yml ps     # STATUS: Up (healthy)
curl -s http://127.0.0.1:5050/v2/_catalog                    # список репозиториев
docker compose -f preload-registry/docker-compose.yml down   # остановить
docker volume rm preload_registry                            # стереть склад
```

| Параметр | Значение |
|---|---|
| Адрес | `192.168.10.188:5050` — **статический DHCP-лиз** на MikroTik для Ethernet-интерфейса консоли. Адрес лежит внутри пула и это нормально: статический лиз приоритетнее пула, из пула выводят только VIP (`.230`, `.240`) |
| Порт контейнера | 5000 внутри, **5050** снаружи (на macOS 5000/7000 держит AirPlay Receiver) |
| Образ | `registry:2@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373` — пин по digest, «latest» молча не подтянется |
| Данные | именованный том `preload_registry` (`/var/lib/registry`), переживает `down`; создан вне compose (первым `docker run`), поэтому при каждом `up` compose печатает warning `volume ... was not created by Docker Compose` — на работу не влияет |
| Auth / TLS | нет: обычный HTTP, только LAN демо-стенда |
