# ГНИВЦ Design System для Slidev

---

## 1. Стиль

**Dual-mode корпоративная тема** на единственном шрифте **Rubik** (400/700/900) — системность строится на weight-контрасте, serif-пар нет.

- **Dark mode** (фиолетовый градиент `#6B3FF7 → #4A25B8`, белый текст): cover, section-divider, scenario-intro, closing
- **Light mode** (белый/сиреневый фон `#FFFFFF → #F4EFFF`, чёрный заголовок): content, steps, results, perspective

**Фирменные маркеры:**
- Логотип «ГНИВЦ» — top-right; белый на dark, фиолетовый `#6B3FF7` на light
- Лайм `#C6F542` — **только** на финальных/акцентных картах и сепараторах
- Dot pattern (точки, right-bottom cover) · левый лайм-бордер на цитатах/тезисах · нумерованные карточки с большим числом (60pt bold) как якорь

---

## 2. Design Tokens

### 2.1 Цвета

| Token | Hex | Назначение |
|-------|-----|-----------|
| `--color-primary` | `#6B3FF7` | Бренд, фон dark-слайдов |
| `--color-primary-dark` | `#4A25B8` | 2-я точка градиента |
| `--color-primary-light` | `#9B7DF9` | Hover / светлые варианты |
| `--color-accent` | `#C6F542` | Финальные карты, сепараторы, highlight |
| `--color-surface-dark` | `#2A2735` | Фон карт на dark (оверлей) |
| `--color-surface-light` | `#F4EFFF` | Фон карт на light (сиреневый тинт) |
| `--color-surface-white` | `#FFFFFF` | Белые карточки на light |
| `--color-bg-light` | `#FFFFFF` | Фон light-слайдов |
| `--color-text-primary-dark` | `#FFFFFF` | Текст на dark |
| `--color-text-primary-light` | `#0F0F14` | Текст на light |
| `--color-text-muted-dark` | `#E7DDFF` | Subdued на dark |
| `--color-text-muted-light` | `#6B6680` | Subdued на light |
| `--color-text-accent-dark` | `#C6F542` | Лайм-текст на dark (highlight, номера акцент-карт) |
| `--color-text-accent-light` | `#6B3FF7` | Фиолет на light (номера, метки) |
| `--color-border-card` | `rgba(107,63,247,0.18)` | Граница карт (light) |
| `--color-border-card-dark` | `rgba(231,221,255,0.15)` | Граница карт (dark) |
| `--color-tag-bg` | `rgba(255,255,255,0.1)` | Фон пилюли-тега (dark) |
| `--color-tag-bg-light` | `rgba(107,63,247,0.08)` | Фон пилюли-тега (light) |
| `--color-separator` | `#C6F542` | Горизонтальный акцент-разделитель в картах |

**Градиент (dark):** `linear-gradient(135deg, #6B3FF7 0%, #5831D6 40%, #4A25B8 100%)`

### 2.2 Типографика

| Role | Size | Weight | Цвет dark / light |
|------|------|--------|-------------------|
| display (cover) | 78pt | 700 | #FFFFFF / #0F0F14 |
| h1 | 54–57pt | 700 | #FFFFFF / #0F0F14 |
| h2 | 45–48pt | 700 | #FFFFFF / #0F0F14 |
| h3 | 36–43pt | 700 | #FFFFFF / #0F0F14 |
| subtitle | 25–27pt | 400 | #E7DDFF / #6B6680 |
| card-num | 60pt | 700 | #6B3FF7 / #6B3FF7; акцент: #C6F542 |
| card-title | 21pt | 700 | #FFFFFF / #0F0F14 |
| card-subtitle | 10pt | 400 | #6B6680 (тех-метка в карте) |
| body | 16–18pt | 400 | #E7DDFF / #0F0F14 |
| body-sm | 12–13pt | 400 | #6B6680 |
| caption | 9–10pt | 400 | #6B6680 |
| badge-label | 10pt, uppercase | 400 | #6B3FF7 (тех-метка под числом) |
| page-num | 13pt | 400 | #E7DDFF |
| tag | 11–12pt | 400 | dark: rgba(255,255,255,0.8); light: #0F0F14 |

> **Slidev:** шрифт подключается в `theme/styles/index.css` через `@import` для Rubik 400/700/900.

### 2.3 Spacing / Radius / Shadows / Positioning

```
--spacing: xs4 sm8 md16 lg20 xl32 2xl48 3xl64 px   # отступы карт, gap, поля слайда
--radius:  sm8 md12 lg16 pill9999px                 # badge/карты/фреймы/пилюли
--shadow-card:        0 2px 8px  rgba(107,63,247,0.10)   # light
--shadow-card-dark:   0 2px 12px rgba(0,0,0,0.25)        # dark
--shadow-screenshot:  0 4px 24px rgba(107,63,247,0.18)   # mockup-frame

--logo-top 46px · right 58px · height 54px
--page-num  right 46px · bottom 56px
--slide-pad x 120px · y 64px
--header-zone  44%  (H1+subtitle занимают верх ~44%)
--content-zone-top 44%  (контент начинается с ~44%)
```

---

## 3. Компоненты

Все компоненты имеют `mode: 'dark' | 'light'` (исключения отмечены). Dark/light в дизайне — наследуется от класса `dark-family` / `light-family` корня лейаута.

- **`LogoBadge`** — логотип «ГНИВЦ» top-right (отступы `--logo-top/right`), 54px. `mode → color: white | #6B3FF7`. На каждом слайде.
- **`PageNumber`** — номер страницы bottom-right «01»…, Rubik 400 13pt, muted (`#E7DDFF` dark / `#6B6680` light). Props: `n`. Не на section-divider.
- **`SlideTag`** — breadcrumb top-left («Сценарий 1 · Транскрибация»). Pill, border `1px rgba(107,63,247,0.25)`, фон `rgba(107,63,247,0.06)`, 11–12pt; dark→белый, light→`#0F0F14`. Props: `label`.
- **`NumberedRowCard`** — горизонтальная строка `[01] | Заголовок | Описание`. Grid `80px 2px 1fr`, min-height 72px, фон `rgba(255,255,255,0.07)`/`#F4EFFF`, radius 12px; номер 36px bold фиолет / лайм в акценте; вертикальный разделитель 1×48px `rgba(107,63,247,0.3)`. Акцент: полностью `#6B3FF7`, белый текст, лайм-номер. Props: `n, title, subtitle?, description, variant: 'default'|'accent'`.
- **`NumberedCard`** — вертикальная карточка: число 60pt bold (`#6B3FF7` / `#C6F542` в акценте) → сепаратор-чёрточка 60×4px `#C6F542` → title 21pt → body 12–13pt muted. Фон `#F4EFFF`/white (light) или `rgba(255,255,255,0.07)` (dark), radius 12px. Акцент: полный `#6B3FF7`, белый текст. Props: `n, title, body?, variant`.
- **`ScreenshotFrame`** — мокап скриншота: border `1.5px rgba(107,63,247,0.25)`, radius 16px, `box-shadow --shadow-screenshot`; на dark — стекло `backdrop-filter: blur(8px)`; label «Интерфейс» caption над блоком. Props: `label?`, слот.
- **`AccentCallout`** — цитата/тезис с левым лайм-бордером: `border-left 4px #C6F542`, padding-left 16px, прозрачный. Props: `lines: string[]` (только dark).
- **`DotPattern`** — декор-сетка белых точек (right-bottom, ~50%×25% cover): `radial-gradient` точки 3px, gap 20px, opacity 0.25–0.3. Без props.
- **`StepFlow`** — горизонтальная цепочка шагов: карточки (radius 12px, `#F4EFFF`), номер-кружок ~42px `border 2px #6B3FF7`, стрелки `▶` `#6B3FF7`; финальный шаг — акцент (`#6B3FF7` фон, лайм-кружок). Props: `steps: {label, title, body, variant?}[]`.
- **`InfoCalloutRow`** — нижний footer-блок пояснения: `border 1px rgba(107,63,247,0.2)`, radius 12px, padding 12px 24px; label (caption) + text (body). Props: `label, text`.
- **`SectionDividerLabel`** — крупный заголовок секции на full-purple (80pt, white, left, ~25–30% сверху), без структуры. Без props.

---

## 4. Layouts

**dark-family** — `gradient-dark-bg`; **light-family** — `#FFFFFF`.

| Layout | Фон | Зоны | Слайды |
|--------|-----|------|--------|
| `cover` | dark | Display 78pt white + accent-underline; subtitle (25pt, #E7DDFF); `AccentCallout` с 3 тезисами bottom-left; `DotPattern` bottom-right; `LogoBadge`; `PageNumber` «01» | 1 (только первый) |
| `section-divider` | dark | `LogoBadge`; заголовок секции 80pt white, left, ~25–30% сверху; breathing room. Без `PageNumber` | 5, 18 |
| `split-dark` (scenario-intro) | dark | `SlideTag` top-left; левая ~40%: H1 48–54pt + 3 блока `[label/body]` с сепараторами; правая ~55%: `ScreenshotFrame`; `LogoBadge` | 6, 10, 13, 16 |
| `split-light` | light | `SlideTag`; левая ~40%: H1 45–48pt + `NumberedRowCard`×3–4 (последний accent); правая ~55%: `ScreenshotFrame`; `LogoBadge` (purple); `PageNumber` | 11, 15, 17 |
| `numbered-row-list` | light | H1 + subtitle; ниже 4×`NumberedRowCard` column, gap 20px | 2, 8, 14 |
| `card-grid-4` | light | Header ~44% (H1+subtitle); grid 4×`NumberedCard` `repeat(4,1fr)` gap 20px, последняя accent | 3, 12 |
| `card-grid-mixed` | light | Header; 2×2 карточки (~50% ширины каждая) + accent-карточка справа на всю высоту (`grid-template-areas`/абс. позиционирование) | 4 |
| `step-flow` | light | `SlideTag` + H1 + subtitle; `StepFlow` 4–5 шагов; внизу `InfoCalloutRow` (если итог) | 7, 9 |
| `definition-split` | dark | Левая ~40%: H1 + `_` курсор; правая ~55%: описание 27pt #E7DDFF; ниже subheading + `NumberedRowCard`×4 | 10, 13 |
| `closing` | dark | `SlideTag` (опц.); H1 с лайм-выделением `#C6F542`; `AccentCallout`; внизу 3 мини-карточки row (стекло) | 20 |
| `perspective` | light | `SlideTag` + H1 + subtitle; 3 карточки в ряд + 1 full-width accent внизу | 19 |

---

## 5. Правила стиля

**Акцент `#C6F542`** — только highlight, никогда крупной площадью: исключительно на последней/финальной карточке группы, сепараторе-чёрточке, выделенной фразе в H1 closing, номере акцент-карты. На dark заметен максимально, на light умеренно. Не в body.

**Фоновые режимы:** hard-switch, без промежуточных серых. Dark — ритмические разделители: cover → section-divider → scenario-intro → closing каждые 3–4 light-слайда. Light доминирует (~14/20).

**Заголовки:** всегда Rubik 700, без italic. H1 cover 78pt; контент 45–57pt (уменьшается с длиной). Dark → белый, light → `#0F0F14`. Subtitle 400 muted 25–27pt. `SlideTag` идёт над H1 (навигация, не типографическая иерархия).

**Карточки:** `default` (сиреневый/белый фон, фиолетовый border) и `accent` (полностью `#6B3FF7`). Акцент **всегда последний**. Сепаратор-чёрточка обязателен в `NumberedCard`. Числа: фиолет в default, лайм в accent.

**Иллюстрации:** только внутри `ScreenshotFrame`, правая колонка (~55%); label «Интерфейс»; на dark — glass, на light — border + тень.

**Обязательные элементы:** `LogoBadge` — на всех без исключения; `PageNumber` — кроме section-divider; `SlideTag` — на всех content/steps/results + closing (не cover/divider); акцент-карта — в каждой card-grid и row-list (последний item).

---

## 6. Структура темы

```
theme/
├── package.json              # slidev-theme-gnivts
├── README.md
├── styles/   tokens.css · index.css · prism.css
├── components/  LogoBadge · PageNumber · SlideTag · NumberedRowCard · NumberedCard
│                ScreenshotFrame · AccentCallout · DotPattern · StepFlow · InfoCalloutRow
└── layouts/   cover · section-divider · default · numbered-row-list · card-grid-4
               split-dark · split-light · step-flow · definition-split · closing · perspective
```

**В markdown:**
```yaml
---
layout: cover
---
# ИИ-песочница ГНИВЦ
Практические сценарии применения ИИ

---
layout: section-divider
---
# Кейсы

---
layout: split-dark
tag: Сценарий 1 · Транскрибация
---
...
```

---

## 7. CSS-токены (черновик)

```css
@import url('https://fonts.googleapis.com/css2?family=Rubik:wght@400;700;900&display=swap');

:root {
  /* Brand */
  --color-primary:#6B3FF7; --color-primary-dark:#4A25B8; --color-primary-light:#9B7DF9;
  --color-accent:#C6F542;
  /* Surfaces */
  --color-surface-dark:#2A2735; --color-surface-light:#F4EFFF; --color-surface-white:#FFF;
  --color-bg-light:#FFF;
  /* Text */
  --color-text-on-dark:#FFF; --color-text-on-light:#0F0F14;
  --color-text-muted-dark:#E7DDFF; --color-text-muted-light:#6B6680;
  --color-text-accent-dark:#C6F542; --color-text-accent-light:#6B3FF7;
  /* Borders · Tags */
  --color-border-card-light:rgba(107,63,247,.18); --color-border-card-dark:rgba(231,221,255,.15);
  --color-tag-bg-dark:rgba(255,255,255,.10); --color-tag-bg-light:rgba(107,63,247,.08);
  --color-tag-border:rgba(107,63,247,.25); --color-separator:#C6F542;
  /* Shadows */
  --shadow-card-light:0 2px 8px rgba(107,63,247,.10); --shadow-card-dark:0 2px 12px rgba(0,0,0,.25);
  --shadow-screenshot:0 4px 24px rgba(107,63,247,.18);
  /* Spacing · Radius */
  --spacing-xs:4px; --spacing-sm:8px; --spacing-md:16px; --spacing-lg:20px;
  --spacing-xl:32px; --spacing-2xl:48px; --spacing-3xl:64px;
  --radius-sm:8px; --radius-md:12px; --radius-lg:16px; --radius-pill:9999px;
  /* Type */
  --font-primary:'Rubik', system-ui, sans-serif;
  --type-display:clamp(54px,6vw,78px); --type-h1:clamp(42px,5vw,57px);
  --type-h2:clamp(36px,4.5vw,48px); --type-h3:clamp(30px,3.5vw,43px);
  --type-subtitle:clamp(18px,2vw,25px); --type-card-num:clamp(42px,4vw,60px);
  --type-card-title:clamp(16px,1.5vw,21px); --type-body:clamp(13px,1.2vw,18px);
  --type-body-sm:clamp(11px,1vw,13px); --type-caption:clamp(9px,.8vw,10px);
  --type-page-num:13px;
  /* Positioning */
  --logo-top:46px; --logo-right:58px; --logo-height:54px;
  --page-num-right:46px; --page-num-bottom:56px;
  --slide-pad-x:clamp(48px,6.25vw,120px); --slide-pad-y:64px;
  /* Gradient */
  --gradient-dark-bg:linear-gradient(135deg,#6B3FF7 0%,#5831D6 40%,#4A25B8 100%);
}

* { box-sizing:border-box; }
.slidev-layout { font-family:var(--font-primary); padding:var(--slide-pad-y) var(--slide-pad-x); position:relative; overflow:hidden; }
.slidev-layout.dark-family  { background:var(--gradient-dark-bg); color:var(--color-text-on-dark); }
.slidev-layout.light-family { background:var(--color-bg-light);   color:var(--color-text-on-light); }

/* LogoBadge */
.logo-badge { position:absolute; top:var(--logo-top); right:var(--logo-right); height:var(--logo-height);
  font-size:42px; font-weight:700; letter-spacing:.08em; font-variant-numeric:tabular-nums; }
.dark-family .logo-badge { color:#FFF; } .light-family .logo-badge { color:var(--color-primary); }

/* PageNumber */
.page-number { position:absolute; bottom:var(--page-num-bottom); right:var(--page-num-right); font-size:var(--type-page-num); }
.dark-family .page-number { color:var(--color-text-muted-dark); } .light-family .page-number { color:var(--color-text-muted-light); }

/* SlideTag */
.slide-tag { display:inline-flex; align-items:center; padding:4px 12px; border-radius:var(--radius-pill);
  border:1px solid var(--color-tag-border); font-size:12px; margin-bottom:var(--spacing-md); }
.dark-family .slide-tag { background:var(--color-tag-bg-dark); color:rgba(255,255,255,.85); border-color:rgba(255,255,255,.2); }
.light-family .slide-tag { background:var(--color-tag-bg-light); color:var(--color-text-on-light); }

/* NumberedCard */
.numbered-card { border-radius:var(--radius-md); padding:var(--spacing-xl) var(--spacing-md);
  border:1px solid var(--color-border-card-light); background:var(--color-surface-light);
  display:flex; flex-direction:column; }
.numbered-card.accent { background:var(--color-primary); border-color:transparent; color:#FFF; }
.numbered-card__num { font-size:var(--type-card-num); font-weight:700; color:var(--color-primary); line-height:1; }
.numbered-card.accent .numbered-card__num { color:var(--color-accent); }
.numbered-card__sep { width:60px; height:4px; background:var(--color-accent); margin:var(--spacing-sm) 0 var(--spacing-md); border-radius:2px; }
.numbered-card__title { font-size:var(--type-card-title); font-weight:700; margin-bottom:var(--spacing-sm); }
.numbered-card__body { font-size:var(--type-body-sm); color:var(--color-text-muted-light); }
.dark-family .numbered-card { background:rgba(255,255,255,.07); border-color:var(--color-border-card-dark); }
.dark-family .numbered-card__body { color:var(--color-text-muted-dark); }
.numbered-card.accent .numbered-card__body { color:rgba(255,255,255,.75); }

/* NumberedRowCard */
.numbered-row-card { display:grid; grid-template-columns:80px 2px 1fr; align-items:center; gap:0 var(--spacing-md);
  padding:var(--spacing-md) var(--spacing-lg); border-radius:var(--radius-md);
  border:1px solid var(--color-border-card-light); background:var(--color-surface-light); min-height:72px; }
.numbered-row-card.accent { background:var(--color-primary); border-color:transparent; color:#FFF; }
.numbered-row-card__num { font-size:36px; font-weight:700; color:var(--color-primary); }
.numbered-row-card.accent .numbered-row-card__num { color:var(--color-accent); }
.numbered-row-card__divider { width:1px; height:48px; background:rgba(107,63,247,.3); }
.numbered-row-card.accent .numbered-row-card__divider { background:rgba(255,255,255,.3); }

/* AccentCallout */
.accent-callout { border-left:4px solid var(--color-accent); padding-left:var(--spacing-md); }
.accent-callout p { font-size:var(--type-body); color:var(--color-text-on-dark); margin:4px 0; line-height:1.5; }

/* ScreenshotFrame */
.screenshot-frame { border:1.5px solid rgba(107,63,247,.25); border-radius:var(--radius-lg);
  box-shadow:var(--shadow-screenshot); overflow:hidden; position:relative; }
.dark-family .screenshot-frame { background:rgba(42,39,53,.6); backdrop-filter:blur(8px); border-color:rgba(231,221,255,.2); }
.screenshot-frame__label { font-size:var(--type-caption); color:var(--color-text-muted-light); margin-bottom:var(--spacing-xs); }

/* DotPattern */
.dot-pattern { position:absolute; bottom:0; right:0; width:50%; height:25%; pointer-events:none;
  background-image:radial-gradient(circle, rgba(255,255,255,.28) 2px, transparent 2px); background-size:20px 20px; }

/* StepFlow */
.step-flow { display:flex; align-items:flex-start; }
.step-card { flex:1; border-radius:var(--radius-md); border:1px solid var(--color-border-card-light);
  background:var(--color-surface-light); padding:var(--spacing-lg); position:relative; }
.step-card.accent { background:var(--color-primary); border-color:transparent; color:#FFF; }
.step-arrow { display:flex; align-items:center; padding:0 8px; color:var(--color-primary); font-size:20px; flex-shrink:0; margin-top:40px; }
.step-circle { width:42px; height:42px; border-radius:50%; border:2px solid var(--color-primary);
  display:flex; align-items:center; justify-content:center; font-size:19px; font-weight:700; color:var(--color-primary); margin:var(--spacing-sm) 0; }
.step-card.accent .step-circle { background:var(--color-accent); border-color:var(--color-accent); color:#0F0F14; }
```

---

## Примечания к реализации

1. **Шрифт** — `@import` Rubik 400/700/900 в `styles/index.css`; offline: пакет `fontsource`.
2. **LogoBadge** — `<LogoBadge />` в каждом layout; «ГНИВЦ» с `letter-spacing:.1em` как аппроксимация пиксельного написания.
3. **Dark/Light семьи** — каждый layout добавляет `dark-family`/`light-family` на корень; компоненты адаптируются через наследование CSS (не props `mode` в каждом вызове).
4. **Slidev frontmatter** — `tag` из шапки слайда принимается лейаутом через `defineProps`/`useSlideContext()`.
5. **Акцент-карточки** — последний элемент группы автоматически accent через `:nth-child(N):last-child` CSS или `v-if="isLast"` в шаблоне.
