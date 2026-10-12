# 0006. Recovery exit codes derive from broker coverage

Date: 2026-10-12. Status: accepted.

## Context

`submit_entry.py`, `replace_stop.py` and `close_position.py` are resumable:
a rerun after a crash picks up from broker state. Their exit codes, however,
were classified from a process-local `cancel_sent` flag. A rerun after an
earlier process cancelled a stop and died saw no stop and no flag, so a
preflight refusal reported exit 3 ("refused; the stop still protects") and a
failed read reported exit 4 ("nothing changed"), while the position was naked
(V1-FOUNDATION defect 2, wayfinder ticket #95). Routines and the protection
monitor escalate only on exit 8, so the incident was invisible.

## Decision

Before classifying any refusal or pre-mutation read failure, each script reads
the symbol's **verified coverage** through `risk_engine.reconciliation` — the
same conservative definition `doctor.py --broker` uses (unexpired GTC stops
resting as `new` for the full held quantity). A held position without verified
coverage is exit 8 whichever process removed the stop. Exit 3 now means a
verified stop rests and nothing changed; exit 4 means nothing changed and no
uncovered position was observed. The success paths are unchanged: an OTO entry
whose leg is still `held` is not an incident at submission.

## Considered options

Keeping a per-process flag and adding a "stops present" heuristic was
rejected: a stop that is `held`, `pending_cancel`, expired or short would still
have downgraded the incident. Reusing reconciliation costs two extra GET calls
per replacement and makes those states exit 8 as well; that is the intended
conservatism — a repeat 8 is escalated to a human, a false 3 is not.
