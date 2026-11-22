# Motion notes

Where each motion item (M1 to M20 in `uiux-improvement-plan.md`) lives, and why some do not apply in full.
Every duration and curve comes from `frontend/src/styles/tokens.css`, mirrored in `frontend/src/motion/presets.js`.
With reduced motion on, the CSS tokens drop to 0.01ms and `usePresets()` returns `{ duration: 0 }`, so every change is instant.

| Code | Where | Notes |
|---|---|---|
| M1 | `presets.enter` / `item`: summary, hero, rows, chat messages. Toasts get the token curve via CSS. | sonner animates its own toasts. We only set its duration and curve. |
| M2 | CSS `pop-in`: select list and place list 180ms, popovers 160ms, tooltips 150ms. | |
| M3 | `StaggerItem` (hero + 4 rows), chat history on mount, planner rows 1 to 10 (CSS). | Delay is `min(i, 4) × 30ms`, so the most is 120ms. On load the chat holds only the greeting, so history has little to stagger. New messages enter one at a time with M1. |
| M4 | CSS `:active` on `.btn`, `.tab`, `.icon-btn`, `.mic`, `.select-trigger`, `.row-head`. | Full-width rows scale to 0.99, not 0.97. At 0.97 a 600px row moves each edge by 9px, which reads as a jump, not a press. |
| M5 | Slider thumb `scaleX(var(--stretch))` while held. Switch knob stretches toward its next side while pressed. | |
| M6 | `ResultDetails` wraps each section in `presets.settle(i)`, 30ms apart, 6px up. | |
| M7 | `ResultsMap` `flyTo` with `duration: 0.8, easeLinearity: 0.25` (Leaflet zooms out, pans, zooms in). | Case 2 (an example chip value moving into the form fields) is not built. The chips sit right under the fields and the search starts on click. An arc would add travel time and show nothing new. |
| M8 | `ConfirmedSignal` in `result/CardFront.jsx`: one scale pulse (1 to 1.04 to 1, 280ms) when a phone confirmation was just saved, plus the toast. | It does not pulse on later renders or fresh searches. |
| M9 | `presets.move` (ease-in-out, 280ms) on the tab underline, the selection ring, rank badges and row position changes after a refresh. | |
| M10 to M12 | `transform-origin` from the `--radix-*-content-transform-origin` variables. Open from 0.95, close back to the trigger at 0.8 of the open duration. Leaflet popups pop from their tip. | Leaflet owns the popup's outer transform, so the animation is on `.leaflet-popup-content-wrapper`. Popups have no exit animation, because Leaflet removes the node at once. |
| M13 | No springs anywhere. All curves are the three token beziers, none passes 1. `grep -n "bounce\|overshoot\|cubic-bezier(.*1\.[0-9]" app/frontend/src` returns nothing. | |
| M14 | Radix sets the slider position directly, and the thumb has no position transition. Only the stretch and the rubber-band pull tween. | The switch knob only stretches while pressed. It moves on release, so nothing follows a held pointer. Leaflet drag is native. |
| M15 | `--dur-exit = enter × 0.8`, `DUR.exit` in JS, and `--dur-pop-exit` / `--dur-list-exit` for pop surfaces. | |
| M16 | `AnimatePresence mode="popLayout"` on the Search/Chat/Voice panel, the summary, skeleton/results/example, the row body and the details panel. | |
| M17 | `Reveal` (clip-path, left to right, 400ms) on the quality bar and the key-items meter. The details panel and row body open with a top-down clip-path mask. | The reveal runs on mount, not with `whileInView`: inside the scrolling list column the observer never fired. Cards mount when first shown, so the effect is the same. The tab underline has one colour and slides (M20), so there is no colour change to mask. |
| M18 | `IconSwap` on: mic and stop (chat and voice), row chevron, Details chevron, Search and Send spinners (all `Button` spinners). | No stop control exists for "Read aloud", and the app has no copy action, so those two pairs have nothing to swap. |
| M19 | Slider: past either end the thumb follows 0.3 of the pointer (16px at most) and returns on release (200ms ease-out). `overscroll-behavior: contain` on the results column, the chat list and the place list. | |
| M20 | `tab-underline-input`, `tab-underline-view`, `card-selection` (one ring that slides between hero and rows), `rank-${id}`. | |

## Infinite animations

The plan allows one infinite animation per page (the skeleton pulse). The plan also asks for spinners in the
Search button and the place field, three dots in chat and a progress line on refresh. We read the rule as one
looping indicator per wait: each wait shows a single indicator, or a spinner together with the skeleton for the
same search. Nothing loops while the page is idle. With reduced motion, loops run once and stop.
