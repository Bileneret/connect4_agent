# connect4_agent

[Русская версия](README.ru.md) · MIT · Python 3.12 + Numba

**An exact-play Connect 4 engine with a multi-threaded search core and a live vision/CDP benchmark harness.**

## What this is

This project is systems engineering in three layers:

1. **Perfect-play engine** — a bitboard Negamax solver following the published algorithm of
   Pascal Pons: binary-search score resolution, a lockless transposition table shared by search
   threads, principal-variation search and a move-ordering heuristic.
   Validated against the reference benchmark: **6/6 position sets solved 100%**, ≈8.1M nodes/s
   average (27.4M peak) on a 4-core laptop CPU.
2. **State readers** — two independent board-state pipelines: a DOM reader and a pure
   **computer-vision fallback** (screen capture, board-plate detection, multi-sample cell
   classification), cross-checked cell-by-cell: **42/42 cells**, verified at two display scales.
3. **Live benchmark harness** — CDP-driven input (trusted input events, **no OS cursor movement**,
   0.6–0.8 s click round-trip) with a physical-mouse fallback, plus an evaluation overlay rendered
   directly over the board.

The live harness is used as a *real-environment test bench*: it exercises the engine and the CV
pipeline under real rendering, animations, network latency and a real interface.

## Demo

![demo](connect4_agent/docs/assets/demo_overlay.png)

Per-column exact scores (`WIN`/`LOSS`/`DRAW` with distance) rendered as an overlay during a live game.

## Key metrics

| Metric | Value |
|---|---|
| Benchmark gate (reference datasets) | **6/6 sets, 100%** of positions solved correctly |
| Search speed | ≈8.1M nodes/s average, 27.4M peak (i5-11300H, 4C/8T, Numba `nogil`) |
| Transposition table | 16 B/entry, lockless; packed entry + `key ^ entry` verification |
| Live click round-trip (CDP) | **0.6–0.8 s** (single flight + atomic click; was 17–22 s before optimization) |
| Vision fallback | **42/42 cells** vs DOM, at 125% and 100% display scale |
| Live series vs the site's strongest bot | 20 games: **11 W / 7 L / 2 D**; **3/3 as first player** |

## Architecture

```
 DOM reader ─┐
             ├─► state validation (column heights + stone-balance invariants)
 Vision(mss)─┘            │
                          ├─► decision cascade:
                          │     book (optional, external)  →  tactical win/block
                          │     →  exact solve (bisection over shared TT)
                          │     →  partial-book / emergency fallbacks
                          └─► input actuator:  CDP trusted events (default)
                                               physical mouse fallback (pyautogui + window guard)
```

Repository layout:

```
connect4_agent/
  engine/       bitboard, Numba solver, lockless TT, opening-book loader, ponder manager
  browser/      CDP connector, DOM reader, vision fallback, overlay, CDP input
  actuator/     physical mouse controller, global hotkeys
  state/        session tracker, game loop, incident dumps, bot PID lock
  tools/        live probes, robot-game driver, series runner
  tests/        offline suites (mocked page, no browser needed) + benchmark runners
  docs/         engineering log, demo asset
```

## Engineering highlights

- **Lockless TT**: each slot is one packed 64-bit entry (`score | bound | move | depth`) plus a
  check word `key ^ entry`; a torn (racy) read can only ever verify for the same key. All ponder
  threads share the table with no locks.
- **Per-thread move-ordering scratch**: found in live play — two threads writing the same scratch
  row at equal depth injected foreign moves (including full columns) and produced phantom children
  with corrupted scores. Fixed with per-thread buffers and an invalid-move guard
  (`engine.invalid_moves` is 0 in a healthy run).
- **Generation-guarded ponder workers** at `BELOW_NORMAL` OS priority: they yield CPU to the
  input path, which dropped CDP click latency from 2.0–2.5 s to 0.6–0.8 s.
- **Reader hardening against a live UI**: invisible nickname duplicates, per-side disc colors,
  CSS-class-based ownership, drop animations, hover placeholders, ad-driven layout shifts.
- **Clock discipline**: per-move deadline plus a total-bank share
  `(bank − margin) / remaining own moves`.

Full post-mortems: [docs/ENGINEERING_LOG.md](connect4_agent/docs/ENGINEERING_LOG.md).

## Quick start (offline)

```bash
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r connect4_agent/requirements.txt
.venv\Scripts\python connect4_agent/run.py --selftest        # engine warm-up + sanity values
.venv\Scripts\python connect4_agent/tests/test_stage5_offline.py   # and the other *_offline suites
```

All `*_offline` suites are self-contained (mocked page, no browser, no network).

## Live harness (optional)

```bash
msedge.exe --remote-debugging-port=9222        # or any Chromium-based browser
.venv\Scripts\python connect4_agent/run.py --live
# hotkeys: F7 auto/hint · F8 pause · F9 resync · double-Esc exit
```

Input mode is `cdp` by default (the OS cursor is never touched and the window does not need
focus); `INPUT_MODE = "physical"` in `config.py` switches to the pyautogui fallback.

## Opening book (not shipped)

The engine reaches full strength with an optional opening book (16.5M positions, compact `.npz`,
≈40 MB). It is **intentionally not included**: the reference book data is published by Pascal Pons
under **AGPL-3.0** and is not redistributable inside this MIT-licensed project. The loader
(`engine/opening_book.py`) documents the file format; the engine also plays standalone without it
(the decision cascade falls back to the exact solver).

## Acknowledgments & disclaimer

- The engine follows the **published algorithm and benchmarks of Pascal Pons** (bitboard
  representation, negamax with binary-search score resolution, lockless transposition table).
  His code and opening-book data are AGPL-3.0 and are **not** included in this repository.
- This project is for **research and benchmarking purposes**. Automating third-party services may
  violate their terms of use; use it only where you are authorized (for example, on your own
  account) and at your own risk.

## License

[MIT](LICENSE)
