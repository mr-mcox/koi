// Three LLM clients configured per `.env`. BAML names are PascalCase
// keywords; switching happens via `client "Fireworks"|"Openai"|"Anthropic"`
// in `identify.baml`. To swap at runtime by env var use BAML's
// `ClientRegistry`.

client<llm> Openai {
  provider openai
  options {
    model "gpt-4.1-mini"
    api_key env.OPENAI_API_KEY
  }
}

client<llm> Fireworks {
  provider "openai-generic"
  options {
    base_url "https://api.fireworks.ai/inference/v1"
    model "accounts/fireworks/models/nemotron-3-ultra-nvfp4"
    api_key env.FIREWORKS_API_KEY
  }
}

client<llm> Anthropic {
  provider anthropic
  options {
    model "claude-haiku-4-5-20251001"
    api_key env.ANTHROPIC_API_KEY
  }
}

// Sonnet 5 always thinks adaptively (no token budget; `budget_tokens` is a 400),
// and thinking counts against `max_tokens`. BAML's default cap (~4k) lets a
// hard prompt spend it all on thinking and return no text, so the cap is raised
// and truncation is surfaced as a finish-reason error instead.
client<llm> AnthropicSonnet {
  provider anthropic
  options {
    model "claude-sonnet-5"
    api_key env.ANTHROPIC_API_KEY
    max_tokens 32000
    output_config {
      effort "high"
    }
    finish_reason_deny_list ["max_tokens"]
  }
}

// Generates `src/screen/baml_client/` from these definitions. Run
// `baml-cli generate` (or use the BAML VSCode extension's
// save-on-edit hook) to regenerate.
generator target {
  output_type python/pydantic
  output_dir ".."
  version "0.226.1"
}
