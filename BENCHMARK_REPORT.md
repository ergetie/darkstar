# Kepler Solver Benchmark Report
Generated: 2026-01-18 13:09:48

## System Context
- **CPU**: 13th Gen Intel(R) Core(TM) i5-13600K
- **RAM**: 31.1 GB
- **OS**: x86_64 (Linux)
- **Python**: 3.12.0

## Results
| Scenario | Complex | Python (s) | Rust (s) | Speedup | RAM (Py/Rs) | Correct | Economy |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| Baseline (24h) | 96 | 0.0260s | 0.0110s | 2.4x | 2.0/0.0 | ✅ | 4.29 SEK Cr |
| Baseline (48h) | 192 | 0.0548s | 0.0094s | 5.8x | 2.1/0.0 | ✅ | 7.92 SEK Cr |
| Water Heat (48h) | 384 | 0.2090s | 0.0177s | 11.8x | 2.5/0.0 | ❌ (0.600) | 6.87 SEK Cr |
| Water + Spacing (48h) | 768 | 5.2462s | 0.0642s | 81.7x | 1.7/0.0 | ❌ (0.400) | 5.09 SEK Cr |
| Water + Spacing (72h) | 1152 | 6.7991s | 0.0773s | 88.0x | 0.6/0.0 | ❌ (0.600) | 7.24 SEK Cr |
| Extreme (4 Days) | 1536 | 114.2411s | 0.1264s | 904.1x | 4.5/0.0 | ❌ (0.800) | 9.39 SEK Cr |
