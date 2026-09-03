# Backtest Audit Log

Persistent audit trail written by the `@backtest-auditor` agent.
One file per audit: `<backtest-name>_<UTC-date>.md`.
Each records: verdict (PASS/WARN/FAIL), whether the headline number reproduced, findings by class (A-data / B-wrong-thing / C-instructions / D-statistical), what passed, and what could not be checked.
