# Putting the app online for free (PythonAnywhere "Beginner" account)

Read the limits first (they matter for children's data):
- The free web app must be **renewed every month** (a button on the Web tab). If you forget, it goes offline.
- Free accounts can only contact websites on PythonAnywhere's allow-list. Check that your AI provider's address is on it
  (run `flask --app run ai-check` on the server to test).
- 512 MB of storage, one web worker, no SSH, no scheduled tasks, no custom domain.
- No LibreOffice, so the Word page check is an *estimate*. Open one exported file in Word to confirm.
- Free services can change their rules. **Always keep your own backups.**

## 1. On your Windows laptop
1. In the project folder, with `(venv)` active: `python tools/make_deploy_zip.py`
2. This creates `happy-report-app-deploy.zip` (no secrets, no database, no uploads).

## 2. Create the account
1. pythonanywhere.com -> Pricing -> **Create a Beginner account**.
2. The username becomes the web address (`username.pythonanywhere.com`). Pick a neutral name; do not use a child's name.

## 3. Upload and install (Files tab, then a Bash console)
1. Files tab: upload `happy-report-app-deploy.zip` to your home folder.
2. Open a **Bash console**:
   ```
   unzip happy-report-app-deploy.zip -d happy-report-app
   cd happy-report-app
   python3 --version
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
   Python must be 3.10 or newer. Remember the version for step 5.
3. Create the settings file: `nano .env` and type (use your own long random SECRET_KEY, different from your laptop's):
   ```
   APP_ENV=production
   SECRET_KEY=<64 random characters>
   TRUST_PROXY=1
   AI_PROVIDER=openai
   OPENAI_API_KEY=...
   OPENAI_MODEL=...
   ```
   Save with Ctrl+O, Enter, then exit with Ctrl+X. (For the free Gemini test, use the Gemini lines from `.env.example`.)
4. Create the database:
   ```
   flask --app run db upgrade
   flask --app run seed-defaults
   flask --app run create-admin
   flask --app run ai-check
   ```

## 4. Web tab
1. **Add a new web app** -> *Manual configuration* -> choose the **same Python version** as in step 3.
2. Source code: `/home/USERNAME/happy-report-app`
3. Virtualenv: `/home/USERNAME/happy-report-app/venv`
4. Click the WSGI configuration file link, delete everything, and paste:
   ```python
   import sys
   path = "/home/USERNAME/happy-report-app"
   if path not in sys.path:
       sys.path.insert(0, path)
   from wsgi import application
   ```
5. Turn on **Force HTTPS**, then press the green **Reload** button.
6. Open `https://USERNAME.pythonanywhere.com`, log in, and test with FICTIONAL data first.

## 5. Every month
Press **Run until 1 month from today** on the Web tab. Put a repeating reminder in your calendar.

## 6. Updating the app later
Build a new deploy zip, upload it, unzip over the old folder (never delete `instance` or `.env`), run
`flask --app run db upgrade`, press Reload.
