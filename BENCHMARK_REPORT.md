# Kepler Solver Benchmark Report
Generated: 2026-01-18 15:02:02

## System Context
- **CPU**: 13th Gen Intel(R) Core(TM) i5-13600K
- **RAM**: 31.1 GB
- **OS**: x86_64 (Linux)
- **Python**: 3.12.0

## Results
| Scenario | Complex | Python (s) | Rust (s) | Speedup | RAM (Py/Rs) | Correct | Economy |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| Baseline (24h) | 96 | 0.0263s | 0.0127s | 2.1x | 2.1/0.0 | ✅ | 4.29 SEK Cr |
| Baseline (48h) | 192 | 0.0574s | 0.0122s | 4.7x | 2.1/0.0 | ✅ | 7.92 SEK Cr |
| Water Heat (48h) | 384 | 0.2098s | 0.0453s | 4.6x | 2.4/0.0 | ✅ | 6.27 SEK Cr |
| Water + Spacing (48h) | 768 | 5.3087s | 3.9939s | 1.3x | 1.7/0.0 | ❌ (2.000) | 3.49 SEK Cr |
| Heavy Home (48h) | 960 | 3.3206s | 2.6873s | 1.2x | 0.4/0.0 | ❌ (2.000) | 272.27 SEK Dr |
