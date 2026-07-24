## CLAUDE MODE RULES for ARIA

- Act as Claude Code: Generate artifacts, use tools, iterative development.
- Always reason step by step, create real Shopify products with images/videos.
- Use tool calling for LinkedIn, Shopify, media generation.
- Never say 'I can't' if credentials provided.

## Multi-agent coordination

Multiple Claude sessions may work on this repo concurrently. To avoid clobbering
each other's work:

- Before starting, `git fetch origin main` and rebase/merge your feature branch
  onto the latest `main` — don't assume the branch you started from is still current.
- Keep branches short-lived: get CI green and merge to `main` promptly rather than
  letting a branch sit for many commits. The longer it lives, the more likely another
  agent's merge collides with it.
- If your PR shows a merge conflict or goes stale after another PR merges, re-fetch
  `main`, re-merge, and re-verify before merging — don't force-push over it.
- `main.py`, `app.html`, and `index.html` are hot files that multiple redesign/feature
  efforts tend to touch at once — expect conflicts there and resolve by reading both
  sides' actual behavior, not by blindly taking "ours" or "theirs".
- `deploy.yml` deploys on every push to `main`, and `main`'s CI gate is real — always
  confirm CI is green on your PR before merging, since the merge itself triggers a
  production deploy.