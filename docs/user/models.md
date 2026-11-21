# Choose a local model

VIRA ships with **`nemotron-3.5-bolt:e4b`** through Ollama. That is the recommended
first-run model: it is fast, follows the tool protocol reliably and fits an
8–16 GB CPU-only machine.

The Chatbot drives tools by emitting small JSON calls. Very small models can
chat well and still fail that job by repeating calls, inventing tool names or
returning malformed JSON. Use this page to pick a model that matches your
hardware before you conclude that VIRA is broken.

!!! warning "Tool use below the recommended tier"
    Tool use may be unreliable below about **4 GB RAM or a 4B-parameter model**.
    If the agent repeats calls, ignores tools or returns broken JSON, move up a
    tier or use a cloud fallback.

## Tiers by memory and GPU

| Tier | RAM | Suggested model | Tool reliability | Notes |
|---|---|---|---|---|
| Minimal | 4–8 GB | `llama3.2:3b` | Experimental | Chat works; multi-step tool use is unreliable. Use for quick tests. |
| Recommended | 8–16 GB | `nemotron-3.5-bolt:e4b` | Good | VIRA's default. Fast on CPU; much better tool support than its size suggests. |
| Comfortable | 16–32 GB | `qwen2.5:14b` | Better | Better instruction following and tool selection. |
| Large | 32 GB+ | `qwen2.5:32b` | Best local | Best local quality; needs a GPU or a large-memory host to be usable. |

The one-command installer chooses a tier from detected RAM. Override it with:

```bash
VIRA_OLLAMA_MODEL=qwen2.5:14b scripts/install.sh
```

A GPU does not change the tier names, but it changes what is comfortable: a
24 GB GPU can run the 32B tier quantized while a CPU-only host with the same RAM
will be too slow for a good first impression.

## Context size matters more than parameter count

A model also needs room for the tool catalogue, history and observations. VIRA
sets Ollama's `num_ctx` explicitly (the default config uses 65536) because
Ollama's own default can drop the start of a long prompt.

If you use a smaller model, keep `num_ctx` at **8192 or more**:

```yaml
llm:
  default_model: "nemotron-3.5-bolt:e4b"
  models:
    - name: "local-llama"
      provider: "ollama"
      model: "nemotron-3.5-bolt:e4b"
      base_url: "http://localhost:11434"
      num_ctx: 8192
```

Run the doctor to confirm the model is installed and the context is configured:

```bash
python -m vira doctor
```

## Check your machine first

```bash
python -m vira doctor
```

The doctor checks Docker and Compose, Ollama reachability, the selected model
and its context size, port conflicts, the Chatbot agent, database writability
and the master key. It prints a fix for every warning or failure. See
[Troubleshooting](troubleshooting.md#run-the-doctor) for the full list.

## Cloud fallback

A local model is optional. If your hardware cannot run the recommended tier, or
you want faster answers, configure a cloud provider.

OpenAI:

```yaml
llm:
  default_model: "gpt-4o-mini"
  models:
    - name: "gpt-4o-mini"
      provider: "openai"
      model: "gpt-4o-mini"
      api_key: "${OPENAI_API_KEY}"
```

```bash
export OPENAI_API_KEY="..."
```

Anthropic:

```yaml
llm:
  default_model: "claude-3-5-sonnet-latest"
  models:
    - name: "claude-3-5-sonnet-latest"
      provider: "anthropic"
      model: "claude-3-5-sonnet-latest"
      api_key: "${ANTHROPIC_API_KEY}"
```

```bash
export ANTHROPIC_API_KEY="..."
```

Reload the runtime from the dashboard after changing `config.yaml`, or restart
VIRA. Provider keys are read from the environment and are never returned from
the API.

A larger Ollama host also works:

```bash
VIRA_OLLAMA_URL=http://gpu-box.lan:11434 python run.py
```

## Switch models without restarting

Administrators can switch the active Ollama model from the chat recovery panel
after a failure. The same action is available over the API:

```bash
curl -s http://localhost:8000/api/v1/models \
  -H "Authorization: Bearer <session>"
```

```bash
curl -s -X POST http://localhost:8000/api/v1/models/select \
  -H "Authorization: Bearer <session>" \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen2.5:14b"}'
```

VIRA saves the choice to `config.yaml` and updates the running provider. Pull the
model first with `ollama pull <model>`.

## Measure before you change

Run the tool-use benchmark against your own server and model:

```bash
VIRA_USERNAME=you VIRA_PASSWORD=... python3 scripts/benchmark.py --runs 10
```

The deterministic layer runs in CI. The live layer records whether device,
database, RAG and web questions actually selected tools. See the
[tool-use benchmark](../dev/benchmarks/tool-use.md) for the current baseline.
