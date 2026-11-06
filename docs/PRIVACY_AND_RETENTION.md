# Privacy, retention and deletion (starting draft for Happy Children Nepal)

This is a technical starting point, not legal advice. Your organisation must decide and approve the final rules.

## What the app stores
Children's names, current education, optional living-situation note, dated observations, uploaded previous reports,
generated drafts and Word files, user accounts, and an audit log (who did what, without personal details).

## What is sent to the AI service
Only the child's FIRST name, current education, the chosen observations, pasted bullet points, the chosen previous
report text, and the answers to clarification questions. Never the surname. Read the AI provider's current data terms
before sending real data. Free AI tiers may let the provider use or read the data: use fictional data only with them.

## Decisions your organisation must make (suggested starting points)
- Who may have an account (suggest: only staff who write reports; remove leavers the same day).
- How long to keep a child's records after they leave the programme (decide a number of years).
- How long to keep backup copies (suggest: delete copies older than 3 months).
- Who may approve reports (the app: administrators only).

## Deleting a child's data
1. Make a backup first: `flask --app run backup`
2. `flask --app run delete-child <child id>` and type the child's full name to confirm.
3. This permanently removes the child, observations, previous reports, generated reports, versions, approvals, Word
   files and stored files. The audit log keeps only the child's ID and the fact that deletion happened.
4. Old backup zips still contain the child until they are deleted too. Delete them as well.

## Everyday rules
- Never put real children's information in emails or chat tools; use the app.
- Use strong, unique passwords and log out on shared computers.
- Report lost laptops or phones immediately and change passwords.
- No secrets (`.env`, keys, backups) in Git or in screenshots.
