# Windows 11 local startup

These scripts start the development backend and Vite frontend from this
checkout. They bind to `127.0.0.1` only. The controller does not stop processes
by port number; it stops only a process whose PID record and command line match
this project.

## First-time setup

Install Git, Python 3.10 or newer, and a Node.js version accepted by
`src/frontend/package.json` (20.19+, 22.13+, or 24.x). Then, in PowerShell from
the repository root, install the project dependencies:

```powershell
py -3.12 -m venv .\src\backend\.venv
Set-Location .\src\backend
.\.venv\Scripts\python.exe -m pip install -e ".[dev,backtrader]"
Copy-Item .env.example .env
```

Edit `src/backend/.env` before first launch:

- Set `DEBUG=true` for this local development launcher.
- Replace `SECRET_KEY` and `JWT_SECRET_KEY` with different random values of at
  least 32 characters. For example, run `python -c "import secrets; print(secrets.token_hex(32))"`
  twice and use one output for each key.
- Keep `DATABASE_TYPE=sqlite` for a local SQLite setup, or set the correct
  `DATABASE_URL` and ensure the selected database is running.

Install frontend dependencies:

```powershell
Set-Location ..\frontend
npm ci
Set-Location ..\..
```

The backend defaults to a local SQLite database when `DATABASE_URL` is not
specified. Optional AI providers, broker gateways, and market-data services
need their own configuration; they are not required just to open the UI.

## Start, stop, restart

From Explorer, double-click `start_app.bat`, `stop_app.bat`, or
`restart_app.bat`. From PowerShell or Command Prompt, you can also run:

```powershell
scripts\windows\app.bat doctor
scripts\windows\app.bat start
scripts\windows\app.bat status
scripts\windows\app.bat restart
scripts\windows\app.bat stop
```

`start` waits for `/health` to report a healthy database and for the frontend
to return a successful HTTP response. It opens the browser only after both
checks pass. `restart` stops the registered frontend and backend, confirms
their ports are released, then starts both services and repeats the health
checks. If startup fails, the script stops services started by that attempt
and keeps their timestamped logs under `logs\`.

The ports are fixed by the current application configuration: backend `8000`,
frontend `3000`. A process that is not registered by these scripts is never
terminated. If it owns either port, `doctor` and `start` report the conflict;
stop it yourself only after identifying it.

Python selection order is the backend virtual environment, repository virtual
environment, then Python Launcher versions 3.12, 3.11, 3.10, and 3.14. Set
`AI_FOR_INVESTOR_PYTHON` to an absolute `python.exe` path to select another
interpreter explicitly.
