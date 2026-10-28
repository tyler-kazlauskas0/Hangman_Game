# Deployment

The app is deployed to [Render](https://render.com) as a Python web service.
`render.yaml` in the repository root describes the service, so Render can set
everything up from the repository.

## Deploy on Render

1. Sign in at <https://dashboard.render.com> with GitHub.
2. Choose **New → Blueprint** and select the `Hangman_Game` repository.
3. Render reads `render.yaml` and proposes one web service named `hangman`
   on the free plan. Click **Apply**.
4. When the deploy finishes, open the URL Render shows, for example
   `https://hangman-xxxx.onrender.com`.

What `render.yaml` sets up:

| Setting | Value |
| ------- | ----- |
| Build | `pip install -r requirements.txt` |
| Start | `gunicorn server:app --workers 1 --threads 8 --bind 0.0.0.0:$PORT` |
| Health check | `GET /healthz` |
| Python | 3.12 |
| Auto-deploy | On every push to `main`, after the GitHub test checks pass |

Render provides HTTPS automatically. Users only need a browser; there is
nothing to install.

### Manual setup (without the Blueprint)

**New → Web Service**, pick the repository, and enter:

- Runtime: Python 3
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn server:app --workers 1 --threads 8 --bind 0.0.0.0:$PORT`
- Health check path: `/healthz`
- Environment variable: `PYTHON_VERSION` = `3.12.7`

Other platforms that understand a `Procfile` (Heroku, Railway, and similar)
can use the included `Procfile`, which runs the same command.

## Why one worker

Games are stored in the server process's memory. With several gunicorn
worker processes, a guess could reach a process that has never seen that game
and get a 404. One worker with eight threads serves many players at once and
keeps every game in one place.

## Checking a deployment

From your own machine:

```bash
python scripts/check_deployment.py https://YOUR-APP.onrender.com --browser
```

Or without installing anything: on GitHub open **Actions → Check deployment →
Run workflow** and paste the URL. The check:

- requires HTTPS and waits for a sleeping free-tier app to wake up;
- loads the web page and its CSS and JavaScript;
- plays a complete game at each difficulty through the REST API, checking the
  word stays hidden until the end;
- checks duplicate (409), invalid (400), and unknown-game (404) responses;
- with `--browser`, plays a complete game in Chromium by typing letters, then
  starts another game with Enter. The workflow saves a screenshot.

## Limits of the free plan

- The service sleeps after about 15 minutes without traffic. The next visit
  takes up to a minute while it wakes.
- Games live in memory, so a restart, redeploy, or sleep ends any game in
  progress. The page then starts a new game automatically.
