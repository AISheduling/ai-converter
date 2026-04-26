# Synthetic Benchmark Template Prompts

This directory is the active prompt bundle for LLM-assisted synthetic template
generation.

- `v1-system.txt`: system prompt for producing bounded `L0TemplateSpec`
  candidates
- `v1-user.txt`: user prompt rendered from deterministic template-generation
  inputs

The generator lives under
`src/ai_converter/synthetic_benchmark/generators/llm/` and uses the shared
`ai_converter.llm` adapter contract. Tests must use fake or injected adapters;
live model calls are optional example behavior only.
