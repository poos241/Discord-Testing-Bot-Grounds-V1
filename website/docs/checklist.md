# New-feature checklist

Run through this for every feature or fix:

1. **Implement** in the cog; **add tests** (note: no test files are
   currently in the repo — restore them before treating the suite as a
   gate); run the full suite.
2. **Dependencies**: any new package goes in `requirements.txt`
   (`setup.py` picks it up automatically — no other changes needed).
3. **README**: update the command tables and feature docs (standing rule —
   every push updates the README).
4. **This handbook**: update the relevant page if the architecture or a
   pattern changed. Every page has an *Edit this page* link.
5. **Push only when Emily says so** (local-first: she tests locally and
   asks for the push). README and handbook pushes are the exception and
   may go anytime. Push from her PC over SSH with files staged
   explicitly by path — never `git add -A` (runtime files like `bot.db`
   are tracked and must stay out) — then verify local HEAD matches
   `git ls-remote origin main`.
6. **Tell the user** the exact local steps: which files to update, whether
   to `pip install`, and to restart the bot.
