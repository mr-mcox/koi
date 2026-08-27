// Three LLM clients configured per `.env`. BAML names are PascalCase
// keywords; switching happens via `client "Fireworks"|"Openai"|"Anthropic"`
// in `identify.baml`. To swap at runtime by env var use BAML's
// `ClientRegistry` (slice 3+ wires dynamic dispatch).

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
    model "accounts/fireworks/models/inkling"
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

// Generates `src/screen/baml_client/` from these definitions. Run
// `baml-cli generate` (or use the BAML VSCode extension's
// save-on-edit hook) to regenerate.
generator target {
  output_type python/pydantic
  output_dir "../src/screen/baml_client"
  version "0.226.1"
}
