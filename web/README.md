# Planora Web

The web workspace is a browser client for the Python scheduler API. It intentionally keeps
the browser as UI only: solving, timetable CSV import, scoring, conflict checks, local
search improvement, focused CP-SAT polish, and CSV export all run through the same Python
service modules used by the desktop app.

Run the API from the repository root:

```powershell
.venv\Scripts\python.exe -m api.server --host 127.0.0.1 --port 8787
```

Serve the repository with any static server, for example:

```powershell
.venv\Scripts\python.exe -m http.server 8080
```

Open `http://127.0.0.1:8080/web/`.

`src/main.ts` is the typed source. `src/main.js` is checked in so the client works without a Node build toolchain.

When Node is available, the normal TypeScript workflow is:

```powershell
cd web
npm install
npm run typecheck
npm run build
```

Current API-backed actions:

- load presets and instance JSON
- import timetable CSV
- backend workspace sessions for large instances
- solve, async solve jobs, and portfolio solve
- job polling and Server-Sent Events snapshots
- score / conflict diagnostics
- local-search improve with optional focus term
- focused CP-SAT polish on a penalty neighborhood
- manual move / lock / unlock activity actions
- export the current schedule as CSV
- save and reload local web projects under `data/web_projects`
- view the local API schema at `/openapi.json`
