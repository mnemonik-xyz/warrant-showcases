# Agent Guidelines

## Core Principles

- **Clear Code**: Prioritize readability, clarity, and maintainability. Code should be intuitive,
  self-documenting, and idiomatic. Favor explicit and meaningful names over cryptic brevity.
- **DRY (Don't Repeat Yourself)**: Eliminate duplicate logic and structural redundancy. Consolidate
  repeated logic without introducing premature or overly complex abstractions.
- **Minimalism**: Strive for minimal, focused solutions. Avoid over-engineering, unnecessary
  dependencies, and speculative features. Keep implementations lean and purposeful.
- **Remove Legacies**: Actively eliminate dead code, deprecated patterns, obsolete workarounds,
  and legacy baggage. Refactor out outdated constructs rather than building on top of them.
- **Strict Scope (YAGNI)**: Never add new CLI flags, configuration fields, or public 
  API parameters unless explicitly instructed. Keep interfaces minimal and solve problems 
  within existing configuration schemas.
