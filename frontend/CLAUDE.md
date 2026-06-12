# frontend/ — Web Frontend

React + TypeScript + Vite + Tailwind CSS + Redux Toolkit + react-i18next.

## Required Reading

- `docs/frontend-guide/MAISYS_frontend_design_guide.md` — the authoritative frontend spec
- `docs/technical-guides/part1.md` (deployment topology section) — how frontend talks to backend

## Stack — Locked

| Layer | Choice |
|---|---|
| Build tool | Vite |
| Framework | React 18 (function components + hooks only — no class components) |
| Language | TypeScript (strict mode) |
| Styling | Tailwind CSS (utility-first, no custom CSS files except `globals.css`) |
| State management | Redux Toolkit (one slice per module: chatbot, drug, symptom, lab, research, auth, ui) |
| Server state | Redux Toolkit Query for HTTP, native WebSocket for streaming |
| Routing | React Router v6 |
| Forms | React Hook Form + Zod validation |
| i18n | react-i18next, with RTL via `dir="rtl"` driven by language |
| Icons | Lucide React |
| Charts | Recharts |
| Markdown rendering | react-markdown with `remark-gfm` |
| HTTP client | Axios (wrapped in Redux Toolkit Query) |
| Testing | Vitest + React Testing Library |

If a task seems to want a different library, stop. Use what's listed.

## i18n & RTL — First-Class

Arabic and English are equal. Not Arabic-as-translation; both are first-class.

- Every visible string goes through `t()`. No hard-coded strings in JSX.
- Translation files in `src/i18n/locales/<lang>/<namespace>.json`. Namespaces match Redux slices (`chatbot`, `drug`, `auth`, `common`).
- Direction is reactive: `document.dir = i18n.language === 'ar' ? 'rtl' : 'ltr'`. Set in a root effect.
- Use logical CSS properties via Tailwind: `ms-4` (margin-start), not `ml-4`. `text-start`, not `text-left`.
- Test every page in both directions before declaring done.

## Redux Slice Rule

One slice per user-visible module + cross-cutting `auth` and `ui` slices:

```
src/store/
├── store.ts                    Root store, combineReducers
├── slices/
│   ├── auth.ts
│   ├── chatbot.ts
│   ├── drug.ts
│   ├── symptom.ts
│   ├── lab.ts
│   ├── research.ts
│   └── ui.ts                   theme, language, layout state
└── api/                        RTK Query endpoints (one file per service)
    ├── authApi.ts
    ├── chatbotApi.ts
    └── ...
```

Cross-slice communication via dispatch, never direct state imports.

## Component Conventions

- Components are functional, hook-based, default-exported
- File name = component name (`ChatMessage.tsx` exports `ChatMessage`)
- Props are typed; never use `any`
- No prop drilling beyond 2 levels — use Redux or a colocated context

## Page List

See `docs/frontend-guide/MAISYS_frontend_design_guide.md` for the full list of 29 pages (28 user-facing + 1 admin). Each page lives in `src/pages/<module>/<page>.tsx`.

## WebSocket Convention

- Use a single `useWebSocket` hook (in `src/hooks/`) that connects to the API gateway's WebSocket endpoint
- Multiplex by `event_type` field
- Auto-reconnect with exponential backoff
- Per-session event listeners managed via Redux subscribers, not component-level listeners

## Theming

- Light + dark themes both required
- Color tokens defined in Tailwind config; never hard-code hex values in components
- Theme switches by toggling `class="dark"` on `<html>`

## Accessibility

- All interactive elements keyboard-accessible
- ARIA labels on icon-only buttons
- Focus visible (`focus-visible:ring-*`)
- Contrast meets WCAG AA in both themes
- Form fields have associated labels

## What's NEVER in the Frontend

- Hard-coded strings outside `t()`
- Direct `fetch` or `axios` calls outside RTK Query endpoints
- Local storage of sensitive data (use httpOnly cookies for tokens, set by the backend)
- LTR-only assumptions (`ml-*`, `text-left`, fixed pixel margins relative to left edge)
- Inline styles for anything theme-able (color, spacing) — use Tailwind utilities

## Build

```bash
npm install
npm run dev       # local dev server on :5173
npm run build     # production build to dist/
npm run test      # vitest
npm run lint      # eslint + tsc --noEmit
```
