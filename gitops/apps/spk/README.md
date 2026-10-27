# Speakr (`spk.demo-ai-lab.ru`) — шаг 2 демо

Спека: `architecture/spk-spec.md` (фазы S1–S6). Раскатывает ApplicationSet `apps` в ns `spk`
как plain-манифесты (официального Helm-чарта у проекта нет).

| Файл | Что |
|---|---|
| `10-pvc.yaml` | PVC `speakr-data` 20Gi `longhorn` RWO → `/data` (SQLite, uploads, `instance/`) |
| `20-deployment.yaml` | Deployment `speakr` (1 реплика, `strategy: Recreate`), TCP-пробы 8899 |
| `30-service.yaml` | ClusterIP `speakr:8899` |
| `40-ingress.yaml` | `Certificate spk-demo-tls` + `Ingress spk` (class `higress`) |

Почему так (детали в спеке):

- ASR-коннектор — `openai_whisper` (OpenAI-совместимый `/v1/audio/transcriptions` на GPUStack),
  **не** `asr_endpoint` (тот постит multipart на `/asr`).
- `ALLOW_REGISTRATION=false` — в коде дефолт `true`, снаружи это открытая саморегистрация.
- `/health` у приложения нет (`GET /` → 302) → пробы `tcpSocket`.
- Образ работает от root и сам делает `chmod 755` на `/data`: `runAsUser` не задавать.

Секреты (ns `spk`, создаются до первого синка; в git только ссылки):

| Secret | Ключи | Откуда |
|---|---|---|
| `spk-secrets` | `SECRET_KEY`, `TRANSCRIPTION_API_KEY`, `TEXT_MODEL_API_KEY`, `ADMIN_USERNAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` | `spk-admin.local.md`; ключи моделей — `gpustack-admin.local.md` (тот же ключ, что у `owu`) |
| `spk-oidc` | `SSO_CLIENT_ID=spk`, `SSO_CLIENT_SECRET` | `scripts/keycloak_seed.py` → `keycloak-clients.local.md` |

`SECRET_KEY` обязателен и постоянен: без него приложение генерирует свой и кладёт в `/data/instance`
(сессии теряются при пересоздании тома).
