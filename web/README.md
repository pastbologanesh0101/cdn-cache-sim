# CDN Cache Simulator Playground (web)

The browser demo behind **https://cdn-cache-sim-playground.vercel.app**.

- `index.html` — static UI: workload / cache-size / policy controls, "run",
  "compare policies", "cache-size sweep".
- `api/run.py` — a Vercel Python serverless function. `POST {mode, ...}` runs
  the simulation and returns the summary (requests capped at 60k, catalog at
  40k objects).
- `cdnsim/` — a vendored snapshot of the package (kept in sync with the repo
  root), so the function has no install step.

Deploy: `cd web && vercel deploy --prod`.
