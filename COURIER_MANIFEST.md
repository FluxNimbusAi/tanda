# Tanda W1 scaffold — courier manifest (laptop → PC → GitHub)
Date: 2026-11-12T20:49:38-05:00
Courier: OneDrive shared folder (Documents/Tanda), verified by Harley (laptop node) 2026-11-12
Source: profiles/xixi/cache/scratch/tanda (byte-verified: rm out/cache && forge build = zero warnings, Solc 0.8.38; forge test = 11/11 PASS; 232/193/45 lines)

## Files (77 total)
- .gitignore  sha256:56c2a3c96e5713003b3f4cec8ca472eb26ee5b967a7af18cc0943b5ba643f250  29B
- README.md  sha256:334c7b520bea40f39fb66308e96137bd64fbf40fb0bca2af9879f89df3943a99  2107B
- foundry.toml  sha256:544e6e8fa98eab5653ce281bc1ea7c69b355ea9b0cc217d378bb90573e97b077  176B
- contracts/TandaBill.sol  sha256:f056bc20b5e621c30b2288e94e6e21218806e273ddb9c40fbbd97ff4a2c0ab88  11052B
- lib/forge-std/.gitattributes  sha256:2dc1e6a6e64956c4e97344a48324d1ac27842b079fbda3412618f8f8f24515a4  31B
- lib/forge-std/.gitignore  sha256:5bf2d98930b220d7af822314ddd3d13247835a28c3cdde8015896579d4807a0b  30B
- lib/forge-std/CONTRIBUTING.md  sha256:fcb219bb3bc376f845b0cd9ae2a7b4d6f387a09475ee9c2cf6e4237cb01ce61c  11722B
- lib/forge-std/LICENSE-APACHE  sha256:933a9600adc4c65b8c60a6f1b74ccb87709f78fdfcbe12b6ed76d8d80c8a4b9b  11100B
- lib/forge-std/LICENSE-MIT  sha256:c288b6c79d923d48605b45622dc73c0514f5de5a74530852aa725a353310353c  1098B
- lib/forge-std/README.md  sha256:754a9daa38ce0f8dfc0fa9b85b62469628c6c1d8b8f95cfdbc4283027dff67b7  11464B
- lib/forge-std/RELEASE_CHECKLIST.md  sha256:7478ecd66aeb7c0ce0f5472620a67beeeb15d77bafe603a4e093e48463e04f59  533B
- lib/forge-std/foundry.toml  sha256:1f31a15cfa163564fc8379cc47eb6fb83ba6b15cc905e48e977eca661f9e5b86  639B
- lib/forge-std/package.json  sha256:ec90d5e077ef74399c43392854076f42b56a9de43f5d6fe41915caa5fb9bf727  533B
- lib/forge-std/.github/CODEOWNERS  sha256:e2fb23c5af0621ff467d74c84c342b0298dfc69061adb43cc10ab429d091296c  55B
- lib/forge-std/.github/dependabot.yml  sha256:a6a9e9f1c6df7029c61e76817b463e2ceec7575e05870692faaa2b6060278ae6  374B
- lib/forge-std/.github/workflows/ci.yml  sha256:cad02e454dcdc0d47ce7e0decfaf53ebb46689a730aba66aa2bc2fc6e25f6182  6101B
- lib/forge-std/.github/workflows/scan-github-actions.yml  sha256:2359c1869ab6b837e7f40d6b04aee1b8d016bb2bc1c7605f8c33420c1b44b51c  419B
- lib/forge-std/.github/workflows/sync.yml  sha256:42b871c2b7d62910250ae8e849558c5550dc6520a4154bfcb613a3a1fb7bbd6c  1153B
- lib/forge-std/scripts/vm.py  sha256:b6b20e68ae1af2c751a87c88bd08ecb9a3cb51397529c7dd66a8cd86e2dfceca  18776B
- lib/forge-std/src/Base.sol  sha256:608b2a4200d4818f616dd767f0689d3dd26b4c87f5abb1950cc38f3424b6caba  2296B
- lib/forge-std/src/Config.sol  sha256:a58e74ad46ee54e9cef51f446f160c6253fde502ce11126c15d4563e5c792934  2719B
- lib/forge-std/src/LibVariable.sol  sha256:7c2d2d1a281d9c0b9c4f322abe87882825298d62d0689d9c636d4bef462415dc  18464B
- lib/forge-std/src/Script.sol  sha256:1842bb8c8e1516aa9bef2d5c0911ae020f060a8f2b0f99dc2257046e87609911  1140B
- lib/forge-std/src/StdAssertions.sol  sha256:a52d820a775bf1a776542915a83ae181245e8fb12e5db79ac5fc97f505dabc46  60129B
- lib/forge-std/src/StdChains.sol  sha256:2d8b982dc649aa90f4dd28ef22da15f5414022d7df1afacf5ccff3e974921593  16369B
- lib/forge-std/src/StdCheats.sol  sha256:a7a26cc7aa5b5ca76a68dfab84f3e88f294df96f71facd03425b54d99a57b86a  40117B
- lib/forge-std/src/StdConfig.sol  sha256:f07612038ad78431cb2bb887256f2ef2a07421c39ef4f4450dfa2980e45c9099  32482B
- lib/forge-std/src/StdConstants.sol  sha256:572e3c3c4d1f9754e3edc7af5157115235d3ade025a31a9bb4e0429d69602551  1912B
- lib/forge-std/src/StdError.sol  sha256:12cfa17dd3d22d828d05dbb0b49e4b3a4a6c97e1fbabf547ae9776e845bd792e  1948B
- lib/forge-std/src/StdInvariant.sol  sha256:8c00d036f507e30f91d70594b80ef6cd98f5e33aa25ff3c95e1348ab77d3d5b2  7425B
- lib/forge-std/src/StdJson.sol  sha256:a6f0f1477dd76e101f260f83432c0de16109e8069735f44b72e4a363de5cac75  15129B
- lib/forge-std/src/StdMath.sol  sha256:a3086721195ebd3f799d3557333ed3542e8c672517c1ceedb92ad4b329f120e9  3006B
- lib/forge-std/src/StdSecp256k1.sol  sha256:66e03a7f18ab0b584d5b07bbd449640f5dfeb0e03299134e739f902e0d04779c  6328B
- lib/forge-std/src/StdStorage.sol  sha256:08329e0a5869863efd6d2731f0107de7c7b702502a56e2001730f3b44d091911  26954B
- lib/forge-std/src/StdStyle.sol  sha256:b2c9d4f17448d3395fbeb4cd5b0472ab19c29ec15377286a88e113779bc2d4c5  17915B
- lib/forge-std/src/StdToml.sol  sha256:a881e9d6d9bef4b86c35b59e57d72e8a11f6b1c335ed54d7c385709271a3731a  14420B
- lib/forge-std/src/StdUtils.sol  sha256:b476be0123c800f6e118db4c4265427b27926c2cc7aaabeef0118e781fc5fa29  12227B
- lib/forge-std/src/Test.sol  sha256:b6c17d529fdb02b456ffee45838083caa335d0109d9df75602cc880e633c963a  1347B
- lib/forge-std/src/Vm.sol  sha256:f7699e3a4c17e79645c71f4efa62c6247b6acb432528d20be817da4138bf0621  175084B
- lib/forge-std/src/console.sol  sha256:8125f7d9288751c15d4042dd05c275d8a879dd7a074e778977298169c06db39c  72638B
- lib/forge-std/src/console2.sol  sha256:a675b2d87278d46a787546099c20133fa5ec191f293d33bab103b6edcb0bd74e  135B
- lib/forge-std/src/safeconsole.sol  sha256:22bb9e3835a13ed2be569f035eb26c915275fd886cf58f1cb1d318a229cb5aff  422175B
- lib/forge-std/src/interfaces/IERC1155.sol  sha256:087d996a0740f62b852cde30951e785b636dd874328f0218b2722155075fc574  7731B
- lib/forge-std/src/interfaces/IERC165.sol  sha256:fd0ec8a846600c82af8c2c461961fc978529c28a58b21f2495dfd3144b6278a8  571B
- lib/forge-std/src/interfaces/IERC20.sol  sha256:0858203cc8704254a8b048d18e4f153b7bbd2f9f7b438a8cdcbec87616b63815  2132B
- lib/forge-std/src/interfaces/IERC4626.sol  sha256:f3a2be2eb9ad5cb1e9af24f6947b16c6df9a0f53c633004d48acc3747e30c004  12172B
- lib/forge-std/src/interfaces/IERC6909.sol  sha256:c0d065eb42360bf81482dadf8ff4997184d9354254ea12f802526016e97ca032  3575B
- lib/forge-std/src/interfaces/IERC721.sol  sha256:7f2567fd2661ccd47329472e766db030ec0766b4271f4807bdfa02aadf58f3d1  9227B
- lib/forge-std/src/interfaces/IERC7540.sol  sha256:95b84f0b15107fda005d204ff9c8e65e8973d5181e5e963051f1d5711488bbcb  6857B
- lib/forge-std/src/interfaces/IERC7575.sol  sha256:e4f0af7c9ad25db463c48b1952ef35b7de1741f60d64f4d489be6e06e1e25ebb  12846B
- lib/forge-std/src/interfaces/IMulticall3.sol  sha256:9f6f91c8678ebc879f822911013b3eab7e5afba915f931659102c42c3e8fb98d  2209B
- lib/forge-std/test/CommonBase.t.sol  sha256:2dd534e6cf458a5e704bfcb829241d6f2e66a7b382ff7aa67d89da8bd38d7a0d  1377B
- lib/forge-std/test/Config.t.sol  sha256:a0c89bb5cbae8438f2cd917c1b72b56425326ed826f9cefaac901ba714195f75  19861B
- lib/forge-std/test/LibVariable.t.sol  sha256:62a5f88724763effb047de1e2325538e3fc50088de947557c851c38f8970c619  17248B
- lib/forge-std/test/StdAssertions.t.sol  sha256:3192ab5b13010c62309d1c3e0b26fec2f2f8a11198e0cb25b5fc9d9d81895985  4940B
- lib/forge-std/test/StdChains.t.sol  sha256:2b9383f5cc920eade725921019149ff7c1cf462bb0653338217658014bcddddd  9993B
- lib/forge-std/test/StdCheats.t.sol  sha256:d073d5acd5ad277aea15ec065924fdcfcfbcf69976c6ca66c43261c6b75d9f34  26073B
- lib/forge-std/test/StdConstants.t.sol  sha256:7aff5106070ea492867578b6be3641ebfed6062b47591f2dca2df23d7a8f7462  1369B
- lib/forge-std/test/StdError.t.sol  sha256:d844318d431d2ecd082ebd10dd109b3d81ff433297bce1d5aa11a0b5ec565e86  2834B
- lib/forge-std/test/StdJson.t.sol  sha256:9933b9157512edf56823c7f5be4ff22460f7498d748b4b2683736dc47f1b9a0c  3296B
- lib/forge-std/test/StdMath.t.sol  sha256:204b5da37f985d66ebcd1d19bf5666a0c635f5e9a42fa00811ba0c946d5f90e0  8914B
- lib/forge-std/test/StdSecp256k1.t.sol  sha256:c90119f042b459302f7de7190d221bdcb9e3c9c61488ca7b3be6e8ca5f5868d9  5074B
- lib/forge-std/test/StdStorage.t.sol  sha256:353369bd7acc45eaffdcdb26175d439b1096814d65e5b39b8881556ec5fcbc88  25691B
- lib/forge-std/test/StdStyle.t.sol  sha256:157727c84fe2363b6ecfd57c261636468eef90a14e2c2486f9bb1dcb62a494de  5987B
- lib/forge-std/test/StdToml.t.sol  sha256:3118e68a4112fac1f8a136aab315e9ca880cadd0e72f1fbae896b318495aa301  1335B
- lib/forge-std/test/StdUtils.t.sol  sha256:7053cfed035c06ff8cf8ed593f0fcc346bf00f7b3bdd32c73ee646404ae24cce  15259B
- lib/forge-std/test/Vm.t.sol  sha256:e3968daaca52a8ba072842be106d7906d34df0784c9a2abcad5017f9e89452aa  692B
- lib/forge-std/test/compilation/CompilationScript.sol  sha256:42f271d79355c80fc8054babb402bb82e59342ad57ba7eb9139a9f4f77301ae4  397B
- lib/forge-std/test/compilation/CompilationScriptBase.sol  sha256:c280236b37d2b2a50da0a6acc5a3a269899c0eb144a3127105853cee75e925c6  409B
- lib/forge-std/test/compilation/CompilationStdSecp256k1.sol  sha256:05c0d6458773d3ecebe16f2061e122939e9102ac3fa867cb86f044ca2ba640db  1604B
- lib/forge-std/test/compilation/CompilationTest.sol  sha256:19766ac86fa83f04e44c44855dccf8fe68177157b7665f5b767dad8f40516a89  389B
- lib/forge-std/test/compilation/CompilationTestBase.sol  sha256:198b90b28c6494b03601985d0edfa37d3017d87f1328113981911bac0eb35217  401B
- lib/forge-std/test/fixtures/broadcast.log.json  sha256:b00fbfde3288bb2af82d66aca0defab98954b6a73b896b379d02a33d080579b1  11141B
- lib/forge-std/test/fixtures/config.toml  sha256:05f4b4860717dd1ab97aae6be7adc0cf87199dad3c90abfdb06914e72dd82f97  1916B
- lib/forge-std/test/fixtures/test.json  sha256:85a9ab61b49d9a83e896898ae696c09d8185505801d5403c077d9c0b507b2457  80B
- lib/forge-std/test/fixtures/test.toml  sha256:fac3b6ec72b38c67a49ffadb13ecab5afea65ec22414428b73a089d4dab3b63f  49B
- test/TandaBill.t.sol  sha256:769e1a7ac1aa81c3a4b3fcdefdfd3fee9c509424d8d824512994639f87a8cad9  6447B

## Verification record (Harley, independent of author)
- forge clean equivalent: rm -rf out cache && forge build → "Compiler run successful", exit 0, ZERO warnings
- forge test → 11 passed; 0 failed (suite 2.66ms)
- Contract header documents 5 kill-pass invariants (no key custody / no ROSCA / fee-free / World ID soft gate / short-hold)
- foundry.toml src = "contracts"; .gitignore in; script/Counter.s.sol removed; test lint fixed (unused joinedAt slot blanked)
- Settlement-loop lint rationale added (TandaBill.sol:195): "USDC (World Chain) has no transfer hooks — all-or-nothing revert protects partial settlement" — audit note resolved

## Handoff
1. PC node: pull this folder → git init/add/commit → push to FluxNimbusAi/tanda (repo not yet created).
2. Validation bus read-back per standard process.
3. Next W1 item to add: MiniKit UI shell placeholder stub (Xixi lane) + docs/ dir conventions.
