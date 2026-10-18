| mode | solve rate (mean, min–max) | window 1 / 2 / 3 | attempts / solved (task) | attempts / solved (incl. learning) | mutations | KEEP / ROLLBACK | decide µs p50 / p99 | mutate ms p50 | rollback ms p50 | restart ms | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| static | 94.0% (90%–97%) | 100% / 86% / 96% | 3.35 | 3.35 | 0.0 | 0.0 / 0.0 | 868 / 1285 | – | – | – | 8 |
| restart | 94.0% (90%–97%) | 100% / 86% / 96% | 3.35 | 3.35 | 0.0 | 0.0 / 0.0 | 827 / 1149 | – | – | 51 | 12 |
| adaptive | 98.0% (97%–98%) | 100% / 94% / 100% | 2.45 | 5.23 | 10.4 | 6.2 / 4.2 | 725 / 1406 | 20.2 | 3.7 | – | 13 |
| adaptive-nogate | 98.0% (97%–98%) | 100% / 94% / 100% | 2.45 | 2.90 | 9.4 | 9.4 / 0.0 | 714 / 1220 | 24.0 | – | – | 8 |
