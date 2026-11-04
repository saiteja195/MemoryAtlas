# Web App

React 18 + TypeScript + Vite, with Cytoscape for the graph. Source: `frontend/src/`.

## Pages

| Page | What it shows |
|---|---|
| **Atlas** | The memory graph (entities are nodes, claims are edges), a timeline scrubber, an **Ask** panel, and a side panel with **Facts** and **Consent** tabs |
| **Dashboard** | What the models processed (counts only), day coverage, a tracked to-do list, facts by kind, who and what is mentioned most, and what Muse is not sure about |

Everyone signs in with a name and a passcode and gets a **private Atlas** (its own database). There is no email and no passcode reset. Demo profiles hold only demo content and can be reset from **Settings**. **Settings** also lets you delete your profile.

## Reading the graph

- Edge style says how well a claim is evidenced: solid for direct observation, dashed for inferred, and a mark for a user-confirmed correction.
- Colour says where a fact came from: photo, conversation, calendar, several sources (shown as "×N"), or inferred.
- Superseded claims are greyed with a clock mark, because history is kept.
- Every fact in the picture is also in the **All facts as a table** section under it, so the graph is never the only way to read it.

## Ask your memory

One assistant for every page (button bottom right, or `Cmd/Ctrl+K`). It keeps one conversation across pages and reloads, and each question is asked about the day on screen, so "today" means that day, not the computer's date. It answers:

- **Facts**: "Where did I leave my wallet?"
- **Summaries**: "Summarise my day."
- **To-dos**: "Did I promise anyone anything?"
- **The memory itself**: "What did the models read today?", "How much of my day is covered?", "What are you unsure about?" Numbers in these replies are checked against what the code computed.

Each answer shows its status, the claims it cites, and a **Why?** drawer that traces the claim down to its sources.

## Add memory

Press **Add memory** (needs live mode). You can drop or pick files, or capture with the device.

- **Photos**: up to eight at once, each shown as a thumbnail row with its own **Remove** button; they are saved as one memory.
- **Voice**, **video** (optionally follow named objects with SAM 3.1), or a **note**.
- **Review** shows *When*, *Where*, *Doing*, *Seen* and *People*, each marked Sure, Check or Ask, plus only the questions code decides it needs.
- **Save to Atlas** runs in the background with live progress. Afterwards the page shows each consent record's **withdrawal code once**.

## Consent and forgetting

The **Consent** tab lists grants. Withdrawing opens a simulated consent page for the person withdrawing (a second tab, like their own phone). The result is the **forgetting receipt**: removed and retained counts, why survivors survived, and the seven checks. You can also correct a claim ("That's wrong") or delete a single memory.

## Accessibility and design

- Follows the system light or dark theme and reduced-motion setting, with a manual toggle.
- Fully keyboard operable: tabs take arrow keys, `Esc` closes dialogs, focus is managed in dialogs.
- One polite live region announces changes (answers, corrections, saves) so screen-reader users are told what happened.
- The header always shows the model mode and **Raw media kept: 0 B**.
- Playwright walkthroughs run axe audits (see [Testing](Testing)).

## Code map

| Path | |
|---|---|
| `src/App.tsx` | Page shell and Atlas layout |
| `src/components/` | `AddMemory`, `Assistant`, `ConsentPanel`, `ReceiptDialog`, `Dashboard`, `GraphView`, `CorrectClaim`, `Onboarding` and others |
| `src/hooks/` | `useAtlas`, `useAssistant`, `useDay`, `useSession`, `useTodos`, `useTheme` |
| `src/utils/` | Pure, unit-tested helpers (add-memory rules, graph shaping, media decoding, save jobs) |
| `src/api/` | Typed client and response types |
