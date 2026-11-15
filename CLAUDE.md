# CLAUDE.md

## Status log (read by DK's daily chief-of-staff brief)

A scheduled cloud run reads `STATUS.md` on `main` every weekday morning. It cannot see local or unpushed work.

At the end of every working session, or when DK says "wrap up":
1. Update `STATUS.md`: add finished work to "Done recently" with the date (newest first, keep about 10);
   rewrite "Next" as an ordered list of at most 5 items; list blockers and decisions waiting on DK;
   update "Last updated".
2. Only record real metrics (users, feedback, test counts). No estimates.
3. Commit and push (open a PR if working on a branch), so the brief sees it the next morning.
