# OCR evaluation: PP-OCR in the app (ocr_eval/engines/ppocr_scoresight.py), CI baseline (Linux)

Created 2026-10-11T13:43:30+00:00 with harness v1 on Linux 5.15.167.4-microsoft-standard-WSL2 x86_64, Python 3.13.2.

Exact = normalized exact match; Digits = same digits ignoring separators; CER = character error rate; Empty = no output; Post-filter = exact match after ScoreSight's whitelist and format regex for the field type. Percentages with 95% confidence intervals (Wilson; CER: bootstrap). Latency per crop in ms, p50 / p95.

## textocr_scoreboards (1276 crops)

Real scoreboard and clock crops cut from Open Images photos (CC BY), with TextOCR's human transcriptions.

| Engine:variant | Exact % | Digits % | CER % | Empty % | Post-filter exact % | ms single | ms batch | Load s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ppocr-app:accurate | 94.7 (93.4–95.8) | 95.7 | 3.0 (2.2–3.9) | 0.1 | 94.7 (93.4–95.8) | 12.4 / 13.8 | 11.0 / 11.9 | 1.5 |
| ppocr-app:fast | 90.8 (89.0–92.2) | 91.8 | 5.8 (4.7–7.0) | 2.0 | 90.8 (89.0–92.2) | 3.3 / 3.9 | 2.3 / 2.6 | 0.044 |

### By field type (exact %, 95% CI)

| Engine:variant | clock (n=139) | number (n=948) | other (n=4) | text (n=185) |
|---|---:|---:|---:|---:|
| ppocr-app:accurate | 84.2 (77.2–89.3) | 96.1 (94.7–97.2) | 50.0 (15.0–85.0) | 96.8 (93.1–98.5) |
| ppocr-app:fast | 79.1 (71.6–85.1) | 92.4 (90.5–93.9) | 25.0 (4.6–69.9) | 92.4 (87.7–95.4) |

### By display technology (exact %, 95% CI)

| Engine:variant | broadcast (n=69) | bulb (n=60) | dotmatrix (n=458) | flip (n=94) | lcd (n=74) | led7 (n=353) | printed (n=168) |
|---|---:|---:|---:|---:|---:|---:|---:|
| ppocr-app:accurate | 95.7 (88.0–98.5) | 96.7 (88.6–99.1) | 95.6 (93.3–97.2) | 96.8 (91.0–98.9) | 79.7 (69.2–87.3) | 94.6 (91.8–96.5) | 97.0 (93.2–98.7) |
| ppocr-app:fast | 91.3 (82.3–96.0) | 81.7 (70.1–89.4) | 92.1 (89.3–94.3) | 94.7 (88.1–97.7) | 68.9 (57.7–78.3) | 92.4 (89.1–94.7) | 94.0 (89.4–96.7) |

### By split (exact %, 95% CI)

| Engine:variant | dev (n=268) | test (n=1008) |
|---|---:|---:|
| ppocr-app:accurate | 92.5 (88.8–95.1) | 95.3 (93.8–96.5) |
| ppocr-app:fast | 88.4 (84.0–91.7) | 91.4 (89.5–93.0) |

<details><summary>Errors of ppocr-app:accurate (first 25 of 67)</summary>

| id | truth | read | post-filter |
|---|---|---|---|
| 00792db6bb86e0e2_23 | 0:05 | 0.05 | ∅ |
| 013a40f4c388e5b6_98 | 7 | 1 | 1 |
| 025532b54c27c825_4 | 0 | 10 | 10 |
| 04d8d2a90fa1e971_57 | 4 | 8 | 8 |
| 0684ea3155f00794_12 | 3:44 | 199 | ∅ |
| 0684ea3155f00794_14 | 17 | 00 | 00 |
| 071cbc2a74310c4c_3 | 1:25 | 1251 | ∅ |
| 07f3049deeb13d8a_85 | 03 | 033 | 033 |
| 0c59f697a9e3b219_17 | 9:17 | 4:17 | 4:17 |
| 0dcbcc3547b05310_36 | 0 | 1 | 1 |
| 0f8a4d564b264981_54 | 3 | 5 | 5 |
| 112cfdfdeeea5d2f_7 | 05:57 | 0557 | ∅ |
| 11b999ea4caea71c_1 | 89.6 | 896 | ∅ |
| 139bf8dea434ff39_1 | 19:11 | 19:18 | 19:18 |
| 139bf8dea434ff39_2 | 31.0 | 310 | ∅ |
| 145cf4f1c828068a_1 | 20:56 | 2056 | ∅ |
| 1aad647ea6f88a33_2 | 3:25 | 325 | ∅ |
| 1d4a0f82dae4d4da_13 | 12:54 | 12:.54 | ∅ |
| 228f894ef8c27a54_49 | OUTS | DUTS | DUTS |
| 23dbccf70ed6ee45_23 | 4 | 7 | 7 |
| 23dbccf70ed6ee45_36 | 4 | 7 | 7 |
| 265ef87e5c269ff5_260 | 2 | 1 | 1 |
| 2931cd38928e811f_32 | 3 | 8 | 8 |
| 2931cd38928e811f_38 | 12:06 | 1206 | ∅ |
| 2931cd38928e811f_45 | 3 | 8 | 8 |

</details>

## commons_scoreboards (1044 crops)

Real scoreboard fields (scores, clocks, shot clocks, periods, fouls ...) cut from Wikimedia Commons photos of physical scoreboards, labelled field by field.

| Engine:variant | Exact % | Digits % | CER % | Empty % | Post-filter exact % | ms single | ms batch | Load s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ppocr-app:accurate | 94.8 (93.3–96.0) | 95.1 | 2.5 (1.8–3.3) | 0.5 | 94.3 (92.8–95.6) | 13.2 / 14.8 | 10.7 / 11.3 | 0.003 |
| ppocr-app:fast | 88.1 (86.0–90.0) | 89.3 | 7.1 (5.9–8.5) | 1.9 | 87.6 (85.5–89.5) | 3.4 / 5.3 | 2.5 / 2.7 | 0.004 |

### By field type (exact %, 95% CI)

| Engine:variant | clock (n=156) | number (n=359) | other (n=8) | period (n=78) | score (n=309) | text (n=134) |
|---|---:|---:|---:|---:|---:|---:|
| ppocr-app:accurate | 94.2 (89.4–96.9) | 96.1 (93.6–97.7) | 100.0 (67.6–100.0) | 97.4 (91.1–99.3) | 94.8 (91.8–96.8) | 90.3 (84.1–94.2) |
| ppocr-app:fast | 79.5 (72.5–85.1) | 91.9 (88.6–94.3) | 87.5 (52.9–97.8) | 91.0 (82.6–95.6) | 91.9 (88.3–94.5) | 77.6 (69.8–83.8) |

### By display technology (exact %, 95% CI)

| Engine:variant | broadcast (n=216) | bulb (n=54) | dotmatrix (n=304) | flip (n=51) | led7 (n=411) | printed (n=8) |
|---|---:|---:|---:|---:|---:|---:|
| ppocr-app:accurate | 99.5 (97.4–99.9) | 85.2 (73.4–92.3) | 92.1 (88.5–94.6) | 96.1 (86.8–98.9) | 95.4 (92.9–97.0) | 100.0 (67.6–100.0) |
| ppocr-app:fast | 92.1 (87.8–95.0) | 64.8 (51.5–76.2) | 85.5 (81.1–89.0) | 92.2 (81.5–96.9) | 90.3 (87.0–92.8) | 100.0 (67.6–100.0) |

### By split (exact %, 95% CI)

| Engine:variant | dev (n=142) | test (n=902) |
|---|---:|---:|
| ppocr-app:accurate | 99.3 (96.1–99.9) | 94.1 (92.4–95.5) |
| ppocr-app:fast | 93.0 (87.5–96.1) | 87.4 (85.0–89.4) |

<details><summary>Errors of ppocr-app:accurate (first 25 of 54)</summary>

| id | truth | read | post-filter |
|---|---|---|---|
| cm118158456_away_name | KARAGÜMRÜK | KARAGOMROK | KARAGOMROK |
| cm118158456_away_score | 0 | 1 | 1 |
| cm118158456_home_score | 0 | 1 | 1 |
| cm121646772_batter_runs_2 | 0 | 880 | 880 |
| cm121646772_runs | 251 | 257 | 257 |
| cm12276495_home_name | MICHIGAN | MCIW | MCIW |
| cm12354372_home_name | MICHIGAN | MICHIOAN | MICHIOAN |
| cm13726005_away_score | 0 | ∅ | ∅ |
| cm13726005_home_score | 0 | ∅ | ∅ |
| cm13726005_penalty_player | Špirko | Spirko | Spirko |
| cm13726446_home_score | 1 | 0 | 0 |
| cm13727092_clock | 11:24 | 1:24 | 1:24 |
| cm13742585_clock | 12:31 | 02:30 | 02:30 |
| cm143254826_clock | 00.0 | 000 | ∅ |
| cm14522151_away_score | 1 | 0 | 0 |
| cm14522202_away_score | 3 | 33 | 33 |
| cm14522216_away_score | 3 | ∅ | ∅ |
| cm14522216_home_score | 3 | ∅ | ∅ |
| cm15541118_away_name | GÄSTE | GASTE | GASTE |
| cm155701956_away_name | BIG GREEN | BIGGREEH | BIGGREEH |
| cm17263998_home_score | 13 | 03 | 03 |
| cm17264001_home_name | HARVARD | HARUARD | HARUARD |
| cm177793186_away_name | GÄSTE | GASTE | GASTE |
| cm18346109_penalty_time | 1:11 | 111 | ∅ |
| cm1885036_away_score | 18 | 8 | 8 |

</details>

## synthetic_7seg (56 crops)

Rendered 7-segment LED and LCD digits (scores, clocks, periods): a synthetic control set, not a measure of real-world accuracy.

| Engine:variant | Exact % | Digits % | CER % | Empty % | Post-filter exact % | ms single | ms batch | Load s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ppocr-app:accurate | 100.0 (93.6–100.0) | 100.0 | 0.0 (0.0–0.0) | 0.0 | 100.0 (93.6–100.0) | 14.2 / 15.7 | 12.7 / 13.3 | 0.003 |
| ppocr-app:fast | 100.0 (93.6–100.0) | 100.0 | 0.0 (0.0–0.0) | 0.0 | 100.0 (93.6–100.0) | 3.6 / 6.0 | 2.5 / 2.6 | 0.005 |

### By field type (exact %, 95% CI)

| Engine:variant | clock (n=20) | period (n=8) | score (n=28) |
|---|---:|---:|---:|
| ppocr-app:accurate | 100.0 (83.9–100.0) | 100.0 (67.6–100.0) | 100.0 (87.9–100.0) |
| ppocr-app:fast | 100.0 (83.9–100.0) | 100.0 (67.6–100.0) | 100.0 (87.9–100.0) |

### By display technology (exact %, 95% CI)

| Engine:variant | lcd (n=15) | led7 (n=41) |
|---|---:|---:|
| ppocr-app:accurate | 100.0 (79.6–100.0) | 100.0 (91.4–100.0) |
| ppocr-app:fast | 100.0 (79.6–100.0) | 100.0 (91.4–100.0) |

### By split (exact %, 95% CI)

| Engine:variant | dev (n=8) | test (n=48) |
|---|---:|---:|
| ppocr-app:accurate | 100.0 (67.6–100.0) | 100.0 (92.6–100.0) |
| ppocr-app:fast | 100.0 (67.6–100.0) | 100.0 (92.6–100.0) |
