# UI / UX improvement plan: Care Finder app

> Agent plan for Claude Code or Codex. Scope: `app/frontend/` only.
> Read `CLAUDE.md` and `interface_build_plan.md` first. Update the **Status** table at the end when a phase is done.
> Branch: `feature/ui-polish` (make it from the current default branch).

## 0. Rules for the agent

1. Change only `app/frontend/` and `app/package.json` (plus the lockfile). Do not touch `app/backend/`, `src/`, `notebooks/`, `databricks.yml` or `workspace.datathon`.
2. Do not change the API contract in `app/backend/schema.py`. The UI reads those shapes as they are.
3. Do not remove any interpretability content (score breakdown, verbatim quotes, rejected evidence, caveats, sources, "How we score", the double-checks). You may change how it looks and where it sits. You may not hide it for good. The judges look for it.
4. The build runs on Databricks Apps (`npm install` then `npm run build`). Pin every new dependency to an exact version. Commit `package-lock.json`.
5. Ask the user before you pick any item in section 2. Use the recommended default only if the user says "use defaults".
6. Make one commit per phase. Run `npm run build` before each commit. It must pass.
7. Add `prefers-reduced-motion` support in Phase 1, before any animation. Every animation must respect it.
8. No bounce, no overshoot, no decorative motion. Motion must show a change of state or a cause and effect.
9. Write copy in plain, short sentences. No em dashes. No exclamation marks. No hype words.

## 1. What the app looks like now (audit)

Stack: React 18.3.1, Vite 5, Leaflet. About 1,400 lines in total. One stylesheet (`src/styles.css`, 279 lines). No UI library. No animation library. No icon library. No tests.

Layout: a top bar, then a two-column grid. The left column (54vw, max 860px) holds the input panel (tabs: Search, Chat, Voice), a summary, and result cards. The right column is the Leaflet map. A second view, "District planner", is a table.

Problems found, with the files where they are:

| # | Finding | Where |
|---|---|---|
| A1 | Emoji and text glyphs are used as icons: `✚ 📍 🎤 🔊 📞 💡 💬 🛡 ⚠ ✓ ✗ ▸ ▾ ▴ ⓘ ✉`. They render differently on each OS and do not share one stroke or size. | `App.jsx`, `ResultCard.jsx`, `SearchForm.jsx`, `ChatPanel.jsx`, `HowWeScore.jsx`, `styles.css` (`::before '▸'`) |
| A2 | Each result card stacks up to 4 badges (confidence, confirmed by phone, closest option, location score). Then 3 stat tiles, then up to 5 tinted call-out boxes (trade-off, pick strength, tip, heads-up, ask). Everything has a colour, so nothing is first. | `ResultCard.jsx` (`.badges`, `.stats`, `.tradeoff`, `.pick`, `.tip`, `.heads-up`, `.ask`) |
| A3 | All 5 cards have the same size and weight. Rank 1 is the main answer but looks like rank 5. | `App.jsx` `.cards`, `ResultCard.jsx` |
| A4 | The accent blue (`--accent`) is used for tabs, links, chips, rank circles, field tags, claim tags, the trade-off box, the slider, the primary button and the selected ring. Blue marks too many things to mark the one action. | `styles.css` |
| A5 | Tokens exist for colour only. Radius values (14, 10, 9, 8, 6, 5, 4, 3, 999), font sizes (11, 11.5, 12, 12.5, 13, 13.5, 14, 15, 18, 19, 20, 21, 26) and spacing are typed by hand in each rule. Map colours (`#2563eb`, `#f59e0b`, `#111827`) are hard-coded in JS. | `styles.css`, `ResultsMap.jsx` |
| A6 | Small, light text: `.meta` 11px, `.claim` 11.5px, `.field` 11.5px, `.vbtn` 12px, all in `--muted` or in a tint on a tint. `--muted` on `--bg` is about 4.6:1 (light mode). That is close to the limit and fails at small sizes in practice. | `styles.css` |
| A7 | No `text-wrap`. Long facility names and the summary headline break badly. | `h2`, `h3` rules |
| A8 | Numbers do not align in the planner table and in the card stats. No `font-variant-numeric`. | `.planner-table`, `.stat-value` |
| A9 | `font-style: italic` is used for the "Searching…" bubble. `code, .mono` is used for the plain-text explanation and one phrase in "How we score". | `.typing`, `.mono`, `HowWeScore.jsx` |
| A10 | `window.prompt` and `alert` are used for the Confirm / Reject notes, location errors and microphone errors. They block the page and break the look. | `ResultCard.jsx` `recordVerification`, `SearchForm.jsx`, `ChatPanel.jsx` |
| A11 | Native `<select>`, `<datalist>`, `<input type=range>` and `<input type=checkbox>`. They cannot take part in motion or in the design system. | `SearchForm.jsx`, `Planner.jsx`, `ChatPanel.jsx` |
| A12 | Loading states are partial. Results have a generic grey shimmer block (200px) that does not match a card. The service list, the place list, the planner, the "use my location" button and the Confirm / Reject refresh show nothing while they wait. | `App.jsx`, `SearchForm.jsx`, `ResultCard.jsx` |
| A13 | The empty state is two lines of text. It does not show what a result looks like. | `App.jsx` `.empty` |
| A14 | Headlines are generic: "5 best options for Dialysis", "Choose the care you need and where you are", "Things to double-check", "Does the location add up?". | `App.jsx`, `ResultCard.jsx` |
| A15 | Redundant labels: the "Quality score" stat and the score breakdown repeat the same number. "Address:" prefix. The tagline under the logo. "Care needed" and "Your location" repeat the placeholder. The sub-text in the planner repeats the heading. | `ResultCard.jsx`, `App.jsx`, `SearchForm.jsx` |
| A16 | Embellishments: card shadow, 3px glow ring on a selected card, left border on the safety alert, emoji prefixes, gradient shimmer, infinite pulse on the mic, a drop shadow on map pins, a filled square tile behind the logo glyph. | `styles.css` |
| A17 | Two primary-button classes (`.primary` and `.primary-btn`) with different padding. Every card has a full "Call" button, so no button is first. | `styles.css`, `ResultCard.jsx` |
| A18 | Nested boxes. Card, then stat tile, then meter. Radius 14 with 18-20px padding, then tiles at radius 10 inside. The inner radius does not follow the outer radius. | `.card`, `.stat`, `.tabs`, `.row` |
| A19 | No motion except: a 0.15s border colour change, a `<details>` chevron turn, the shimmer and the mic pulse. Cards, details, tabs and results appear with no transition. | `styles.css` |

## 2. Decisions to ask the user first

Ask these in one `AskUserQuestion` (or one chat message). Do not guess.

| # | Decision | Recommended default |
|---|---|---|
| Q1 | Accent colour. Keep the blue hue, or pick a new one (for example a teal for care)? The accent must mark only the primary action, the focus ring and the selected state. | Keep a blue hue, but make it the only saturated colour on the page. Everything else is neutral. |
| Q2 | Icon set. | `lucide-react` 1.77.0 (one stroke width, 1.75, one size scale: 16 and 20) |
| Q3 | Motion library. `layoutId`, exit animations and shared elements need one. | `motion` 14.14.0 (`import { motion, AnimatePresence } from 'motion/react'`) |
| Q4 | Headless components for select, combobox, popover, tooltip, slider, switch. | Radix: `@radix-ui/react-select` 2.4.1, `-popover` 1.3.1, `-tooltip` 1.4.1, `-slider` 1.6.1, `-switch` 1.4.1, `-dialog` 1.3.1. Place box: `cmdk` 1.1.1 inside a Popover. Toasts: `sonner` 2.0.8. |
| Q5 | Rank 1 as the hero card, with ranks 2 to 5 as compact rows that expand? This changes the page structure. | Yes. |
| Q6 | Map tiles. OSM tiles are busy and clash with a calm UI. Keep them, or use a muted tile style? | Keep OSM for now. Tone it down with a CSS filter only. |

## 3. Phases

Each task lists the item numbers it covers from the user's list. Item codes are in section 5.

### Phase 1. Foundation: design system, tokens, type (V5, V3, V4, V15, V16, V18, V14, V12)

1. Create `src/styles/tokens.css` and import it before `styles.css`. Move all `:root` values there. Add scales:
   - Space: `--s-1: 4px; --s-2: 8px; --s-3: 12px; --s-4: 16px; --s-5: 24px; --s-6: 32px; --s-7: 48px`.
   - Type (px, with line height): 12/16, 13/18, 14/20, 16/24, 20/28, 28/34. Use these six only. Remove 11, 11.5, 12.5, 13.5, 15, 18, 19, 21, 26.
   - Radius: `--r-sm: 6px; --r-md: 10px; --r-lg: 16px; --r-pill: 999px`.
   - Elevation: none by default. One token, `--shadow-pop`, for popovers only.
   - Motion tokens (see section 4).
   - Map colours as CSS variables. Read them in `ResultsMap.jsx` with `getComputedStyle`, so there are no hex values in JS.
2. Inner radius rule (V14). For any rounded box inside a rounded box, set `inner radius = outer radius - padding`, with a floor of 4px. Write it as a CSS rule: `--r-inner: max(4px, calc(var(--r-outer) - var(--pad)))`. Apply it to the tab group and its active pill, the place input with the "use my location" button, the stat or meter blocks inside a card, the segmented controls and the chips in the input row.
3. Text contrast (V15). Write `scripts/check-contrast.mjs` (no dependency) that reads the token pairs and prints the ratio for light and dark mode. Rules: body and small text at least 4.5:1, text of 18px or more at least 3:1, UI borders and icons at least 3:1. Raise `--muted` until all text pairs pass at 12px. Remove the "tint on a tint" pairs (`.claim`, `.field`) or darken their text. Minimum text size is 12px.
4. Tabular numbers (V18). Add `font-variant-numeric: tabular-nums` to `.stat-value`, `.formula .big`, the planner table cells, the slider value, the travel and km text and the map legend. Right-align numeric planner columns. The user wrote "tabular names". This plan reads it as tabular numerals. Say so in the commit message.
5. Unitalicize (V3). Remove `font-style: italic` from `.typing`. Use a skeleton or a dot loader instead. Check that no `<em>`, `<i>` or `<q>` rule gives italics by accident.
6. Mono only when needed (V4). Keep mono only for raw machine strings: the regex `match_pattern`, the `rec.how` text and table names. Remove `code` from the prose in `HowWeScore.jsx`. Remove `.mono` from everything else.
7. Headline wrap (V16). Add `text-wrap: balance` to `h1, h2, h3` and to card titles. Add `text-wrap: pretty` to paragraphs in cards and in the details. Add `overflow-wrap: anywhere` to facility names and URLs. Test with the longest facility name in the data.
8. Icons (V12). Install the icon set. Create `src/components/Icon.jsx` that wraps it with fixed sizes (16 and 20) and stroke width. Replace every emoji and glyph listed in A1. Replace the `::before '▸'` with a chevron icon that turns. Use `aria-hidden` on icons that sit next to a text label. Add `aria-label` on icon-only buttons.
9. Build the components that other phases need, in `src/components/ui/`: `Button` (primary, secondary, ghost, danger; sizes md and sm), `Badge` (neutral, success, warning, danger), `Tabs`, `Select`, `Combobox`, `Slider`, `Switch`, `Popover`, `Tooltip`, `Dialog`, `Skeleton`, `Toast`. Delete the old `.primary`, `.primary-btn`, `.ghost`, `.btn`, `.chip`, `.vbtn` classes when no code uses them.
10. Add `prefers-reduced-motion` handling: a `useReducedMotion` hook from the motion library, plus a CSS media query that sets all token durations to 0.01ms.
11. Add visible `:focus-visible` rings on every control (2px, accent, 2px offset).

Done when: `npm run build` passes, contrast script passes, no emoji or glyph icons are left (`grep -nP '[\x{2600}-\x{27BF}\x{1F300}-\x{1FAFF}\x{25B4}\x{25B8}\x{25BE}\x{24D8}]' app/frontend/src` returns nothing), no hex colour in any `.jsx`.

### Phase 2. Visual hierarchy and copy (V1, V2, V7, V8, V9, V10, V11, V13, V17)

1. Remove filler badges (V1). Keep at most **two** signals on the front of a card:
   - Confidence (High, Medium, Likely, Unconfirmed). One badge.
   - One caution, only if it changes what the user does (for example "Reported unavailable"). Show it as text with an icon, not as a coloured pill.
   Move "Closest option", "Confirmed by phone" and the location score into the details, or into one line of plain text under the name (for example "Confirmed by phone"). A location score of 5/5 is not news. Show the location badge only when the score is below 5.
2. Drop redundant labels (V2). Remove: the tagline under the logo (keep the name only, or one short line), the "Address:" prefix, the "Quality score" stat when the breakdown shows it (keep one number, in the hero), the planner sub-text that repeats the heading (shorten to one line, move the long method note to a "How this works" popover), and "Care needed" or "Your location" labels if the field is self-evident. Keep labels that screen readers need (use `aria-label` or visually hidden text).
3. Enlarge the main feature (V7). Rank 1 becomes a hero card (Q5):
   - Larger name (the 20/28 step), the travel time as the largest number on the card, and the Call button as a large primary button.
   - Ranks 2 to 5 are compact rows: rank, name, confidence, travel time, a small Call icon button, an expand chevron. Expanding a row shows what the card shows today.
   - The list needs less width after this change, so give the map more. Test `grid-template-columns: minmax(480px, 44vw) 1fr`.
4. Group with spacing (V8). Remove the boxes around groups. Use the space scale and a thin divider line where a group needs a break. Target for a card: no more than **two** tinted boxes on the front. Fold "Pick strength", "Tip" and "Before you go" into one "Before you decide" block that uses one background, with a short heading and a list. Keep the double-checks inside a `Popover` or the details, not inline on the front.
5. Specific headlines (V9). Rewrite:
   - Summary: "5 dialysis centres within 75 km of Jaipur" (use `service_label`, `max_km`, `origin.label`). For no results: "No dialysis centres within 75 km of Jaipur". Add one action: "Search up to 150 km".
   - Empty state: see Phase 3 (it shows the product).
   - Detail section titles: "What their record says" (keep), "Exact quotes from the record" (keep), "Things to double-check" becomes "What could be wrong with this record", "Does the location add up?" becomes "Do the pincode, city and map point agree?".
   - Planner heading: "Districts with no quality facility in reach" (use the live count).
6. Emphasize the CTA (V10, V11). Define a clear order of action weight:
   1. **Primary** (accent fill): "Find facilities" in the form, and "Call" on the hero card only.
   2. **Secondary** (outline): "Call" on ranks 2 to 5 (icon plus number on hover), "Directions", "Website".
   3. **Tertiary** (text): "Details", "How we score", "Hide".
   The accent colour is used for: the primary button, the focus ring, the selected state (tab, selected card, selected pin) and links in running text. Nothing else. Rank circles, field tags and claim tags become neutral. Confidence and status colours (green, amber, red) stay, and only on the confidence badge, the status icons and the score bar.
7. Remove embellishments (V13). Remove: card shadow (use a 1px border), the 3px glow ring (use a 1px accent border and a 2px left rule, or only the accent border), the left border on `.alert.safety` (use an icon and a tinted background), the infinite mic pulse (use a static recording state plus a small level indicator), the pin drop shadow, the shimmer gradient (use a flat pulse, see Phase 3), emoji prefixes, the filled square logo tile (use the wordmark and one icon).
8. Align by eye (V17). Do an optical pass in the browser, at 100% and at 200% zoom:
   - Rank number: centre the digit on the cap height of the first line of the name, not on the box. Nudge with `translateY` if needed. The digit `1` is narrower than `4`, so test all five.
   - Icon plus label buttons: icons sit on the x-height centre of the label, not the line box. Use `gap` and a 1px nudge on icons that look high or low.
   - Play, chevron and arrow glyphs look off-centre when centred mathematically. Shift them by 1px toward their visual centre.
   - The stat columns: align the baselines of the large numbers and of the small unit text (`of 100`, `min`).
   - The map pin digit: centre it optically in the circle.
   Add a comment `/* optical: ... */` at each nudge, so nobody removes it later.

Done when: a card front, at 100% zoom, has one primary action in the hero and one badge plus one caution at most; a screenshot at 1440 px shows a clear first read (the hero card and its Call button).

### Phase 3. Real states: loading, empty, errors, feedback (V6, V19, V20)

1. Show the actual product (V6). Replace the empty state with the real thing:
   - On first load, run one demo search (`dialysis`, `Jaipur`) from a "Try an example" button and also show a **static sample hero card** built from a fixed fixture in `src/fixtures/sampleRecommendation.js` that follows the `Recommendation` shape. Label it "Example result". Do not show it as real data. Do not call it a recommendation. Replace it when a real search runs.
   - Show the map zoomed on India with the 3 example chips as pins, or the sample pin. The map must not be a blank grey area.
   - Remove the placeholder paragraph.
2. Loading states (V19). Add one for every wait:
   - Results: skeleton cards that match the real layout (one hero skeleton, four row skeletons). Use a flat opacity pulse (1s, `ease-in-out`), no gradient sweep. Keep the form visible.
   - Services and places: the `Select` shows a disabled "Loading care types" state. The place combobox shows a small spinner when it has no list yet.
   - Search button: the label stays, a spinner icon crossfades in (see M18), and the button keeps its width.
   - "Use my location": spinner while it waits for the browser.
   - Chat: replace the italic "Searching…" with three dots. Keep the bubble size stable.
   - Planner: a table skeleton with the same column widths.
   - Re-run after Confirm / Reject (`refresh()` in `App.jsx`): dim the list to 0.6 opacity and show a thin progress line at the top of the list. Do not clear the cards.
   - Map: a skeleton overlay until the first tile loads.
3. Replace blocking dialogs (A10):
   - `window.prompt` in `recordVerification`: use a `Popover` anchored to the Confirm or Reject button. Fields: optional note (textarea), Save, Cancel. Save shows a spinner, then closes.
   - `alert` for location and microphone errors: use an inline message under the field, or a toast.
   - Add a toast region (`sonner`) for success and for errors that do not belong to one field.
4. Animate useful feedback (V20). Only these events get feedback:
   - Search submit: button press (M4), loading state, results enter (M1, M3).
   - Confirm or Reject saved: the badge changes and pulses once (M8), and a toast says what was saved.
   - Card selected from the map or the list: the other side scrolls to it and highlights it (shared highlight, M20).
   - Copy or call: no animation needed.
   - Errors: the field shakes **no**. Use a colour change and a message. No shake.
5. Error and edge states with real copy and one next action each: API error ("We could not reach the search service. Try again."), no results (offer to widen the radius, which is the open todo in `interface_build_plan.md` phase 7), geolocation denied, microphone not supported (already there, restyle), speech error.

Done when: every network call in `api.js` has a visible waiting state, there is no `prompt(` or `alert(` left in `src/`, and the first screen shows a sample of the real card and the map.

### Phase 4. Motion system (M1 to M20)

Use the tokens in section 4. Build motion as small reusable pieces in `src/motion/`: `presets.js` (variants and transitions), `Stagger.jsx`, `Reveal.jsx` (mask reveal), `IconSwap.jsx` (crossfade with blur), `useReducedMotion` wrapper. Keep CSS transitions for simple hover and press. Use the motion library for exits, layout and shared elements.

| Code | Task | Where in this app |
|---|---|---|
| M1 | Entrances use ease-out. Token `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`. Enter from 8px below and opacity 0, 220ms. | Result cards, details panel, toasts, summary |
| M2 | Dropdowns open in 150 to 250 ms. Select and place list: 180ms. Popovers: 160ms. | `Select`, `Combobox`, `Popover`, `Tooltip` |
| M3 | Stagger lists by 30ms. Cap the total at 150ms (cards 1 to 5, then the rest at once). | Result cards, compact rows, chat history on load, planner rows (first 10 only) |
| M4 | Scale to 0.97 on press, 100ms, ease-out, release 160ms. Use `:active` for CSS, `whileTap` in motion. | All `Button`, `Tab`, chips, the mic, card rows |
| M5 | Stretch moving knobs by 12% along the move axis while moving or held. | Slider thumb (radius), Switch knob (Government only, Read aloud). Thumb width 20px grows to about 22.4px while pressed. |
| M6 | Stagger as details settle. The sections in an opened card enter one after another, 30ms apart, each 6px up and opacity 0 to 1. | `ResultCard` details sections |
| M7 | Arcs for movement. Use a curved path only when an object travels between two points that are not on one axis. Case 1: the map camera (keep `flyTo`, set `duration: 0.8`, `easeLinearity: 0.25`). Case 2 (optional): an example chip value moving into the form fields. Do not add arcs elsewhere. | `ResultsMap.jsx`, `SearchForm.jsx` |
| M8 | Pulse once to confirm success. One ring pulse (scale 1 to 1.04 and back, 280ms) on the "Confirmed by phone" badge, then a toast. Not a loop. | `ResultCard` verification |
| M9 | Ease-in-out for moves. Elements that move on screen use `cubic-bezier(0.65, 0, 0.35, 1)`, 280ms. | Tab indicator, selection highlight, reordered cards after refresh, layout shifts |
| M10 | Popovers start at scale 0.95 and opacity 0. | `Popover`, `Tooltip`, `Select` list, `Combobox` list, Leaflet popup (CSS) |
| M11 | Enter from the trigger. Set `transform-origin` to the trigger point. Radix exposes `--radix-popover-content-transform-origin`, `--radix-select-content-transform-origin` and `--radix-tooltip-content-transform-origin`. | Same as M10 |
| M12 | Exit to the trigger. Same origin, scale back to 0.95. | Same as M10 |
| M13 | No bounce on everyday UI. All springs use `bounce: 0` or no spring at all. No overshoot curves. A lint check: `grep -n "bounce\|overshoot\|cubic-bezier(.*1\.[0-9]" app/frontend/src` must show only `bounce: 0`. | Whole app |
| M14 | Do not tween while held. While a pointer holds a slider thumb, set `transition: none` and follow the pointer 1:1. Apply tweens only on release. Same for the Leaflet map (already native) and any drag. | `Slider`, `Switch` while pressed |
| M15 | Exits are 20% shorter than entrances. Token: `--dur-exit: calc(var(--dur-enter) * 0.8)`. Example: enter 220ms, exit 176ms. | All exit transitions |
| M16 | Overlap old and new states. Use `AnimatePresence mode="popLayout"` so the old content leaves while the new content enters. Do not wait for the exit to end. | Result list on a new search, Search / Chat / Voice panel swap, summary text, details open and close |
| M17 | Mask for reveals and colour. Reveal with `clip-path: inset()` or a `mask-image` gradient, not with height tweens. Apply to: the score bar and the meters (reveal left to right, 400ms, ease-out, once per card on first view), the details panel open, the tab underline colour change. | `ScoreBreakdown`, `.meter`, `ResultCard`, `Tabs` |
| M18 | Crossfade icons with blur. Icon swap: old icon goes to opacity 0, scale 0.8, blur 4px, new icon comes from the same state, 150ms, overlapped. | Mic and stop, chevron open and close, Search button and its spinner, speaker and stop, Send and its spinner, copy and check |
| M19 | Rubber band past bounds. The slider thumb moves past the 10 and 300 km ends with resistance (about 0.3 of the pointer delta) and returns on release (ease-out, 200ms). On touch, apply `overscroll-behavior: contain` to the results list and the chat list, and let the page rubber band. | `Slider`, lists |
| M20 | Reuse the same `layoutId`. `layoutId="tab-underline-input"` for Search, Chat and Voice. `layoutId="tab-underline-view"` for Find care and District planner. `layoutId="card-selection"` for the selected-card highlight so it slides between cards. `layoutId={`rank-${id}`}` for the rank badge if a card moves between hero and row after a refresh. | `Tabs`, `ResultCard` list |

Done when: every row above has code or a written reason in `docs/motion-notes.md` for why it does not apply. Reduced-motion mode shows no movement, only instant state changes. All motion values come from tokens.

### Phase 5. Responsive and polish gate (V21)

"Make beautiful design" is not testable as written. This phase turns it into a checklist.

1. Take screenshots with the browser tool at 1440, 1024 and 390 px wide, in light and dark, for: empty state, loading, 5 results, a card with details open, an error, chat with a long answer, voice, planner. Save to `app/frontend/screenshots/` (add to `.gitignore`).
2. Compare each against the checklist:
   - One clear first read per screen.
   - At most two font weights and six sizes in use.
   - All spacing is on the scale.
   - Nothing smaller than 12px.
   - Contrast script passes.
   - No element touches the screen edge without padding at 390 px. Tap targets are at least 40px.
   - The map and the list never fight for width. On mobile, the map becomes a collapsible panel above the list (it is a fixed 320px block now).
3. Fix every item the checklist finds. Then do a last read of the whole UI, as if it is new, and remove anything that does not earn its place.
4. Run the keyboard path: Tab through the form, open the Select, pick, Tab to the slider, use the arrow keys, submit, move to a card, expand it. Fix every trap.
5. Update `app/README.md` (one short "UI conventions" section) and the status table in `interface_build_plan.md`.

## 4. Motion tokens (put these in `tokens.css` and mirror them in `src/motion/presets.js`)

```css
:root {
  --ease-out:    cubic-bezier(0.23, 1, 0.32, 1);   /* entrances, press release */
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);   /* moves, layout */
  --ease-in:     cubic-bezier(0.64, 0, 0.78, 0);   /* exits only if needed */

  --dur-press:   100ms;
  --dur-fast:    150ms;   /* icon swap, tooltip */
  --dur-enter:   220ms;   /* cards, details, popovers (160 to 250) */
  --dur-move:    280ms;   /* layout moves, shared elements */
  --dur-exit:    calc(var(--dur-enter) * 0.8);   /* 176ms: 20% shorter */
  --dur-reveal:  400ms;   /* score bar mask reveal */
  --stagger:     30ms;    /* max total 150ms */

  --press-scale: 0.97;
  --pop-scale:   0.95;
  --stretch:     1.12;    /* moving knobs */
}
@media (prefers-reduced-motion: reduce) {
  :root { --dur-press: .01ms; --dur-fast: .01ms; --dur-enter: .01ms; --dur-move: .01ms; --dur-reveal: .01ms; --stagger: 0ms; }
}
```

Rules: animate only `transform`, `opacity`, `filter` and `clip-path`. Do not animate `height`, `width`, `top` or `left`. Add `will-change` only during the animation. Never run more than one infinite animation on a page (the skeleton pulse is the only one).

## 5. Coverage of the 41 items

| Code | Item from the list | Phase |
|---|---|---|
| V1 | Remove filler badges | 2 |
| V2 | Drop redundant labels | 2 |
| V3 | Unitalicize random words | 1 |
| V4 | Mono only when needed | 1 |
| V5 | Use a design system | 1 |
| V6 | Show the actual product | 3 |
| V7 | Enlarge the main feature | 2 |
| V8 | Group with spacing | 2 |
| V9 | Make headlines specific | 2 |
| V10 | Emphasize the CTA | 2 |
| V11 | Add an accent colour | 2 (decision Q1) |
| V12 | Keep icons consistent | 1 |
| V13 | Remove embellishments | 2 |
| V14 | Inner radius = outer - padding | 1 |
| V15 | Improve the text contrast | 1 |
| V16 | Wrap headlines properly | 1 |
| V17 | Align by eye, not pixels | 2 |
| V18 | Use tabular names (numbers) | 1 |
| V19 | Add loading states | 3 |
| V20 | Animate useful feedback | 3 |
| V21 | Make beautiful design | 5 |
| M1 | Ease-out for entrances | 4 |
| M2 | Dropdowns at 150 to 250 ms | 4 |
| M3 | Stagger lists by 30ms | 4 |
| M4 | Scale to 0.97 on press | 4 |
| M5 | Stretch moving knobs by 12% | 4 |
| M6 | Stagger as details settle | 4 |
| M7 | Arcs for object movement | 4 |
| M8 | Pulse to confirm success | 4 |
| M9 | Ease in out for moves | 4 |
| M10 | Start popovers at 0.95 | 4 |
| M11 | Enter from the trigger | 4 |
| M12 | Exit to the trigger | 4 |
| M13 | No bounce on everyday UI | 4 |
| M14 | Do not tween while held | 4 |
| M15 | Make exits 20% shorter | 4 |
| M16 | Overlap old and new states | 4 |
| M17 | Mask for reveals and colour | 4 |
| M18 | Crossfade icons plus blur | 4 |
| M19 | Rubber band past bounds | 4 |
| M20 | Reuse the same layoutId | 4 |

## 6. File map (expected new files)

```
app/frontend/src/
  styles/tokens.css
  styles/base.css            (reset, type, focus ring)
  components/Icon.jsx
  components/ui/             Button, Badge, Tabs, Select, Combobox, Slider, Switch, Popover, Tooltip, Dialog, Skeleton, Toast
  components/ResultHero.jsx  (rank 1)
  components/ResultRow.jsx   (ranks 2 to 5)
  motion/presets.js, Stagger.jsx, Reveal.jsx, IconSwap.jsx
  fixtures/sampleRecommendation.js
app/frontend/scripts/check-contrast.mjs
app/docs/motion-notes.md     (only for items that do not apply)
```

`ResultCard.jsx` (440 lines) is the biggest file. Split it as part of Phase 2: `ResultHero`, `ResultRow`, and one file per detail section (`Checklist`, `Quotes`, `PickStrength`, `LocationChecks`). Keep the logic (`rankReason`, `HEADS_UP`, `recordVerification`) unchanged. Move it, do not rewrite it.

## 7. Verification (run at the end of every phase)

```bash
cd app
npm install
npm run build                        # must pass
node frontend/scripts/check-contrast.mjs   # from Phase 1 on
npm run dev                          # UI on :5173, API proxy to :8000 (needs the backend running, see app/README.md)
```

If the backend cannot run (no Databricks login), add a mock server mode: `VITE_MOCK=1` makes `api.js` return the fixture and a short fake delay. This lets you test loading and empty states without data. Do not ship the mock path in the production build (guard it with `import.meta.env.DEV`).

## 8. Status

| Phase | Piece | Status |
|---|---|---|
| 1 | Foundation: tokens, type, icons, UI components, contrast | done |
| 2 | Hierarchy and copy | done |
| 3 | Real states and feedback | done |
| 4 | Motion system | done |
| 5 | Responsive and polish gate | done |

---

## Agent prompt (paste this into Claude Code or Codex)

```
Read CLAUDE.md, interface_build_plan.md and ui_ux_improvement_plan.md in the repo root.

Your task: carry out ui_ux_improvement_plan.md for the Care Finder app in app/frontend/.

Start with section 2. Ask me the 6 decisions in one message. Wait for my answers.
Then work phase by phase (1 to 5). For each phase:
  1. Do the tasks in the plan.
  2. Run npm run build and the contrast script. Fix all errors.
  3. Take screenshots of the changed screens (light and dark, 1440 and 390 px wide).
  4. Make one commit on the branch feature/ui-polish.
  5. Update the Status table. Tell me what changed in 5 lines or less, then continue.

Hard rules:
  - Change only app/frontend/ and app/package.json (and the lockfile).
  - Do not change app/backend/, the API contract or any interpretability content.
  - Pin new dependencies to exact versions.
  - Respect prefers-reduced-motion. Use the motion tokens in section 4. No bounce.
  - If a plan item does not fit the app, say why in app/docs/motion-notes.md. Do not skip it silently.
  - No em dashes and no exclamation marks in UI copy.
```