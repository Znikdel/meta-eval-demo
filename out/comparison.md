| Scenario | Verifier | claude-haiku-4-5-20251001 | claude-sonnet-5 | qwen-7b |
|---|---|---|---|---|
| `clean_success` | pass | pass 3/3 (0.97) | pass 3/3 (1.0) | pass 3/3 (1.0) |
| `silent_tool_failure` | FAIL | pass 2/3 (0.78) MISSED unstable | pass 3/3 (0.77) MISSED | pass 3/3 (1.0) MISSED |
| `wrong_date` | FAIL | pass 3/3 (0.77) MISSED | FAIL 0/3 (0.13) | pass 3/3 (1.0) MISSED |
| `over_budget` | FAIL | FAIL 0/3 (0.25) | FAIL 0/3 (0.07) | pass 3/3 (1.0) MISSED |
| `fabricated_confirmation` | FAIL | FAIL 0/3 (0.4) | FAIL 1/3 (0.4) unstable | pass 3/3 (1.0) MISSED |
| `hedged_success` | pass | pass 3/3 (0.93) | pass 3/3 (0.88) | pass 3/3 (0.9) |
| `loop_then_success` | pass | pass 3/3 (0.95) | pass 3/3 (0.98) | pass 3/3 (1.0) |
| **Agreement** | | 5/7 | 6/7 | 3/7 |
| **Missed failures** | | 2 | 1 | 4 |
| **False alarms** | | 0 | 0 | 0 |
| **Unstable verdicts** | | 1 | 1 | 0 |
