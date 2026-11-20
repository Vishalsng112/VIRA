# Focus Budget plugin

A complete example of event-driven and scheduled plugins:

- `focus_budget` read-only tool;
- subscribes to `device.focus.session` and accumulates local minutes;
- schedules a bounded state cleanup job;
- exposes `GET /api/v1/ext/example.focus-budget/summary`;
- stores only daily minute totals, never session content.

Enable it through `plugins.directories` and reload plugins. State lives in the
VIRA database under the plugin namespace.

```bash
python3 -m unittest vira.tests.test_examples -v
```
