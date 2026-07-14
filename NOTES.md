# Teaching notes

- Learner is on a **separate laptop, Ubuntu 26.04 LTS Desktop**, new to the CLI.
  Match the beginner tone of `deploy/LAPTOP-DEPLOY.md`: show what to type, what to
  see, and a Verify per step. Tell them to STOP and ask when a check fails.
- Never use the em dash. Plain dash only. One sentence per line in long markdown.
- Slice 15 is **HITL**: it is executed and signed by a human on the real box and is
  **not merged AFK**. Do not merge to `master` for them; that is their sign-off call.
- The single source-of-truth docs already exist and are high-trust: guide them TO
  those docs, do not rewrite the detailed steps. My value is orientation + ordering
  + the git path + footgun warnings.
- Git gotcha: `deploy/LAPTOP-DEPLOY.md` is untracked; slice-15 is not on `master`.
  The laptop must clone and checkout branch `agent/slice-15`, not `master`.
