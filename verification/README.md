# Verification records

The "Hybrid Keys" redesign was built in steps (see
[docs/agentic-dev.md](../docs/agentic-dev.md)). After each step's
implementation, a fresh verification agent re-ran the suite, compared the
screenshots with the design, reviewed and cleaned up the code, and wrote its
verdict here: `stepNN.md`, one per step.

Each record lists what was run, every criterion of the step with its verdict
and evidence (the shot it looked at), the cleanups it made, the decisions
taken, and the gaps it left for a later step. The test files and shot names
they mention are as they were at the time: since the switch-over, the scenario
tests are `test/ui/test_<what>.py` instead of `test/ui/test_stepNN_<what>.py`,
and the app is `RosTuiApp` in `ros_tui/ui/app.py` instead of `NextApp`.
