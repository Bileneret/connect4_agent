# Engineering log — how the hard bugs were found

This project was validated end-to-end in a live environment (a real web client used as a
benchmark target). Almost every non-trivial defect below was found by running the system in
that environment and comparing its reads/decisions against independent oracles
(the reference solution file, replaying recorded games through the solver, pixel-truth of
screen frames). The pattern that paid off every time: **do not trust any single source —
cross-check state, decisions and timing against a second, independent one.**

## 1. Cross-thread corruption of move-ordering scratch buffers

*Symptom.* In live games, the exact solver occasionally claimed several "equally best" moves
where the reference solution file showed exactly one best move. In one recorded game the engine
threw away a forced win on move 5 of its own and later lost.

*Root cause.* The alpha-beta move-ordering scores lived in shared per-depth scratch arrays
(`sc_row/col_row`). Ponder worker threads and the main search both used them; when two searches
worked at the same depth, a foreign move list overwrote the current one. A column belonging to
another position (e.g. an already-full column) then produced

```python
move_bit = possible & COLUMN_MASK[col]   # == 0
cpos, cmask = play_bit(position, mask, move_bit)   # turn passed WITHOUT a stone
```

i.e. the search descended into a "phantom child" and polluted the tree with garbage scores.

*Fix.* Per-thread scratch buffers (`SolverEngine.make_scratch()` — each search thread owns its
pair), a guard that skips invalid move bits and counts them (`engine.invalid_moves`, always 0 in
a healthy run), and generation-numbered ponder workers so stale workers die immediately.
*Verification.* Replayed the lost game position-by-position: engine values match the reference
book oracle exactly after the fix (unique best move, +1 where the bug had claimed a tie).

## 2. Zombie ponder threads (stop flag cleared too early)

*Symptom.* CPU stayed saturated long after "stopping" pondering; the main solve competed with
threads that should have been gone.

*Root cause.* `stop()` set the stop flag, waited 1 s for threads to join, then **cleared the
flag** — a worker still inside a long `@njit` call saw a cleared flag when it returned and
continued with the next position.

*Fix.* A generation counter: `start()` increments it, workers capture their generation and exit
when it changes; the stop flag is never cleared by `stop()` itself.

## 3. CDP input round-trips: a single click that took 22 seconds

*Symptom.* Some live games were lost on the move clock although the engine had decided quickly.

*Root cause.* The synthetic click path walked a 14–26-step Bezier trajectory, one
`page.mouse.move()` call per step. Under full CPU load (ponder workers + browser) every CDP
round-trip costs ~0.6 s, so one click dispatch took 17–22 s.

*Fix.* One `mouse.move` flight + one atomic `mouse.click`, with the click point still randomized
inside the target cell → click round-trip dropped to ~2 s; then lowering ponder workers to
`BELOW_NORMAL` OS priority (they yield to the input path and the browser) → **0.6–0.8 s**.

## 4. The turn marker arrives late

*Symptom.* A strict state invariant ("it cannot be our turn if we own one stone more") fired
repeatedly right after our own moves and deadlocked a bot in two games.

*Root cause.* The site flips the active-timer marker **0.6–1 s after** the stone is rendered;
for that window the state "our stone is on the board AND the turn is shown as ours" is legal.

*Fix.* The invariant now checks the stone-balance only; a separate watchdog treats "we already
moved, yet the turn is still ours" persisting for > 6 s as a move that never reached the server
(phantom stone) and clears the guard so the engine plays again instead of timing out.

## 5. Clock discipline

*Symptom.* Long games ended in "won by time-up" losses: thinking consumed the whole 4-minute
bank, and the click+verification did not fit into the per-move margin.

*Fix.* Per-move deadline with an 8 s reserve for clicking/verification and a total-bank share:
`think_cap = (bank − margin) / remaining_own_moves`, so the engine spends the bank evenly instead
of exhausting it in the middlegame. Verified in live play: caps ramp 11 → 20 s, no more time-ups.

## 6. Reader hardening against a live UI

Fixes accumulated from live observations (each now covered by an offline test or a live check):

- **Invisible nickname duplicates**: the player-name lookup matched hidden DOM copies (0×0 rect)
  and mis-detected which side we play. Reader now only accepts visible elements.
- **Colors are assigned per side**, not per player: the left player's discs are light, the right
  player's dark — so ownership is taken from the piece's CSS class and only falls back to colors.
- **A broken color parser**: the computed-style regex had silently stopped matching at all
  (offline mocks used a different parser, so tests stayed green).
- **Drop-animation transients**: a freshly dropped disc may be unreadable for ~150 ms; the reader
  retries once.
- **Hover placeholder**: the hovered column's landing cell carries a `piece-hover-placeholder`
  class with a preview circle of the current player's color — which the DOM reader briefly counted
  as a real stone. Those cells are now ignored.
- **Ad-driven layout shifts**: click coordinates are re-measured immediately before the click.

## 7. Vision fallback (screen-only reading)

The computer-vision reader (mss capture, board-plate detection by color, multi-sample cell
classification) is cross-checked against the DOM cell-by-cell: **42/42 cells at two display
scales**. Two defects found this way:

- The plate profile occasionally clipped the leftmost column (when an ad panel overlaps the
  board edge), shifting the whole grid by one column → the plate box is now repaired from the
  reliable right edge and the height (`column step = height / 6`).
- A synthetic aspect-ratio guard keeps that repair exact and testable offline.

## 8. Lockless transposition table (design note)

Each 16-byte slot is one packed 64-bit entry (`score+offset | bound | column | depth`) plus a
check word stored as `key ^ entry`; a lookup accepts a slot only if `check ^ entry == key`.
A torn read (new entry + old check, or vice versa) cannot impersonate another key: the payload
occupies < 2²⁰ bits while bucket indices are a prime modulus, so the XOR-difference needed for a
false positive forces the same key — in which case the value read is a valid older bound of that
same position. The table is shared by all ponder threads without locks.

## Live-benchmark methodology (short version)

- State is trusted only if two independent readings agree (DOM vs screen pixels; stone-balance
  invariants; heights vs the engine's bitboard).
- Decisions are audited afterwards by replaying recorded games through the solver and comparing
  with the reference solution file (an independent oracle, not our own search).
- Timings are measured from logs of real games (click round-trip, think caps, clock burn), not
  from microbenchmarks alone.
