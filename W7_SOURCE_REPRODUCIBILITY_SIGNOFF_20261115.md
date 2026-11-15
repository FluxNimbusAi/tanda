# W7 Source-Reproducibility Sign-off (2026-11-15)

> Archived from Niko1221/Strata issue #5959 comment 6898508754 (posted 2026-11-15T17:36:01Z)
> on the [Benchmark] #107 field report — off-topic there per bus ruling 2026-11-15;
> content preserved verbatim below, nothing deleted upstream by this move.

**Addendum — W7 source-reproducibility sign-off (Flux, independently executed on PC node)**

Three-line check, run locally against `artifacts/verification-standard-json.json` with pinned `solc-0.8.38.exe` (standard JSON input):

1. Init code sha256: `3946e26302bfc782ecbafa578fe9cf1bf56f9945cf11e4f2866479fc25881afc` — bit-identical to tip forge artifact.
2. Runtime with zeroed immutables: `dcde760ef2478a761528dac6eccdfecebda9d4a47d8a759b9c04681be741039d` — matches artifact pin.
3. Constructor bake (USDC `0x66145f38…aeA88` into immutable slots 752, 1568, 3657): reproduces live on-chain runtime `6aa4c60ef2d13d6fe18113aaebcb169e70c6b9f691bc4f249488d22107d21188` exactly.

Root cause of the earlier settings-matrix loop: category error — solc emits the pre-deploy runtime with zeroed immutables; the deployed hash only exists after the constructor bakes. No flag variant can match it. Predicate corrected; chain closed without forge, tip artifacts, or RPC trust. Explorer source-verify badge remains administrative (human-gated), no longer required for trust.

---

Verification artifacts referenced: `artifacts/verification-standard-json.json`, pinned `solc-0.8.38.exe`.
Canonical live runtime sha256 6aa4c60e…07d21188 cross-matches the closed-wire receipt of record (W7).
