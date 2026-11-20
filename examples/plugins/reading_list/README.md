# Reading List plugin

A complete example of the VIRA plugin SDK:

- `reading_list` (read-only tool) and `reading_add` (write tool);
- `GET/POST /api/v1/ext/example.reading-list/items`;
- namespaced persisted state (`storage`);
- a `reading_coach` prompt specialist that can only call the read tool.

Enable it by adding `examples/plugins` to `plugins.directories` (the default
config already does) or copy this directory into your plugin directory.

```bash
curl -s http://localhost:8000/api/v1/plugins \
  -H "Authorization: Bearer <admin-session>"
```

Test it:

```bash
python3 -m unittest vira.tests.test_examples -v
```
