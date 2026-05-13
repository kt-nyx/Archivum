# Release Model

## Branches

- `dev`
  - Primary development and integration branch.
  - Requires passing PR-fast checks before merge.
- `main`
  - Stabilization branch promoted from `dev` after integration checks and owner checkpoint.
- `release`
  - Production release branch promoted from candidate-approved state.

## Promotion flow

1. Merge approved work into `dev`.
2. Promote `dev` to candidate with `candidate/vX.Y.Z` tag after required CI and evidence checks.
3. Promote candidate to `release` with `release/vX.Y.Z` tag after final rerun and smoke sign-off.

## Protection defaults

- No force push on `main` or `release`.
- Require one owner approval for protected branch merges.
- Require required status checks to pass before merge:
  - PR-fast lint/type/test checks on `dev`.
  - Full integration and release-gate checks for promotions.

## Version channels

- `dev` channel: frequent integration updates.
- `candidate` channel: gated pre-release validation.
- `release` channel: signed-off production package lineage.
