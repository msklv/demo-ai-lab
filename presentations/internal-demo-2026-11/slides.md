---
theme: default
layout: cover
title: AI Демо стенд
subtitle: ГНИВЦ · внутреннее демо. Стенд, архитектура, семь кейсов — и три задания, которые вы выполните сами.
info: |
  Внутренний показ стенда demo-ai-lab: архитектура, семь кейсов,
  три интерактивных задания и список сервисов со ссылками.
canvasWidth: 1280
aspectRatio: 16/9
transition: fade
drawings: false
fonts:
  sans: Rubik
  provider: google
---

<AccentCallout :lines="[
  'Четыре мини-ПК, одна GPU-карта, ноль облачных инференсов',
  'Наружу уходит только обезличенное — и только через шлюз',
  'Сервисы открыты: входите и проверяете сами'
]" />

<!--
Приветствие. Рамка: «сегодня не доклад, а экскурсия по работающему стенду».
Полтора часа: ~30 минут архитектура и кейсы, ~30 минут задания, остальное — вопросы.
Сразу предупредить: учётки демо-пула выдаются на входе, ссылки — на слайде после архитектуры.
-->

---
layout: numbered-row-list
tag: Формат
title: Как устроено это демо
subtitle: Сначала показываю стенд и логику решений, потом идём по кейсам. Задания идут по ходу, а не свалкой в конце.
---

<NumberedRowCard n="01" title="Интерактив, а не лекция" description="На трёх станциях вы сами отправляете запрос и видите результат: DLP, разбор документа, агент. Учётки — пул demo01…, выдаются на входе." />
<NumberedRowCard n="02" title="Стенд — не облако" description="Всё, что видно на экране, считается здесь: кластер из четырёх мини-ПК и одна RTX 5060 Ti на 16 ГБ." />
<NumberedRowCard n="03" title="Модели переключаются по ходу" description="Карта одна, поэтому перед каждым кейсом поднимается нужная модель. Один Start/Stop — 1–2 минуты; это часть рассказа, а не пауза." />
<NumberedRowCard n="04" title="Ссылки — на слайде «Что открыть»" description="Список пользовательских сервисов со ссылками идёт сразу после архитектуры. Откройте вкладки заранее." variant="accent" />

<!--
Правила зала: заходим по Wi-Fi, адреса — LAN-имена, интернет не обязателен.
Ключевая мысль: переключение моделей — не техническая пауза, а главный аргумент «цена одной карты».
-->

---
layout: section-divider
tag: Часть 1
title: Стенд и архитектура
subtitle: Что стоит в стойке, из каких слоёв это собрано и по какому пути идёт запрос.
---

---
layout: card-grid-4
tag: Стенд · физика
title: Стенд в цифрах
subtitle: Один стенд, который целиком помещается в стойку и не зависит от облачного инференса.
---

<NumberedCard n="4" unit="узла" title="мини-ПК GMKtec" body="Ubuntu 24.04, kubeadm 1.35, Cilium + Longhorn. Три control-plane и одна GPU-нода k8s-04." />
<NumberedCard n="16" unit="ГБ" title="VRAM на стенде" body="RTX 5060 Ti. Полезно 16 GiB — этого хватает ровно на одну большую модель за раз." />
<NumberedCard n="2" unit="VIP" title="разные плоскости" body=".240 — API кластера, .230 — вход сервисов. Разведены, чтобы падение ingress не роняло кластер." />
<NumberedCard n="0" unit="" title="облачных инференсов" body="LLM, OCR, эмбеддинги и диффузия считаются на стенде. Наружу — только текст под DLP." variant="accent" />

<!--
Цифры — якорь всего рассказа. 16 GiB — это не «мало», это «ровно один кейс за раз».
Два VIP — следствие решения: плоскость управления и плоскость входа не склеиваем.
-->

---
layout: split-light
tag: Стенд · физика
title: Одна стойка, четыре узла
frameLabel: Схема стенда
---

<template #left>

# Одна стойка, четыре узла

<NumberedRowCard n="01" title="Кластер на мини-ПК" description="k8s-01…04: три control-plane и GPU-нода. MikroTik, L2-коммутатор и консоль — в той же стойке." />
<NumberedRowCard n="02" title="Одна GPU-карта" description="RTX 5060 Ti 16 ГБ на выносном подключении к k8s-04; веса моделей — на local hostPath, не на сетевом томе." />
<NumberedRowCard n="03" title="Два пути, один адрес" description="Из LAN — split-DNS на .230; снаружи — внешняя VM в Cloud.ru: haproxy в режиме tcp и SSH-hop с k8s-02/03. Имя и TLS одинаковые." />
<NumberedRowCard n="04" title="Данные на Longhorn" description="Три диска по 250 ГБ, replica=2. k8s-01 вне пула реплик: у него самый изношенный NVMe." variant="accent" />

</template>

<template #right>

<StandTopology />

</template>

<!--
Провести по схеме: гость → MikroTik → коммутатор → узлы; вход сервисов — .230 на паре 02/03.
Отдельно про GPU: карта одна и она на выносном подключении — это ограничение всей программы.
-->

---
layout: split-dark
tag: Стенд · логика
title: Шесть слоёв C2
frameLabel: Слои
---

<template #left>

# Шесть слоёв, один вход

<div class="block-list">
<div class="block-list__item">
<div class="block-list__label">Пользовательские сервисы</div>
<div class="block-list__body">Open WebUI, Speakr, Docling, RAG в OWU — то, что зал открывает в браузере.</div>
</div>
<div class="block-list__item">
<div class="block-list__label">MCP и агенты</div>
<div class="block-list__body">doc. и ysrch. как инструменты, Hermes Agent как рантайм. Инструменты берутся из каталога, а не зашиты в код.</div>
</div>
<div class="block-list__item">
<div class="block-list__label">Инференс и периметр</div>
<div class="block-list__body">GPUStack + vLLM на карте; Higress — единственный вход, Keycloak — SSO, DLP и страж — на том же шлюзе.</div>
</div>
</div>

</template>

<template #right>

<LayerStack />

</template>

<!--
Слои показывать снизу вверх: данные/ops → инференс → guardrail → MCP → сервисы → агент.
Подчеркнуть: защиты не отдельный сервис, а плагины шлюза — поэтому их нельзя «забыть включить в приложении».
-->

---
layout: step-flow
tag: Стенд · потоки
title: Путь запроса
subtitle: Любой пользовательский запрос идёт одной дорогой — поэтому защита, лимиты и учёт стоят в одном месте.
calloutLabel: Исключение
calloutText: Внешняя модель идёт не в GPUStack, а через llm-svc. key-auth → DLP → страж → провайдер → лимиты. Это отдельный кейс 02.
---

<StepFlow :steps="[
  { label: 'Шаг 1', title: 'DNS и вход', body: 'split-DNS на .230, TLS Let’s Encrypt' },
  { label: 'Шаг 2', title: 'Higress', body: 'маршрут по хосту, SSO-редирект в Keycloak' },
  { label: 'Шаг 3', title: 'Сервис', body: 'OWU, Speakr, Docling, агент' },
  { label: 'Шаг 4', title: 'GPUStack', body: 'OpenAI-совместимый API, модель из каталога' },
  { label: 'Шаг 5', title: 'GPU', body: 'RTX 5060 Ti или 780M на k8s-01', variant: 'accent' }
]" />

<!--
Смысл слайда: одна точка входа = одна точка контроля. Не надо объяснять каждому сервису, что такое DLP.
Если спросят про внешний трафик — переходим к исключению и обещаем вернуться в кейсе 02.
-->

---
layout: split-light
tag: Стенд · бюджет VRAM
title: Цена одной карты
frameLabel: Занято на RTX 5060 Ti
---

<template #left>

# 16 GiB — это один кейс за раз

<p class="subtitle">Страж внешнего маршрута занимает 12,7 GiB. 27B — до 15,6. Поэтому локальная модель и внешний маршрут на одной карте не живут вместе — отсюда порядок кейсов.</p>

<NumberedRowCard n="01" title="Страж Qwen3Guard 4B" description="12,7 GiB, util 0.80. На нём стоят все кейсы с внешней моделью: 02, 05, 06." />
<NumberedRowCard n="02" title="Qwen3.8-27B-UD" description="15,1–15,6 GiB эксклюзивно. 128K контекста — кейс 01." />
<NumberedRowCard n="03" title="Z-Image-Turbo" description="12,4 GiB простой, 15,3 в пике на 1024². Кейс 07." />
<NumberedRowCard n="04" title="bge-m3 + реранк" description="2,8 GiB GTT — но на 780M узла k8s-01, карту не занимают. Кейс 05." variant="accent" />

</template>

<template #right>

<VramBars :items="[
  { label: 'Qwen3.8-27B-UD', value: 15.6 },
  { label: 'Страж 4B', value: 12.7 },
  { label: 'Z-Image-Turbo', value: 12.4 },
  { label: 'GLM-OCR', value: 11.9 },
  { label: 'ASR + страж 0.6B', value: 3.7 },
  { label: 'bge-m3 + реранк (780M)', value: 2.8, variant: 'accent' }
]" />

</template>

<!--
Ключевой слайд экономики: не «почему нельзя всё сразу», а «почему программа так устроена».
16 GiB (16 311 MiB). Страж — util 0.80, это осознанное решение (ADR-0007): модерация в горячем пути.
-->

---
layout: links
tag: Сервисы · ссылки
title: Что можно открыть прямо сейчас
subtitle: Пользовательские сервисы стенда. Вход по SSO Keycloak — учётка из пула demo01…; doc., ysrch. и каталог MCP открыты без входа.
---

<div class="link-grid">
<ServiceLink name="Open WebUI" url="https://owu.demo-ai-lab.ru" auth="SSO" note="чат к локальным моделям и к deepseek-flash через llm-svc." />
<ServiceLink name="GPUStack" url="https://api.demo-ai-lab.ru" auth="SSO · ключ" note="каталог моделей, деплой и API; здесь переключаются модели" />
<ServiceLink name="Speakr" url="https://spk.demo-ai-lab.ru" auth="SSO" note="транскрибация аудио и видео, саммари" />
<ServiceLink name="Docling" url="https://doc.demo-ai-lab.ru/ui" auth="без входа" note="OCR и разбор документов → markdown; MCP на /mcp" />
<ServiceLink name="Hermes Agent" url="https://hm.demo-ai-lab.ru" auth="SSO" note="агент с инструментами doc. и ysrch." />
<ServiceLink name="MCP-каталог" url="https://mcp.demo-ai-lab.ru" auth="без входа" note="витрина MCP-серверов: docling и yandex-search" />
<ServiceLink name="Yandex Search MCP" url="https://ysrch.demo-ai-lab.ru/mcp" auth="без входа" note="веб-поиск как инструмент агента, /mcp" />
<ServiceLink name="Keycloak" url="https://auth.demo-ai-lab.ru" auth="SSO" note="единый вход: одна учётка на все сервисы" />
</div>

<p class="muted" style="font-size: 11.5px; margin-top: 10px;">Служебные UI — Argo CD (argo.), консоль Higress (hgc.), Longhorn (lng.), мониторинг (mon.) — только из LAN: снаружи <span class="mono">403</span>.</p>

<!--
Попросить открыть две вкладки сразу: OWU и Docling — они нужны в заданиях.
Про api.: UI — через SSO, API-путь — по ключу GPUStack, это разные вещи.
-->

---
layout: section-divider
tag: Часть 2
title: Семь кейсов
subtitle: "По одному вопросу на кейс: что показываем, чем платим и что уходит наружу."
---

---
layout: case-title
number: "\"01\""
kicker: "инференс"
title: "27B на одной карте"
thesis: "128K контекста в 16 ГБ — и только эксклюзивно: рядом на карте не живёт ничего."
models: "Qwen3.8-27B-UD · 15,1–15,6 ГБ"
---

---
layout: split-dark
tag: Кейс 01 · 27B на одной карте
title: 128K контекста в 16 ГБ
frameLabel: Факты
---

<template #left>

# 128K контекста в 16 ГБ

<div class="block-list">
<div class="block-list__item">
<div class="block-list__label">Что показываем</div>
<div class="block-list__body">Qwen3.8-27B-UD через BeeLlama custom backend: контекст 128K, needle-тест пройден на 97K.</div>
</div>
<div class="block-list__item">
<div class="block-list__label">Чем платим</div>
<div class="block-list__body">15,1–15,6 GiB — модель только эксклюзивная. Рядом на карте не живёт ничего, переключение — 40–90 секунд.</div>
</div>
<div class="block-list__item">
<div class="block-list__label">Почему это важно</div>
<div class="block-list__body">Модель класса «нужен сервер» работает на одной потребительской карте — если уметь обращаться с квантованием и KV-кэшем.</div>
</div>
</div>

</template>

<template #right>

<div class="fact-stack">
<div class="fact"><div class="fact__value">128K</div><div class="fact__label">контекст без облака</div></div>
<div class="fact"><div class="fact__value">97K</div><div class="fact__label">needle-тест пройден</div></div>
<div class="fact"><div class="fact__value">15,6 ГБ</div><div class="fact__label">пик VRAM — карта занята целиком</div></div>
<div class="fact fact--accent"><div class="fact__value">0</div><div class="fact__label">соседей на карте: эксклюзивный режим</div></div>
</div>

</template>

<!--
Тезис: «27B на одной карте — это не про скорость, а про то, что модель никуда не уходит».
Отметить: пока идёт кейс, параллельно уже жмём Stop 27B за минуту до конца — переключение не должно стать паузой.
-->

---
layout: case-title
number: "\"02\""
kicker: "периметр"
title: "Внешний маршрут под защитой"
thesis: "Локальные модели — не религия: наружу можно, но только через DLP, стража и квоты."
models: "Qwen3Guard-Gen-4B · ≈12,7 ГБ"
---

---
layout: split-light
tag: Кейс 02 · внешний маршрут
title: Наружу — только под защитой
frameLabel: Конвейер llm-svc.
---

<template #left>

# Наружу — только под защитой

<NumberedRowCard n="01" title="Один шлюз, четыре защиты" description="key-auth → DLP ai-data-masking → страж ai-qwen-guard → ai-proxy (DeepSeek) → ai-token-ratelimit. В приложении правок нет." />
<NumberedRowCard n="02" title="DLP видит ПДн, модель — нет" description="Телефон и почта заменяются на <PHONE>/<EMAIL> до провайдера и восстанавливаются в ответе (restore)." />
<NumberedRowCard n="03" title="Страж — рубильник" description="Нет стража — нет запроса: 503 guard unavailable (fail-closed). Не «пропустили без проверки», а «не проверили — не пропустили»." />
<NumberedRowCard n="04" title="Пять кодов одного маршрута" description="200 — обычный, «0 цифр» — DLP, 403 — страж, 429 — квота, 503 — предохранитель." variant="accent" />

</template>

<template #right>

<ChainDiagram direction="col" :steps="[
  { label: 'вход', title: 'key-auth', note: 'статический ключ, 401 без него' },
  { label: 'DLP', title: 'ai-data-masking', note: 'телефон, почта, IP, ключи → токены' },
  { label: 'страж', title: 'Qwen3Guard-Gen-4B', note: 'Safe / Controversial / Unsafe, fail-closed' },
  { label: 'прокси', title: 'ai-proxy → DeepSeek', note: 'ключ провайдера в Secret, наружу не выдаётся' },
  { label: 'лимиты', title: 'ai-token-ratelimit', note: '60 000 ток/мин, 2 000 000 ток/сутки', variant: 'accent' }
]" />

</template>

<!--
Важно: это не «ещё один прокси», а единственная точка, где политика применяется ко всем клиентам.
DLP в логах не виден — доказывается поведением (следующее задание). Страж блокирует 403 за 0,31 с.
-->

---
layout: task
tag: Задание 1 · DLP · 7 минут
title: Поймайте DLP на внешней модели
subtitle: Откройте owu.demo-ai-lab.ru, выберите deepseek-flash и задайте вопрос про телефон. Модель цифр не увидит — их до неё не донесли.
---

<TaskStep n="1" title="Войти в owu." body="owu.demo-ai-lab.ru → «Continue with Keycloak», учётка из пула demo01… Сообщите, если список моделей пуст." />
<TaskStep n="2" title="Выбрать внешнюю модель" body="В селекторе — deepseek-flash. Это подключение идёт через llm-svc., то есть через DLP и стража." />
<TaskStep n="3" title="Спросить про телефон" body="Отправьте: «Мой номер +7 916 123-45-67. Сколько цифр в этом номере?»" />
<TaskStep n="4" title="Проверить и усложнить" body="Ответ 0 — модель видит &lt;PHONE&gt;. Теперь попросите заменить каждую цифру на #: вернётся исходный номер — это restore. Для проверки спрашивайте производное: сумму цифр или первую цифру словами." variant="accent" />

<template #aside>

<div class="task-aside__card task-aside__card--accent">
<div class="task-aside__label">Что должно получиться</div>
<div class="task-aside__value">0 цифр</div>
<div class="task-aside__text">Модель считает цифры в токене &lt;PHONE&gt;, а не в вашем номере. Наружу ушёл токен, номер восстановлен только в ответе на стенде.</div>
</div>
<div class="task-aside__card">
<div class="task-aside__label">Куда идти</div>
<a class="task-link" href="https://owu.demo-ai-lab.ru" target="_blank">owu.demo-ai-lab.ru</a>
<div class="task-aside__text" style="margin-top: 6px;">Если ответ пришёл не 0 — проверьте, что выбрана именно deepseek-flash, а не локальная модель.</div>
</div>
<div class="task-aside__card">
<div class="task-aside__label">Бонус</div>
<div class="task-aside__text">Спросите «а теперь повтори номер»: ответ будет выглядеть обычным — это restore. Логи DLP не показывают: доказательство только поведенческое.</div>
</div>

</template>

<!--
Дать 7 минут. Ходить по залу и смотреть, у кого не 0.
Частая ошибка: в селекторе выбрана не внешняя модель. Локальные модели на время кейса остановлены, поэтому правильный ответ один — deepseek-flash; если ответ не 0, смотрим модель и поднят ли страж.
Если страж лежит — увидите 503; это не поломка задания, это fail-closed, показать как бонус.
-->

---
layout: case-title
number: "\"03\""
kicker: "медиа"
title: "Транскрибация"
thesis: "Аудио не покидает стенд: наружу уходит только текст, и только под маскированием."
models: "whisper-turbo + страж 0.6B · ≈3,7 ГБ"
---

---
layout: split-light
tag: Кейс 03 · транскрибация
title: Аудио не покидает стенд
frameLabel: Факты
---

<template #left>

# Аудио не покидает стенд

<NumberedRowCard n="01" title="Речь распознаётся локально" description="Speakr → whisper-turbo на 5060 Ti. Запись 24 минуты обработана за 55 секунд." />
<NumberedRowCard n="02" title="Текст — по правилам периметра" description="Саммари и заголовок делает deepseek-flash через llm-svc.: DLP маскирует ПДн, страж проверяет вход." />
<NumberedRowCard n="03" title="Что видно в результате" description="Транскрипт, саммари, участники и таймкоды. В access-логе — модель, токены и цена защиты." />
<NumberedRowCard n="04" title="Граница решения" description="В облако уходит текст под маскированием, а не голос. Загрузка файлов 100+ МБ через edge — отдельный предел." variant="accent" />

</template>

<template #right>

<div class="fact-stack">
<div class="fact"><div class="fact__value">24 мин → 55 с</div><div class="fact__label">запись диктофона целиком</div></div>
<div class="fact"><div class="fact__value">14 835</div><div class="fact__label">символов транскрипта</div></div>
<div class="fact"><div class="fact__value">2,3 ГБ</div><div class="fact__label">ASR на карте рядом со стражем 0.6B</div></div>
<div class="fact fact--accent"><div class="fact__value">0 с</div><div class="fact__label">аудио, ушедшего наружу</div></div>
</div>

</template>

<!--
Тезис: «самое дорогое в транскрибации — не модель, а доверие к тому, куда уехал звук».
Рядом со стражем 4B ASR не влезает, поэтому в этом кейсе страж — 0.6B под тем же внешним ID. Плагин не меняется.
-->

---
layout: case-title
number: "\"04\""
kicker: "документы"
title: "OCR на своём железе"
thesis: "Бумага — самый частый вид данных, которые нельзя отдавать. Распознаём здесь."
models: "GLM-OCR · ≈11,9 ГБ"
---

---
layout: split-dark
tag: Кейс 04 · OCR
title: Бумага остаётся на стенде
frameLabel: Конвейер разбора
---

<template #left>

# Бумага остаётся на стенде

<div class="block-list">
<div class="block-list__item">
<div class="block-list__label">Что показываем</div>
<div class="block-list__body">Docling на CPU делает layout, таблицы и markdown; GLM-OCR на GPU распознаёт текст. Русский скан — за 0,4 секунды на страницу.</div>
</div>
<div class="block-list__item">
<div class="block-list__label">Где тонко</div>
<div class="block-list__body">Кириллица требует явного пресета ru-en: без него сервер идёт auto и портит текст. Рукопись и повёрнутые сканы — по-прежнему слабое место.</div>
</div>
<div class="block-list__item">
<div class="block-list__label">Зачем это агенту</div>
<div class="block-list__body">Тот же движок доступен как MCP-инструмент на /mcp — агент разбирает документы, не зная, как устроен OCR.</div>
</div>
</div>

</template>

<template #right>

<ChainDiagram direction="col" :steps="[
  { label: 'вход', title: 'Скан или фото', note: 'PDF, PNG, страница с телефона' },
  { label: 'Docling', title: 'layout · таблицы', note: 'CPU, без GPU и без облака' },
  { label: 'GLM-OCR', title: 'распознавание', note: 'vLLM на 5060 Ti, ≈11,9 ГБ, 0,4 с/стр.' },
  { label: 'выход', title: 'markdown', note: 'структура и таблица сохранены', variant: 'accent' }
]" />

</template>

<!--
Честно про ограничения: это не «любой документ», а «хороший скан — да».
Если спросят про VLM-описания картинок — в бюджете карты их нет, DO_PICTURE_DESCRIPTION выключен.
-->

---
layout: task
tag: Задание 2 · Docling · 8 минут
title: Превратите Word (docx) в markdown
subtitle: doc.demo-ai-lab.ru/ui открывается без входа. Загрузите свой рабочий .docx — с заголовками, списками и хотя бы одной таблицей.
---

<TaskStep n="1" title="Открыть playground" body="doc.demo-ai-lab.ru/ui — без входа. Для docx это структурный разбор документа: распознавание текста не требуется." />
<TaskStep n="2" title="Загрузить .docx" body="Свой рабочий документ: заголовки, списки, таблица. Файл с картинками и вложенными объектами — тоже годится." />
<TaskStep n="3" title="Сравнить структуру" body="В playground справа появится markdown: заголовки — своими уровнями, списки — нумерацией, таблица — markdown-таблицей. Смотрите структуру, а не только текст." />
<TaskStep n="4" title="Проверить критерий" body="Документ читается как markdown без ручной правки: таблица осталась таблицей, порядок блоков сохранён. Где тонко — сложные таблицы и вложенные объекты." variant="accent" />

<template #aside>

<div class="task-aside__card task-aside__card--accent">
<div class="task-aside__label">Критерий</div>
<div class="task-aside__value">без ручной правки</div>
<div class="task-aside__text">Таблица — таблицей, заголовки — заголовками, списки — списками. Если структура поехала, это и есть честный результат: покажите его.</div>
</div>
<div class="task-aside__card">
<div class="task-aside__label">Куда идти</div>
<a class="task-link" href="https://doc.demo-ai-lab.ru/ui" target="_blank">doc.demo-ai-lab.ru/ui</a>
<div class="task-aside__text" style="margin-top: 6px;">Тот же движок доступен агенту как MCP — на /mcp; его использует агент в третьем задании.</div>
</div>
<div class="task-aside__card">
<div class="task-aside__label">Подсказка</div>
<div class="task-aside__text">Если захотите сравнить: тот же текст в PDF идёт через OCR и пресет ru-en — разница в структуре видна сразу. Это уже кейс 04.</div>
</div>

</template>

<!--
8 минут. docx разбирается на CPU как структура документа — GPU и OCR здесь не нужны.
Замечание вслух: скан или PDF идёт другим путём (OCR, пресет ru-en, GLM-OCR) — это кейс 04, а не это задание.
Кто закончил раньше — пусть сравнит результат с тем же текстом в PDF: структура docx обычно чище.
-->

---
layout: case-title
number: "\"05\""
kicker: "поиск"
title: "RAG: дорогая часть — поиск"
thesis: "Эмбеддинги и реранк на стенде; наружу уходит только отобранный контекст."
models: "страж 4B + bge-m3 и реранк на 780M"
---

---
layout: split-dark
tag: Кейс 05 · RAG
title: Дорогая часть RAG — поиск
frameLabel: Конвейер RAG
---

<template #left>

# Дорогая часть RAG — поиск

<div class="block-list">
<div class="block-list__item">
<div class="block-list__label">Что считается на стенде</div>
<div class="block-list__body">bge-m3 и bge-reranker-v2-m3 на 780M узла k8s-01: 2,8 из 11,6 GiB GTT. 5060 Ti в этом кейсе занята только стражем.</div>
</div>
<div class="block-list__item">
<div class="block-list__label">Что уходит наружу</div>
<div class="block-list__body">Только отобранный после реранка контекст. Корпус и эмбеддинги не покидают стенд.</div>
</div>
<div class="block-list__item">
<div class="block-list__label">Где потрогать сегодня</div>
<div class="block-list__body">RAG в Open WebUI: база знаний в чате, гибридный поиск, реранк. RAGFlow как отдельный сервис — следующий шаг.</div>
</div>
</div>

</template>

<template #right>

<ChainDiagram direction="col" :steps="[
  { label: 'корпус', title: 'документы стенда', note: 'разбор через Docling' },
  { label: 'поиск', title: 'bge-m3 · 780M', note: 'эмбеддинги, dim 1024, 0,10–0,13 с' },
  { label: 'уточнение', title: 'bge-reranker-v2-m3', note: 'топ-k после реранка, 0,13–0,21 с' },
  { label: 'генерация', title: 'deepseek-flash', note: 'через llm-svc.: DLP + страж', variant: 'accent' }
]" />

</template>

<!--
Аккуратно с ожиданиями: RAGFlow не развёрнут, сегодня RAG — в Open WebUI на тех же моделях 780M.
Тезис: наружу уезжает не база, а три-четыре отобранных абзаца.
-->

---
layout: case-title
number: "\"06\""
kicker: "агенты"
title: "Агент в песочнице"
thesis: "Агент исполняет чужой текст — значит, ограничен политикой, а не доверием."
models: "страж 4B · deepseek-flash через llm-svc."
---

---
layout: split-light
tag: Кейс 06 · агенты
title: Агент — это цикл, а не чат
frameLabel: Цикл агента
---

<template #left>

# Агент — это цикл, а не чат

<NumberedRowCard n="01" title="Решил → вызвал → посмотрел" description="Модель не отвечает сразу: она выбирает инструмент, получает результат и решает снова." />
<NumberedRowCard n="02" title="Инструменты — из каталога" description="doc. и ysrch. подключены как MCP-серверы и опубликованы в mcp. Агент видит их как инструменты, а не как захардкоженный код." />
<NumberedRowCard n="03" title="Рантайм — в кластере" description="Hermes Agent на hm.demo-ai-lab.ru за SSO, отдельный namespace, свои requests/limits. Модель — deepseek-flash через llm-svc." />
<NumberedRowCard n="04" title="Ограничен политикой, не доверием" description="Агент исполняет чужой текст. Полная песочница (квоты + NetworkPolicy + запрет API кластера) — следующий шаг, не сегодняшний." variant="accent" />

</template>

<template #right>

<ChainDiagram direction="col" :steps="[
  { label: 'шаг 1', title: 'задача', note: 'разбери документ и сверь с вебом' },
  { label: 'шаг 2', title: 'tools/list', note: 'какие инструменты доступны' },
  { label: 'шаг 3', title: 'docling', note: 'PDF → markdown на стенде' },
  { label: 'шаг 4', title: 'web_search', note: 'ysrch. → Yandex Search API' },
  { label: 'шаг 5', title: 'ответ + трейс', note: 'шаги, инструменты, токены', variant: 'accent' }
]" />

</template>

<!--
Главное: разница между «чатом побольше» и агентом — в цикле и в инструментах.
Про песочницу говорить честно: сегодня изоляция — namespace и лимиты; полноценная песочница в плане (ADR).
-->

---
layout: task
tag: Задание 3 · агент · 10 минут
title: Дайте агенту задачу с двумя источниками
subtitle: hm.demo-ai-lab.ru → вход через Keycloak. Задача — заставить агента использовать и разбор документа, и веб-поиск.
---

<TaskStep n="1" title="Войти в панель" body="hm.demo-ai-lab.ru, «войти через Keycloak» (клиент hm, public + PKCE)." />
<TaskStep n="2" title="Дать задачу с PDF" body="«Разбери PDF по ссылке &lt;ваша ссылка&gt; инструментом docling и найди в интернете, что это за стандарт. Дай ответ со ссылками на оба источника.»" />
<TaskStep n="3" title="Смотреть трейс, не только ответ" body="В панели видно шаги: какие инструменты вызваны, в каком порядке, сколько токенов ушло." />
<TaskStep n="4" title="Сломать по-доброму" body="Попросите инструмент, которого нет, или недоступную ссылку. Хороший агент не падает: сообщает об отказе и предлагает обход." variant="accent" />

<template #aside>

<div class="task-aside__card task-aside__card--accent">
<div class="task-aside__label">Критерий</div>
<div class="task-aside__value">≥ 2 инструмента</div>
<div class="task-aside__text">В трейсе — вызов docling и web_search, ответ опирается на оба источника, а не на память модели.</div>
</div>
<div class="task-aside__card">
<div class="task-aside__label">Куда идти</div>
<a class="task-link" href="https://hm.demo-ai-lab.ru" target="_blank">hm.demo-ai-lab.ru</a>
<div class="task-aside__text" style="margin-top: 6px;">Модель — deepseek-flash через llm-svc. Если страж выключен, ответ будет 503: это fail-closed, не поломка агента.</div>
</div>
<div class="task-aside__card">
<div class="task-aside__label">Запасной вариант</div>
<div class="task-aside__text">Без PDF: «Найди в интернете актуальную версию ГОСТ … и кратко опиши, что он регулирует; укажи ссылку».</div>
</div>

</template>

<!--
10 минут. Просить показать трейс — это важнее ответа.
Если агент долго думает: deepseek-flash тратит много reasoning-токенов, это нормально.
-->

---
layout: case-title
number: "\"07\""
kicker: "генерация"
title: "Картинка на своей карте"
thesis: "Самый «облачный» на вид результат — и всё равно без облака."
models: "Z-Image-Turbo fp8 · 12,4–15,3 ГБ"
---

---
layout: split-light
tag: Кейс 07 · генерация изображений
title: Картинка без облака
frameLabel: Факты
---

<template #left>

# Картинка без облака

<NumberedRowCard n="01" title="Самый «облачный» на вид результат" description="Z-Image-Turbo, 8 шагов, 512×512 — 3,0–3,6 секунды на кадр. Промпт не покидает стенд." />
<NumberedRowCard n="02" title="Квант — только fp8" description="int8 падает на sm_120: Blackwell в этой сборке vLLM-Omni его не поддерживает. Это выяснилось замером, а не документацией." />
<NumberedRowCard n="03" title="Цена — вся карта" description="12,4 GiB простой, 15,3 в пике на 1024². Страж гасится, внешний маршрут отдаёт 503 — в кейсе он не нужен." />
<NumberedRowCard n="04" title="Счёт за картинку — нулевой" description="Нет ни промпта наружу, ни изображения наружу. Модерировать нечего: текстовый плагин на этом маршруте не стоит." variant="accent" />

</template>

<template #right>

<div class="fact-stack">
<div class="fact"><div class="fact__value">3,0–3,6 с</div><div class="fact__label">512×512, 8 шагов</div></div>
<div class="fact"><div class="fact__value">12,8–13,4 с</div><div class="fact__label">1024², если нужно крупнее</div></div>
<div class="fact"><div class="fact__value">12,4 / 15,3 ГБ</div><div class="fact__label">простой / пик VRAM</div></div>
<div class="fact fact--accent"><div class="fact__value">0 ₽</div><div class="fact__label">за кадр: карта своя</div></div>
</div>

</template>

<!--
Финальный кейс программы: после него карту возвращать не нужно.
Закрывающая мысль: «даже то, что принято отдавать в облако, может остаться здесь».
-->

---
layout: perspective
tag: Что дальше
title: Куда двигается стенд
subtitle: Семь кейсов — это не финальная точка, а работающий каркас. Дальше — три направления.
---

<div class="card-grid card-grid--3">
<NumberedCard n="01" title="RAGFlow" body="Отдельный RAG-сервис на k8s-01 с собственной базой знаний: сейчас RAG живёт внутри Open WebUI." />
<NumberedCard n="02" title="Песочница агентов" body="Квоты, NetworkPolicy и запрет API кластера для рантаймов. Сейчас изоляция — namespace и лимиты." />
<NumberedCard n="03" title="Операционная зрелость" body="Мониторинг Kuvasz, health-скрипты, автопродление TLS — чтобы стенд переживал ребуты без ручной сборки." variant="accent" />
</div>

<div style="margin-top: 12px; border-radius: 12px; background: #6B3FF7; color: #FFF; padding: 14px 22px; display: flex; align-items: center; gap: 18px;">
<div style="font-size: 26px; font-weight: 700; color: #C6F542; line-height: 1;">→</div>
<div>
<div style="font-size: 10.5px; letter-spacing: .09em; text-transform: uppercase; color: #C6F542; margin-bottom: 3px;">Следующий шаг</div>
<div style="font-size: 14px; line-height: 1.4;">Сценарии, которых здесь нет: что из вашей работы стоит перевести на этот стенд — и что для этого нужно.</div>
</div>
</div>

<!--
Мостик к разговору: стенд открыт для экспериментов, а не только для показа.
Собрать запросы зала: какие документы, какие модели, какие интеграции нужны в первую очередь.
-->

---
layout: closing
tag: Вопросы
---

# Стенд открыт — <em>и он ваш</em>

<p style="font-size: 19px; color: #E7DDFF; max-width: 52ch; line-height: 1.45;">Ссылки — на слайде «Что можно открыть». Учётки — пул demo01…, стенд живёт в LAN, адреса те же, что и снаружи.</p>

<div class="accent-callout" style="margin-top: 18px;">
<p>Задания можно доделать после демо: сервисы никуда не денутся</p>
<p>Ограничения и планы — в документации стенда, не в презентации</p>
</div>

<template #footer>

<div class="mini-cards">
<div class="mini-card"><div class="mini-card__label">Документация</div><div class="mini-card__text">architecture/ARCHITECTURE.md, cases/ — по кейсу на файл</div></div>
<div class="mini-card"><div class="mini-card__label">Здоровье стенда</div><div class="mini-card__text">scripts/k8s_health.py и env_health.py — один прогон</div></div>
<div class="mini-card"><div class="mini-card__label">Контакт</div><div class="mini-card__text">Соколов М.А. — вопросы по стенду и доступам</div></div>
</div>

</template>

<!--
Спасибо. Дальше — вопросы и подходите к стенду: можно потрогать руками.
Не обещать сроков по RAGFlow и песочнице: это направления, а не даты.
-->
