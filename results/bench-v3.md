| mode | solve rate (mean, min–max) | window 1 / 2 / 3 | attempts / solved (task) | attempts / solved (incl. learning) | mutations | KEEP / ROLLBACK | decide µs p50 / p99 | mutate ms p50 | rollback ms p50 | restart ms | wall s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| static | 94.0% (90%–97%) | 100% / 86% / 96% | 3.35 | 3.35 | 0.0 | 0.0 / 0.0 | 2101 / 3619 | – | – | – | 8 |
| restart | 94.0% (90%–97%) | 100% / 86% / 96% | 3.35 | 3.35 | 0.0 | 0.0 / 0.0 | 2170 / 3048 | – | – | 86 | 13 |
| adaptive | 98.0% (97%–98%) | 100% / 94% / 100% | 2.45 | 5.23 | 10.4 | 6.2 / 4.2 | 1739 / 2909 | 73.2 | 8.6 | – | 14 |
| adaptive-nogate | 98.0% (97%–98%) | 100% / 94% / 100% | 2.45 | 2.90 | 9.4 | 9.4 / 0.0 | 1215 / 2889 | 73.5 | – | – | 9 |
