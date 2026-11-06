# Backups and restoring

The database and all uploaded or generated files are in the `instance` folder. A backup is one zip with both.
**A backup contains information about children. Treat it like the application itself.**

## Make a backup (on the server or on your laptop)
```
flask --app run backup
```
The zip appears in `instance/backups/`. On PythonAnywhere use the **Files** tab to download it,
then **delete it from the server** (storage is only 512 MB).

## How often
- After every working session where many observations were added, and at least once a week.
- Always before an update, before `restore`, and before `delete-child`.
- Keep at least two recent copies in two places (for example a laptop and an encrypted USB drive).

## Protect the copies
- Store them in a folder only authorised people can open. Encrypt them (for example with 7-Zip: "Add to archive",
  choose the encryption password) before putting them on a USB drive or cloud storage.
- Delete old copies according to the retention policy.

## Restore
1. Stop or ignore the app. 2. Upload the backup zip. 3. Run:
```
flask --app run restore path/to/backup-YYYYMMDD-HHMMSS.zip --yes
```
The command first saves a safety copy of the current data, checks the backup, then replaces everything.
4. Reload the web app and log in. 5. **Test a restore at least once** with fictional data, so you know it works
before you need it.

Note: a database backup alone does NOT include the uploaded files. This backup includes both.
