# OCR evaluation: Tesseract baseline on commons_scoreboards (Linux)

Created 2026-10-11T13:39:51+00:00 with harness v1 on Linux 5.15.167.4-microsoft-standard-WSL2 x86_64, Python 3.13.2.

Exact = normalized exact match; Digits = same digits ignoring separators; CER = character error rate; Empty = no output; Post-filter = exact match after ScoreSight's whitelist and format regex for the field type. Percentages with 95% confidence intervals (Wilson; CER: bootstrap). Latency per crop in ms, p50 / p95.

## commons_scoreboards (1044 crops)

Real scoreboard fields (scores, clocks, shot clocks, periods, fouls ...) cut from Wikimedia Commons photos of physical scoreboards, labelled field by field.

| Engine:variant | Exact % | Digits % | CER % | Empty % | Post-filter exact % | ms single | ms batch | Load s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| tesseract:tuned | 58.0 (54.9–60.9) | 60.9 | 29.3 (26.7–32.3) | 5.2 | 57.8 (54.7–60.7) | 2.1 / 6.1 | 2.1 / 6.1 | 0.116 |
| tesseract:eng-nobin | 52.8 (49.7–55.8) | 54.9 | 34.6 (31.6–38.1) | 8.5 | 52.6 (49.5–55.6) | 2.8 / 9.0 | 2.8 / 9.0 | 0.12 |
| tesseract:eng | 47.4 (44.4–50.4) | 50.2 | 42.1 (38.9–45.4) | 10.0 | 47.3 (44.3–50.3) | 2.8 / 10.2 | 2.8 / 10.2 | 0.148 |
| tesseract:scoreboard_general-nobin | 44.4 (41.5–47.5) | 45.3 | 65.5 (61.8–69.1) | 3.7 | 44.3 (41.3–47.3) | 1.5 / 4.4 | 1.5 / 4.4 | 0.017 |
| tesseract:scoreboard_general | 40.5 (37.6–43.5) | 41.1 | 69.2 (65.9–72.4) | 4.4 | 40.4 (37.5–43.4) | 1.6 / 4.9 | 1.6 / 4.9 | 0.747 |
| tesseract:scoreboard_general_large-nobin | 37.4 (34.5–40.3) | 38.2 | 68.0 (64.8–71.1) | 3.1 | 37.4 (34.5–40.3) | 4.9 / 15.9 | 4.9 / 15.9 | 0.026 |
| tesseract:scoreboard_general_large | 33.9 (31.1–36.8) | 34.8 | 71.4 (68.2–74.4) | 3.5 | 33.8 (31.0–36.7) | 4.9 / 17.1 | 4.9 / 17.1 | 0.03 |
| tesseract:daktronics-nobin | 22.4 (20.0–25.0) | 22.9 | 79.5 (77.3–81.5) | 5.1 | 22.3 (19.9–24.9) | 1.6 / 4.1 | 1.6 / 4.1 | 0.016 |
| tesseract:daktronics | 20.2 (17.9–22.8) | 20.6 | 83.0 (80.9–85.1) | 4.5 | 20.1 (17.8–22.7) | 1.5 / 3.6 | 1.5 / 3.6 | 0.017 |

### By field type (exact %, 95% CI)

| Engine:variant | clock (n=156) | number (n=359) | other (n=8) | period (n=78) | score (n=309) | text (n=134) |
|---|---:|---:|---:|---:|---:|---:|
| tesseract:tuned | 29.5 (22.9–37.1) | 61.6 (56.4–66.4) | 37.5 (13.7–69.4) | 69.2 (58.3–78.4) | 65.4 (59.9–70.5) | 59.0 (50.5–66.9) |
| tesseract:eng-nobin | 32.7 (25.8–40.4) | 52.4 (47.2–57.5) | 25.0 (7.1–59.1) | 60.3 (49.2–70.4) | 62.8 (57.3–68.0) | 51.5 (43.1–59.8) |
| tesseract:eng | 22.4 (16.6–29.6) | 52.1 (46.9–57.2) | 50.0 (21.5–78.5) | 52.6 (41.6–63.3) | 55.3 (49.8–60.8) | 42.5 (34.5–51.0) |
| tesseract:scoreboard_general-nobin | 17.9 (12.7–24.7) | 59.3 (54.2–64.3) | 0.0 (0.0–32.4) | 71.8 (61.0–80.6) | 54.0 (48.5–59.5) | 0.0 (0.0–2.8) |
| tesseract:scoreboard_general | 16.0 (11.1–22.6) | 53.2 (48.0–58.3) | 0.0 (0.0–32.4) | 69.2 (58.3–78.4) | 49.5 (44.0–55.1) | 0.0 (0.0–2.8) |
| tesseract:scoreboard_general_large-nobin | 12.2 (7.9–18.2) | 49.6 (44.4–54.7) | 12.5 (2.2–47.1) | 69.2 (58.3–78.4) | 44.7 (39.2–50.2) | 0.0 (0.0–2.8) |
| tesseract:scoreboard_general_large | 9.0 (5.4–14.5) | 42.9 (37.9–48.1) | 0.0 (0.0–32.4) | 64.1 (53.0–73.9) | 44.0 (38.6–49.6) | 0.0 (0.0–2.8) |
| tesseract:daktronics-nobin | 0.6 (0.1–3.5) | 24.5 (20.3–29.2) | 0.0 (0.0–32.4) | 42.3 (32.0–53.4) | 36.2 (31.1–41.7) | 0.0 (0.0–2.8) |
| tesseract:daktronics | 0.0 (0.0–2.4) | 22.8 (18.8–27.5) | 0.0 (0.0–32.4) | 42.3 (32.0–53.4) | 31.1 (26.2–36.4) | 0.0 (0.0–2.8) |

### By display technology (exact %, 95% CI)

| Engine:variant | broadcast (n=216) | bulb (n=54) | dotmatrix (n=304) | flip (n=51) | led7 (n=411) | printed (n=8) |
|---|---:|---:|---:|---:|---:|---:|
| tesseract:tuned | 79.6 (73.8–84.5) | 38.9 (27.0–52.2) | 57.2 (51.6–62.7) | 72.5 (59.1–82.9) | 47.9 (43.1–52.8) | 50.0 (21.5–78.5) |
| tesseract:eng-nobin | 72.7 (66.4–78.2) | 37.0 (25.4–50.4) | 50.3 (44.7–55.9) | 62.7 (49.0–74.7) | 45.0 (40.3–49.9) | 50.0 (21.5–78.5) |
| tesseract:eng | 61.6 (54.9–67.8) | 27.8 (17.6–40.9) | 43.4 (38.0–49.0) | 68.6 (55.0–79.7) | 43.1 (38.4–47.9) | 37.5 (13.7–69.4) |
| tesseract:scoreboard_general-nobin | 21.3 (16.4–27.2) | 55.6 (42.4–68.0) | 34.9 (29.7–40.4) | 29.4 (18.7–43.0) | 65.0 (60.2–69.4) | 0.0 (0.0–32.4) |
| tesseract:scoreboard_general | 19.4 (14.7–25.2) | 55.6 (42.4–68.0) | 31.2 (26.3–36.7) | 23.5 (14.0–36.8) | 59.4 (54.5–64.0) | 0.0 (0.0–32.4) |
| tesseract:scoreboard_general_large-nobin | 24.5 (19.3–30.7) | 46.3 (33.7–59.4) | 28.3 (23.5–33.6) | 31.4 (20.3–45.0) | 51.1 (46.3–55.9) | 0.0 (0.0–32.4) |
| tesseract:scoreboard_general_large | 22.7 (17.6–28.7) | 44.4 (32.0–57.6) | 26.0 (21.4–31.2) | 25.5 (15.6–38.9) | 46.0 (41.2–50.8) | 0.0 (0.0–32.4) |
| tesseract:daktronics-nobin | 18.1 (13.5–23.7) | 22.2 (13.2–34.9) | 16.8 (13.0–21.4) | 19.6 (11.0–32.5) | 29.7 (25.5–34.3) | 0.0 (0.0–32.4) |
| tesseract:daktronics | 14.8 (10.7–20.2) | 22.2 (13.2–34.9) | 15.8 (12.1–20.3) | 21.6 (12.5–34.6) | 26.3 (22.3–30.7) | 0.0 (0.0–32.4) |

### By split (exact %, 95% CI)

| Engine:variant | dev (n=142) | test (n=902) |
|---|---:|---:|
| tesseract:tuned | 67.6 (59.5–74.8) | 56.4 (53.2–59.6) |
| tesseract:eng-nobin | 59.9 (51.6–67.6) | 51.7 (48.4–54.9) |
| tesseract:eng | 55.6 (47.4–63.5) | 46.1 (42.9–49.4) |
| tesseract:scoreboard_general-nobin | 39.4 (31.8–47.6) | 45.2 (42.0–48.5) |
| tesseract:scoreboard_general | 39.4 (31.8–47.6) | 40.7 (37.5–43.9) |
| tesseract:scoreboard_general_large-nobin | 35.2 (27.8–43.4) | 37.7 (34.6–40.9) |
| tesseract:scoreboard_general_large | 30.3 (23.3–38.3) | 34.5 (31.4–37.6) |
| tesseract:daktronics-nobin | 21.1 (15.2–28.6) | 22.6 (20.0–25.5) |
| tesseract:daktronics | 21.1 (15.2–28.6) | 20.1 (17.6–22.8) |

<details><summary>Errors of tesseract:tuned (first 25 of 439)</summary>

| id | truth | read | post-filter |
|---|---|---|---|
| cm10782695_away_timeouts | 3 | ∅ | ∅ |
| cm10782695_clock | 3:45 | 3 | ∅ |
| cm10782695_home_score | 9 | 1 | 1 |
| cm10782695_other | 0 | ∅ | ∅ |
| cm10782695_other_3 | 3 | ∅ | ∅ |
| cm10782695_other_5 | 0 | ∅ | ∅ |
| cm10810202_away_score | 34 | 4 | 4 |
| cm10810202_down | 4 | 14 | 14 |
| cm10810202_home_score | 31 | 3 | 3 |
| cm110212961_away_score | 45 | 49 | 49 |
| cm110212961_clock | 0:00 | 4   . 0 | 4.0 |
| cm110212961_down | 1 | ∅ | ∅ |
| cm110212961_home_score | 24 | 4 | 4 |
| cm110212961_to_go | 10 | 1 | 1 |
| cm110947456_clock | 4:13 | ∅ | ∅ |
| cm110947456_clock_2 | 4:13 | 1413 | ∅ |
| cm11219820_clock | 90:00 | : 540 | ∅ |
| cm118158456_away_name | KARAGÜMRÜK | YARASUMRUE | YARASUMRUE |
| cm118158456_away_score | 0 | 1 | 1 |
| cm118158456_clock | 90:00 | 0:00 | 0:00 |
| cm118158456_home_score | 0 | 1 | 1 |
| cm11907497_away_name | CZECH REP | C2ECH REP | C2ECH REP |
| cm11907497_away_score | 66 | 6 | 6 |
| cm11907497_period | 4 | 141 | ∅ |
| cm121544991_runs | 41 | 4 | 4 |

</details>
