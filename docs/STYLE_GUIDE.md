# ros_tui style guide

How `ros_tui` looks, and the rules that keep it consistent as the UI grows. The visual
identity lives in three small modules — read them alongside this doc:

- `ros_tui/ui/theme.py` — the colour palette, as one Textual `Theme`.
- `ros_tui/ui/styles.py` — the glyph + semantic-colour vocabulary for log/status text.
- `ros_tui/ui/app.py` (`RosTuiApp.CSS`) — the layout, spacing, and border system.

## The idea: "the blue seam"

ROS is a graph — nodes joined by live connections. The design leans on that with a strict
**two-tier colour system**:

1. **One saturated blue (`$primary`, `#4DA3FF`) means interaction and focus** — and nothing
   else. It is the active tab, the focused pane's border, the selection highlight, the
   primary-action button, and the draggable seam between the panes. Anchored on the ROS
   brand blue `#22314E` (too dark to use literally on a dark canvas, so lifted into a
   legible range).
2. **Green / amber / rose mean operation outcomes** — success / warning·streaming / error.
   They appear **only** in the status strip and the output log, never in the chrome.

Everything else is one of three quiet blue-grey neutrals. Boldness is spent in one place
(the blue seam); the rest stays calm for long terminal sessions.

**Colour is never the only signal.** Every semantic colour is paired with a glyph
(`✓ ✗ ⚠ → ←`) so meaning survives colour-blindness and no-colour terminals (WCAG 1.4.1).

## Palette

Defined once in `ros_tui/ui/theme.py` as the `ros-dark` theme. Reference hex values:

| Token | Hex | Role |
|---|---|---|
| `$background` | `#161922` | App canvas (near-black navy; never pure black) |
| `$surface` | `#1E2230` | Panels: entity list, editor, output log |
| `$panel` | `#2A3042` | Highest layer: selected row, modal layering |
| `$foreground` | `#C8D0E0` | Primary text (soft blue-grey; never pure white) |
| `$text-muted` | ~`#8A93A8` | Secondary text: placeholders, type names, idle status |
| `$primary` | `#4DA3FF` | The one bold blue — interaction, focus, in-flight |
| `$success` | `#4EBF71` | SUCCEEDED / responded / published (with `✓`) |
| `$warning` | `#E5A33B` | Feedback·streaming, running toggles, dropped counts (with `⚠`) |
| `$error` | `#F2607B` | REJECTED / ABORTED / failure / timeout (with `✗`) |

Success(green) / warning(amber) / error(rose) / info(blue) are separated by **both hue and
luminance** — not the fragile red↔green axis — so they stay distinct under colour-vision
deficiency and in greyscale.

## Rule #1: all colour comes from theme variables

Never write a hardcoded hex value or a Rich colour name (`red`, `cyan`, …) in CSS or in
Python. Use the theme variables (`$primary`, `$surface-lighten-2`, `$text-success`, …).
This is what keeps the look coherent and lets `ctrl+p → change theme` work. To retune the
palette, edit `theme.py` — nothing else.

In CSS, prefer the auto-derived, contrast-safe variables: the 11 base colours, their
`-lighten-N`/`-darken-N` and `-muted` shades, `$text` / `$text-muted`, the legible-on-any-
surface `$text-primary` / `$text-success` / `$text-warning` / `$text-error`, and
`$border` (focus) / `$border-blurred` (resting). A *custom* theme variable is only reliably
available in CSS if it also has an app-wide default; `$text-muted` covers our needs, so we
don't define custom CSS variables.

## Spacing

A small, predictable scale measured in cells: **{0, 1, 2}**.

- Inside a pane: `padding: 0 1` (one cell of horizontal breathing room, no vertical waste).
- Control row: `height: 3`, buttons `margin: 0 1 0 0` with `min-width: 10`.
- The status strip and single-line labels: `height: 1`.

Don't introduce other padding/margin values; reach for 0, 1, or 2.

## Borders & focus

One resting treatment and one focus treatment — that contrast *is* the blue seam:

- **Resting** panes (list, editor, log): `border: round $surface-lighten-2` — a quiet hairline.
- **Focused**: `round $primary` — via `:focus` (editor) or `:focus-within` (the list pane).

Every pane carries a **`border_title`** (set in Python) so the layout is self-labelling:
the left list = the tab noun (`Actions` / `Services` / `Topics`) with a `border_subtitle`
count; the editor = the message kind (`Goal` / `Request` / `Message`); the log = `Output`.
Border titles render muted and left-aligned (`border-title-color: $text-muted`).

## Text: the glyph + role vocabulary

Log and status text never uses raw style strings. Call a builder from
`ros_tui/ui/styles.py`; it returns a theme-aware Textual `Content`. `write_log(...)` and a
`Static`'s `.update(...)` both accept these directly.

| Builder | Theme variable | Use for |
|---|---|---|
| `styles.ok(text)` | `$text-success` (bold) | success result, response OK, publish OK |
| `styles.fail(text)` | `$text-error` (bold) | rejected/aborted/failure/timeout, errors |
| `styles.info(text)` | `$text-primary` (bold) | `→`/`←` request·response lines, in-flight |
| `styles.warn(text)` | `$text-warning` (bold) | cancel notices, warnings |
| `styles.feedback(text)` | `$text-warning` | streaming action feedback labels |
| `styles.muted(text)` | `$text-muted` | echo separators, coalesced/meta notices |
| `styles.title(text)` | `$foreground` (bold) | the detail-line type name |
| `styles.state(label, role)` | per role + glyph | the status strip (see below) |

Glyph vocabulary (also in `styles.py`): `→` request · `←` response · `✓` ok · `✗` fail ·
`⚠` warn · `───` echo separator · `◆` idle · `▸` busy/in-flight.

## Components

- **Status line** (the signature). Each tab has one single-line `Static` with
  `classes='status-strip'` — a calm, glyph-led "what just happened" line on the canvas (no
  filled band; the glyph + colour carry the state). For a single live state (Actions,
  Services) update it with `styles.state(label, role)` where role is `idle` (`◆`, muted),
  `busy` (`▸`, blue), `ok` (`✓`, green), `fail` (`✗`, rose), or `warn` (`⚠`, amber). A
  multi-signal readout (Topics — what's publishing *and* echoing, refreshed ~10 Hz) stays
  calm with `styles.muted(text)` while active and `styles.state('idle', 'idle')` when not.
  Either way it's the one "live vitals" line — keep the tabs' strips parallel.
- **Buttons** are a flat, outlined set — no filled bevel — so they rhyme with the round-
  bordered panes. Three tiers, all `border: round` and `height: 3`, distinguished only by
  colour, and each fills its colour on hover/press (the one bit of motion):
  - **Primary action** (Send goal / Call / Publish): `variant='primary'` → blue outline +
    `$text-primary` label; fills `$primary` on touch. The one call to action per tab.
  - **Secondary** (Cancel, Echo, Start rate, Pause): default variant → quiet
    `$surface-lighten-2` outline + `$text`; the outline brightens to `$primary` on hover.
  - **Running toggle** (rate publish, echo, paused-resume): the `running` class →
    `$warning` outline + `$text-warning` while live. Do **not** reuse Textual's internal
    `-active` class for this; it collides with the button press animation.
  `:disabled` buttons drop to a muted outline + `$text-muted` so inactive reads at a glance.
  The rate `Input` matches the buttons (`round`, `height: 3`).
- **Editor.** A `TextArea.code_editor(language='yaml', theme='css')` — YAML highlighting that
  follows the app theme (needs the `textual[syntax]` extra; see `setup.py` / `Dockerfile`).
- **Editor error.** The hidden `#editor-error` line turns on with `background: $error-muted;
  color: $text-error`. Keep its text the raw message (no glyph prefix) — the colour is the signal.

## The resize seam

`ros_tui/ui/resize_grip.py` is a 1-cell `Static` placed between the list and the right pane.
It resists Textual's lack of a splitter with the standard mouse-capture pattern: on
mouse-down it `capture_mouse()`s and records the start; on move it sets the target pane's
`styles.width` in cells (clamped to `[LIST_MIN_WIDTH, screen − 1 − RIGHT_PANE_MIN_WIDTH]`,
both in `constants.py`); on up it `release_mouse()`s. It lights up `$primary` on hover/drag.
The right pane stays `1fr` and absorbs the change.

## Checklist: adding a new tab

1. Subclass `InterfaceTab`; set `kind`, `list_placeholder`, and `list_title`.
2. Override `compose_controls` (primary action = `variant='primary'`) and, if the tab has
   live state, `compose_status` → `Static(id='<x>-status', classes='status-strip')`.
3. Drive the strip and the log only through the `styles.*` builders (`styles.state` for a
   single live state; `styles.muted` for a multi-signal readout). No raw colour strings, anywhere.
4. Pair every semantic colour with a glyph from the vocabulary above.
5. You get the seam, border titles, focus borders, spacing, and the YAML editor for free
   from the base class — don't re-style them per tab.
