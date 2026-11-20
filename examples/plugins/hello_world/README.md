# Hello World plugin

The smallest complete VIRA plugin:

- `example_word_count` read-only tool;
- `GET /api/v1/ext/example.hello-world/hello` route;
- persistent request counter in namespaced plugin state.

Start here, then read `reading_list` for write tools/agent definitions and
`focus_budget` for events/scheduled jobs.

```bash
python3 -m unittest vira.tests.test_examples -v
```
