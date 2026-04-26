# Synthetic Benchmark Examples

This directory contains runnable wrappers around the library-first synthetic
benchmark APIs.

## Offline Repeated Benchmark

`run_example.py` builds one deterministic canonical scenario, renders a base
bundle plus rename and nesting drift bundles, adapts them into benchmark
scenarios, and exports repeated-run reports.

Run from the repository root:

```bash
python examples/synthetic_benchmark/run_example.py --run-count 2
```

By default it writes artifacts under
`examples/synthetic_benchmark/generated/`.

## Multi-Model Orchestrator

`run_multimodel_orchestrator.py` compares static synthetic templates with an
LLM-assisted template surface, then synthesizes converters for multiple
OpenAI-compatible endpoints and benchmarks each result.

Repository tests run this path offline by injecting fake OpenAI-compatible
clients. Live runs require explicit endpoint configuration in the script and
are not part of the default verification flow.

Focused offline smoke command:

```bash
python -m pytest tests/integration/converter_pipeline/test_synthetic_benchmark_example.py tests/integration/converter_pipeline/test_multimodel_synthetic_benchmark_orchestrator.py -q -p no:cacheprovider
```
