# Documentation

Technical background for **City Energy Lab** — the physics, the architecture, and the modeling choices. Start with the [project README](../README.md) for setup and a tour.

| Doc | What's inside |
|---|---|
| [The Energy Model](energy-model.md) | The single-node 1C RC thermal model: governing equation, envelope UA, window solar gain with façade orientation, internal/HVAC/lighting/appliance loads, rooftop PV, the CO₂ factor, the `Params` system, constant tables with sources, and an honest limitations section. |
| [Architecture & Data Flow](architecture.md) | The server-authoritative design: the `asyncio` tick loop, the 10 Hz browser poll, `world_rev` layout sync, the full JSON API, and the unbundled native-ES-module frontend. |
| [The City & Agent Simulation](simulation.md) | Building the world from OpenStreetMap (and the offline grid world), the street-graph random walk for cars & people, the weather state machine + Open-Meteo, design-day warm-start, and live edits. |
| [Retrofit Scenario Analysis](retrofit-scenarios.md) | The stateless before/after methodology — a deterministic design-day recompute under baseline vs. retrofitted `Params` — the measures, targeting, and the indicative cost/payback model. |
| [Modeling Scope & Limitations](modeling-scope.md) | What turbo-city models versus what a fuller research-grade model adds, framed as deliberate design choices for interactivity. |

## Diagrams & images

Diagrams in these docs use [Mermaid](https://mermaid.js.org/), which GitHub renders natively. Figures and UI graphics live in [`assets/`](assets/) — see [`assets/README.md`](assets/README.md) for how to add real screenshots.
