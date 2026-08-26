// Risk score has no fixed scale -- it's coupling_density * (1/author_count) *
// log(commit_count+1), which varies by orders of magnitude between repos of
// different activity levels. Grading relative to the worst score in the
// current list (rather than a hardcoded absolute threshold) keeps the color
// meaningful regardless of which repo is loaded: the single riskiest file
// shown is always the most severe color, fading toward "good" for
// comparatively low-risk entries in the same list.
export type RiskTier = "critical" | "serious" | "warning" | "good";

export function riskTier(score: number, maxScore: number): RiskTier {
  if (maxScore <= 0) return "good";
  const ratio = score / maxScore;
  if (ratio >= 0.75) return "critical";
  if (ratio >= 0.5) return "serious";
  if (ratio >= 0.25) return "warning";
  return "good";
}

export function riskColorVar(tier: RiskTier): string {
  return `var(--status-${tier})`;
}
