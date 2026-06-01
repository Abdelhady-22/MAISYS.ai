# MAISYS — Frontend Design Guide
## Brand Identity · Design System · UI Components · RTL · Accessibility

> This guide is a standalone frontend reference. It does not modify any technical guide (Parts 1–6).
> Use this file whenever building, reviewing, or extending any MAISYS interface.

---

## Table of Contents

1. [Brand Identity](#1-brand-identity)
2. [Color System](#2-color-system)
3. [Typography System](#3-typography-system)
4. [Spacing and Layout](#4-spacing-and-layout)
5. [Logo Usage Guidelines](#5-logo-usage-guidelines)
6. [Component Library](#6-component-library)
7. [Medical UI Patterns](#7-medical-ui-patterns)
8. [RTL — Arabic Support](#8-rtl--arabic-support)
9. [Dark Mode System](#9-dark-mode-system)
10. [Icons and Patterns](#10-icons-and-patterns)
11. [Motion and Transitions](#11-motion-and-transitions)
12. [Responsive Breakpoints](#12-responsive-breakpoints)
13. [Accessibility Standards](#13-accessibility-standards)
14. [Tailwind Configuration Reference](#14-tailwind-configuration-reference)

---

## 1. Brand Identity

### 1.1 Brand Positioning

MAISYS is a trusted, bilingual medical AI education platform. The visual identity communicates:

- **Trustworthy** — clinical blue palette establishes medical authority
- **Intelligent** — clean geometry and precise typography signal AI precision
- **Accessible** — balanced contrast, generous spacing, full Arabic RTL support
- **Modern** — gradient accents, smooth transitions, glassmorphism elements

### 1.2 Design Principles

**1 — Safety first, visually.** Emergency states, warnings, and disclaimers are always visually prominent. They are never hidden, muted, or styled to look optional.

**2 — Never show a blank screen.** Every loading state shows progress — a label, a percentage, an estimated time. Skeleton screens fill space while content loads.

**3 — Bilingual is native, not translated.** Arabic and English are equal. RTL is not a mirror of LTR — it is a first-class layout. Every component is designed for both directions.

**4 — Cite everything.** Every AI-generated claim carries a visible source badge. Users must be able to verify where information comes from.

**5 — One visual language.** Spacing, radius, shadow, and color tokens are the same across all five modules. A user switching from Chatbot to Drug Agent should feel at home immediately.

---

## 2. Color System

### 2.1 Official Brand Colors (from Brand Guideline)

```
MAIN COLORS:
  Primary Blue:      #0487d9
  Primary Dark Blue: #0268a8
  Teal:              #03a6a6
  Cyan:              #00cccc

SECONDARY COLORS:
  Deep Navy:         #000216
  Dark Gray:         #292d36
  Light Gray:        #cccccc
  Off White:         #f9f9f9
```

### 2.2 Full Design Token System

Building on the brand palette, here is the complete set of design tokens used in the application.

#### Primary Palette
| Token | Hex | Usage |
|---|---|---|
| `--color-primary-50` | `#e8f4fd` | Hover background, light tints |
| `--color-primary-100` | `#c5e4fa` | Focus ring, active backgrounds |
| `--color-primary-200` | `#8ec9f4` | Disabled states |
| `--color-primary-400` | `#3aa1e5` | Secondary button fill |
| `--color-primary-500` | `#0487d9` | **Brand Primary** — buttons, links, focus |
| `--color-primary-600` | `#0268a8` | **Brand Dark** — hover on primary |
| `--color-primary-700` | `#015380` | Pressed state |
| `--color-primary-900` | `#000216` | **Brand Navy** — text on light, deep backgrounds |

#### Teal / Cyan Accent
| Token | Hex | Usage |
|---|---|---|
| `--color-teal-400` | `#06c4c4` | Accent highlight, AI-generated labels |
| `--color-teal-500` | `#03a6a6` | **Brand Teal** — RAG source badge, secondary CTA |
| `--color-teal-600` | `#028080` | Hover on teal elements |
| `--color-cyan-400` | `#00cccc` | **Brand Cyan** — gradient end, visual accents |

#### Neutral Palette
| Token | Hex | Usage |
|---|---|---|
| `--color-neutral-0` | `#ffffff` | Card background (light mode) |
| `--color-neutral-50` | `#f9f9f9` | **Brand Off-White** — page background |
| `--color-neutral-100` | `#f0f0f0` | Input background, subtle dividers |
| `--color-neutral-200` | `#cccccc` | **Brand Light Gray** — borders, placeholders |
| `--color-neutral-400` | `#8a8f9a` | Muted text |
| `--color-neutral-600` | `#4a4f5a` | Body text |
| `--color-neutral-700` | `#292d36` | **Brand Dark Gray** — headings |
| `--color-neutral-900` | `#000216` | **Brand Navy** — primary text |

#### Semantic Colors
| Token | Hex | Usage |
|---|---|---|
| `--color-success-500` | `#16a34a` | Normal lab values, safe states |
| `--color-success-100` | `#dcfce7` | Success background |
| `--color-warning-500` | `#ca8a04` | Consultation triage, caution |
| `--color-warning-100` | `#fef9c3` | Warning background |
| `--color-danger-500` | `#dc2626` | Emergency, critical lab values, contraindicated |
| `--color-danger-100` | `#fee2e2` | Danger background |
| `--color-info-500` | `#0487d9` | Information, source badges |
| `--color-info-100` | `#e8f4fd` | Info background |

#### Triage Color Tokens (Medical-Specific)
| Triage Level | Color | Hex | Text |
|---|---|---|---|
| `emergency` | Red | `#dc2626` | White `#ffffff` |
| `emergency_ambulance` | Red | `#dc2626` | White `#ffffff` |
| `consultation_24` | Orange | `#ea580c` | White `#ffffff` |
| `consultation` | Amber | `#ca8a04` | White `#ffffff` |
| `self_care` | Green | `#16a34a` | White `#ffffff` |
| `normal` (lab result) | Green | `#16a34a` | White `#ffffff` |
| `high` (lab result) | Orange | `#ea580c` | White `#ffffff` |
| `low` (lab result) | Blue | `#0487d9` | White `#ffffff` |
| `critical` (lab result) | Red | `#dc2626` | White `#ffffff` |

### 2.3 Brand Gradients

```css
/* Primary gradient — used in hero sections, feature cards, visual accents */
--gradient-primary: linear-gradient(135deg, #0487d9 0%, #03a6a6 50%, #00cccc 100%);

/* Dark gradient — used in navbars, sidebar dark mode, footers */
--gradient-dark: linear-gradient(135deg, #000216 0%, #292d36 100%);

/* Subtle gradient — used in card hover states, section backgrounds */
--gradient-subtle: linear-gradient(135deg, #e8f4fd 0%, #e0f5f5 100%);

/* Button gradient — primary CTA buttons */
--gradient-cta: linear-gradient(90deg, #0487d9 0%, #0268a8 100%);

/* Teal accent gradient — AI badges, visual banners */
--gradient-teal: linear-gradient(90deg, #03a6a6 0%, #00cccc 100%);
```

### 2.4 Color Usage Rules

**Do:**
- Use `#0487d9` (Primary Blue) for all interactive elements: buttons, links, focus rings, toggles
- Use `#03a6a6` (Teal) for AI-generated content labels, RAG source badges, secondary CTAs
- Use `#000216` (Navy) for all primary text in light mode
- Use `#f9f9f9` (Off-White) for page backgrounds in light mode

**Do Not:**
- Use raw color values in component code — always use CSS variables or Tailwind tokens
- Mix gradient directions inconsistently — always 90° horizontal for buttons, 135° for backgrounds
- Use semantic colors for non-semantic purposes — danger red must only appear for actual danger states
- Place blue text on teal background — contrast ratio falls below WCAG AA

---

## 3. Typography System

### 3.1 Typeface Stack (from Brand Guideline)

**English:** Outfit — Google Fonts
**Arabic:** IBM Plex Sans Arabic — Google Fonts

```css
/* English font stack */
font-family: 'Outfit', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;

/* Arabic font stack */
font-family: 'IBM Plex Sans Arabic', 'Outfit', sans-serif;

/* Applied via :lang() attribute */
:lang(ar) {
  font-family: 'IBM Plex Sans Arabic', sans-serif;
}
:lang(en) {
  font-family: 'Outfit', sans-serif;
}
```

**Google Fonts import:**
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@100;200;300;400;500;600;700;800;900&family=IBM+Plex+Sans+Arabic:wght@100;200;300;400;500;600;700&display=swap" rel="stylesheet">
```

### 3.2 Type Scale

| Token | Size | Weight | Line Height | Usage |
|---|---|---|---|---|
| `text-display` | 48px / 3rem | 700 Bold | 1.1 | Hero headings, module titles |
| `text-h1` | 36px / 2.25rem | 700 Bold | 1.2 | Page headings |
| `text-h2` | 28px / 1.75rem | 600 SemiBold | 1.25 | Section headings |
| `text-h3` | 22px / 1.375rem | 600 SemiBold | 1.3 | Card titles, sub-sections |
| `text-h4` | 18px / 1.125rem | 500 Medium | 1.4 | Component headings |
| `text-body-lg` | 17px / 1.0625rem | 400 Regular | 1.6 | Lead paragraphs, responses |
| `text-body` | 15px / 0.9375rem | 400 Regular | 1.7 | Body text, descriptions |
| `text-body-sm` | 13px / 0.8125rem | 400 Regular | 1.6 | Captions, helper text |
| `text-label` | 13px / 0.8125rem | 500 Medium | 1.4 | Form labels, badges |
| `text-caption` | 11px / 0.6875rem | 400 Regular | 1.5 | Footnotes, timestamps |
| `text-mono` | 13px / 0.8125rem | 400 Regular | 1.5 | Code, RxCUI, citations |

### 3.3 Font Weights (Outfit)

| Weight Name | Value | Usage |
|---|---|---|
| Thin | 100 | Large decorative display only |
| Extra Light | 200 | Subtle labels on dark backgrounds |
| Light | 300 | Placeholder text, muted labels |
| Regular | 400 | All body text, paragraphs |
| Medium | 500 | Labels, badge text, navigation items |
| Semi Bold | 600 | Section headings, card titles, buttons |
| Bold | 700 | Page headings, key values, CTAs |
| Extra Bold | 800 | Hero headings, emphasis only |
| Black | 900 | Display text, brand statements only |

### 3.4 Font Weights (IBM Plex Sans Arabic)

| Weight | Value | Arabic Usage |
|---|---|---|
| Thin | 100 | Large decorative Arabic display |
| Extra Light | 200 | Subtle Arabic labels |
| Light | 300 | Arabic placeholder text |
| Regular | 400 | All Arabic body text |
| Medium | 500 | Arabic labels, navigation |
| Semi Bold | 600 | Arabic section headings |
| Bold | 700 | Arabic page headings, CTAs |

### 3.5 Typography Rules

- Minimum body font size: 15px (never below 13px for any readable content)
- Maximum line width: 72 characters (750px) for LLM response text — improves readability
- Arabic text: increase line height by 15% over English equivalent (Arabic letters have more vertical rhythm)
- Never use Thin or Extra Light for body text or anything below 24px
- Use Medium (500) not Regular (400) for button labels

---

## 4. Spacing and Layout

### 4.1 Spacing Scale (4px base unit)

| Token | Value | Usage |
|---|---|---|
| `space-1` | 4px | Icon margins, micro gaps |
| `space-2` | 8px | Inline element gaps, tight padding |
| `space-3` | 12px | Badge padding, small component padding |
| `space-4` | 16px | Default padding, component gaps |
| `space-5` | 20px | Card padding (compact) |
| `space-6` | 24px | Card padding (default), section gaps |
| `space-8` | 32px | Section padding |
| `space-10` | 40px | Large section padding |
| `space-12` | 48px | Module-level spacing |
| `space-16` | 64px | Page-level section separation |
| `space-24` | 96px | Hero sections |

### 4.2 Border Radius

| Token | Value | Usage |
|---|---|---|
| `radius-sm` | 4px | Badges, tags, small chips |
| `radius-md` | 8px | Buttons, inputs, small cards |
| `radius-lg` | 12px | Cards, panels, dropdowns |
| `radius-xl` | 16px | Modal dialogs, large cards |
| `radius-2xl` | 24px | Feature cards, hero panels |
| `radius-full` | 9999px | Pills, circular avatars, toggles |

### 4.3 Shadows

```css
/* Card elevation levels */
--shadow-sm:   0 1px 3px rgba(4, 135, 217, 0.08);
--shadow-md:   0 4px 12px rgba(4, 135, 217, 0.12);
--shadow-lg:   0 8px 24px rgba(4, 135, 217, 0.16);
--shadow-xl:   0 16px 48px rgba(0, 2, 22, 0.20);

/* Focus ring */
--shadow-focus: 0 0 0 3px rgba(4, 135, 217, 0.35);

/* Teal accent shadow (AI elements) */
--shadow-teal:  0 4px 16px rgba(3, 166, 166, 0.20);
```

### 4.4 Grid and Layout

The layout system uses a 12-column grid with the following max-widths:

| Context | Max Width | Usage |
|---|---|---|
| Page content | `1280px` | Full-width page layouts |
| Reading width | `750px` | LLM responses, articles |
| Narrow form | `480px` | Auth forms, quick forms |
| Chat area | Flexible (fills remaining after sidebar) | All chat interfaces |

**Standard sidebar widths:**
- Collapsed: 64px (icons only)
- Default: 280px (session list + labels)
- Expanded: 320px (search enabled)

### 4.5 Z-Index Scale

| Token | Value | Usage |
|---|---|---|
| `z-base` | 0 | Normal flow elements |
| `z-raised` | 10 | Cards, dropdowns |
| `z-sticky` | 100 | Sticky headers, sidebars |
| `z-overlay` | 200 | Drawer overlays, backdrop |
| `z-modal` | 300 | Modal dialogs |
| `z-toast` | 400 | Toast notifications |
| `z-emergency` | 500 | Emergency alert overlay — always topmost |

---

## 5. Logo Usage Guidelines

### 5.1 Clear Space

The MAISYS logo requires a minimum clear space equal to the height of the letter "M" in the logo on all four sides. Never place any other element, text, or image inside this clear space.

### 5.2 Logo Versions

The brand guide specifies multiple logo versions. Use this decision tree:

**Main Logo (Full):** Use on landing page hero, login page, print materials, and official documents where space allows.

**Horizontal Logo:** Use in navigation bars, page headers, and anywhere width is greater than height.

**Icon / Mark Only:** Use as favicon (32×32px), app icon, avatar, and when space is severely constrained (under 120px width).

**White Version:** Use on dark backgrounds — deep navy (`#000216`), dark gray (`#292d36`), or gradient backgrounds.

**Dark Version:** Use on white or off-white (`#f9f9f9`) backgrounds only.

**Gradient Version:** Use in marketing materials, splash screens, and hero sections. Never use the gradient version at sizes below 120px wide.

### 5.3 What Not to Do with the Logo

- Never rotate the logo
- Never stretch or distort the logo's proportions
- Never apply drop shadows or glows directly to the logo
- Never place the full-color logo on a patterned background without a white clearance zone
- Never use the gradient logo in body text or functional UI (navigation, buttons)
- Never recreate the logo using text — always use the provided asset file

### 5.4 Minimum Sizes

| Usage | Minimum Width |
|---|---|
| Full horizontal logo | 120px |
| Stacked logo | 80px |
| Icon mark only | 24px |
| Favicon | 32×32px |

---

## 6. Component Library

### 6.1 Buttons

**Four variants — always use the correct variant for the action's importance.**

#### Primary Button
Used for the main action on any page. One per screen section maximum.
```
Background: #0487d9 → #0268a8 (horizontal gradient)
Text: White #ffffff, Outfit SemiBold 15px
Padding: 12px 24px
Radius: 8px
Min width: 120px
Hover: background darkens to #0268a8, shadow-md
Focus: shadow-focus (3px blue ring)
Disabled: opacity 40%, cursor not-allowed
```

#### Secondary Button
Used for secondary actions alongside a primary button.
```
Background: transparent
Border: 1.5px solid #0487d9
Text: #0487d9, Outfit Medium 15px
Padding: 12px 24px
Hover: background #e8f4fd
Focus: shadow-focus
```

#### Ghost Button
Used for tertiary actions, cancel buttons, and inline text actions.
```
Background: transparent
Border: none
Text: #292d36 / #0487d9 (context-dependent)
Padding: 10px 16px
Hover: background #f0f0f0
```

#### Danger Button
Used only for destructive actions (delete session, revoke access, withdraw consent).
```
Background: #dc2626
Text: White
Hover: #b91c1c
Requires: explicit confirmation dialog before execution
```

#### Button Sizes
| Size | Padding | Font Size | Usage |
|---|---|---|---|
| `sm` | 8px 16px | 13px | Inline table actions, compact cards |
| `md` | 12px 24px | 15px | Default — most buttons |
| `lg` | 16px 32px | 17px | Primary CTA, hero section |
| `icon` | 10px | — | Icon-only buttons |

### 6.2 Input Fields

```
Height: 44px (minimum touch target)
Background: #ffffff (light) / #1a1f2e (dark)
Border: 1.5px solid #cccccc
Radius: 8px
Padding: 0 16px
Font: Outfit Regular 15px, #000216
Placeholder: Outfit Light 15px, #8a8f9a

Focus:
  Border: 1.5px solid #0487d9
  Shadow: shadow-focus (3px blue ring)

Error:
  Border: 1.5px solid #dc2626
  Helper text: #dc2626, 12px, shown below input

Disabled:
  Background: #f0f0f0
  Text: #8a8f9a
  Cursor: not-allowed
```

**Drug name chip input** (multi-drug entry in Drug Agent):
```
Container: min-height 44px, flex-wrap, gap-8px, border radius-md
Chip: background #e8f4fd, text #0268a8, border #c5e4fa
Chip × button: #0487d9, hover #dc2626
Autocomplete dropdown: shadow-lg, max-height 240px, scrollable
```

### 6.3 Cards

**Standard card:**
```
Background: #ffffff (light) / #1a1f2e (dark)
Border: 1px solid #f0f0f0
Radius: 12px
Padding: 24px
Shadow: shadow-sm
Hover (interactive cards): shadow-md, border-color #c5e4fa
Transition: all 0.2s ease
```

**Feature card (module cards on dashboard):**
```
Background: white with gradient left border (4px, brand gradient)
Radius: 16px
Padding: 28px
Hover: translateY(-2px), shadow-lg
Icon: 48×48px, background brand gradient, radius-xl
```

**AI response card (chatbot message):**
```
Background: #f9f9f9 (light) / #242836 (dark)
Left border: 3px solid #03a6a6 (teal — marks AI content)
Radius: 0 12px 12px 12px (asymmetric — chatbot bubble shape)
Padding: 20px 24px
```

**User message card:**
```
Background: #0487d9 (primary blue)
Text: white
Radius: 12px 0 12px 12px (asymmetric — user bubble shape)
Align: right (LTR) / left (RTL)
```

### 6.4 Badges and Tags

**Source tier badges (always shown on AI responses):**
```
Structured DB (DDIMDL):  📊  background #e0f5f5, text #028080, border #03a6a6
Local Knowledge Base:    ✅  background #dcfce7, text #166534, border #16a34a
Web Source (Drugs.com):  🌐  background #e8f4fd, text #0268a8, border #0487d9
```

**Triage level badges:**
```
Height: 24px
Padding: 4px 10px
Radius: 9999px (pill)
Font: Outfit SemiBold 12px
Colors: per triage token table in Section 2.2
```

**General status badges:**
```
Normal:    background #dcfce7, text #166534
High:      background #fff7ed, text #c2410c
Low:       background #eff6ff, text #1d4ed8
Critical:  background #fee2e2, text #991b1b
Unknown:   background #f3f4f6, text #4b5563
```

**Module tags (drug feature tabs):**
```
Default:   background #f9f9f9, text #292d36, border #cccccc
Active:    background #0487d9, text white, border transparent
Hover:     background #e8f4fd, text #0268a8
```

### 6.5 Navigation

**Top Navigation Bar:**
```
Height: 64px
Background: white (light) / #000216 (dark)
Logo: left-aligned (LTR) / right-aligned (RTL)
Border-bottom: 1px solid #f0f0f0
Items: Outfit Medium 15px, #292d36
Active item: #0487d9
```

**Session Sidebar:**
```
Width: 280px
Background: #f9f9f9 (light) / #12172a (dark)
Border-right (LTR) / Border-left (RTL): 1px solid #f0f0f0
Session item height: 52px
Session item active: background #e8f4fd, left border 3px solid #0487d9
Session title: Outfit Medium 14px, truncated with ellipsis
Session timestamp: Outfit Light 12px, #8a8f9a
```

**Module Tab Bar (Drug Agent 12 tabs):**
```
Height: 48px
Tab background: transparent
Active tab: border-bottom 2px solid #0487d9, text #0487d9
Hover: background #f0f0f0
Overflow: horizontal scroll on mobile, show scroll indicators
```

### 6.6 Progress and Loading States

**Linear progress bar:**
```
Track: #f0f0f0, height 6px, radius-full
Fill: gradient #0487d9 → #03a6a6, animated width
Animated fill: CSS transition width 0.3s ease-in-out
Striped animation (processing): diagonal stripe overlay at 30% opacity
```

**Progress with status label:**
```
Layout: progress bar + percentage text (right-aligned LTR, left-aligned RTL)
Status message: below bar, Outfit Medium 14px, #292d36
Detail text: below status, Outfit Light 12px, #8a8f9a
ETA: right side of detail line, Outfit Light 12px, #8a8f9a
```

**Skeleton loading:**
```
Background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%)
Animation: shimmer left-to-right, 1.5s infinite
Radius: matches the element being replaced
```

**Spinner (fallback only):**
```
Do not use spinner without an accompanying status label.
Never show a spinner with no other context.
Size: 24px (inline), 40px (page-level)
Color: #0487d9
```

**Streaming text cursor:**
```
After last visible token: blinking cursor (|)
Color: #0487d9
Animation: blink 0.7s step-end infinite
Remove cursor when stream_complete event received
```

### 6.7 Alerts and Notifications

**Toast notifications (react-hot-toast):**
```
Position: top-right (LTR) / top-left (RTL)
Width: max 360px
Radius: 10px
Shadow: shadow-lg
Font: Outfit Medium 14px
Duration: 4s default, 8s for warnings, persistent for errors

Success: border-left 4px solid #16a34a, icon ✓
Warning: border-left 4px solid #ca8a04, icon ⚠
Error:   border-left 4px solid #dc2626, icon ✗
Info:    border-left 4px solid #0487d9, icon ℹ
```

**Emergency alert (full-screen — z-index 500):**
```
Background: rgba(220, 38, 38, 0.97) — critical red, high opacity
Text: white
Layout: centered, full viewport overlay
Icon: large warning ⚠ (64px)
Headline: Outfit Bold 28px
Message: Outfit Regular 17px, line-height 1.6
Actions (phone numbers): Outfit Bold 20px, underlined
Cannot be dismissed by clicking outside — user must see the full content
Close: only by explicit button "I understand — this is not an emergency"
  → show only after 5 seconds (prevent accidental dismissal)
```

**Medical disclaimer box:**
```
Background: #fff7ed
Border: 1px solid #fed7aa
Border-left: 4px solid #ca8a04
Radius: 8px
Padding: 16px 20px
Icon: ℹ️ or ⚕️
Text: Outfit Regular 13px, #92400e
Appears at bottom of every AI response — never collapsible
```

### 6.8 Modal Dialogs

```
Backdrop: rgba(0, 2, 22, 0.6), blur(4px)
Container background: white (light) / #1a1f2e (dark)
Width: min(560px, 90vw)
Radius: 16px
Padding: 32px
Shadow: shadow-xl
Header: Outfit SemiBold 20px, border-bottom 1px solid #f0f0f0
Footer: border-top 1px solid #f0f0f0, right-aligned buttons (LTR) / left-aligned (RTL)
Close button: top-right corner, ghost style
Transition: scale(0.95) → scale(1) + opacity 0 → 1, 200ms
```

**Destructive confirmation modal:**
```
Danger icon: red background circle with ✗, 48px
Header: Outfit Bold, #dc2626
Primary action: danger button (red)
Cancel: secondary button — always left of danger button (LTR) / right (RTL)
```

---

## 7. Medical UI Patterns

These patterns are specific to MAISYS and handle medical content display conventions.

### 7.1 Agent Activity Panel

The live agent activity panel appears during any agent-powered operation. It is collapsible.

```
Panel width: 320px, fixed right panel (desktop) / bottom drawer (mobile)
Background: white (light) / #1a1f2e (dark)
Border-left (LTR) / Border-right (RTL): 1px solid #f0f0f0
Header: "Agent Activity" + collapse toggle

Agent row:
  Height: auto
  Left indicator: 3px color bar (blue = running, green = complete, red = error, gray = skipped)
  Agent name: Outfit SemiBold 14px
  Target (e.g. "warfarin + aspirin"): Outfit Light 13px, #8a8f9a

Node step (inside agent row):
  Indent: 16px
  Icon states:
    Running:  pulsing blue dot (8px)
    Complete: green checkmark + duration in ms
    Error:    red × + retry count
    Skipped:  gray dash + reason tooltip
  Font: Outfit Regular 13px

Tool call (indented under node):
  Icon: 🔧 or 🌐
  Label: tool name + input summary
  Color: #03a6a6 (teal — marks external tool call)

Footer: total tokens + total duration when agent_complete received
```

### 7.2 Drug Interaction Severity Display

```
Severity badges (ordered, worst-first visually):

Contraindicated:  background #dc2626, text white, icon 🚫
Major:            background #ea580c, text white, icon ⚠️
Moderate:         background #ca8a04, text white, icon ⚡
Minor:            background #16a34a, text white, icon ℹ️
```

Drug pair card layout:
```
Card header: Drug A + Drug B name, severity badge right-aligned
Section: Mechanism (body text)
Section: Clinical Significance (body text)
Section: Recommendation (highlighted box, border-left colored by severity)
Footer: Source badge (📊 DDIMDL / ✅ Local KB / 🌐 Drugs.com) + citation link
```

### 7.3 Lab Result Cards

Each test gets its own expandable card:
```
Card header:
  Left: test name (Outfit SemiBold 15px) + panel tag
  Right: value + unit (Outfit Bold 17px, colored by status) + status badge

Card body (expanded):
  Reference range: Outfit Regular 13px, #8a8f9a
  Explanation sections (4 parts, accordion within card):
    1. What it measures
    2. What your result means
    3. Possible causes (abnormal only)
    4. Affecting factors
  Urgency: colored left border strip (green/amber/orange/red by urgency level)
```

Bar chart (auto-generated visual):
```
X-axis: test names (shortened to 3-4 chars for mobile)
Y-axis: normalized percentage of reference range (0% = min, 100% = max normal, 150% = max shown)
Bar color: green (normal), orange (mildly abnormal), red (significantly abnormal/critical)
Reference range: horizontal band, semi-transparent #16a34a at 10% opacity
```

### 7.4 Symptom Checker Conversation UI

```
Question display area:
  Background: #e8f4fd
  Border-left: 4px solid #0487d9
  Padding: 20px
  Radius: 0 12px 12px 12px
  Font: Outfit Medium 16px, #000216

Quick answer buttons (Yes / No / Not Sure):
  Height: 44px
  Width: equal thirds of container
  Style: secondary button for Yes/No, ghost for Not Sure
  Submits immediately on click (no separate send button needed)

Current conditions sidebar:
  Title: "Current Assessment" — updates after each turn
  Condition row: name (Outfit Medium 14px) + probability bar + percentage
  Top condition: full opacity, others at 70%
  Probability bar: 0–100% width, color by probability (green >60%, amber 30-60%, gray <30%)

Turn counter:
  Position: below question
  Label: "Question 3 of 8 maximum"
  Color: #8a8f9a
```

### 7.5 Citation Display

Citations appear below every AI response. They are never hidden or collapsed by default.

```
Citation block:
  Background: #f9f9f9
  Border-top: 1px solid #f0f0f0
  Padding: 12px 20px
  Header: "Sources" — Outfit SemiBold 12px, #8a8f9a

Per citation:
  Icon: document icon (🔬 for medical, 📋 for lab, 📖 for drug)
  Source name: Outfit Medium 13px, #0487d9 (clickable link)
  Section: Outfit Regular 12px, #8a8f9a
  URL: opens in new tab

Source tier label (separate from citations — shown above citations):
  Prominent badge: see Section 6.4 source tier badges
  Always visible — never below fold when response is short
```

### 7.6 Research Paper Workspace

**Paper card (in paper list):**
```
Card: standard card with left border 3px solid #03a6a6
Status badge: top-right corner
  indexed:       teal, ✓ Indexed
  processing:    blue pulsing, ⏳ Processing
  awaiting_file: amber, 📥 Upload Required
  error:         red, ✗ Error

For awaiting_file papers:
  Link section: Outfit Regular 13px, external link icon
  Upload button: primary button "Upload PDF"
  Abstract snippet: collapsed by default, expand on click
```

**NLP Tool mode selector:**
```
Two-tab toggle: "Quick (Local Model)" / "Quality (AI Generated)"
Default tab: "Quick" to set cost expectations
Active tab: background gradient-teal, text white
Inactive tab: ghost style
```

---

## 8. RTL — Arabic Support

### 8.1 Direction Switching

The app switches direction based on user language preference. The `dir` attribute is applied to the root `<html>` element.

```html
<!-- English -->
<html lang="en" dir="ltr">

<!-- Arabic -->
<html lang="ar" dir="rtl">
```

The `useRTL` hook in React:
```
Reads language from Redux auth.user.language_preference
Sets document.documentElement.dir = isRTL ? 'rtl' : 'ltr'
Sets document.documentElement.lang = language
Triggers re-render of all directional components
```

### 8.2 Tailwind RTL Configuration

Use Tailwind's logical properties instead of directional properties:

| Physical (avoid) | Logical (use) |
|---|---|
| `ml-4` | `ms-4` (margin-inline-start) |
| `mr-4` | `me-4` (margin-inline-end) |
| `pl-4` | `ps-4` (padding-inline-start) |
| `pr-4` | `pe-4` (padding-inline-end) |
| `left-0` | `start-0` |
| `right-0` | `end-0` |
| `border-l` | `border-s` |
| `text-left` | `text-start` |
| `text-right` | `text-end` |
| `rounded-l` | `rounded-s` |
| `rounded-r` | `rounded-e` |

For elements that must have physical direction regardless of language (e.g. left-side triage color strip on cards), use explicit `left`/`right` with RTL override:
```css
.triage-strip {
  left: 0;
}
[dir="rtl"] .triage-strip {
  left: auto;
  right: 0;
}
```

### 8.3 Component RTL Adaptations

**Navigation sidebar:** switches from left (LTR) to right (RTL). Session items keep the same internal layout but text-align changes.

**Chat bubbles:** User messages align end (right in LTR, left in RTL). AI messages align start. The asymmetric border radius flips automatically with RTL.

**Drug Agent tabs:** Tab bar scrolls in the correct direction. Active tab indicator (bottom border) remains under the tab.

**Progress bars:** Fill direction reverses automatically with CSS `direction: rtl`.

**Toasts:** Position switches from top-right to top-left.

**Form labels:** Always above inputs (not inline) to handle both directions correctly.

### 8.4 Arabic Typography Adjustments

When `lang="ar"` is active:
```css
/* Increase line height for Arabic */
body {
  line-height: 1.85; /* vs 1.7 for English */
}

/* Increase letter spacing slightly */
p, li {
  word-spacing: 0.05em;
}

/* Larger font size for same visual weight */
/* Arabic characters are optically smaller at same pt size */
.text-body {
  font-size: 16px; /* vs 15px for English */
}
```

### 8.5 Export RTL

All PDF and DOCX exports produced in Arabic use:
- Noto Sans Arabic font (embedded in export-service)
- RTL paragraph direction
- Right-aligned text
- Right-to-left page margins (wide margin on left, narrow on right — reversed from LTR)

---

## 9. Dark Mode System

### 9.1 Dark Mode Tokens

The dark mode is implemented with Tailwind's `dark:` prefix. The `dark` class is toggled on the `<html>` element.

| Token | Light | Dark |
|---|---|---|
| Page background | `#f9f9f9` | `#0d1117` |
| Surface (cards) | `#ffffff` | `#1a1f2e` |
| Surface elevated | `#f0f0f0` | `#242836` |
| Border | `#f0f0f0` | `#2d3348` |
| Border subtle | `#cccccc` | `#1e2436` |
| Text primary | `#000216` | `#f0f0f0` |
| Text secondary | `#292d36` | `#b0b8cc` |
| Text muted | `#8a8f9a` | `#6b7280` |
| Input background | `#ffffff` | `#12172a` |
| Sidebar | `#f9f9f9` | `#12172a` |
| Nav bar | `#ffffff` | `#000216` |

**Brand colors remain unchanged** in dark mode — Primary Blue `#0487d9`, Teal `#03a6a6`, and Cyan `#00cccc` are used consistently across both modes with adjusted opacity on backgrounds.

### 9.2 Dark Mode Shadows

In dark mode, shadows use opacity instead of color shift:
```css
.dark .card {
  box-shadow: 0 4px 12px rgba(0, 2, 22, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.06);
}
```

### 9.3 Dark Mode Storage

Mode persists in `localStorage` under key `maisys-theme`. Default follows system preference (`prefers-color-scheme`). User toggle overrides system preference.

---

## 10. Icons and Patterns

### 10.1 Icon Library

Primary icon library: **Lucide React** (`lucide-react@0.383.0`) — already in the tech stack.

Icon usage rules:
```
Default size: 20px (inline with text), 24px (standalone), 16px (badge/tag)
Color: inherits from parent text color
Stroke width: 1.5px (Lucide default — do not change)
Never use filled/solid variants for UI icons — outline only
```

Semantic icon mapping:
```
Medical Chatbot:    MessageSquare, Stethoscope
Drug Agent:         Pill, FlaskConical
Symptom Checker:    ClipboardList, Activity
Lab Explainer:      TestTube, Microscope
Research Paper:     BookOpen, GraduationCap
Emergency:          AlertTriangle, Siren
Safety/Shield:      Shield, ShieldCheck
Source/Citation:    ExternalLink, Link
Export:             Download, FileDown
Share:              Share2
Voice/STT:          Mic, MicOff
Voice/TTS:          Volume2, VolumeX
Loading:            Loader2 (animated spin)
Agent/Robot:        Bot, Cpu
Chart/Visual:       BarChart2, LineChart, PieChart
Settings:           Settings, Sliders
```

### 10.2 Brand Pattern

The brand guide shows an icon and pattern system. The repeating geometric pattern from the brand guide can be used as:
- Background texture on hero sections (very low opacity: 3–5%)
- Decorative element on loading screens
- Footer background decoration

Pattern implementation:
```css
.brand-pattern {
  background-image: url('/assets/maisys-pattern.svg');
  background-size: 120px 120px;
  background-repeat: repeat;
  opacity: 0.04;  /* very subtle — decoration only, never distracts from content */
}
```

### 10.3 Custom Medical Icons

For medical-specific concepts not covered by Lucide, use SVG inline icons at 24px. Key custom icons:
- MAISYS logo mark (used as favicon and app icon)
- Triage level icons (traffic light metaphor)
- RAG source tier icons (📊 📋 🌐 — emoji acceptable in badge context)
- Arabic script medical symbol (هـ in a circle — for Arabic mode indicator)

---

## 11. Motion and Transitions

### 11.1 Transition Tokens

```css
--transition-fast:   all 0.15s ease;
--transition-normal: all 0.2s ease;
--transition-slow:   all 0.3s ease;
--transition-bounce: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
```

### 11.2 Transition Usage Map

| Element | Property | Duration | Easing |
|---|---|---|---|
| Buttons (hover) | background, shadow | 0.15s | ease |
| Cards (hover) | shadow, transform | 0.2s | ease |
| Sidebar collapse | width | 0.25s | ease-in-out |
| Modal open | transform, opacity | 0.2s | ease |
| Visual iframe appear | opacity | 0.3s | ease |
| Progress bar fill | width | 0.3s | ease-in-out |
| Streaming text | — | — | No animation — instant append |
| Emergency overlay | opacity | 0.15s | ease |
| Toast appear | transform (slide in), opacity | 0.2s | ease |
| Tab switch | — | 0.15s | ease |
| Accordion expand | height, opacity | 0.2s | ease |
| Skeleton shimmer | background-position | 1.5s | linear infinite |

### 11.3 Reduced Motion

Always respect the `prefers-reduced-motion` media query. When active:
- Remove skeleton shimmer animation (use static gradient instead)
- Remove card hover translateY transform
- Reduce all transition durations to 0.05s or remove
- Do not use bouncy easing (`cubic-bezier` bounce variants)

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## 12. Responsive Breakpoints

Tailwind breakpoints used in MAISYS:

| Name | Min Width | Layout Change |
|---|---|---|
| `sm` | 640px | Mobile → tablet transition |
| `md` | 768px | Stack → side-by-side layouts |
| `lg` | 1024px | Sidebar becomes persistent (not drawer) |
| `xl` | 1280px | Full 3-column layouts possible |
| `2xl` | 1536px | Max content width caps, layout stops expanding |

### 12.1 Key Responsive Behaviors

**Navigation sidebar:**
- `< lg`: Hidden by default, opens as drawer overlay. Hamburger menu icon in nav bar.
- `>= lg`: Always visible, fixed position, no overlay.

**Drug Agent tabs (12 tabs):**
- `< md`: 2-column grid of feature buttons (not tabs)
- `>= md`: Horizontal scrollable tab bar

**Lab test results:**
- `< md`: Test cards stack, bar chart is horizontal scroll on small screens
- `>= md`: 2-column card grid, full-width chart

**Chat messages:**
- All sizes: single column. Max width of message bubble: 75% of container width.

**Agent Activity Panel:**
- `< lg`: Bottom drawer (slides up from bottom, half-screen height)
- `>= lg`: Right panel (280px), pushes chat area left

### 12.2 Mobile-Specific Rules

- All interactive elements: minimum 44×44px touch target
- No hover-only states — all hover effects have equivalent focus/active states
- Font sizes: minimum 15px for body text (never allow 13px on mobile)
- Bottom safe area: add `padding-bottom: env(safe-area-inset-bottom)` to fixed bottom bars
- No horizontal scroll on any page — test at 320px minimum width

---

## 13. Accessibility Standards

### 13.1 Color Contrast Requirements

All text must meet WCAG 2.1 AA minimums:
- Normal text (<= 18px): minimum contrast ratio **4.5:1**
- Large text (>= 19px, Bold >= 14px): minimum contrast ratio **3:1**
- UI components (borders, focus rings): minimum **3:1**

Brand color contrast notes:
- `#0487d9` on white: **4.6:1** — passes AA for large text, marginal for small — use `#0268a8` for small text
- `#0268a8` on white: **5.9:1** — passes AA for all sizes ✓
- `#03a6a6` on white: **3.4:1** — only for large text or decorative elements — not body text
- White on `#0487d9`: **4.6:1** — passes AA ✓
- `#000216` on `#f9f9f9`: **19.5:1** — excellent ✓

### 13.2 Keyboard Navigation

Every interactive element must be reachable and operable with keyboard alone:
- Tab order: logical reading order (LTR: left-to-right, top-to-bottom / RTL: right-to-left)
- Focus visible: custom focus ring using `shadow-focus` (3px `#0487d9` ring) — never remove outline without replacement
- Skip link: "Skip to main content" link as first focusable element on each page
- Escape key: closes all modals, dropdowns, drawers
- Arrow keys: navigate within tab bars, option lists, and dropdown menus
- Enter/Space: activates focused button or link

### 13.3 Screen Reader Support

- All images: descriptive `alt` text
- All icons (without visible text labels): `aria-label` or `aria-hidden="true"` with adjacent visible label
- Loading states: `aria-live="polite"` region announces progress updates to screen readers
- Emergency alert: `role="alertdialog"`, `aria-modal="true"`, `aria-live="assertive"`
- Progress bar: `role="progressbar"`, `aria-valuenow`, `aria-valuemin`, `aria-valuemax`
- Streaming text: `aria-live="polite"` on the response container
- Agent activity panel: `aria-live="polite"` for node completion events
- Medical disclaimer: `role="note"` so screen readers identify it as supplementary content

### 13.4 Form Accessibility

- Every input has an associated `<label>` (not just placeholder text)
- Error messages: linked to input via `aria-describedby`
- Required fields: marked with `aria-required="true"` and visible asterisk (*)
- Autocomplete: `role="listbox"` on dropdown, `role="option"` on each item
- Drug chip input: `aria-label="Drug names, {count} added"` updated dynamically

---

## 14. Tailwind Configuration Reference

### 14.1 `tailwind.config.js` Key Extensions

```javascript
module.exports = {
  content: ['./src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Brand primary
        primary: {
          50:  '#e8f4fd',
          100: '#c5e4fa',
          200: '#8ec9f4',
          400: '#3aa1e5',
          500: '#0487d9',   // Brand primary blue
          600: '#0268a8',   // Brand dark blue
          700: '#015380',
          900: '#000216',   // Brand navy
        },
        // Brand teal/cyan
        teal: {
          400: '#06c4c4',
          500: '#03a6a6',   // Brand teal
          600: '#028080',
        },
        cyan: {
          400: '#00cccc',   // Brand cyan
        },
        // Neutrals
        neutral: {
          0:   '#ffffff',
          50:  '#f9f9f9',   // Brand off-white
          100: '#f0f0f0',
          200: '#cccccc',   // Brand light gray
          400: '#8a8f9a',
          600: '#4a4f5a',
          700: '#292d36',   // Brand dark gray
          900: '#000216',   // Brand navy
        },
        // Semantic
        success: { 100: '#dcfce7', 500: '#16a34a' },
        warning: { 100: '#fef9c3', 500: '#ca8a04' },
        danger:  { 100: '#fee2e2', 500: '#dc2626' },
        info:    { 100: '#e8f4fd', 500: '#0487d9' },
      },
      fontFamily: {
        sans:   ['Outfit', 'sans-serif'],
        arabic: ['IBM Plex Sans Arabic', 'Outfit', 'sans-serif'],
      },
      fontSize: {
        'display': ['3rem', { lineHeight: '1.1', fontWeight: '700' }],
        'h1':      ['2.25rem', { lineHeight: '1.2', fontWeight: '700' }],
        'h2':      ['1.75rem', { lineHeight: '1.25', fontWeight: '600' }],
        'h3':      ['1.375rem', { lineHeight: '1.3', fontWeight: '600' }],
        'h4':      ['1.125rem', { lineHeight: '1.4', fontWeight: '500' }],
        'body-lg': ['1.0625rem', { lineHeight: '1.6' }],
        'body':    ['0.9375rem', { lineHeight: '1.7' }],
        'body-sm': ['0.8125rem', { lineHeight: '1.6' }],
        'label':   ['0.8125rem', { lineHeight: '1.4', fontWeight: '500' }],
        'caption': ['0.6875rem', { lineHeight: '1.5' }],
      },
      borderRadius: {
        'sm': '4px',
        'md': '8px',
        'lg': '12px',
        'xl': '16px',
        '2xl': '24px',
      },
      boxShadow: {
        'sm':    '0 1px 3px rgba(4,135,217,0.08)',
        'md':    '0 4px 12px rgba(4,135,217,0.12)',
        'lg':    '0 8px 24px rgba(4,135,217,0.16)',
        'xl':    '0 16px 48px rgba(0,2,22,0.20)',
        'focus': '0 0 0 3px rgba(4,135,217,0.35)',
        'teal':  '0 4px 16px rgba(3,166,166,0.20)',
      },
      backgroundImage: {
        'gradient-primary': 'linear-gradient(135deg, #0487d9 0%, #03a6a6 50%, #00cccc 100%)',
        'gradient-dark':    'linear-gradient(135deg, #000216 0%, #292d36 100%)',
        'gradient-subtle':  'linear-gradient(135deg, #e8f4fd 0%, #e0f5f5 100%)',
        'gradient-cta':     'linear-gradient(90deg, #0487d9 0%, #0268a8 100%)',
        'gradient-teal':    'linear-gradient(90deg, #03a6a6 0%, #00cccc 100%)',
      },
      transitionDuration: {
        'fast':   '150ms',
        'normal': '200ms',
        'slow':   '300ms',
      },
      zIndex: {
        'raised':    '10',
        'sticky':    '100',
        'overlay':   '200',
        'modal':     '300',
        'toast':     '400',
        'emergency': '500',
      },
      spacing: {
        '18': '4.5rem',
        '22': '5.5rem',
        '72': '18rem',
        '84': '21rem',
        '96': '24rem',
      },
    },
  },
  plugins: [],
}
```

### 14.2 CSS Variables Setup

```css
/* globals.css */
:root {
  --color-primary:    #0487d9;
  --color-primary-dk: #0268a8;
  --color-teal:       #03a6a6;
  --color-cyan:       #00cccc;
  --color-navy:       #000216;
  --color-dark-gray:  #292d36;
  --color-light-gray: #cccccc;
  --color-off-white:  #f9f9f9;

  --gradient-primary: linear-gradient(135deg, #0487d9, #03a6a6, #00cccc);
  --gradient-cta:     linear-gradient(90deg, #0487d9, #0268a8);
  --gradient-teal:    linear-gradient(90deg, #03a6a6, #00cccc);

  --shadow-focus:     0 0 0 3px rgba(4, 135, 217, 0.35);
  --transition-normal: all 0.2s ease;
}

.dark {
  --color-bg-page:    #0d1117;
  --color-bg-surface: #1a1f2e;
  --color-text-primary: #f0f0f0;
  --color-text-secondary: #b0b8cc;
  --color-border:     #2d3348;
}
```

---

*MAISYS Frontend Design Guide — Standalone document based on official brand guideline.*
*Does not modify or replace any section of the MAISYS Technical Development Guide (Parts 1–6).*

---

## 15. Page-by-Page UI Specifications

Each of the 29 pages is specified here with layout, key components, Redux slice, API calls on mount, and WebSocket usage.

### 15.1 Public Pages (Unauthenticated — app.maisys.x)

---

**Page 1 — Landing Page (`/`)**

Layout: Full-width, no sidebar. Sticky top nav with logo + language toggle + dark mode toggle + Login/Register CTAs.

Sections (top to bottom):
- Hero: headline (gradient text using `--gradient-primary`), subheadline, two CTAs (Get Started → `/register`, Learn More → smooth scroll to features)
- Brand pattern background at 4% opacity behind hero
- Five module cards in 2+3 grid — icon, title, one-line description, arrow
- How it works: 3-step horizontal flow (Ask → AI Retrieves → Cited Answer)
- Safety promise: 3-column feature strip (Safety-First, Evidence-Based, Bilingual)
- CTA banner: gradient background, register prompt
- Footer: logo, links, language toggle, social links

Redux: none — fully static
API calls: none
WebSocket: none

---

**Page 2 — Login (`/login`)**

Layout: Centered card (480px wide), no sidebar, background uses `gradient-subtle`.

Components:
- Logo centered above card
- Tab toggle: "Email & Password" / "OTP Login"
- Email input, password input (show/hide toggle)
- "Remember me" checkbox
- Primary button "Sign In"
- Divider: "or continue with"
- Google OAuth button, Apple OAuth button
- Links: "Forgot password?" / "Create account"
- OTP tab: email input → send code → 6-digit code input → verify

Error handling: inline error below form (not toast) for credential errors.
Success: redirect to `/dashboard` or `?next=` param target.

Redux: updates `auth.user`, `auth.accessToken`
API calls on submit: `POST /auth/login`, `POST /auth/otp/verify`

---

**Page 3 — Register (`/register`)**

Layout: Same centered card as login.

Fields (step 1 — single form):
- Email input
- Password input with strength indicator (4-bar visual: weak/fair/good/strong)
- Confirm password
- Language preference toggle (EN / AR — saves preference)
- Terms and Privacy checkbox (required)
- Register button

Step 2 (auto-advance after register success):
- OTP verification screen (6-digit input)
- Resend code button with 60s countdown timer
- "Check your email at {masked_email}"

Redux: updates `auth.user` on success
API calls: `POST /auth/register`, `POST /auth/verify-email`

---

**Page 4 — Forgot Password (`/forgot-password`) and Reset Password (`/reset-password`)**

Layout: Centered card, 3-step linear flow.

Step 1: Email input → send code
Step 2: OTP verification (6-digit)
Step 3: New password + confirm → success message → redirect to `/login`

API calls: `POST /auth/forgot-password`, `POST /auth/otp/verify`, `POST /auth/reset-password`

---

**Page 5 — OTP Verification (`/verify-otp`)**

Standalone page used after registration for email verification. Shows:
- Checkmark animation on success
- Error count indicator (5 max attempts shown visually)
- Auto-redirect to dashboard after verified

---

### 15.2 Authenticated Pages

---

**Page 6 — Main Dashboard (`/dashboard`)**

Layout: Top nav + page body, no left sidebar (dashboard is the home, not a module workspace).

Grid sections:
```
Top row: greeting ("Good morning, {name}") + health profile completion % ring
Module grid: 2×3 responsive grid of ModuleCard components
  Each card: icon + gradient top strip, module name, one-sentence description,
             "Open →" CTA, last session preview (title + relative time)
Recent Activity: horizontal scroll list of last 5 sessions across all modules
Beta CTA: conditional — shown only if user is eligible and not enrolled
Health profile prompt: shown if profile is empty
```

Redux slices touched: `chatbot.sessions`, `drug.sessions`, `symptom.sessions`, `lab.sessions`, `research.sessions`, `auth.user`

API calls on mount (parallel):
- `GET /chat/sessions?per_page=2`
- `GET /drug/sessions?per_page=2`
- `GET /symptom/sessions?per_page=2`
- `GET /lab/sessions?per_page=2`
- `GET /research/sessions?per_page=2`

---

**Page 7 — Profile Settings (`/settings/profile`)**

Layout: Settings shell (tabs on left: Profile, Security, Beta, History). Profile tab active.

Fields:
- Display name (text input)
- Email (read-only with "Change email" action)
- Language preference (EN/AR toggle — persists to DB)
- Avatar upload (circle crop, max 2MB, JPG/PNG)
- Save button (only enabled when form is dirty)

Health Profile sub-section (collapsible card):
- Age, gender (radio), blood type (dropdown)
- Toggle switches: Is Pregnant, Has Diabetes, Has Hypertension, Has Heart Disease, Has Kidney Disease
- Chronic conditions (chip tag input, free text)
- Current medications (chip tag input, with RxNorm autocomplete)
- Allergies (chip tag input)
- Clear all button, Save button

Redux: updates `auth.user.language_preference` immediately (triggers RTL switch if changed)
API calls: `POST /auth/profile`, `POST /chat/profile`

---

**Page 8 — Security Settings (`/settings/security`)**

Sections:
- Password change (current + new + confirm, strength indicator)
- Login OTP: toggle ON/OFF + "Send test OTP" button
- Connected accounts: Google / Apple — each row shows email + "Disconnect" button
- Active sessions: table (device, location, last active, "Sign out" per row) + "Sign out all other devices" button

API calls: `POST /auth/reset-password`, `POST /auth/otp/send`, `DELETE /auth/sessions`

---

**Page 9 — Beta Settings (`/settings/beta`)**

Three consent gate status cards (visual step indicator):
```
Gate 1 — Consent Screen:  [✓ Completed mm/dd/yyyy] or [○ Not yet completed]
Gate 2 — Account Toggle:  ON/OFF switch (controls Gate 2)
Gate 3 — Onboarding:      [✓ Completed] or [Begin Onboarding →]
```

If all three complete: green "Beta Access Active" badge.
Withdrawal section: red bordered card "Withdraw Beta Participation" with confirmation modal.
Link to Beta FAQ explaining what data is collected, how it's used, GP review process.

API calls: `GET /symptom/consent`, `POST /symptom/consent`, `DELETE /symptom/consent`

---

**Page 10 — History (`/history`)**

Layout: Full-width list, filters on top.

Filters bar:
- Module filter (All / Chatbot / Drug / Symptom / Lab / Research) — pill toggle
- Date range picker (Today / This week / This month / Custom)
- Search input (searches session titles)

Session list:
- Each row: module icon, session title, date, status badge, "Open →" link
- Bulk select checkboxes + "Delete selected" action
- Pagination (20 per page)

Redux: local filter state (not persisted)
API calls: per-module `GET /sessions` combined and sorted client-side

---

**Page 11 — Saved / Starred Sessions (`/saved`)**

Same layout as History but filtered to `is_starred = true`. Star toggle available inline.

---

### 15.3 Module Pages

---

**Page 12 — Medical Chatbot (`/chatbot`)**

Layout: Three-panel layout.

```
┌─────────────────────────────────────────────────────────┐
│ Top Nav (64px)                                          │
├──────────────────┬──────────────────────────────────────┤
│                  │                                       │
│  Session         │   Chat Area                           │
│  Sidebar         │   (flex-col, fills remaining)         │
│  (280px)         │                                       │
│                  │                         ┌─────────┐   │
│  [New Session]   │                         │ Agent   │   │
│                  │                         │ Panel   │   │
│  Session List    │                         │ (320px) │   │
│                  │                         └─────────┘   │
└──────────────────┴──────────────────────────────────────┘
```

**Session Sidebar:**
- "New Chat" button (primary, full-width in sidebar)
- Search input for sessions
- Session list: grouped (Today, Yesterday, This Week, Older)
- Each session: title (truncated), relative timestamp, star icon on hover
- Long-press / right-click context menu: Rename, Star, Delete

**Chat Area — Main:**
- Chat header: session title (editable on click), share button, export dropdown (TXT/DOCX/PDF), health profile indicator dot
- Message list: scrollable, auto-scroll to bottom on new message
- Empty state (new session): MAISYS icon centered, "What would you like to know?" prompt, 4 suggestion chips
- Each `assistant` message: AI bubble + streaming cursor + citations block + visual iframe (if generated)
- Each `user` message: user bubble right-aligned (LTR) / left-aligned (RTL)
- Feedback bar below each assistant message: 👍 👎 buttons, copy button

**Input Area:**
- Text input (multiline, auto-expands up to 5 lines, then scrolls)
- Voice button (hold to record — shows recording indicator)
- Attach button (opens file picker: PDF, DOCX, JPG, PNG, WEBP)
- Send button (arrow icon — active only when input non-empty)
- Char count shown when > 500 chars typed

**Agent Activity Panel:**
- Collapsible from right side (chevron toggle)
- Shows live node pipeline per agent
- Collapses to icon-only strip when no agents running

Redux slice: `chatbot` — `sessions`, `messages`, `isStreaming`, `streamBuffer`, `agentActivity`

WebSocket: `wss://api.maisys.x/ws/chat/{session_id}` — open on session select, close on navigate away

API calls on mount:
- `GET /chat/sessions` (load session list)
- `GET /chat/sessions/{id}/messages` (load messages on session select)

---

**Page 13 — Drug Agent (`/drugs`)**

Layout: No sidebar. Full-width with 12-tab navigation across top.

**Feature Tab Bar:**
Horizontal scrollable tabs (12 tabs). On mobile: 2-column feature grid replaces tab bar.

Tab labels and icons:
```
Profile (Pill), Interactions (Zap), Food (Utensils), Disease (Heart),
Pregnancy (Baby), Dosage (Calculator), Alternatives (RefreshCw),
Comparison (BarChart2), Pharmacokinetics (Activity),
Off-Label (Search), Brand/Generic (Tag), Drug Class (Layers)
```

**Drug Input Area (shared across all tabs):**
- Drug chip input with RxNorm autocomplete (500ms debounce)
- Input placeholder adapts per tab: "Enter drug name..." or "Enter two or more drugs..."
- Chip: drug canonical name in blue chip, × to remove
- Duplicate detection: shows warning chip in orange if same RxCUI added twice
- "Check Interactions" / "Search" button (label adapts per feature)

**Additional Inputs (per feature — appear conditionally):**
- Dosage tab: weight (kg), eGFR (mL/min), Child-Pugh (A/B/C dropdown), indication
- Comparison tab: automatically requires 2–3 drugs (chip input min/max enforced)
- Drug Class tab: text input for class name instead of drug chip

**Results Area:**
- Progress bar + agent activity panel during processing
- Streaming LLM response in result card
- Source badge prominent at top of result
- Visual (chart/infographic) rendered in sandboxed iframe below response
- Per-pair interaction cards for drug-drug feature
- Export bar: TXT / DOCX / PDF — fixed at bottom of results

**Session History Panel (right drawer on desktop, bottom sheet on mobile):**
- Last 10 drug sessions for this feature
- Each: input drugs list, feature type, date

Redux slice: `drug` — `activeFeature`, `currentResult`, `normalizedDrugs`, `isProcessing`, `agentActivity`

WebSocket: `wss://api.maisys.x/ws/drug/{session_id}` — opens when a drug query is submitted

API calls: `POST /drug/{feature}` per tab

---

**Page 14 — Symptom Checker Alpha (`/symptoms`)**

Layout: Centered single-column (max 680px) — conversation-first design.

**State 1 — Initial Form (session not started):**
- Module header with description
- Age slider + number input (0–120)
- Sex: segmented control (Male / Female)
- Language: segmented control (English / العربية)
- Chief complaint textarea (min 20 chars, live char count, placeholder: "Describe your main symptom...")
- "Start Assessment" primary button

**State 2 — Active Session:**
- Session progress strip (top): "Question {n} of 8 maximum" + urgency color strip (updates as assessment progresses)
- Parsed symptoms display (collapsible): chips of detected symptoms
- Current conditions sidebar (right on desktop, collapsible on mobile): top 3 conditions with probability bars
- Question card: teal left-border card with rephrased question text
- Quick-answer buttons row: Yes / No / Not Sure (primary / secondary / ghost styles)
- Or: text input for "Other answer" below quick-answer buttons
- Voice input button

**State 3 — Results:**
- Triage banner (full-width, color by triage level, 72px height)
- "Based on {n} questions answered" subtitle
- Top 3 condition cards (probability bar, plain-language explanation — streaming)
- Background info section (from Medical RAG, subtle blue-tinted card)
- Triage summary card (what to do next)
- Disclaimer box (always visible, amber)
- Export + New Assessment buttons

**Emergency State (overlay, z-index 500):**
- Full-screen red overlay
- Large ⚠️ icon, bold headline, action list with phone numbers
- 5-second lock before dismiss button appears

Redux slice: `symptom` — `alphaSession`, `currentQuestion`, `isFinalized`, `results`

API calls: `POST /symptom/session/start`, `POST /symptom/session/{id}/answer`

---

**Page 15 — Symptom Checker Beta (`/symptoms/beta`)**

Same layout as Alpha with these additions:
- Persistent beta warning banner (amber, top of page, cannot close)
- "⚗️ EXPERIMENTAL" watermark on all results
- Consent gate check runs at route middleware — redirect to `/settings/beta` if gates incomplete

---

**Page 16 — Lab Test Explainer (`/labs`)**

Layout: No sidebar. Full-width with upload → processing → results flow.

**State 1 — Upload Zone:**
- Large drop zone (dashed border, drag-over state: solid border + background tint)
- Accepted formats badge: PDF · JPG · PNG · WEBP · DOCX
- Max size notice: PDF 50MB, Images 10MB
- Alternative: "Browse files" link text button
- Recent sessions list below upload zone (last 5, quick access)

**State 2 — Processing:**
- Uploaded file card: filename, size, file type icon, processing path badge (Path A/B/C/D)
- Progress bar with per-step status labels:
  - Extracting text from document...
  - Analyzing lab report image... (Path C/D)
  - Identifying tests and values...
  - Found {n} tests — generating explanations...
  - Explaining test {k} of {n}: {test_name}...
- Cancel button (allowed before explanation stage starts)

**State 3 — Results Dashboard:**
- Urgency banner (4 levels: none / routine / soon / urgent — color-coded)
- Overall summary card: text summary + count badges (normal/high/low/critical counts)
- Auto-generated bar chart (iframe — Chart.js, values vs reference ranges, color-coded bars)
- Auto-generated test cards (infographic — abnormal tests as cards)
- Test results grid:
  - Filter tabs: All / Abnormal / Normal / Critical
  - Sorted by: abnormal first, then by sort_order
  - Each test card: name, value + unit, status badge, reference range, urgency level left strip
  - Expand to see full explanation (4 accordion sections)
- Export bar (PDF report, DOCX, TXT)
- "Ask about your results" CTA → opens follow-up chat workspace

**State 4 — Follow-Up Chat:**
- Split view: results summary panel (left, collapsible) + chat panel (right)
- Chat follows exact same UI as Medical Chatbot
- Pre-seeded context: lab session results injected into system prompt
- Input area includes voice button

Redux slice: `lab` — `sessions`, `activeSessionId`, `tests`, `isProcessing`, `processingProgress`

WebSocket: `wss://api.maisys.x/ws/lab/{session_id}` — open during processing

API calls: `POST /lab/upload`, `GET /lab/sessions/{id}/results`

---

**Page 17 — Research Paper Assistant (`/research`)**

Layout: Three-panel (same structure as Chatbot).

```
┌────────────┬─────────────────────────────────────────────┐
│  Session   │  Workspace (top: papers / bottom: tools)    │
│  Sidebar   │                                             │
│  (280px)   │  Paper List + Upload + Discover buttons     │
│            │  ─────────────────────────────────────────  │
│            │  Tabs: Chat │ Summarize │ Translate │ Q&A   │
│            │             │ Compare                       │
│            │  Tool Panel (active tab content)            │
└────────────┴─────────────────────────────────────────────┘
```

**Paper List Panel (top of workspace):**
- Each paper card: title (truncated 2 lines), authors + year, status badge
- `indexed` papers: selectable checkbox for multi-paper operations
- `awaiting_file` papers: amber badge + publisher link + "Upload PDF" button + abstract snippet
- "Upload Paper" button, "Discover Papers" button (opens discovery modal)

**Discovery Modal:**
- Textarea: "Describe the research topic you're looking for..."
- Submit → shows discovery progress (WebSocket events)
- Results panel within modal: two sections "Added to Workspace" + "Requires Manual Download"
- Pending papers: title, abstract, DOI, publisher link, per-paper "Upload PDF" button

**Tool Tabs:**

`Chat` tab: identical to Chatbot UI. Paper scope selector: "All Papers" or per-paper dropdown.

`Summarize` tab:
- Paper selector (single-select dropdown)
- Mode toggle: Quick (DistilBART) / Quality (AI)
- Summary type: Brief / Structured / Key Points
- Generate button → streaming output
- Copy / Export buttons on result

`Translate` tab:
- Paper selector
- Direction: EN → AR / AR → EN
- Scope: Abstract / Full Paper / Specific Section (section dropdown)
- Mode toggle: Quick (opus-mt) / Quality (AI)
- Generate → streaming output

`Q&A` tab:
- Paper selector
- Mode toggle: Quick (T5) / Quality (AI)
- Difficulty: Comprehension / Analysis / Application (checkboxes)
- Generate → renders Q&A pair cards with expand/collapse

`Compare` tab:
- Multi-paper selector (2–4 papers with checkboxes)
- Always uses Quality (AI) mode
- Generate → comparison table (sticky header, scrollable) + narrative summary

Redux slice: `research` — `sessions`, `papers`, `pendingUploads`, `messages`, `isDiscovering`, `discoveryProgress`

WebSocket: `wss://api.maisys.x/ws/research/{session_id}`

---

### 15.4 Admin Panel Pages (admin.maisys.x)

---

**Page 18 — Admin Login (`/login`)**

Layout: Centered card. Separate from user auth.
- Email + Password
- After credentials: TOTP code input (6-digit, auto-focus, auto-submit on 6 chars)
- No social login — credentials only
- IP restriction: error shown if IP not in allowlist

---

**Page 19 — GP Review Dashboard (`/review`)**

Layout: Full-width table with review panel.

Left: queue table — columns: submission date, source (infermedica/endlessmedical/beta_session), chief complaint (first 80 chars), Beta model triage estimate, status
Right panel (opens on row click): full session detail — anonymized chief complaint, all conversation turns, Beta model assessment, Beta model triage

Action buttons below right panel:
- ✅ Approve (green)
- ✏️ Correct & Approve (opens correction form: diagnosis field + triage dropdown + notes)
- ✗ Reject (with reason dropdown)
- 🚩 Flag for Discussion

Stats bar at top: Pending / Reviewed Today / Total Approved (live counts, auto-refresh 30s)

---

**Page 20 — System Monitoring (`/monitoring`)**

Layout: Dashboard grid, auto-refreshing every 30 seconds.

Panels:
- Request rate per service (line chart, last 1h)
- P95 latency per service (bar chart)
- Error rate per service (color-coded: green <1%, amber 1-5%, red >5%)
- Active WebSocket connections (gauge)
- LLM call latency by provider (grouped bar chart)
- vLLM GPU utilization % (gauge) + VRAM used/total
- Tier 1 vs Tier 2 retrieval ratio for drug-service (pie chart)
- RabbitMQ queue depths (horizontal bar per queue)
- Circuit breaker status per service (green closed / red open badges)

Time range selector: 1h / 6h / 24h / 7d

---

**Page 21 — User Management (`/users`)**

Searchable table with columns: Email, Role, Registration Date, Last Active, Email Verified, Beta Consent Status.

Row actions: Change Role (dropdown), Force Email Verify, Revoke Beta Access, Deactivate Account.

Audit Log tab: full table of all admin actions with admin email, action, target, timestamp.

---

**Page 22 — Model Performance Tracker (`/models`)**

Two sections:

**Active Configuration table:**
Rows per service × role combination. Columns: Service, Role, Active Model, Provider, Type (Local/Cloud), Avg Latency, Error Rate, Tokens (last 24h).
"Switch Model" button → modal with dropdown of all registered models for that role → instant switch with confirmation.

**Beta Training Runs table:**
Columns: Date, Base Model, Train Size, Triage Acc., Emergency FN Rate, Deployed.
"View Report" link per row. "Deploy" button for approved non-deployed runs (disabled if emergency FN > 0%).

---

## 16. Redux State Management

### 16.1 Store Setup

```typescript
// store/index.ts
import { configureStore } from '@reduxjs/toolkit';
import authReducer     from './slices/authSlice';
import themeReducer    from './slices/themeSlice';
import chatbotReducer  from './slices/chatbotSlice';
import drugReducer     from './slices/drugSlice';
import symptomReducer  from './slices/symptomSlice';
import labReducer      from './slices/labSlice';
import researchReducer from './slices/researchSlice';
import notifyReducer   from './slices/notificationSlice';

export const store = configureStore({
  reducer: {
    auth:         authReducer,
    theme:        themeReducer,
    chatbot:      chatbotReducer,
    drug:         drugReducer,
    symptom:      symptomReducer,
    lab:          labReducer,
    research:     researchReducer,
    notifications: notifyReducer,
  },
});

export type RootState   = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
```

### 16.2 Auth Slice

```typescript
interface AuthState {
  user:          User | null;
  accessToken:   string | null;
  isLoading:     boolean;
  isInitialized: boolean;   // true after initial token check on app load
  error:         string | null;
}

// Key actions
setUser(user: User)          // on login success
setToken(token: string)      // on token refresh
clearAuth()                  // on logout
setLanguage(lang: 'en'|'ar') // triggers RTL hook
```

### 16.3 Theme Slice

```typescript
interface ThemeState {
  mode:     'light' | 'dark';
  language: 'en' | 'ar';
  isRTL:    boolean;
}

// Key actions
toggleTheme()               // light ↔ dark
setLanguage(lang: string)   // sets isRTL = lang === 'ar'
```

### 16.4 Chatbot Slice

```typescript
interface ChatbotState {
  sessions:      ChatSession[];
  activeId:      string | null;
  messages:      Record<string, ChatMessage[]>;   // keyed by session_id
  isStreaming:   boolean;
  streamBuffer:  string;           // accumulates LLM tokens
  streamMsgId:   string | null;    // which message is streaming
  agentEvents:   AgentEvent[];
  citations:     Citation[];       // pending citations for current stream
  activeVisual:  Visual | null;    // visual being rendered
  isLoadingMsgs: boolean;
}

// Key actions
addSession(session: ChatSession)
setActiveSession(id: string)
appendToken(token: string)          // called per token WebSocket event
finalizeStream(message: ChatMessage)
setCitations(citations: Citation[])
setVisual(visual: Visual)
appendAgentEvent(event: AgentEvent)
clearAgentEvents()
```

### 16.5 Drug Slice

```typescript
interface DrugState {
  activeFeature:   DrugFeature;     // which of 12 tabs is active
  sessions:        DrugSession[];
  inputDrugs:      NormalizedDrug[];
  isNormalizing:   boolean;
  isProcessing:    boolean;
  currentResult:   DrugResult | null;
  agentEvents:     AgentEvent[];
  streamBuffer:    string;
}
```

### 16.6 Symptom Slice

```typescript
interface SymptomState {
  alphaSession:    SymptomSession | null;
  betaSession:     BetaSession | null;
  currentQuestion: Question | null;
  currentConditions: ConditionEstimate[];
  turnCount:       number;
  isFinalized:     boolean;
  results:         SymptomResult | null;
  isLoading:       boolean;
  consentStatus:   ConsentStatus | null;   // 3-gate status
}
```

### 16.7 Lab Slice

```typescript
interface LabState {
  sessions:         LabSession[];
  activeId:         string | null;
  tests:            Record<string, LabTest[]>;    // keyed by session_id
  explanations:     Record<string, LabExplanation>; // keyed by test_id
  summary:          LabSummary | null;
  isUploading:      boolean;
  isProcessing:     boolean;
  processingStep:   string;
  processingPct:    number;
  chatMessages:     ChatMessage[];
  chatStreamBuffer: string;
}
```

### 16.8 Research Slice

```typescript
interface ResearchState {
  sessions:         ResearchSession[];
  activeId:         string | null;
  papers:           Record<string, Paper[]>;     // keyed by session_id
  pendingUploads:   PendingPaper[];              // awaiting_file papers
  messages:         Record<string, ChatMessage[]>;
  isDiscovering:    boolean;
  discoveryPct:     number;
  discoveryReport:  DiscoveryReport | null;
  streamBuffer:     string;
  agentEvents:      AgentEvent[];
  activeToolTab:    'chat'|'summarize'|'translate'|'qa'|'compare';
  toolResult:       string;                      // streaming NLP tool output
}
```

---

## 17. WebSocket Integration

### 17.1 `useWebSocket` Hook

```typescript
interface UseWebSocketOptions {
  sessionId:  string;
  service:    'chat' | 'drug' | 'symptom' | 'lab' | 'research';
  onToken:    (token: string) => void;
  onProgress: (event: ProgressEvent) => void;
  onAgent:    (event: AgentEvent) => void;
  onVisual:   (event: VisualEvent) => void;
  onCitations:(event: CitationEvent) => void;
  onComplete: (event: CompleteEvent) => void;
  onError:    (event: ErrorEvent) => void;
  onEmergency:(event: EmergencyEvent) => void;
}
```

**Connection lifecycle:**
- Connect on session open / query submit
- Reconnect automatically on disconnect (exponential backoff: 1s, 2s, 4s, max 30s)
- Max 5 reconnect attempts before showing persistent error banner
- Disconnect on page navigate / session switch / component unmount

**Event routing logic:**
```
event.event === 'token'          → dispatch(appendToken(event.token))
event.event === 'progress'       → dispatch(setProgress(event))
event.event === 'node_start'     → dispatch(appendAgentEvent(event))
event.event === 'node_complete'  → dispatch(appendAgentEvent(event))
event.event === 'visual_ready'   → dispatch(setVisual(event))
event.event === 'citations'      → dispatch(setCitations(event.citations))
event.event === 'result_complete'→ dispatch(finalizeStream())
event.event === 'emergency_detected' → dispatch(showEmergency(event))
event.event === 'error'          → dispatch(handleWsError(event))
```

### 17.2 Streaming Text Rendering

The streaming text area renders incrementally. The `streamBuffer` in Redux holds the growing string. The component re-renders on every token (typically 20–50ms intervals).

Performance: use React `memo` on the streaming text component. Only the buffer string prop changes — prevent unnecessary re-renders of the entire chat list.

Blinking cursor: a `::after` pseudo-element appended only when `isStreaming = true`. Removed immediately when `stream_complete` is received.

Auto-scroll: the message list auto-scrolls to bottom on every new token unless the user has manually scrolled up (scroll position tracked). If user scrolled up: show "↓ New message" floating chip at bottom — clicking it resumes auto-scroll.

### 17.3 Visual iframe Rendering

When a `visual_ready` event arrives, the HTML string is set as `srcDoc` on a sandboxed iframe:

```tsx
<iframe
  srcDoc={visual.html_content}
  sandbox="allow-scripts"
  title={visual.title}
  style={{ width: '100%', height: '400px', border: 'none', borderRadius: '8px' }}
  loading="lazy"
/>
```

The iframe appears with a 0.3s fade-in. On export, Playwright on the backend has already rendered it to PNG — the export uses the PNG path, not the iframe.

---

## 18. API Client Setup

### 18.1 Axios Instance

```typescript
// api/client.ts
import axios from 'axios';
import { store } from '../store';
import { clearAuth, setToken } from '../store/slices/authSlice';

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

// Request interceptor — attach JWT
apiClient.interceptors.request.use((config) => {
  const token = store.getState().auth.accessToken;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Response interceptor — handle 401 (token expired)
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      try {
        const { data } = await axios.post('/auth/refresh', {
          refresh_token: localStorage.getItem('maisys_refresh_token'),
        });
        store.dispatch(setToken(data.data.access_token));
        localStorage.setItem('maisys_refresh_token', data.data.refresh_token);
        original.headers.Authorization = `Bearer ${data.data.access_token}`;
        return apiClient(original);
      } catch {
        store.dispatch(clearAuth());
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default apiClient;
```

### 18.2 Per-Service API Modules

```typescript
// api/chatbot.ts
export const chatbotApi = {
  getSessions: ()                           => apiClient.get('/chat/sessions'),
  getMessages: (id: string)                 => apiClient.get(`/chat/sessions/${id}/messages`),
  sendMessage: (body: SendMessageRequest)   => apiClient.post('/chat/message', body),
  uploadFile:  (formData: FormData)         => apiClient.post('/chat/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }, timeout: 60000
  }),
  shareSession: (id: string, days: number)  => apiClient.post(`/chat/sessions/${id}/share`, { expires_in_days: days }),
  deleteSession: (id: string)               => apiClient.delete(`/chat/sessions/${id}`),
  transcribe:  (formData: FormData)         => apiClient.post('/chat/voice/transcribe', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  }),
};
```

Same pattern for `drugApi`, `symptomApi`, `labApi`, `researchApi`, `authApi`.

---

## 19. Voice (STT/TTS) Integration

### 19.1 `useVoice` Hook

```typescript
interface UseVoiceReturn {
  isRecording:   boolean;
  isTranscribing: boolean;
  transcript:    string | null;
  isSpeaking:    boolean;
  startRecording: () => void;
  stopRecording:  () => void;
  speak:          (text: string) => void;
  stopSpeaking:   () => void;
  error:          string | null;
}
```

**Recording flow:**
1. `startRecording()` → request microphone permission (`navigator.mediaDevices.getUserMedia`)
2. Record with `MediaRecorder` API → collect audio chunks
3. `stopRecording()` → assemble WebM blob → send to `/voice/transcribe` via multipart POST
4. Response transcript set in `transcript` → injected into input field automatically

**Fallback:** if browser does not support `MediaRecorder` → show "Voice not supported on this browser" tooltip, hide voice button.

**Permission denied:** show toast "Microphone access denied. Enable in browser settings." — never crash.

**TTS Playback:**
- API returns audio blob from `/voice/synthesize`
- Play via `Audio` API (`new Audio(blobURL).play()`)
- Show speaking indicator (animated wave icon) on AI message during playback
- Stop button cancels playback (`audio.pause(); audio.currentTime = 0`)
- On session navigate away: stop any active TTS playback

### 19.2 Voice Button States

```
Idle:          mic icon, gray (#8a8f9a)
Hold to start: brief tooltip appears on hover
Recording:     red pulsing dot + mic icon, red (#dc2626), waveform animation
Processing:    spinner, blue (#0487d9), "Transcribing..." tooltip
Error:         mic-off icon, amber (#ca8a04), error tooltip
```

---

## 20. Internationalization (i18n)

### 20.1 Setup — react-i18next

```typescript
// i18n/index.ts
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './translations/en.json';
import ar from './translations/ar.json';

i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, ar: { translation: ar } },
  lng: 'en',           // default — overridden by user preference on login
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
});

export default i18n;
```

### 20.2 Translation File Structure

```json
// en.json
{
  "nav": { "dashboard": "Dashboard", "chatbot": "Medical Chatbot", ... },
  "chatbot": {
    "newChat": "New Chat",
    "inputPlaceholder": "Ask any medical question...",
    "sources": "Sources",
    "disclaimer": "This information is for educational purposes only..."
  },
  "drug": {
    "features": {
      "profile": "Drug Profile",
      "interaction": "Drug Interactions",
      ...
    }
  },
  "triage": {
    "emergency": "Emergency — Call Emergency Services Immediately",
    "consultation_24": "See a Doctor Today",
    "consultation": "Schedule an Appointment",
    "self_care": "Home Care — Monitor Symptoms"
  },
  "emergency": {
    "title": "This may be a medical emergency",
    "action1": "Call emergency services immediately",
    "acknowledge": "I understand — this is not an emergency"
  },
  ...
}
```

```json
// ar.json
{
  "nav": { "dashboard": "لوحة التحكم", "chatbot": "المساعد الطبي", ... },
  "chatbot": {
    "newChat": "محادثة جديدة",
    "inputPlaceholder": "اطرح أي سؤال طبي...",
    "sources": "المصادر",
    "disclaimer": "هذه المعلومات لأغراض تعليمية فقط..."
  },
  ...
}
```

### 20.3 Language Switch Pattern

```typescript
// hooks/useRTL.ts
export const useRTL = () => {
  const { language } = useSelector(state => state.theme);

  useEffect(() => {
    const isRTL = language === 'ar';
    document.documentElement.dir  = isRTL ? 'rtl' : 'ltr';
    document.documentElement.lang = language;
    document.documentElement.style.fontFamily = isRTL
      ? "'IBM Plex Sans Arabic', sans-serif"
      : "'Outfit', sans-serif";
    i18n.changeLanguage(language);
  }, [language]);

  return language === 'ar';
};
```

---

## 21. File Upload Patterns

### 21.1 Upload Flow (all services)

```
User selects file (drag-drop or file picker)
  → client-side validation first (extension, size, basic MIME check)
  → if invalid: inline error message, no upload attempt
  → if valid: show file preview card with progress bar
  → POST multipart/form-data with X-Request-ID header
  → on progress: update progress bar width
  → on success: handle per-service response
  → on error: show error in file card, allow retry
```

### 21.2 File Preview Card States

```
Pending (before upload):  file icon, filename, size, "Upload" button
Uploading:               progress bar (0–100%), cancel button
Processing:              spinner, "Processing..." label, progress events via WebSocket
Complete:                checkmark, green border, "View Results" link
Error:                   red border, error message, "Retry" button
```

### 21.3 Accepted File Types Per Service

| Service | Types | Max Size |
|---|---|---|
| Chatbot (file context) | PDF, DOCX | 50 MB |
| Chatbot (image) | JPG, PNG, WEBP | 10 MB |
| Lab Test Explainer | PDF, JPG, PNG, WEBP, DOCX | 50 MB PDF / 10 MB image |
| Research Papers | PDF, DOCX | 50 MB |

---

## 22. Error States and Error Boundaries

### 22.1 Error Boundary

A React error boundary wraps each module page. On uncaught error:
- Shows a friendly "Something went wrong" card with the MAISYS icon
- Shows "Try again" button (resets boundary state)
- Logs error to monitoring (Sentry or equivalent)
- Never shows stack traces or technical details to users

### 22.2 API Error Handling

All API errors are caught in Axios interceptor and dispatched to the `notifications` slice:

| HTTP Status | User-facing Behavior |
|---|---|
| 400, 422 | Inline form error below the relevant input |
| 401 | Auto-retry with refresh token → if fails: redirect to login |
| 403 | Toast: "You don't have permission to do that" |
| 404 | Inline "Not found" state in the affected component |
| 429 | Toast with retry countdown: "Too many requests. Try again in {n}s" |
| 500, 503 | Toast: "Something went wrong on our end. Please try again." + retry button |
| Network error | Banner: "Connection lost. Reconnecting..." (auto-dismisses when restored) |

### 22.3 Empty States

Every list, result area, and data panel has an empty state:

```
New session empty state:
  MAISYS icon (gradient tint, 64px)
  Headline: "What would you like to know?"
  4 suggestion chips (contextual per module)

No results empty state:
  Search icon, "No results found"
  Suggestion: try broader search terms

Error empty state:
  Warning icon, "Couldn't load content"
  "Try again" button

Pending upload empty state (research):
  Upload icon, "Add papers to get started"
  Two buttons: Upload PDF / Discover Papers
```

---

## 23. Performance Guidelines

### 23.1 Code Splitting

Every module page is lazy-loaded with React Suspense:

```typescript
const ChatbotPage  = lazy(() => import('./pages/Chatbot'));
const DrugPage     = lazy(() => import('./pages/Drug'));
const SymptomPage  = lazy(() => import('./pages/Symptom'));
const LabPage      = lazy(() => import('./pages/Lab'));
const ResearchPage = lazy(() => import('./pages/Research'));
```

Fallback: skeleton screen matching the module's layout (not a spinner).

### 23.2 Image Optimization

- Use WebP format for all static images
- Specify explicit `width` and `height` on all `<img>` tags (prevents layout shift)
- Use `loading="lazy"` on all below-fold images
- Logo and icons: SVG inline (no network request, scales perfectly)

### 23.3 Font Loading

```html
<!-- Preconnect to font servers (in <head>) -->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>

<!-- Load only used weights -->
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=IBM+Plex+Sans+Arabic:wght@300;400;500;600;700&display=swap" rel="stylesheet">
```

`display=swap` ensures text is visible while fonts load. Never use `display=block` (hides text during load).

### 23.4 Streaming Text Performance

Appending tokens to a growing string on every WebSocket message is a high-frequency operation. Avoid re-rendering the entire message list on every token:
- `streamBuffer` in Redux is updated on every token
- Only the streaming message component subscribes to `streamBuffer` — all other messages use memoized selectors
- Use `React.memo` on `MessageBubble` with custom comparison that prevents re-render when `streamBuffer` changes for a different message ID

### 23.5 Virtualization

Session lists longer than 50 items use `react-window` (or Tanstack Virtual) to virtualize the list. Only visible rows are rendered. Drug Agent session history, lab session list, and research session list use this.

---

## 24. Testing Guidelines (Frontend)

### 24.1 Tools

- **React Testing Library** — component tests
- **Vitest** — test runner (compatible with Vite)
- **MSW (Mock Service Worker)** — API mocking in tests (intercepts fetch/axios)
- **Playwright** — end-to-end tests (critical user flows)

### 24.2 What to Test

**Component tests (RTL):**
- All form validation rules (invalid email, short password, missing required fields)
- Emergency overlay renders and 5-second lock behavior
- RTL layout renders correctly when `dir="rtl"` on container
- Source tier badge renders with correct color per tier
- Progress bar renders at correct percentage
- Streaming text appends tokens in order

**Integration tests (RTL + MSW):**
- Login flow: submit form → mock success → Redux state updated → redirect
- Drug chip input: type → autocomplete appears → select → chip appears → × removes
- Lab upload: drop file → mock upload → progress updates → results render

**E2E tests (Playwright):**
- Full chatbot conversation (type → submit → streaming response → citation visible)
- Drug interaction check (enter 2 drugs → check → interaction result appears)
- Symptom checker session (fill form → 3 turns → results rendered)
- Lab upload (drag file → processing → results visible)
- Language switch (toggle to Arabic → RTL active → text in Arabic)

### 24.3 Coverage Targets

| Layer | Target |
|---|---|
| Utility functions (pure) | 90% |
| Redux slices (reducers) | 85% |
| Component rendering | 75% |
| User interaction flows | 70% |
| E2E critical paths | All 5 modules covered |

---

## 25. Environment Variables (Frontend)

All variables must be prefixed with `VITE_` for Vite to expose them to the client bundle.

```env
# .env.development
VITE_API_BASE_URL=http://localhost:8000/api
VITE_WS_BASE_URL=ws://localhost:8000/ws

# .env.production (GCP)
VITE_API_BASE_URL=https://api.maisys.x/api
VITE_WS_BASE_URL=wss://api.maisys.x/ws

# .env.production (Azure — same values, different deployment)
VITE_API_BASE_URL=https://api.maisys.x/api
VITE_WS_BASE_URL=wss://api.maisys.x/ws

# Feature flags
VITE_ENABLE_BETA=true
VITE_ENABLE_VOICE=true
VITE_ENABLE_VISUALS=true

# Analytics (optional)
VITE_POSTHOG_KEY=phc_...

# Build info
VITE_APP_VERSION=1.0.0
VITE_BUILD_DATE=2025-05-31
```

**Important:** Never put secrets in `VITE_*` variables — they are bundled into the client JavaScript and visible to anyone who inspects the source. API keys live server-side only.

---

## 26. Build and Deployment (Frontend)

### 26.1 Build Command

```bash
npm run build
# → outputs to /dist
# → Vite bundles, tree-shakes, minifies
# → CSS purged (Tailwind removes unused classes)
# → Code split per module page (lazy imports)
```

### 26.2 Dockerfile

```dockerfile
# Build stage
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Serve stage
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### 26.3 nginx.conf

```nginx
server {
  listen 80;
  root /usr/share/nginx/html;
  index index.html;

  # React Router — all non-asset paths serve index.html
  location / {
    try_files $uri $uri/ /index.html;
  }

  # Cache static assets aggressively (hashed filenames)
  location /assets/ {
    expires 1y;
    add_header Cache-Control "public, immutable";
  }

  # No cache for index.html (ensures latest JS loads on deploy)
  location = /index.html {
    add_header Cache-Control "no-cache, no-store, must-revalidate";
  }
}
```

---

*MAISYS Frontend Design Guide — Final Version*
*Covers: Brand Identity (from official guideline) · Design System · Components · Medical UI Patterns · RTL · Dark Mode · All 22 Pages · Redux · WebSocket · API Client · Voice · i18n · File Upload · Error Handling · Performance · Testing · Build*
*Standalone document — does not modify MAISYS Technical Development Guide Parts 1–6.*
