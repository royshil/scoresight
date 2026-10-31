# OCR evaluation: Windows OCR (Windows 11 build 26200, en-US)

Created 2026-10-10T20:20:12+00:00 with harness v1 on Windows 11 AMD64, Python 3.13.2.

Exact = normalized exact match; Digits = same digits ignoring separators; CER = character error rate; Empty = no output; Post-filter = exact match after ScoreSight's whitelist and format regex for the field type. Percentages with 95% confidence intervals (Wilson; CER: bootstrap). Latency per crop in ms, p50 / p95.

## textocr_scoreboards (1276 crops)

Real scoreboard and clock crops cut from Open Images photos (CC BY), with TextOCR's human transcriptions.

| Engine:variant | Exact % | Digits % | CER % | Empty % | Post-filter exact % | ms single | ms batch | Load s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| windows-ocr:tile-digits | 25.5 (23.2–28.0) | 26.0 | 65.5 (62.3–68.9) | 62.9 | 25.9 (23.5–28.3) | 2.0 / 8.4 | 2.0 / 8.4 | 0.0 |
| windows-ocr:tile | 21.7 (19.5–24.1) | 22.0 | 68.6 (65.3–72.0) | 62.9 | 22.0 (19.8–24.4) | 2.1 / 7.9 | 2.1 / 7.9 | 0.0 |
| windows-ocr:upscale-digits | 15.4 (13.5–17.4) | 15.7 | 72.3 (69.3–75.4) | 80.9 | 15.6 (13.7–17.7) | 0.6 / 2.5 | 0.6 / 2.5 | 0.0 |
| windows-ocr:upscale | 15.1 (13.3–17.2) | 15.5 | 72.9 (69.9–76.0) | 80.9 | 15.5 (13.6–17.6) | 0.7 / 3.1 | 0.7 / 3.1 | 0.0 |
| windows-ocr:raw-digits | 6.6 (5.3–8.1) | 6.6 | 86.8 (84.2–89.4) | 91.2 | 6.6 (5.3–8.1) | 0.2 / 1.4 | 0.2 / 1.4 | 0.0 |
| windows-ocr:raw | 6.3 (5.1–7.8) | 6.6 | 87.4 (84.8–89.9) | 91.2 | 6.6 (5.3–8.1) | 0.2 / 1.4 | 0.2 / 1.4 | 0.01 |

### By field type (exact %, 95% CI)

| Engine:variant | clock (n=139) | number (n=948) | other (n=4) | text (n=185) |
|---|---:|---:|---:|---:|
| windows-ocr:tile-digits | 22.3 (16.2–29.9) | 21.8 (19.3–24.6) | 0.0 (0.0–49.0) | 47.6 (40.5–54.7) |
| windows-ocr:tile | 21.6 (15.6–29.1) | 16.8 (14.5–19.3) | 0.0 (0.0–49.0) | 47.6 (40.5–54.7) |
| windows-ocr:upscale-digits | 21.6 (15.6–29.1) | 9.8 (8.1–11.9) | 0.0 (0.0–49.0) | 39.5 (32.7–46.7) |
| windows-ocr:upscale | 20.9 (14.9–28.4) | 9.6 (7.9–11.6) | 0.0 (0.0–49.0) | 39.5 (32.7–46.7) |
| windows-ocr:raw-digits | 9.4 (5.5–15.3) | 3.2 (2.2–4.5) | 0.0 (0.0–49.0) | 22.2 (16.8–28.7) |
| windows-ocr:raw | 7.9 (4.5–13.6) | 3.1 (2.1–4.4) | 0.0 (0.0–49.0) | 22.2 (16.8–28.7) |

### By display technology (exact %, 95% CI)

| Engine:variant | broadcast (n=69) | bulb (n=60) | dotmatrix (n=458) | flip (n=94) | lcd (n=74) | led7 (n=353) | printed (n=168) |
|---|---:|---:|---:|---:|---:|---:|---:|
| windows-ocr:tile-digits | 39.1 (28.5–50.9) | 11.7 (5.8–22.2) | 31.9 (27.8–36.3) | 23.4 (16.0–32.9) | 4.1 (1.4–11.2) | 13.6 (10.4–17.6) | 43.5 (36.2–51.0) |
| windows-ocr:tile | 39.1 (28.5–50.9) | 5.0 (1.7–13.7) | 26.9 (23.0–31.1) | 13.8 (8.3–22.2) | 4.1 (1.4–11.2) | 9.9 (7.2–13.5) | 43.5 (36.2–51.0) |
| windows-ocr:upscale-digits | 29.0 (19.6–40.6) | 0.0 (0.0–6.0) | 19.0 (15.7–22.8) | 9.6 (5.1–17.2) | 4.1 (1.4–11.2) | 5.4 (3.5–8.2) | 34.5 (27.8–42.0) |
| windows-ocr:upscale | 29.0 (19.6–40.6) | 0.0 (0.0–6.0) | 18.8 (15.5–22.6) | 9.6 (5.1–17.2) | 4.1 (1.4–11.2) | 5.1 (3.2–7.9) | 33.9 (27.2–41.4) |
| windows-ocr:raw-digits | 10.1 (5.0–19.5) | 0.0 (0.0–6.0) | 6.6 (4.6–9.2) | 4.3 (1.7–10.4) | 2.7 (0.7–9.3) | 2.0 (1.0–4.0) | 20.2 (14.9–27.0) |
| windows-ocr:raw | 10.1 (5.0–19.5) | 0.0 (0.0–6.0) | 6.3 (4.4–8.9) | 4.3 (1.7–10.4) | 2.7 (0.7–9.3) | 1.7 (0.8–3.7) | 19.6 (14.3–26.3) |

### By split (exact %, 95% CI)

| Engine:variant | dev (n=268) | test (n=1008) |
|---|---:|---:|
| windows-ocr:tile-digits | 15.3 (11.5–20.1) | 28.3 (25.6–31.1) |
| windows-ocr:tile | 13.1 (9.5–17.6) | 24.0 (21.5–26.7) |
| windows-ocr:upscale-digits | 6.3 (4.0–9.9) | 17.8 (15.5–20.2) |
| windows-ocr:upscale | 5.6 (3.4–9.0) | 17.7 (15.4–20.1) |
| windows-ocr:raw-digits | 4.1 (2.3–7.2) | 7.2 (5.8–9.0) |
| windows-ocr:raw | 3.4 (1.8–6.3) | 7.1 (5.7–8.9) |

<details><summary>Errors of windows-ocr:tile-digits (first 25 of 950)</summary>

| id | truth | read | post-filter |
|---|---|---|---|
| 00792db6bb86e0e2_19 | 0:00 | ∅ | ∅ |
| 00792db6bb86e0e2_22 | 5 | ∅ | ∅ |
| 00792db6bb86e0e2_23 | 0:05 | ∅ | ∅ |
| 00918f59a42f88f5_2 | 5:21 | ∅ | ∅ |
| 00918f59a42f88f5_4 | 19 | ∅ | ∅ |
| 00d480fe5f01a039_1 | 10 | ∅ | ∅ |
| 00d480fe5f01a039_2 | 1 | ∅ | ∅ |
| 00dd785b54674737_1 | 0 | ∅ | ∅ |
| 00dd785b54674737_2 | 1 | ∅ | ∅ |
| 00dd785b54674737_4 | VISITORS | I VISITORS I | I VISITORS I |
| 012929dbb05a8ddf_41 | 2 | ∅ | ∅ |
| 012929dbb05a8ddf_47 | 1 | ∅ | ∅ |
| 013a40f4c388e5b6_101 | R | ∅ | ∅ |
| 013a40f4c388e5b6_102 | H | ∅ | ∅ |
| 013a40f4c388e5b6_109 | 0 | ∅ | ∅ |
| 013a40f4c388e5b6_116 | 0 | ∅ | ∅ |
| 013a40f4c388e5b6_122 | 2 | 0 | 0 |
| 013a40f4c388e5b6_129 | 6 | ∅ | ∅ |
| 013a40f4c388e5b6_131 | 1 | 0 | 0 |
| 013a40f4c388e5b6_93 | 2 | ∅ | ∅ |
| 013a40f4c388e5b6_98 | 7 | ∅ | ∅ |
| 016894011b8686b4_33 | 12:00 | ∅ | ∅ |
| 016894011b8686b4_36 | 0 | ∅ | ∅ |
| 016894011b8686b4_40 | 6 | ∅ | ∅ |
| 016894011b8686b4_42 | 0 | ∅ | ∅ |

</details>

## synthetic_7seg (56 crops)

Rendered 7-segment LED and LCD digits (scores, clocks, periods): a synthetic control set, not a measure of real-world accuracy.

| Engine:variant | Exact % | Digits % | CER % | Empty % | Post-filter exact % | ms single | ms batch | Load s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| windows-ocr:tile | 10.7 (5.0–21.5) | 10.7 | 93.1 (84.4–100.6) | 80.4 | 10.7 (5.0–21.5) | 2.7 / 6.4 | 2.7 / 6.4 | 0.0 |
| windows-ocr:tile-digits | 10.7 (5.0–21.5) | 10.7 | 92.4 (83.5–100.0) | 80.4 | 10.7 (5.0–21.5) | 3.0 / 6.3 | 3.0 / 6.3 | 0.001 |
| windows-ocr:upscale | 5.4 (1.8–14.6) | 5.4 | 95.1 (88.6–100.0) | 94.6 | 5.4 (1.8–14.6) | 0.8 / 1.8 | 0.8 / 1.8 | 0.0 |
| windows-ocr:upscale-digits | 5.4 (1.8–14.6) | 5.4 | 95.1 (88.6–100.0) | 94.6 | 5.4 (1.8–14.6) | 0.8 / 1.8 | 0.8 / 1.8 | 0.0 |
| windows-ocr:raw | 3.6 (1.0–12.1) | 3.6 | 95.1 (88.8–100.0) | 92.9 | 3.6 (1.0–12.1) | 0.2 / 1.0 | 0.2 / 1.0 | 0.0 |
| windows-ocr:raw-digits | 3.6 (1.0–12.1) | 3.6 | 95.1 (88.8–100.0) | 92.9 | 3.6 (1.0–12.1) | 0.3 / 1.0 | 0.3 / 1.0 | 0.0 |

### By field type (exact %, 95% CI)

| Engine:variant | clock (n=20) | period (n=8) | score (n=28) |
|---|---:|---:|---:|
| windows-ocr:tile | 10.0 (2.8–30.1) | 12.5 (2.2–47.1) | 10.7 (3.7–27.2) |
| windows-ocr:tile-digits | 10.0 (2.8–30.1) | 12.5 (2.2–47.1) | 10.7 (3.7–27.2) |
| windows-ocr:upscale | 5.0 (0.9–23.6) | 0.0 (0.0–32.4) | 7.1 (2.0–22.7) |
| windows-ocr:upscale-digits | 5.0 (0.9–23.6) | 0.0 (0.0–32.4) | 7.1 (2.0–22.7) |
| windows-ocr:raw | 5.0 (0.9–23.6) | 0.0 (0.0–32.4) | 3.6 (0.6–17.7) |
| windows-ocr:raw-digits | 5.0 (0.9–23.6) | 0.0 (0.0–32.4) | 3.6 (0.6–17.7) |

### By display technology (exact %, 95% CI)

| Engine:variant | lcd (n=15) | led7 (n=41) |
|---|---:|---:|
| windows-ocr:tile | 6.7 (1.2–29.8) | 12.2 (5.3–25.5) |
| windows-ocr:tile-digits | 6.7 (1.2–29.8) | 12.2 (5.3–25.5) |
| windows-ocr:upscale | 6.7 (1.2–29.8) | 4.9 (1.4–16.1) |
| windows-ocr:upscale-digits | 6.7 (1.2–29.8) | 4.9 (1.4–16.1) |
| windows-ocr:raw | 0.0 (0.0–20.4) | 4.9 (1.4–16.1) |
| windows-ocr:raw-digits | 0.0 (0.0–20.4) | 4.9 (1.4–16.1) |

### By split (exact %, 95% CI)

| Engine:variant | dev (n=8) | test (n=48) |
|---|---:|---:|
| windows-ocr:tile | 0.0 (0.0–32.4) | 12.5 (5.9–24.7) |
| windows-ocr:tile-digits | 0.0 (0.0–32.4) | 12.5 (5.9–24.7) |
| windows-ocr:upscale | 0.0 (0.0–32.4) | 6.2 (2.1–16.8) |
| windows-ocr:upscale-digits | 0.0 (0.0–32.4) | 6.2 (2.1–16.8) |
| windows-ocr:raw | 0.0 (0.0–32.4) | 4.2 (1.1–14.0) |
| windows-ocr:raw-digits | 0.0 (0.0–32.4) | 4.2 (1.1–14.0) |

<details><summary>Errors of windows-ocr:tile (first 25 of 50)</summary>

| id | truth | read | post-filter |
|---|---|---|---|
| syn7_score_0_2_56 | 0 | ∅ | ∅ |
| syn7_score_0_3_28 | 0 | ∅ | ∅ |
| syn7_score_3_0_28 | 3 | ∅ | ∅ |
| syn7_score_7_2_56 | 7 | ∅ | ∅ |
| syn7_score_7_1_56 | 7 | ∅ | ∅ |
| syn7_score_9_1_40 | 9 | ∅ | ∅ |
| syn7_score_9_0_40 | 9 | ∅ | ∅ |
| syn7_score_12_0_56 | 12 | ∅ | ∅ |
| syn7_score_12_3_28 | 12 | ∅ | ∅ |
| syn7_score_21_0_28 | 21 | ∅ | ∅ |
| syn7_score_21_1_56 | 21 | ∅ | ∅ |
| syn7_score_45_0_28 | 45 | ∅ | ∅ |
| syn7_score_45_1_56 | 45 | ∅ | ∅ |
| syn7_score_58_3_28 | 58 | ∅ | ∅ |
| syn7_score_58_0_56 | 58 | ∅ | ∅ |
| syn7_score_99_2_40 | 99 | ∅ | ∅ |
| syn7_score_99_0_28 | 99 | ∅ | ∅ |
| syn7_score_105_0_40 | 105 | ∅ | ∅ |
| syn7_score_105_3_40 | 105 | 11—1 D | 111 |
| syn7_score_118_2_56 | 118 | ∅ | ∅ |
| syn7_score_118_3_28 | 118 | ∅ | ∅ |
| syn7_score_147_3_40 | 147 | ∅ | ∅ |
| syn7_score_147_0_40 | 147 | ∅ | ∅ |
| syn7_score_199_3_40 | 199 | ∅ | ∅ |
| syn7_score_199_0_28 | 199 | ∅ | ∅ |

</details>
