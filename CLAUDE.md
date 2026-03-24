# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A private lab codebase for controlling superconducting qubit experiments. The core package is `nsqdriver` — custom Python drivers for NanSuan (NS) quantum control hardware. This is **not** the upstream QCoDeS project; the directory name is coincidental.

## No build/test tooling

There is no `setup.py`, `pyproject.toml`, test suite, or Makefile. Development is done interactively via Jupyter notebooks (e.g., `251208.ipynb`). There are no commands to run for build, lint, or test.

## Architecture

### `nsqdriver/` — hardware driver package (v0.0.238)

| Module | Role |
|---|---|
| `NS_MCI.py` | Core AWG+ADC driver for the RFSoC-based MCI board. Communicates via XML-RPC (port 10801) and a custom binary FastRPC protocol (port 10800). Handles waveform upload, IQ demodulation, trigger, and data readback. |
| `NS_QSYNC.py` | Synchronization module driver. Manages multi-device clock sync, trigger generation, and firmware updates via raw TCP (port 5001) with a custom binary ICD protocol. Uses `InfoSharedList` shared memory to track connected device IPs across processes. |
| `NS_CST.py` | Coaxial Switch Tree driver — controls a microwave switch matrix via TCP binary commands. |
| `NS_DDS_v3.py` / `NS_DDS_v4.py` | Higher-level DDS drivers built on `NS_MCI`. Integrate with the `waveforms` library to compile parametric waveform objects into raw sample arrays. v4 is current. |
| `common.py` | Shared base classes (`BaseDriver`, `Quantity`, `QInteger`). |
| `compiler/` | Pre-compiled Cython `.pyd` extensions (CPython 3.13, win64) for the waveform compiler pipeline (IR, optimization, simulation, translation). `.pyi` stubs provided for IDE support. |
| `nswave/` | Pre-compiled waveform assembly extensions (`ns_wave`, `py_wave_asm`, `assembler`) that translate waveform descriptions into hardware instruction sequences. |
| `wrapper/AWG_ADC.py` | High-level abstraction presenting MCI hardware as separate AWG and ADC objects with channel objects (`DAChannelData`, `ADConfig`). |
| `wrapper/ND_NSMCI.py` | QCoDeS-style channel wrapper mapping qubit control lines (XY drive, Z flux bias, readout probe) onto MCI driver calls. |

### `prompt_engineering/` — AI agent skill definitions

Defines this Claude Code agent's role as an automated measurement controller:

- `system_prompt.md` — 4-level permission system (I: silent execute → IV: DC bias double-confirm), 8-step SOP, anti-hallucination rules.
- `skill_generate_wiring.md` — generates a YAML wiring map before any measurement.
- `skill_manage_context.md` — maintains `memory/short_term_context.md` tracking experiment progress and fitted parameters.
- `skill_extract_cheatsheet.md` — extracts a minimal API dictionary from example code into `memory/driver_cheatsheet.md`.

### `memory/` — agent runtime scratch space

Intended to hold `driver_cheatsheet.md`, `wiring_map.yaml`, `short_term_context.md`, and long-term skill notes. Check here before starting any experiment session.

## Key conventions

- All instrument communication is over TCP to local network IPs. Never hardcode IPs — they come from the wiring map.
- The `.pyd` binaries in `compiler/` and `nswave/` are CPython 3.13 win64 only. Do not attempt to rebuild or replace them.
- DC bias operations require Level IV confirmation (explicit user double-confirm) per the system prompt safety rules.
- The `waveforms` library (external dependency, not in this repo) is required by the DDS drivers for waveform compilation.
