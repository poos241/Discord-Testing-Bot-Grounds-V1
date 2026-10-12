# New-feature checklist

Run through this for every feature or fix:

1. **Implement** in the cog; **add tests**; run the full suite.
2. **Dependencies**: any new package goes in `requirements.txt`
   (`setup.py` picks it up automatically — no other changes needed).
3. **README**: update the command tables and feature docs (standing rule —
   every push updates the README).
4. **This handbook**: update the relevant page if the architecture or a
   pattern changed. Every page has an *Edit this page* link.
5. **Push files one at a time** and verify each by comparing the GitHub
   file **size** to the local size — never "verify" by decoding content.
6. **Tell the user** the exact local steps: which files to update, whether
   to `pip install`, and to restart the bot.
