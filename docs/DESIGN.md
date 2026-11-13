# Interface design plan

## Direction

A quiet, precise verification tool for students checking an offer under pressure. The result is the visual anchor; supporting evidence reads like an auditable account ledger. All app surfaces use the supplied dark monochrome palette. White is reserved for the high-risk verdict plate and keyboard focus. The app does not use a UI kit, gradients, shadows, glow, or decorative illustrations.

## Tokens

| Token | Value | Use |
| --- | --- | --- |
| `--obsidian` | `#08090B` | Page background and text on white |
| `--basalt` | `#121418` | Input well, disclosure panels, modal, fields |
| `--graphite` | `#2A2D33` | Hairline borders, quiet verdict outline |
| `--steel` | `#8C9099` | Metadata and secondary copy |
| `--platinum` | `#E6E7EA` | Primary text, manual-review outline |
| `--white` | `#FFFFFF` | High-risk verdict and focus ring only |
| `--radius-control` | `2px` | Inputs and buttons |
| `--radius-verdict` | `4px` | Verdict plate |
| `--font-display` | Instrument Serif | Page titles and verdict only |
| `--font-body` | Hanken Grotesk | All other copy, labels, charts, tables |

No other color values are permitted. Scores and counts use tabular numerals. Body typography scales from 16px to 18px, section titles 20px, page titles 48px desktop / 38px mobile, verdict 38px desktop / 32px mobile. Metadata is 13px. Text labels remain sentence case; no eyebrow headings, all-caps, monospace labels, or numbered stage markers.

Steel on obsidian and basalt measures 6.23:1 and 5.76:1 respectively, above WCAG AA for normal text. Platinum and white exceed AA on both surfaces.

## Screen wireframes

### Check an offer (`/`)

Desktop:
```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Offer shield                         How it works   For placement cells │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│ Check an offer before you pay anything.                                  │
│ We check payment demands, sender details and available company records.  │
│                                                                          │
│ ┌──────────────────────────────────────┐  ┌───────────────────────────┐ │
│ │ Paste offer text                      │  │ Upload PDF, image or .eml │ │
│ │                                       │  │ Original email verifies   │ │
│ │                                       │  │ who sent the offer.       │ │
│ └──────────────────────────────────────┘  └───────────────────────────┘ │
│ Your college's code [                         ]                           │
│ [Check offer]  We don't store your offer or personal details.             │
│ Try a sample: [Company offer] [Government scheme] [Internship offer]      │
└──────────────────────────────────────────────────────────────────────────┘
```
Mobile (360px):
```text
┌──────────────────────────────┐
│ Offer shield       Menu links│
│                              │
│ Check an offer before you    │
│ pay anything.                │
│ Plain-language scope.        │
│ [Paste offer text           ]│
│                              │
│ [Choose PDF, image or .eml  ]│
│ .eml sender-verification tip│
│ Gmail download instructions │
│ [College code              ]│
│ [Check offer               ]│
│ Privacy line                 │
│ Try a sample:                │
│ [Sample] [Sample]            │
└──────────────────────────────┘
```

### Result

Desktop:
```text
┌──────────────────────────────┬───────────────────────────────────────────┐
│ [High risk] 72 / 100         │ Why                                       │
│ completeness                 │ • Risk factors in API order               │
│                              ├───────────────────────────────────────────┤
│ What to do next              │ Evidence ledger                            │
│ • Next action                │ Who sent it             ○ Not enough info  │
│ • Next action                │ Email domain             ✓ Passed         │
│                              │ Company registration    ✕ Failed          │
│ [Report this scam]           │ Payment request         ✕ Failed          │
│ [Check another offer]        │ Reports from students   — Not applicable │
│                              │ [Details expand in place]                 │
│ [Report to police]           │                                           │
└──────────────────────────────┴───────────────────────────────────────────┘
```
Mobile: verdict plate first, then Why, ledger rows with details below their row, next steps, report controls, and complaint summary. Each section spans the content width; there is no card grid. Result uses `aria-live`; rows enter sequentially after the verdict unless reduced motion is enabled.

### Report scam modal

Desktop: centered basalt dialog with selected masked indicators, consent, then submit; success replaces content with withdrawal code. Mobile: near-full-height dialog with vertical scrolling, Escape and close control, focus remains trapped. Each flow step uses plain headings, not progress numbering. Unticking all indicators disables submit. Success code is displayed once and never persisted in browser storage.

### Withdraw report (`/withdraw`)

Desktop/mobile share the focused single-column form: heading, one code input, withdraw button, inline status. Mobile uses full-width controls. Successful copy confirms the report contribution was removed; invalid/used code is explained without exposing report state.

### Dispute (`/dispute`)

Desktop: restrained form with indicator type, value, contact email, reason, and a conditional same-domain verification note for domain disputes; submit and response below. Mobile: same order, one column. Response copy reflects whether a verification link was actually sent and whether scoring continues.

### Placement-cell dashboard (`/dashboard`)

Desktop:
```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Placement cell dashboard                                                │
│ [API key in memory only] [Load dashboard]                                │
│ Counts aren't deduplicated by student.                                    │
│ Results by week                                                          │
│ [Monochrome hand-written SVG chart, 12 weeks, accessible legend]          │
│ Scam categories by week                                                  │
│ [Semantic table: category × week; suppressed values show <5 with tooltip]│
└──────────────────────────────────────────────────────────────────────────┘
```
Mobile: inputs stack; chart preserves a 12-week horizontal viewport with text summary and legend; category table scrolls horizontally inside a labelled region without shrinking text.

### What this checks (`/how-it-works`)

Desktop: editorial single column, wide reading measure, check-by-check explanation, verified/planned distinction, honest limits, privacy design link. Mobile: one column with clear section spacing and no decorative cards.

### Shared navigation and footer

At 1440px, the header spans a centered 1120px content measure. At 390px, it wraps navigation into compact text links without a hamburger dependency. Footer links to withdraw and dispute. Interactive controls always retain a 2px white focus ring with offset.

## Motion and accessibility

Only result arrival is orchestrated: verdict fades in and ledger rows follow at roughly 90ms intervals. Disclosure and modal transitions animate only on activation. `prefers-reduced-motion` removes all transitions. Dialog keyboard handling includes focus trap and Escape. Buttons, links, inputs, rows and file picker have visible 2px white focus outline plus offset. Ledger and dashboard data are semantic tables. Contrast is checked at the supplied steel values above. API result changes are announced in an `aria-live` region.

### Result mobile wireframe

```text
┌──────────────────────────────┐
│ Offer shield         Nav     │
├──────────────────────────────┤
│ [high risk verdict plate]    │
│ 72 / 100, completeness      │
│                              │
│ Why                          │
│ • Risk factor                │
│ • Risk factor                │
│                              │
│ Evidence                     │
│ Who sent it       ○ Not enough│
│   Details expand here        │
│ Email domain     ✓ Passed    │
│ Company record  ✕ Failed     │
│ Payment request ✕ Failed     │
│ Student reports — Not applied│
│                              │
│ What to do next              │
│ • Action                     │
│ [Report scam]                │
│ [Check another offer]        │
│ Police summary, when present │
└──────────────────────────────┘
```

### Report modal wireframes

Desktop:
```text
┌────────────────────────────────────────────┐
│ Choose details to share              Close │
│ ☑ Payment UPI ID       rky.ver•••@ybl       │
│ ☑ Contact phone        +91 ••••••1234       │
│ Untick anything that's yours or unwanted.  │
│ [Continue]                                  │
│                                             │
│ Step 2: consent and Report scam             │
│ Success: one-time withdrawal code and copy  │
└────────────────────────────────────────────┘
```
Mobile:
```text
┌──────────────────────────────┐
│ Choose details to share Close│
│ ☑ Payment UPI ID             │
│   rky.ver•••@ybl             │
│ ☑ Contact phone              │
│   +91 ••••••1234             │
│ Untick anything that's yours │
│ [Continue]                   │
│                              │
│ Consent step scrolls in place│
│ Success code wraps safely    │
└──────────────────────────────┘
```

### Withdraw report (`/withdraw`) wireframes

Desktop:
```text
┌───────────────────────────────────────────┐
│ Withdraw a report                         │
│ Enter the one-time code you saved.        │
│ Withdrawal code [                         ]│
│ [Withdraw report]                         │
│ Inline success or an actionable error     │
└───────────────────────────────────────────┘
```
Mobile:
```text
┌──────────────────────────────┐
│ Withdraw a report            │
│ Enter the one-time code.     │
│ [Withdrawal code            ]│
│ [Withdraw report            ]│
│ Inline status or error       │
└──────────────────────────────┘
```

### Dispute (`/dispute`) wireframes

Desktop:
```text
┌───────────────────────────────────────────┐
│ Dispute an indicator                      │
│ Type [Domain                          v]   │
│ Value [                                  ] │
│ Contact email [                          ] │
│ Same-domain verification note, if needed  │
│ Reason [                                  ]│
│        [                                  ]│
│ [Submit dispute]                           │
│ API response: under review / link sent     │
└───────────────────────────────────────────┘
```

Mobile:
```text
┌──────────────────────────────┐
│ Dispute an indicator         │
│ Plain-language limit         │
│ [Type                      v]│
│ [Indicator value           ] │
│ [Contact email             ] │
│ Domain verification note     │
│ [Reason                    ] │
│ [                           ]│
│ [Submit dispute            ] │
│ API response inline          │
└──────────────────────────────┘
```

### Placement-cell dashboard (`/dashboard`) mobile wireframe

```text
┌──────────────────────────────┐
│ Placement cell dashboard    │
│ [Institution API key        ]│
│ [Load dashboard             ]│
│ Counts aren't deduplicated   │
│ Results by week              │
│ Legend                       │
│ [12-week chart scrolls →    ]│
│ Scam categories by week      │
│ [Table scrolls →            ]│
│ <5 cells have privacy tooltip│
└──────────────────────────────┘
```

### What this checks (`/how-it-works`) wireframes

Desktop:
```text
┌───────────────────────────────────────────┐
│ What this checks                          │
│ Plain-language scope and limitations      │
│ Who sent it                               │
│ Email domain                              │
│ Company registration                      │
│ Payment request                           │
│ Reports from other students               │
│ Verified signals / unavailable checks     │
│ Privacy and limits → privacy design       │
└───────────────────────────────────────────┘
```

Mobile:
```text
┌──────────────────────────────┐
│ What this checks             │
│ Short scope statement        │
│ Who sent it                  │
│ Email domain                 │
│ Company registration         │
│ Payment request              │
│ Reports from other students  │
│ Verified and unavailable     │
│ Privacy and limits           │
│ Read privacy design          │
└──────────────────────────────┘
```

## Self-review

- **Generic centered SaaS hero:** changed to a narrow editorial heading and a functional two-column input/workspace split; no abstract promise badges or decorative art.
- **Generic three-card feature grid:** removed. Result evidence uses an ordered ledger, while guidance and action occupy a separate column.
- **Default colorful risk chart:** replaced with monochrome fills/patterns, explicit labels, and a legend so no meaning depends on color.
- **Template eyebrow labels and uppercase microcopy:** excluded; section titles are sentence case and directly describe their contents.
- **Generic icon decoration:** excluded. The evidence glyphs carry explicit words and status labels, not decorative icons.
- **Drop-shadow modal and glossy panels:** excluded; surfaces rely on basalt and hairline borders only.
- **Overloaded mobile dashboard:** chart scrolls as a labelled region, while form controls and key explanation remain readable at 360px.
