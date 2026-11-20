# Good first issues

A curated, current list for new contributors. Each task has one outcome,
one or two files to touch and a runnable acceptance check. Create the
GitHub issues from this list with `python3 scripts/good_first_issues.py --gh`.

| ID | Task | Area | Effort | Acceptance |
|---|---|---|---|---|
| `dashboard-aria-labels` | Improve keyboard and screen-reader labels on dashboard buttons<br><small>`vira/web/static/dashboard.html`, `vira/web/static/app.js`</small> | accessibility | 1–2 hours | Icon-only buttons have descriptive aria-labels and focus-visible styling; the page still works without a mouse. |
| `client-collector-status-test` | Add a client test for collector permission and unavailable states<br><small>`client/lib/services/capture/capture_service.dart`, `client/test/`</small> | client | half a day | A Flutter unit test asserts permission_denied and unavailable are surfaced without throwing; `flutter test` passes. |
| `plugin-sdk-typings` | Add type hints to the plugin context registration methods<br><small>`vira/plugins/api.py`</small> | developer experience | 1–2 hours | Registration methods have precise type hints and the plugin examples still load and pass `vira.tests.test_examples`. |
| `doctor-json-schema` | Document the `vira doctor --json` schema and add a shape test<br><small>`vira/doctor.py`, `docs/user/troubleshooting.md`, `vira/tests/test_doctor.py`</small> | documentation | 1–2 hours | The JSON keys are documented and a test asserts the report contains ok/counts/checks with name/status/summary. |
| `eventbus-docstrings` | Add docstrings to EventBus public methods<br><small>`vira/kernel/event_bus.py`</small> | documentation | 1–2 hours | Every public method and property has a concise docstring; `python3 -m unittest vira.tests.test_event_bus -v` still passes. |
| `sensor-flow-example` | Add a sensor → event → agent → answer example<br><small>`docs/dev/architecture/framework.md`, `docs/dev/agent-platform.md`</small> | documentation | half a day | A new example shows the event name, dispatcher path, agent subscription and the visible result, with real code references. |
| `eventbus-tests` | Add EventBus subscribe, publish, unsubscribe and wildcard tests<br><small>`vira/kernel/event_bus.py`</small> | testing | half a day | New tests cover subscribe, publish, unsubscribe, a wildcard subscriber and a slow subscriber; `python3 -m unittest vira.tests.test_event_bus -v` passes. |
| `hello-plugin-route-test` | Add an HTTP route test for the hello-world plugin<br><small>`examples/plugins/hello_world/plugin.py`, `vira/tests/test_examples.py`</small> | testing | 1–2 hours | A test calls the plugin route handler or mounted router and asserts the greeting and persisted request count. |
| `run-resume-test` | Add an API test for resuming a failed run<br><small>`vira/tests/test_phase5.py`, `vira/api/app.py`</small> | testing | half a day | A TestClient test resumes a failed run with its original message and asserts a new run is returned without duplicating the user message. |
| `docs-link-checker` | Add a docs link checker to CI<br><small>`scripts/`, `.github/workflows/docs.yml`</small> | tooling | half a day | A script reports broken relative links in README/docs and fails CI when a new broken link is introduced. |

## How to claim one

1. Open the matching issue and comment that you are taking it.
2. Read `CONTRIBUTING.md` and the linked code.
3. Make the smallest change that satisfies the acceptance check.
4. Open a PR with the test output and any docs updates.

Maintainers aim to give an initial response within **three business days**.
If an issue is stale or no longer accurate, say so in the issue rather than
working around it.

