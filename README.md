# spory

Smart laptop power management tool. The first feature is **charge by deadline**: keep a normal battery cap while plugged in, then charge toward a requested target shortly before a chosen departure time.

The initial implementation is a pure Python planning function with tests. It does **not** control hardware yet. See [the project brief](docs/PROJECT.md) for the intended MSI Prestige 14 Evo B13M integration and its verification steps.

Run the starter tests with Python 3.11+:

```bash
python -m unittest discover -s tests -v
```

Codex cloud can develop and test the planner and simulator. Real battery control needs Windows and the supported laptop for read-only diagnosis and eventual testing.
