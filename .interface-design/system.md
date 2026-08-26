# Repo Intelligence Graph — interface design system

## Direction and feel

A developer analytics tool, not a marketing product. Dense-but-legible, like a
terminal or a code review tool — not airy/brochure-like. The product's world is
git itself: commits, diffs, blame, coupling. Color should draw from that world
rather than a generic SaaS palette.

**Signature:** git's own diff language (additions = green, deletions = red) is
the app's real semantic color vocabulary for risk/health — not decorative,
not a generic single-accent blue slapped on everything. Already present in
`CommitList` (+/- counts); extended to hotspot risk severity (see below).
Reuse this whenever a new risk-adjacent number is added — don't reach for a
generic accent color for anything that represents risk, health, or churn.

## Depth strategy

Borders + subtle shadow (light layering), not pure-borders and not heavy
layered shadows. Committed values:

- Borders: low-opacity rgba, not solid hex — `--border: rgba(11,11,11,.1)`
  light / `rgba(255,255,255,.1)` dark; `--border-strong` for emphasis (`.16`
  / `.18`).
- Card elevation: one subtle shadow step, `--shadow-card` — two soft layers
  (`0 1px 2px`, `0 1px 12px`) at very low opacity. No dropdown/popover
  elevation scale exists yet; if one gets added, keep it whisper-quiet (a
  few % lightness/opacity per step), not a jump.
- Radius scale: `--radius-sm: 6px` (inputs/buttons) · `--radius-md: 10px`
  (cards) · `--radius-lg: 16px` (larger containers). Concentric nesting —
  don't reuse the same radius on a parent and its child.

## Spacing

Base unit is 4px, but not yet strictly enforced everywhere — most real
values cluster on 4/6/8/10/12/16/20/22/32/40px. Card interior padding is
`20px 22px` (`.card-pad`), leaning toward Stripe's airiness rather than
Linear's tightness — this is a data-review tool, not a control panel, so a
bit of breathing room is correct. Hold this density if extending to new
pages rather than tightening ad hoc.

## Color system

- `--cat-1..8`: categorical/identity color, hash-assigned per module name
  (`ModuleChip`). Legitimate use of a multi-color palette — this is
  identity, not severity, so it's fine for it to be "decorative" in the
  sense of not encoding a scalar value.
- `--status-good/warning/serious/critical`: the semantic severity ramp.
  This is the one to reach for anywhere risk, health, or churn is shown.
- `--seq-150/300/450/600`: sequential/quantitative scale (currently used
  for the blast-radius graph's edge/node weighting).
- Generic UI chrome (nav active state, primary buttons) uses `--cat-1`
  (blue) as a plain brand accent — this is fine and shouldn't change; it's
  not a "default to avoid," it's consistent brand identity for pure
  navigation/actions with no data-severity meaning attached.

## Hierarchy: the focal-metric pattern

Established in `StatTile` (28px/700 value + 12px/600/uppercase/tracked/muted
label) and now reused for the Dashboard hotspot risk score (24px/700/
tabular-nums, severity-colored + 10px/600/uppercase/tracked "risk score"
caption beneath). **This is the house pattern for any flagship number**:
large/bold/tabular-nums value, tiny/muted/uppercase/tracked label directly
beneath it, supporting metadata demoted further (11-12.5px, `--text-muted`
or `--text-secondary`). Reuse this exact shape rather than inventing a new
one when another flagship metric needs surfacing (e.g. if `FileDetail` ever
exposes its own `risk_score`, or an author's bus-factor becomes a first-class
number).

## Key component pattern: risk-tier severity grading

`frontend/src/lib/riskColor.ts` — `riskTier(score, maxScore)` grades a risk
score into good/warning/serious/critical **relative to the max score in the
currently displayed list**, not a fixed absolute threshold (risk_score has no
universal scale — it varies by orders of magnitude between a quiet repo and
a hyperactive one). Thresholds: ≥75% of max = critical, ≥50% = serious,
≥25% = warning, below = good. Reuse this function (don't hardcode a new
threshold scheme) anywhere else a risk-like score needs color-grading.

Currently applied: Dashboard hotspot list (focal number color + left-border
heat-strip per row, 3px solid).

## Not yet extended (known follow-up)

Files, Authors, Modules, and Collaboration pages still use the pre-existing
(reasonable, already-consistent) styling and haven't been passed through
this system's focal-metric/severity-grading pattern yet. If any of those
pages surface a risk-like or flagship number, apply the same two patterns
above rather than defaulting to plain text.

## Explicitly rejected

The `taste-skill` repo's other 12 skills (`gpt-taste`,
`industrial-brutalist-ui`, `minimalist-ui`, `high-end-visual-design`, etc.)
are built for marketing/landing pages — GSAP scroll animations, hero
sections, bento grids. Wrong tool for a dense data dashboard; don't apply
them here even though they're installed in `.claude/skills/`.
