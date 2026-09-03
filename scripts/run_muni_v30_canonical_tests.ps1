param([switch]$StaticSelfTest,[switch]$EmitExpectedAuthorization,[switch]$LogBridgeSelfTest)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$wsl = 'C:\Windows\System32\wsl.exe'
$taskkill = 'C:\Windows\System32\taskkill.exe'
$repo = 'C:\mnt\d\stuff\projects\sites\planora'
$repoWsl = '/mnt/d/Stuff/Projects/Sites/Planora'
$runId = 'e358bc6417224fe6a329ad3775853f01'
$root = "/tmp/planora-muni-v30-canonical-tests-$runId"
$snapshotRepo = '/snapshot/repo'
$runnerRelative = 'scripts/run_muni_v30_canonical_tests.ps1'
$runnerPath = Join-Path $repo 'scripts\run_muni_v30_canonical_tests.ps1'
$authorizationRelative = 'output/diagnostic-receipts/muni-fspsx-v30-canonical-tests-authorization-20260828T101448Z.receipt.json'
$authorizationPath = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v30-canonical-tests-authorization-20260828T101448Z.receipt.json'
$testsRelative = 'benchmarks/probe_diagnostics/muni_v28/planora-muni-fspsx-frontier-v28-tests.py'
$testsPath = Join-Path $repo 'benchmarks\probe_diagnostics\muni_v28\planora-muni-fspsx-frontier-v28-tests.py'
$builderPath = Join-Path $repo 'scripts\build_muni_v28_chain.ps1'
$certificatePath = Join-Path $repo 'benchmarks\probe_diagnostics\muni_v28\planora-muni-fspsx-frontier-v28-certificate.json'
$manifestPath = Join-Path $repo 'benchmarks\probe_diagnostics\muni_v28\planora-muni-fspsx-frontier-v28-freeze-manifest.json'
$prefix = Join-Path $repo "output\diagnostic-receipts\muni-fspsx-v30-canonical-readonly-tests-$runId"
$prefixWsl = "$repoWsl/output/diagnostic-receipts/muni-fspsx-v30-canonical-readonly-tests-$runId"
$sharedLockPath = Join-Path $repo 'output\diagnostic-receipts\planora-shared-heavy-wsl.lock'
$successorBuilderPath = Join-Path $repo 'scripts\build_muni_v30_successor.py'
$admissionTestsPath = Join-Path $repo 'tests\test_run_muni_v30_successor.py'
$v28ReceiptPath = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v28-canonical-readonly-tests-e7cf1df162074402994a9d0ad763c824.receipt.json'
$v28PassSealPath = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v28-canonical-readonly-tests-e7cf1df162074402994a9d0ad763c824.pass-publication-shutdown-seal.json'
$v29ReceiptPath = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.receipt.json'
$v29PassSealPath = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.pass-publication-shutdown-seal.json'
$v29RejectionPath = Join-Path $repo 'output\diagnostic-receipts\muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.rejection.json'
$staleArchiveRelative = 'output/diagnostic-receipts/retained-stale-planora-shared-heavy-wsl-v28-e7cf1df162074402994a9d0ad763c824.lock.json'
$staleArchivePath = Join-Path $repo 'output\diagnostic-receipts\retained-stale-planora-shared-heavy-wsl-v28-e7cf1df162074402994a9d0ad763c824.lock.json'
$predecessorCustodyFile = "$prefix.predecessor-custody.json"
$predecessorContractJson = @'
{"schema":"planora.muni-v30.v28-v29-predecessor-custody-contract.v1","v28":{"carrier":{"path":"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.rejection.json","size":15496,"sha256":"8d41c0131c3f7faf34591943acd11e41215e8fe511ddb0c8cab9c4466120856b","file_id":"00000000000000000008000000172649","last_write_utc_ticks":639235086944311433},"embedded_evidence_schema":"planora.muni-v29.complete-v28-predecessor-evidence.v1","embedded_evidence_sha256":"1f4dca36e66fb41be3c39ed4d559106e278e1263e86b170fb9609701666923e6","reconciliation_sha256":"009735b8f561a24509b758d9026f5cd96d8e30b1b3a3e89ecd1513e432e89c7a","archive":{"path":"output/diagnostic-receipts/retained-stale-planora-shared-heavy-wsl-v28-e7cf1df162074402994a9d0ad763c824.lock.json","size":370,"sha256":"dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98","file_id":"0000000000000000000c000000172456","last_write_utc_ticks":639235031172129106},"pass_receipt":"output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-e7cf1df162074402994a9d0ad763c824.receipt.json","pass_seal":"output/diagnostic-receipts/muni-fspsx-v28-canonical-readonly-tests-e7cf1df162074402994a9d0ad763c824.pass-publication-shutdown-seal.json"},"v29":{"run_id":"ca79220da7db46b6996fe1f05785dde7","sources":{"builder":{"path":"scripts/build_muni_v29_successor.py","size":65112,"sha256":"ec1cf8b79dc57d322f7f79a359bf378471a311122e40c92b7da3c7407d241208","file_id":"00000000000000000009000000172458","last_write_utc_ticks":639235075700468377},"runner":{"path":"scripts/run_muni_v29_canonical_tests.ps1","size":206139,"sha256":"c6dab5988cdd8f0a41061ab8d2fd6a7f33a68fe40b4e52815b846ce4fefa93b2","file_id":"0000000000000000000900000017245e","last_write_utc_ticks":639235077051249998},"tests":{"path":"tests/test_run_muni_v29_successor.py","size":14889,"sha256":"4bbb2726b7d0adb4751423e153421ff3b8707482e5dbc92790e7919440446705","file_id":"00000000000000000009000000172459","last_write_utc_ticks":639235075402265092},"authorization":{"path":"output/diagnostic-receipts/muni-fspsx-v29-canonical-tests-authorization-20260828T084512Z.receipt.json","size":14101,"sha256":"dfc87e6f55f0c19c308ecc0a2b7effd9341ceaf9eadac034f09ca56773375233","file_id":"0000000000000000000c00000017245b","last_write_utc_ticks":639235077058307759}},"artifacts":{"claim":{"path":"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.claim.json","size":541,"sha256":"8d9118d11fbb2b43dee08962abaab995782331fd2d289473e7df9d794e39d9aa","file_id":"0000000000000000000b00000017263f","last_write_utc_ticks":639235086848838432},"heavy_lock_release":{"path":"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.heavy-lock-release.json","size":460,"sha256":"0e01c49c6dfd34c13209ef40cd166d07ebefd4b22cedcd80de68f88f37af6a26","file_id":"0000000000000000000a000000172642","last_write_utc_ticks":639235086944440014},"heavy_lock":{"path":"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.heavy-lock.json","size":1642,"sha256":"ec27396012ef78c235931ef356f9f95a429fef75a4e7096a55bcaabf2ffaf503","file_id":"00000000000000000009000000172643","last_write_utc_ticks":639235086875573576},"watch_error":{"path":"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.mutation-watch.error.log","size":129,"sha256":"8db6fba9adec989417d4f452bfab33911d83f66377347d0661d9035dfc6e4dec","file_id":"0000000000000000000a000000172645","last_write_utc_ticks":639235086936166608},"watch_log":{"path":"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.mutation-watch.jsonl","size":239,"sha256":"e72977bad3da18e17202b3f1c0ea9f537145f7b9f36486c9ea97d44d70bde290","file_id":"0000000000000000000a000000172644","last_write_utc_ticks":639235086935127141},"watch_stop":{"path":"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.mutation-watch.stop","size":146,"sha256":"2eaeae4e1f591219a4cdc93429ae695fb0f8e03e7e17625dc623d873545bc071","file_id":"0000000000000000000b000000172646","last_write_utc_ticks":639235086935744482},"watch_wrapper_stderr":{"path":"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.mutation-watch.wrapper.stderr.log","size":168,"sha256":"ef92522da12d329a46fcd93e2aee0dbf0fde00be6a9d11e714cc0531bae71a4f","file_id":"0000000000000000000a000000172648","last_write_utc_ticks":639235086936643843},"watch_wrapper_stdout":{"path":"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.mutation-watch.wrapper.stdout.log","size":0,"sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","file_id":"00000000000000000008000000172647","last_write_utc_ticks":639235086936623289},"rejection":{"path":"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.rejection.json","size":15496,"sha256":"8d41c0131c3f7faf34591943acd11e41215e8fe511ddb0c8cab9c4466120856b","file_id":"00000000000000000008000000172649","last_write_utc_ticks":639235086944311433},"stale_lock_reconciliation":{"path":"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.stale-lock-reconciliation.json","size":26456,"sha256":"009735b8f561a24509b758d9026f5cd96d8e30b1b3a3e89ecd1513e432e89c7a","file_id":"0000000000000000000a000000172641","last_write_utc_ticks":639235086873841528},"static_evidence":{"path":"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.static-adversarial.json","size":2875,"sha256":"34c39b634835a746b479ee569126044fde2f3656f4f9e3d3761b7b84a4bf26bb","file_id":"0000000000000000000a000000172640","last_write_utc_ticks":639235086870151804}},"failure":{"status":"REJECTED_AUTHORIZATION_CONSUMED","phase":"before_staging_and_before_canonical_launch","primary_root_cause":"host_ReadAllText_sharing_violation_against_lifetime_open_WSL_mutation_log","secondary_failure":"abort_control_caused_watcher_stopped_before_staging_completed","canonical_suite_executed":false,"automatic_retry_authorized":false},"pass_receipt":"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.receipt.json","pass_seal":"output/diagnostic-receipts/muni-fspsx-v29-canonical-readonly-tests-ca79220da7db46b6996fe1f05785dde7.pass-publication-shutdown-seal.json"},"shared_lock":"output/diagnostic-receipts/planora-shared-heavy-wsl.lock","required_pre_acquisition_state":"archive_exact_shared_lock_absent_v28_v29_pass_absent"}
'@
$utf8 = New-Object System.Text.UTF8Encoding($false)

$claimFile="$prefix.claim.json"; $lockEvidenceFile="$prefix.heavy-lock.json"; $lockReleaseFile="$prefix.heavy-lock-release.json"
$stagingInventoryFile="$prefix.staging-inventory.json"; $preInventoryFile="$prefix.pre-inventory.json"; $postInventoryFile="$prefix.post-inventory.json"
$staticEvidenceFile="$prefix.static-adversarial.json"; $watchLogFile="$prefix.mutation-watch.jsonl"; $watchErrorFile="$prefix.mutation-watch.error.log"
$watchWrapperOutFile="$prefix.mutation-watch.wrapper.stdout.log"; $watchWrapperErrFile="$prefix.mutation-watch.wrapper.stderr.log"; $watchStopFile="$prefix.mutation-watch.stop"; $watchCleanupFile="$prefix.mutation-watch.cleanup.json"
$resourceLogFile="$prefix.resource-exclusivity.jsonl"; $resourceErrorFile="$prefix.resource-exclusivity.error.log"; $resourceStopFile="$prefix.resource-exclusivity.stop"
$resourceWrapperOutFile="$prefix.resource-exclusivity.wrapper.stdout.log"; $resourceWrapperErrFile="$prefix.resource-exclusivity.wrapper.stderr.log"
$stdoutFile="$prefix.stdout.log"; $stderrFile="$prefix.stderr.log"; $exitFile="$prefix.exit-code.txt"; $planFile="$prefix.plan.json"; $acceptanceFile="$prefix.acceptance-commitment.json"; $receiptFile="$prefix.receipt.json"; $passSealFile="$prefix.pass-publication-shutdown-seal.json"; $cleanupFile="$prefix.cleanup.json"; $rejectionFile="$prefix.rejection.json"; $rejectionEmergencyFile="$prefix.rejection-emergency.json"
$hostDeadlineSeconds=630

$snapshotContractJson = @'
{"schema":"planora.muni-v30.snapshot-closure.v3","tree_digests":{"16":"f5f663575cbff160bc291d0de618abc6052b863d91bdc686c18a1858b0674202","17":"4898668e9c19d0a8cb3724f96c7083716b9e8b18c3ff747f53e6fb4b56fd26a4","18":"2ee23445d8a0691c1a3dc05b035d0265c94a9b6dc641c4bbceb76c381d53335b","19":"c69d9feb3633db7e625f839ebad77edd4b9874e73950f27802e7d6b14585642a","20":"4c850d0efef25e016c9e5bf92bdeb2a2f4e7df0d23e84251077bf52ac42f5ee3","21":"5e8cbdc955568c29434c36875fe593223cd0c520819d2db4a50b2976d0e2fecd","22":"ed1b901170089e08db59d1ae376897d4aca514fe85092eb314bb09cbc3b820eb","23":"e1e109484eb584843e9a40cb5dd25a8351b233be63f139390119f5a2f2e7e7c5","24":"54b208e878bd88906b96d1e4b1121060257aeb7b5c8b10599d2e6b9c19a93922","25":"f731bbbedc064d217f27a5e49439788f3105a18292f6ba50fb264574e91dc227","26":"916a42957f81524a8014a1a5997ef6a54d1a4a3a1560ea589a47dfe2413fa86e","27":"3ae4be16e8735ec64971aea78020077df1f1706d08eaad6a83ec9b084e0e5e58"},"v28_tree":{"files":14,"bytes":673928,"digest":"e3bba7f9585503bce91ecc02e95c493fb0a5fdd89639d60a2dc999debd877bee"},"source_files":{"paths":["benchmarks/itc2019.py","benchmarks/itc2019_preprocessing.py","benchmarks/itc2019_frontier_joint.py","benchmarks/itc2019_room_oracle.py","benchmarks/itc2019_compact_joint.py","benchmarks/itc2019_corpus.py","benchmarks/itc2019_decomposed.py","benchmarks/itc2019_decomposed_quality.py","benchmarks/itc2019_factorized.py","benchmarks/itc2019_generalized_occurrences.py","benchmarks/itc2019_global_components.py","benchmarks/itc2019_global_quality.py","benchmarks/itc2019_grouped_calendar.py","benchmarks/itc2019_resource_seed.py","benchmarks/itc2019_sparse_joint.py","benchmarks/itc2019_structural.py","benchmarks/itc2019_violation_lns.py"],"files":17,"bytes":854835,"digest":"9dabacd2fa3071ca2f4d1de7fa447b481792fb5cec964b8f89c8f16ebc077f3a"},"runtime_records":{"paths":["ortools-9.15.6755.dist-info/RECORD","numpy-2.4.2.dist-info/RECORD","pandas-3.0.1.dist-info/RECORD","python_dateutil-2.9.0.post0.dist-info/RECORD","six-1.17.0.dist-info/RECORD","absl_py-2.4.0.dist-info/RECORD","immutabledict-4.3.1.dist-info/RECORD","protobuf-6.33.5.dist-info/RECORD","typing_extensions-4.15.0.dist-info/RECORD"],"files":9,"bytes":415655,"digest":"f30b88cd4c345aab9f8ae2526f83cd7608759a46cc13fb681a65263e07eed78f"},"runtime_policy":{"max_files":6000,"max_total_bytes":536870912,"max_file_bytes":134217728,"exclude_pyc":true,"reject_absolute_parent_backslash_and_duplicates":true},"mounts":{"snapshot":"/snapshot","repository_overlay":"/mnt/d/Stuff/Projects/Sites/Planora","hide_live_drive":"/mnt/d","scratch_tmpfs":"/tmp","legacy_ro_binds":48},"modes":{"root":"0700","directories":"0500","files":"0400"},"all_staged_files_require_nlink":1}
'@

# This assignment deliberately supersedes the earlier authorization-v3 contract while preserving
# its historical digest constants for audit comparison. Normal and static paths consume only v4.
$snapshotContractJson = @'
{"schema":"planora.muni-v30.snapshot-closure.v4","historical":{"versions":[16,17,18,19,20,21,22,23,24,25,26,27],"name_templates":["planora_muni_v{v}_benchmarks_stub.py","planora-muni-fspsx-frontier-v{v}-bootstrap.py","planora-muni-fspsx-frontier-v{v}-certificate.json","planora-muni-fspsx-frontier-v{v}-freeze-manifest.json","planora-muni-fspsx-frontier-v{v}-generic-validator.py","planora-muni-fspsx-frontier-v{v}-inline-trust-root.txt","planora-muni-fspsx-frontier-v{v}-launcher.sh","planora-muni-fspsx-frontier-v{v}-minimal-tcb.sha256","planora-muni-fspsx-frontier-v{v}-runner.py","planora-muni-fspsx-frontier-v{v}-stdlib.sha256","planora-muni-fspsx-frontier-v{v}-supervisor.py","planora-muni-fspsx-frontier-v{v}-tests.py","planora-muni-fspsx-v35-derivation-audit-v1.json"],"tree_digests":{"16":"f5f663575cbff160bc291d0de618abc6052b863d91bdc686c18a1858b0674202","17":"4898668e9c19d0a8cb3724f96c7083716b9e8b18c3ff747f53e6fb4b56fd26a4","18":"2ee23445d8a0691c1a3dc05b035d0265c94a9b6dc641c4bbceb76c381d53335b","19":"c69d9feb3633db7e625f839ebad77edd4b9874e73950f27802e7d6b14585642a","20":"4c850d0efef25e016c9e5bf92bdeb2a2f4e7df0d23e84251077bf52ac42f5ee3","21":"5e8cbdc955568c29434c36875fe593223cd0c520819d2db4a50b2976d0e2fecd","22":"ed1b901170089e08db59d1ae376897d4aca514fe85092eb314bb09cbc3b820eb","23":"e1e109484eb584843e9a40cb5dd25a8351b233be63f139390119f5a2f2e7e7c5","24":"54b208e878bd88906b96d1e4b1121060257aeb7b5c8b10599d2e6b9c19a93922","25":"f731bbbedc064d217f27a5e49439788f3105a18292f6ba50fb264574e91dc227","26":"916a42957f81524a8014a1a5997ef6a54d1a4a3a1560ea589a47dfe2413fa86e","27":"3ae4be16e8735ec64971aea78020077df1f1706d08eaad6a83ec9b084e0e5e58"}},"v28_tree":{"names":["planora_muni_v28_benchmarks_stub.py","planora-muni-fspsx-frontier-v28-bootstrap.py","planora-muni-fspsx-frontier-v28-certificate.json","planora-muni-fspsx-frontier-v28-freeze-manifest.json","planora-muni-fspsx-frontier-v28-generic-validator.py","planora-muni-fspsx-frontier-v28-inline-trust-root.txt","planora-muni-fspsx-frontier-v28-launcher.sh","planora-muni-fspsx-frontier-v28-minimal-tcb.sha256","planora-muni-fspsx-frontier-v28-runner.py","planora-muni-fspsx-frontier-v28-stdlib.sha256","planora-muni-fspsx-frontier-v28-supervisor.py","planora-muni-fspsx-frontier-v28-tests.py","planora-muni-fspsx-frontier-v28-v27-canonical-evidence-no-go.json","planora-muni-fspsx-v35-derivation-audit-v1.json"],"files":14,"bytes":673928,"digest":"e3bba7f9585503bce91ecc02e95c493fb0a5fdd89639d60a2dc999debd877bee"},"source_files":{"rows":[["benchmarks/itc2019.py",142021,"5577c6227037fa615df741a4b0b351b05ec11c7c4ce4ebe9a4489554122b2c1f","pinned-live"],["benchmarks/itc2019_preprocessing.py",34963,"b98b6d56bcbdedaf491ac91194c9eef8997f624ab81c7f52e3a647c174994644","pinned-live"],["benchmarks/itc2019_frontier_joint.py",38279,"ade6b42c3baa08a53454db3842b0c4f3cd2e2738c6eb0c54108f419a148d7793","pinned-live"],["benchmarks/itc2019_room_oracle.py",25356,"ff16e0a6045bffa7402748c537213c727918afddd35d92513ba4133972753ca6","pinned-live"],["benchmarks/itc2019_compact_joint.py",35402,"427264334276fb48ce5b54c151a42d4a85b75055c0bea96f47a928b1fe28362a","pinned-live"],["benchmarks/itc2019_corpus.py",43195,"1c83f9f26362d0c8c06d1d9bcabc2b015ac4e09216fdd91df1eaa7255933c621","pinned-live"],["benchmarks/itc2019_decomposed.py",135880,"0b6f07a64c139f3cfdcc9d5dd8ce945be1d7278e7f52b6eee2719e1f5560debf","pinned-live"],["benchmarks/itc2019_decomposed_quality.py",76030,"534622d096728ff4e4e9b53fd8d58ec3827ec09540d4c95a3e3dcad271c7f78b","pinned-live"],["benchmarks/itc2019_factorized.py",97255,"a773110756e612e26dfd792ea6f289ca9a36d526fc807f790f674233ec8df1bf","embedded-gzip"],["benchmarks/itc2019_generalized_occurrences.py",16871,"7ed4224c0f338f9f983a358babb5dfdb6b90d5026383283cd0d805aef733d85f","pinned-live"],["benchmarks/itc2019_global_components.py",22141,"c2d158dc9434f8da4f3e9478b1526face365702cf317fd14e693af75769e7f11","pinned-live"],["benchmarks/itc2019_global_quality.py",26372,"397d308a4fb368aaab96db1789394e1b9f289a8f6b8d87b9ce5b4a569f8ccc7f","pinned-live"],["benchmarks/itc2019_grouped_calendar.py",22700,"37b82b7f01fb47a655bb76ae0d6734315b00bf58ec7ebf28c66bb701c00a6ee5","pinned-live"],["benchmarks/itc2019_resource_seed.py",32338,"8d497bc609ec5b717b0d9e2b77406e89c45c6eaef378148c0bebadd6a429d665","pinned-live"],["benchmarks/itc2019_sparse_joint.py",43287,"2f2a40180f86fdcc7b76d9c10730cecbda7114713d504ecfe6b98008f105c2c2","pinned-live"],["benchmarks/itc2019_structural.py",25151,"db4ac0adbfe38f1b618b2e8f7a5a9e5a613000a62034017819cca2c20640d024","pinned-live"],["benchmarks/itc2019_violation_lns.py",37594,"9f1e4f66c4fadea2813ec86de451206102928c5c7b1dfdf786d900c8dc137343","pinned-live"]],"files":17,"bytes":854835,"digest":"9dabacd2fa3071ca2f4d1de7fa447b481792fb5cec964b8f89c8f16ebc077f3a","embedded_gzip_sha256":"29dbbf41cf60e4ef8ef35619cb6703da8877cd253a56959170b692cf2ef7799c"},"runtime_records":{"paths":["ortools-9.15.6755.dist-info/RECORD","numpy-2.4.2.dist-info/RECORD","pandas-3.0.1.dist-info/RECORD","python_dateutil-2.9.0.post0.dist-info/RECORD","six-1.17.0.dist-info/RECORD","absl_py-2.4.0.dist-info/RECORD","immutabledict-4.3.1.dist-info/RECORD","protobuf-6.33.5.dist-info/RECORD","typing_extensions-4.15.0.dist-info/RECORD"],"files":9,"bytes":415655,"digest":"f30b88cd4c345aab9f8ae2526f83cd7608759a46cc13fb681a65263e07eed78f"},"runtime_policy":{"max_files":6000,"max_total_bytes":536870912,"max_file_bytes":134217728,"exclude_pyc":true,"reject_absolute_parent_backslash_and_duplicates":true,"exact_tree_no_extras":true},"mounts":{"host_root":"/tmp/planora-muni-v30-canonical-tests-e358bc6417224fe6a329ad3775853f01","snapshot_bind":"/snapshot","repository_overlay":"/mnt/d/Stuff/Projects/Sites/Planora","hide_live_drive":"/mnt/d","scratch_tmpfs":"/tmp","legacy_ro_binds":48,"order":"root-ro-bind-before-hidden-tmp-and-overlay"},"modes":{"root":"0700","directories":"0500","files":"0400"},"all_staged_files_require_nlink":1,"unittest":{"tests":119,"passes":117,"skips":2,"identity_result_digest":"d61d584f9d8678cf0fe0f92a85f56674773b0d39aacbf1de722b886213af71b1"}}
'@

$snapshotContractJson=$snapshotContractJson.Replace('"pinned-live"','"frozen-hash-source"').Replace('"embedded-gzip"','"frozen-git-object"').Replace('"embedded_gzip_sha256":"29dbbf41cf60e4ef8ef35619cb6703da8877cd253a56959170b692cf2ef7799c"','"frozen_git_object":{"path":".git/objects/3a/de50192a6e87d04b5f75dfeafd239a7723d181","size":21343,"sha256":"72246865f277ef0076012fa92f1219fe04bc079007e902b134e1026a6fcacfc3","git_object_id":"3ade50192a6e87d04b5f75dfeafd239a7723d181","decoded_size":97255,"decoded_sha256":"a773110756e612e26dfd792ea6f289ca9a36d526fc807f790f674233ec8df1bf"}').Replace('d61d584f9d8678cf0fe0f92a85f56674773b0d39aacbf1de722b886213af71b1','d4dbb5189bcf65870954e5159efbe1ce52208d3b3a0cabc734f7b3f380266afa')

function Get-Sha256([string]$Path){$s=New-Object IO.FileStream($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,([IO.FileShare]::ReadWrite-bor[IO.FileShare]::Delete));$sha=[Security.Cryptography.SHA256]::Create();try{return([BitConverter]::ToString($sha.ComputeHash($s))-replace'-','').ToLowerInvariant()}finally{$sha.Dispose();$s.Dispose()}}
function Write-NewBytes([string]$Path,[byte[]]$Bytes){$s=New-Object IO.FileStream($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);try{$s.Write($Bytes,0,$Bytes.Length);$s.Flush($true)}finally{$s.Dispose()}}
function Write-NewUtf8([string]$Path,[string]$Value){Write-NewBytes $Path $utf8.GetBytes($Value)}
function Write-FinalPassSeal([string]$Path,[string]$Value,[IO.FileStream]$ArchiveGuard){$expectedArchiveBytes=$utf8.GetBytes('{"schema":"planora.shared-heavy-wsl-lock.v1","run_id":"e7cf1df162074402994a9d0ad763c824","authorization_sha256":"1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d","runner_sha256":"fbf0a2f4449806cec331c71efc79417553f2d1cd6b060f5d481a32dbfc896d60","created_at_utc":"2026-08-28T08:38:37.2109195Z","mechanism":"FileMode.CreateNew_held_open","owner_pid":1140}');if($null-eq$ArchiveGuard-or[IO.Path]::GetFullPath($ArchiveGuard.Name)-cne[IO.Path]::GetFullPath($staleArchivePath)){throw 'Final archived-lock guard rejected'};[void](Assert-HeldStreamBytes $ArchiveGuard $expectedArchiveBytes 'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98' 'Final archived stale lock guard');$bytes=$utf8.GetBytes($Value);$stream=$null;$durablyFlushed=$false;try{$stream=New-Object IO.FileStream($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true);$durablyFlushed=$true}finally{if($null-ne$stream){if($durablyFlushed){try{$stream.Dispose()}catch{}}else{$stream.Dispose()}};if($null-ne$ArchiveGuard){if($durablyFlushed){try{$ArchiveGuard.Dispose()}catch{}}else{$ArchiveGuard.Dispose()}}}}
function Write-NewAscii([string]$Path,[string]$Value){Write-NewBytes $Path ([Text.Encoding]::ASCII.GetBytes($Value))}

function ConvertTo-JsonTokenStream([string]$Json){
    $b=New-Object Text.StringBuilder;$inside=$false;$escaped=$false
    foreach($c in $Json.ToCharArray()){
        if($inside){[void]$b.Append($c);if($escaped){$escaped=$false}elseif($c-eq'\'){$escaped=$true}elseif($c-eq'"'){$inside=$false}}
        elseif($c-eq'"'){$inside=$true;[void]$b.Append($c)}elseif(-not[char]::IsWhiteSpace($c)){[void]$b.Append($c)}
    }
    if($inside-or$escaped){throw 'JSON token stream unterminated'};return $b.ToString()
}

function Assert-LocalPin([string]$Path,[long]$Size,[string]$Hash){$i=Get-Item -LiteralPath $Path;if(($i.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0-or$i.Length-ne$Size-or(Get-Sha256 $Path)-cne$Hash){throw "Local pin drift: $Path"}}
function Get-LocalFileId([string]$Path){
    $normalized=([IO.Path]::GetFullPath($Path)).Replace('\','/');$fsutil=Join-Path $env:SystemRoot 'System32\fsutil.exe';$p=New-Object Diagnostics.Process;$p.StartInfo=New-SafeStartInfo $fsutil @('file','queryfileid',$normalized) $false
    try{if(-not$p.Start()){throw 'fsutil file identity start failed'};$ot=$p.StandardOutput.ReadToEndAsync();$et=$p.StandardError.ReadToEndAsync();if(-not$p.WaitForExit(10000)){try{$p.Kill()}catch{};throw 'fsutil file identity deadline exceeded'};$o=$ot.GetAwaiter().GetResult();$e=$et.GetAwaiter().GetResult();if($p.ExitCode-ne0-or$e.Length-ne0-or$o-cnotmatch'(?m)^File ID is 0x([0-9a-fA-F]{32})\r?$'){throw 'fsutil file identity result rejected'};return $Matches[1].ToLowerInvariant()}finally{$p.Dispose()}
}
function Get-LocalEvidencePin([string]$Path){
    $full=[IO.Path]::GetFullPath($Path);$before=Get-Item -LiteralPath $full;if(($before.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0-or$before.PSIsContainer){throw "Evidence type rejected: $full"};$id=Get-LocalFileId $full;$hash=Get-Sha256 $full;$after=Get-Item -LiteralPath $full;$idAfter=Get-LocalFileId $full
    if($idAfter-cne$id-or$after.Length-ne$before.Length-or$after.LastWriteTimeUtc.Ticks-ne$before.LastWriteTimeUtc.Ticks){throw "Evidence identity drift: $full"};return [ordered]@{path=$full.Replace($repo+'\','').Replace('\','/');size=$after.Length;sha256=$hash;file_id=$id;last_write_utc_ticks=$after.LastWriteTimeUtc.Ticks}
}
function Assert-LocalEvidencePin([object]$Pin){$current=Get-LocalEvidencePin (Join-Path $repo ($Pin.path.Replace('/','\')));if((ConvertTo-JsonTokenStream ($current|ConvertTo-Json -Depth 5 -Compress))-cne(ConvertTo-JsonTokenStream ($Pin|ConvertTo-Json -Depth 5 -Compress))){throw "Evidence pin replay rejected: $($Pin.path)"};return $true}

function Test-SafeNativeAtom([string]$Value){return (-not[string]::IsNullOrEmpty($Value)-and$Value-cmatch"^[A-Za-z0-9_./:=,+@%()'<>;\-]+$")}
function New-SafeStartInfo([string]$FileName,[string[]]$Tokens,[bool]$RedirectInput){
    if(-not(Test-Path -LiteralPath $FileName)){throw "Executable missing: $FileName"}
    foreach($t in $Tokens){if(-not(Test-SafeNativeAtom $t)){throw "Unsafe native argument atom rejected: $t"}}
    $joined=$Tokens-join' ';$again=@($joined-split' ');if($again.Count-ne$Tokens.Count){throw 'Argument count replay rejected'}
    for($i=0;$i-lt$Tokens.Count;$i++){if($again[$i]-cne$Tokens[$i]){throw 'Argument boundary replay rejected'}}
    $p=New-Object Diagnostics.ProcessStartInfo;$p.FileName=$FileName;$p.Arguments=$joined;$p.UseShellExecute=$false;$p.CreateNoWindow=$true;$p.RedirectStandardInput=$RedirectInput;$p.RedirectStandardOutput=$true;$p.RedirectStandardError=$true;return $p
}
function Invoke-SafeStdinProcess([string]$FileName,[string[]]$Tokens,[string]$Payload,[string]$Context){
    $p=New-Object Diagnostics.Process;$p.StartInfo=New-SafeStartInfo $FileName $Tokens $true;if(-not$p.Start()){throw "$Context start failed"}
    $ot=$p.StandardOutput.ReadToEndAsync();$et=$p.StandardError.ReadToEndAsync();$bytes=$utf8.GetBytes($Payload);$p.StandardInput.BaseStream.Write($bytes,0,$bytes.Length);$p.StandardInput.Close();$p.WaitForExit();$o=$ot.GetAwaiter().GetResult();$e=$et.GetAwaiter().GetResult();$code=$p.ExitCode;$p.Dispose();if($code-ne0){throw "$Context failed with exit $code`: $e"};return [ordered]@{exit_code=$code;stdout=$o;stderr=$e}
}
function Start-SafeStdinProcess([string]$FileName,[string[]]$Tokens,[string]$Payload){
    $p=New-Object Diagnostics.Process;$p.StartInfo=New-SafeStartInfo $FileName $Tokens $true;if(-not$p.Start()){throw 'Bound watcher start failed'}
    $ot=$p.StandardOutput.ReadToEndAsync();$et=$p.StandardError.ReadToEndAsync();$bytes=$utf8.GetBytes($Payload);$p.StandardInput.BaseStream.Write($bytes,0,$bytes.Length);$p.StandardInput.Close();return [pscustomobject]@{Process=$p;OutTask=$ot;ErrTask=$et;Tokens=$Tokens}
}
function Start-SafeLoggedProcess([string]$FileName,[string[]]$Tokens,[string]$OutPath,[string]$ErrPath){
    $out=New-Object IO.FileStream($OutPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read);$err=New-Object IO.FileStream($ErrPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read);$p=New-Object Diagnostics.Process;$p.StartInfo=New-SafeStartInfo $FileName $Tokens $false
    try{if(-not$p.Start()){throw 'Canonical process start failed'};$ot=$p.StandardOutput.BaseStream.CopyToAsync($out);$et=$p.StandardError.BaseStream.CopyToAsync($err);return [pscustomobject]@{Process=$p;OutTask=$ot;ErrTask=$et;OutStream=$out;ErrStream=$err;Tokens=$Tokens}}catch{$p.Dispose();$out.Dispose();$err.Dispose();throw}
}
function Complete-SafeLoggedProcess([object]$Execution){
    if($null-eq$Execution){throw 'Canonical execution handle missing'}
    try{
        if(-not$Execution.Process.HasExited-and-not$Execution.Process.WaitForExit(15000)){throw 'Canonical outer wsl.exe completion deadline exceeded'}
        if(-not$Execution.OutTask.Wait(15000)-or-not$Execution.ErrTask.Wait(15000)){throw 'Canonical redirected stream drain deadline exceeded'}
        $Execution.OutTask.GetAwaiter().GetResult();$Execution.ErrTask.GetAwaiter().GetResult();$Execution.OutStream.Flush($true);$Execution.ErrStream.Flush($true);return [pscustomobject]@{ExitCode=$Execution.Process.ExitCode;Id=$Execution.Process.Id}
    }finally{$Execution.Process.Dispose();$Execution.OutStream.Dispose();$Execution.ErrStream.Dispose()}
}
function Stop-CanonicalProcess([object]$Execution){
    if($null-eq$Execution-or$Execution.Process.HasExited){return}
    $pidText=[string]$Execution.Process.Id;$killer=New-Object Diagnostics.Process;$killer.StartInfo=New-SafeStartInfo $taskkill @('/PID',$pidText,'/T','/F') $false
    try{if($killer.Start()){$ot=$killer.StandardOutput.ReadToEndAsync();$et=$killer.StandardError.ReadToEndAsync();if(-not$killer.WaitForExit(10000)){try{$killer.Kill()}catch{}}else{[void]$ot.GetAwaiter().GetResult();[void]$et.GetAwaiter().GetResult()}}}catch{}finally{$killer.Dispose()}
    if(-not$Execution.Process.HasExited){try{$Execution.Process.Kill()}catch{}}
    if(-not$Execution.Process.WaitForExit(10000)){throw 'Canonical outer wsl.exe termination deadline exceeded'}
}

function Invoke-WslText([string[]]$Arguments,[string]$Context){$lines=@(&$wsl @Arguments 2>&1);$code=$LASTEXITCODE;if($code-ne0){throw "$Context failed with exit $code`: $($lines-join' | ')"};return @($lines|ForEach-Object{"$_"})}
function Get-MemAvailable{$lines=@(Invoke-WslText @('-d','Ubuntu','--exec','grep','^MemAvailable:','/proc/meminfo') 'MemAvailable census');if($lines.Count-ne1-or$lines[0]-cnotmatch'^MemAvailable:[ \t]+([0-9]+)[ \t]+kB[ \t]*$'){throw 'MemAvailable malformed'};return [long]$Matches[1]}

function Convert-WslProcessCensus([string[]]$Lines){
    $rows=@();foreach($line in $Lines){if($line-cnotmatch'^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(.+)$'){throw "Census row malformed: $line"};$rows+=[pscustomobject]@{pid=[int]$Matches[1];ppid=[int]$Matches[2];uid=[int]$Matches[3];comm=$Matches[4];args=$Matches[5]}}
    $psRows=@($rows|Where-Object{$_.comm-ceq'ps'-and$_.args-cmatch'^ps -eo pid=,ppid=,uid=,comm=,args=$'});if($psRows.Count-ne1){throw "Census ancestry ambiguous: $($psRows.Count)"}
    $by=@{};foreach($r in $rows){if($by.ContainsKey($r.pid)){throw 'Duplicate census PID'};$by[$r.pid]=$r};$ancestry=@{};$cursor=$psRows[0]
    while($null-ne$cursor){$ancestry[$cursor.pid]=$true;if($cursor.ppid-eq0){break};if(-not$by.ContainsKey($cursor.ppid)){throw 'Incomplete census ancestry'};$cursor=$by[$cursor.ppid]}
    $infra=@('init','systemd','systemd-journal','systemd-udevd','systemd-network','systemd-resolve','systemd-timesyn','systemd-logind','dbus-daemon','cron','rsyslogd','wsl-pro-service')
    $deny='(?i)(stress-ng|pytest|python|java|javac|scip|gurobi|cplex|cbc|glpsol|minisat|kissat|cadical|clasp|sat4j|solver|docker|docker-compose|dockerd|containerd|buildkit|gcc|g\+\+|clang|cargo|rustc|(^|[ /])go([ /]|$)|make|ninja|cmake|gradle|mvn|node|npm|pnpm|yarn|bun|dotnet|msbuild)'
    foreach($r in $rows){if($ancestry.ContainsKey($r.pid)){continue};if(("$($r.comm) $($r.args)")-match$deny){throw "Explicit heavy workload rejected: pid=$($r.pid) comm=$($r.comm)"};if($infra-cnotcontains$r.comm){throw "Unknown WSL workload rejected: pid=$($r.pid) uid=$($r.uid) comm=$($r.comm)"}}
    $none=@()
    return [ordered]@{rows=$rows;current_ancestry_pids=@($ancestry.Keys|Sort-Object);allowed_infrastructure=$infra;rejected_workloads=$none}
}
function Get-WslProcessCensus{return Convert-WslProcessCensus @(Invoke-WslText @('-d','Ubuntu','--exec','ps','-eo','pid=,ppid=,uid=,comm=,args=') 'conservative WSL process census')}

function Get-ObsoleteV3AuthorizationJson([long]$RunnerSize,[string]$RunnerHash){
    $snapshot=$snapshotContractJson|ConvertFrom-Json
    return([ordered]@{schema='planora.itc2019.canonical-test-authorization.v3';created_at_utc='2026-08-27T04:51:49Z';instance='muni-fspsx-fal17';candidate='muni_v30';test_id=$runId;decision='GO_FOR_EXACTLY_ONE_CANONICAL_IMMUTABLE_SNAPSHOT_SUITE';retained_probe_authorized=$false;official_input_authorized=$false;official_launch_authorized=$false;solver_authorized=$false;publication_authorized=$false;automatic_retry_authorized=$false;runner=[ordered]@{path=$runnerRelative;size=$RunnerSize;sha256=$RunnerHash};pinned_v28_files=[ordered]@{builder=[ordered]@{path='scripts/build_muni_v28_chain.ps1';size=44779;sha256='bca84d0a27ef25e4e716422590aa0e188d3dae22579c9393b51e62c182dde28d'};tests=[ordered]@{path=$testsRelative;size=178441;sha256='f7d16b989ecd3ac22bd218da24c5e9c9bc1dca875f3593d0bad9248eaacfa5ab'};certificate=[ordered]@{path='benchmarks/probe_diagnostics/muni_v28/planora-muni-fspsx-frontier-v28-certificate.json';size=31261;sha256='7b1f4b1ffc3a6cf53389d5cc6c585662536af50f06aced6b5d30fff3e32ad432'};freeze_manifest=[ordered]@{path='benchmarks/probe_diagnostics/muni_v28/planora-muni-fspsx-frontier-v28-freeze-manifest.json';size=33749;sha256='f47beb315d0ea92eec1942f89a9398cd84f4ad81cb1d7f1aff219c1fbbc435e6'}};snapshot_contract=$snapshot;heavy_gate=[ordered]@{shared_lock='output/diagnostic-receipts/planora-shared-heavy-wsl.lock';lock_mode='CreateNew_held_open';memavailable_minimum_kib=1900000;samples=2;minimum_separation_seconds=5;census='fail_closed_allow_current_ancestry_and_explicit_minimal_infrastructure_only'};launch_contract=[ordered]@{watcher='ProcessStartInfo_safe_atoms_plus_stdin_source';root_read_only=$true;snapshot_read_only=$true;live_drive_hidden=$true;environment_cleared=$true;capabilities_dropped=$true;canonical_execute_sites=1};canonical_contract=[ordered]@{unique_tests=119;expected_passes=117;expected_skips=2;expected_failures=0;expected_errors=0;exact_skip_reasons=@('heavy sealed-runtime import probe disabled by test contract','real sealed chain admission disabled by test contract')};evidence_contract=[ordered]@{atomic_claim='CreateNew_before_preflight';any_failure_consumes_authorization=$true;all_file_nlinks_retained=$true;plan_and_receipt_bind_runner_authorization_snapshot=$true;cleanup_binds_receipt_and_post_inventory=$true;rejection_retains_snapshot=$true}}|ConvertTo-Json -Depth 15)
}

function Get-ObsoleteV5AuthorizationJson([long]$RunnerSize,[string]$RunnerHash){
    $snapshot=$snapshotContractJson|ConvertFrom-Json;$sha=[Security.Cryptography.SHA256]::Create();try{$snapshotHash=([BitConverter]::ToString($sha.ComputeHash($utf8.GetBytes((ConvertTo-JsonTokenStream $snapshotContractJson))))-replace'-','').ToLowerInvariant()}finally{$sha.Dispose()}
    $factorized=$snapshot.source_files.frozen_git_object
    $closure=[ordered]@{schema=$snapshot.schema;contract_sha256=$snapshotHash;historical=[ordered]@{versions=12;files_per_version=13;tree_digests=$snapshot.historical.tree_digests};v28=[ordered]@{files=$snapshot.v28_tree.files;bytes=$snapshot.v28_tree.bytes;digest=$snapshot.v28_tree.digest;explicit_names=14};source_files=[ordered]@{files=$snapshot.source_files.files;bytes=$snapshot.source_files.bytes;digest=$snapshot.source_files.digest;explicit_rows=17;factorized_frozen_git_object=$factorized};runtime=[ordered]@{record_files=$snapshot.runtime_records.files;record_bytes=$snapshot.runtime_records.bytes;record_digest=$snapshot.runtime_records.digest;exclude_pyc=$true;exclude_pycache=$true;exact_tree_no_extras=$true};mounts=$snapshot.mounts;modes=$snapshot.modes;all_staged_files_require_nlink=1}
    return([ordered]@{schema='planora.itc2019.canonical-test-authorization.v5';created_at_utc='2026-08-27T04:51:49Z';instance='muni-fspsx-fal17';candidate='muni_v30';test_id=$runId;decision='GO_FOR_EXACTLY_ONE_CANONICAL_IMMUTABLE_SNAPSHOT_SUITE';retained_probe_authorized=$false;official_input_authorized=$false;official_launch_authorized=$false;solver_authorized=$false;publication_authorized=$false;automatic_retry_authorized=$false;runner=[ordered]@{path=$runnerRelative;size=$RunnerSize;sha256=$RunnerHash};pinned_v28_files=[ordered]@{builder=[ordered]@{path='scripts/build_muni_v28_chain.ps1';size=44779;sha256='bca84d0a27ef25e4e716422590aa0e188d3dae22579c9393b51e62c182dde28d'};tests=[ordered]@{path=$testsRelative;size=178441;sha256='f7d16b989ecd3ac22bd218da24c5e9c9bc1dca875f3593d0bad9248eaacfa5ab'};certificate=[ordered]@{path='benchmarks/probe_diagnostics/muni_v28/planora-muni-fspsx-frontier-v28-certificate.json';size=31261;sha256='7b1f4b1ffc3a6cf53389d5cc6c585662536af50f06aced6b5d30fff3e32ad432'};freeze_manifest=[ordered]@{path='benchmarks/probe_diagnostics/muni_v28/planora-muni-fspsx-frontier-v28-freeze-manifest.json';size=33749;sha256='f47beb315d0ea92eec1942f89a9398cd84f4ad81cb1d7f1aff219c1fbbc435e6'}};snapshot_closure=$closure;heavy_gate=[ordered]@{shared_lock='output/diagnostic-receipts/planora-shared-heavy-wsl.lock';lock_mode='CreateNew_held_open';memavailable_minimum_kib=1900000;samples=2;minimum_separation_seconds=5;continuous_monitor='100ms_fail_closed_process_and_memavailable_census_during_canonical_execution';census='fail_closed_allow_current_ancestry_watcher_exact_canonical_chain_and_explicit_minimal_infrastructure_only'};launch_contract=[ordered]@{watcher='ProcessStartInfo_safe_atoms_plus_stdin_source';watcher_lifetime='parent_inotify_started_before_staging_READY_immediately_prelaunch_and_every_poll_through_post_inventory';staged_identity='device_inode_nlink_mode_size_sha256_frozen_and_replayed';host_root=$root;explicit_snapshot_ro_bind='/snapshot';mount_order='synthetic_root_then_snapshot_overlay_then_explicit_empty_host_route_masks';root_read_only=$true;snapshot_read_only=$true;live_drive_hidden=$true;alternate_host_routes_masked=@('/mnt/c','/mnt/wsl','/run/desktop','/media/host','/media/windows');environment_cleared=$true;capabilities_dropped=$true;gnu_timeout=[ordered]@{term_seconds=600;kill_after_seconds=15};host_wsl_deadline_seconds=$hostDeadlineSeconds;host_deadline_termination='taskkill_tree_then_ProcessKill_fail_closed';canonical_execute_sites=1};canonical_contract=[ordered]@{unique_tests=119;expected_passes=117;expected_skips=2;expected_failures=0;expected_errors=0;identity_result_digest='d4dbb5189bcf65870954e5159efbe1ce52208d3b3a0cabc734f7b3f380266afa';strict_stderr_grammar=$true;exact_skip_identities=[ordered]@{'__main__.RuntimeClosureTests.test_real_sealed_runtime_imports_ortools_without_live_site_packages'='heavy sealed-runtime import probe disabled by test contract';'__main__.SealedImportProbeTests.test_real_chain_reaches_probe_admission_without_opening_inputs'='real sealed chain admission disabled by test contract'}};evidence_contract=[ordered]@{atomic_claim='CreateNew_before_preflight';any_failure_consumes_authorization=$true;all_file_nlinks_and_device_inode_retained=$true;exact_staged_file_and_directory_set=$true;no_recursive_copy_or_cache_artifacts=$true;plan_and_receipt_bind_runner_authorization_snapshot=$true;pass_receipt_create_only_after_cleanup_process_lock_mount_and_final_semantic_identity_hash_replay=$true;final_replay_files=@('stdout','stderr','watcher_log','watcher_error','watcher_wrapper_logs','resource_log','resource_error','resource_wrapper_logs','acceptance','cleanup');cleanup_binds_nonpass_acceptance_commitment=$true;rejection_retains_snapshot_when_present=$true}}|ConvertTo-Json -Depth 18)
}

function Get-ExpectedAuthorizationJson([long]$RunnerSize,[string]$RunnerHash){
    $o=(Get-ObsoleteV5AuthorizationJson $RunnerSize $RunnerHash)|ConvertFrom-Json;$o.schema='planora.itc2019.canonical-test-authorization.v8'
    $o.heavy_gate.continuous_monitor='target_100ms_with_authenticated_monotonic_sequence_and_750ms_maximum_gap'
    $o.heavy_gate.census='fail_closed_allow_live_proven_ancestry_or_previously_frozen_descendant_identity_in_exact_launch_namespace_plus_minimal_infrastructure_reject_hostile_siblings'
    $o.heavy_gate|Add-Member -NotePropertyName target_interval_ms -NotePropertyValue 100;$o.heavy_gate|Add-Member -NotePropertyName maximum_gap_ms -NotePropertyValue 750;$o.heavy_gate|Add-Member -NotePropertyName cadence_claim -NotePropertyValue 'bounded_maximum_gap_not_exact_interval';$o.heavy_gate|Add-Member -NotePropertyName pinned_subprocess_sites -NotePropertyValue 16;$o.heavy_gate|Add-Member -NotePropertyName descendant_policy -NotePropertyValue 'live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace'
    $o.launch_contract.watcher_lifetime='ARMED_before_staging_lossless_events_through_final_census_lock_release_replays_and_conditional_PASS_publication_then_receipt_bound_shutdown'
    $o.launch_contract|Add-Member -NotePropertyName staging_event_policy -NotePropertyValue 'preserve_every_armed_parent_event_reject_target_rename_delete_move_overflow_and_parent_IN_IGNORED_IN_UNMOUNT';$o.launch_contract|Add-Member -NotePropertyName parent_watch_policy -NotePropertyValue 'descriptor_identity_pinned_and_loss_or_queue_overflow_rejected_in_every_phase';$o.launch_contract|Add-Member -NotePropertyName cleanup_protocol -NotePropertyValue 'create_only_exclusive_writer_then_two_stable_descriptor_replays_acceptance_bound_control_and_observed_exact_cleanup';$o.launch_contract|Add-Member -NotePropertyName postflight_mutation_policy -NotePropertyValue 'watcher_live_cleaned_state_rejects_snapshot_reappearance_until_conditional_PASS_publication_and_post_publication_replay';$o.launch_contract|Add-Member -NotePropertyName shutdown_protocol -NotePropertyValue 'after_PASS_publication_create_only_control_binds_receipt_inventory_acceptance_cleanup_and_post_publication_replay_then_required_shutdown_seal_binds_DONE'
    $o.evidence_contract.PSObject.Properties.Remove('pass_receipt_create_only_after_cleanup_process_lock_mount_and_final_semantic_identity_hash_replay')
    $o.evidence_contract.atomic_claim='claim_attempt_marked_before_CreateNew_inside_outer_rejection_try_default_fail_closed_claim_v2_before_preflight';$o.evidence_contract.final_replay_files=@('runner','authorization','claim','heavy_lock','staging_inventory','pre_inventory','post_inventory','static_adversarial','plan','stdout','stderr','exit','resource_log','resource_error','resource_wrapper_stdout','resource_wrapper_stderr','acceptance','cleanup','watcher_cleanup_control','heavy_lock_release','conditional_pass_receipt','watcher_log','watcher_error','watcher_wrapper_stdout','watcher_wrapper_stderr','watcher_shutdown_control','pass_publication_shutdown_seal')
    $o.evidence_contract|Add-Member -NotePropertyName pass_receipt_requires_post_publication_authenticated_watcher_shutdown_seal -NotePropertyValue $true;$o.evidence_contract|Add-Member -NotePropertyName watcher_active_through_pass_publication -NotePropertyValue $true;$o.evidence_contract|Add-Member -NotePropertyName watcher_shutdown_evidence_bound_to_pass_receipt -NotePropertyValue $true;$o.evidence_contract|Add-Member -NotePropertyName claim_constructor_write_flush_and_immediate_failures_require_durable_rejection -NotePropertyValue $true;$o.evidence_contract|Add-Member -NotePropertyName emergency_rejection_fallback_create_only -NotePropertyValue $true;$o.evidence_contract|Add-Member -NotePropertyName staging_and_cleanup_event_digests_bound -NotePropertyValue $true;$o.evidence_contract|Add-Member -NotePropertyName resource_admitted_identity_rows_and_digest_bound -NotePropertyValue $true
    return($o|ConvertTo-Json -Depth 20)
}

function Get-ExpectedAuthorizationJson([long]$RunnerSize,[string]$RunnerHash){
    $closure=$snapshotContractJson|ConvertFrom-Json;$predecessor=$predecessorContractJson|ConvertFrom-Json
    $o=[ordered]@{
        schema='planora.itc2019.canonical-test-authorization.v10';created_at_utc='2026-08-28T10:14:48Z';instance='muni-fspsx-fal17';candidate='muni_v30';test_id=$runId
        decision='GO_FOR_EXACTLY_ONE_CANONICAL_IMMUTABLE_SNAPSHOT_SUITE_AFTER_AUTHENTICATED_V29_PRECANONICAL_LOG_FAILURE';retained_probe_authorized=$false;official_input_authorized=$false;official_launch_authorized=$false;solver_authorized=$false;publication_authorized=$false;automatic_retry_authorized=$false
        runner=[ordered]@{path=$runnerRelative;size=$RunnerSize;sha256=$RunnerHash}
        successor_admission=[ordered]@{builder=[ordered]@{path='scripts/build_muni_v30_successor.py';size=59115;sha256='c33cafd5260b79365ce434c086cf4e31c4333c904480b7ae445f15970201cb25'};tests=[ordered]@{path='tests/test_run_muni_v30_successor.py';size=17533;sha256='a0f7cad0ff955827f061a5f6228a45e1f8b9c09b22fa378318f4aea3793c621e'}}
        predecessor_custody_contract=$predecessor
        snapshot_closure=$closure
        log_bridge_contract=[ordered]@{writer='create_only_reserve_close_then_identity_checked_short_lived_append_fsync';reader='bounded_explicit_FileStream_stable_identity_length_terminal_LF_UTF8_JSON';watcher_and_resource_monitor_both_fixed=$true;legacy_lifetime_open_negative_baseline_required=$true;isolated_switch='LogBridgeSelfTest';canonical_suite_executed_by_bridge_test=$false}
        heavy_gate=[ordered]@{shared_lock='output/diagnostic-receipts/planora-shared-heavy-wsl.lock';lock_mode='CreateNew_ReadWrite_FileShareNone_DeleteOnClose_same_handle_seek_read_hash';memavailable_minimum_kib=1900000;samples=2;minimum_separation_seconds=5;continuous_monitor='target_100ms_with_authenticated_monotonic_sequence_and_750ms_maximum_gap';census='fail_closed_allow_live_proven_ancestry_or_previously_frozen_descendant_identity_in_exact_launch_namespace_plus_minimal_infrastructure_reject_hostile_siblings';target_interval_ms=100;maximum_gap_ms=750;cadence_claim='bounded_maximum_gap_not_exact_interval';pinned_subprocess_sites=16;descendant_policy='live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace'}
        launch_contract=[ordered]@{watcher='ProcessStartInfo_safe_atoms_plus_stdin_source';watcher_lifetime='ARMED_before_staging_lossless_events_through_final_census_same_handle_lock_release_replays_and_conditional_PASS_publication_then_receipt_bound_shutdown';staged_identity='device_inode_nlink_mode_size_sha256_frozen_and_replayed';host_root=$root;explicit_snapshot_ro_bind='/snapshot';root_read_only=$true;snapshot_read_only=$true;live_drive_hidden=$true;environment_cleared=$true;capabilities_dropped=$true;gnu_timeout=[ordered]@{term_seconds=600;kill_after_seconds=15};host_wsl_deadline_seconds=$hostDeadlineSeconds;canonical_execute_sites=1}
        canonical_contract=[ordered]@{unique_tests=119;expected_passes=117;expected_skips=2;expected_failures=0;expected_errors=0;identity_result_digest='d4dbb5189bcf65870954e5159efbe1ce52208d3b3a0cabc734f7b3f380266afa';strict_stderr_grammar=$true;exact_skip_identities=[ordered]@{'__main__.RuntimeClosureTests.test_real_sealed_runtime_imports_ortools_without_live_site_packages'='heavy sealed-runtime import probe disabled by test contract';'__main__.SealedImportProbeTests.test_real_chain_reaches_probe_admission_without_opening_inputs'='real sealed chain admission disabled by test contract'}}
        evidence_contract=[ordered]@{atomic_claim='claim_attempt_marked_before_CreateNew_inside_outer_rejection_try_default_fail_closed_claim_v2_before_preflight';any_failure_consumes_authorization=$true;complete_v28_v29_predecessor_evidence_bound_to_plan_pass_and_all_rejections=$true;all_predecessor_file_ids_and_timestamps_authorized=$true;predecessor_pins_in_protected_replay_sets=$true;v28_v29_pass_absence_replayed_through_final_pass_seal_publication=$true;retained_archive_validated_in_place_without_mutation=$true;terminal_archived_lock_identity_replay_bound_by_final_pass_seal=$true;terminal_archived_lock_read_guard_held_through_final_pass_seal_flush=$true;final_pass_seal_create_only_durable_last_operation=$true;new_lock_verified_only_through_held_handle=$true;new_lock_release='same_handle_stable_bytes_then_DeleteOnClose';all_file_nlinks_and_device_inode_retained=$true;exact_staged_file_and_directory_set=$true;plan_and_receipt_bind_runner_authorization_snapshot_predecessor_and_custody=$true;pass_receipt_requires_post_publication_authenticated_watcher_shutdown_seal=$true;watcher_active_through_pass_publication=$true;claim_constructor_write_flush_and_immediate_failures_require_durable_rejection=$true;emergency_rejection_fallback_create_only=$true}
    }
    return($o|ConvertTo-Json -Depth 40 -Compress)
}

if($EmitExpectedAuthorization){
    $runnerItem=Get-Item -LiteralPath $runnerPath
    [Console]::Out.WriteLine((Get-ExpectedAuthorizationJson $runnerItem.Length (Get-Sha256 $runnerPath)))
    return
}

function Get-AuthorizationState{$i=Get-Item -LiteralPath $runnerPath;$h=Get-Sha256 $runnerPath;$ah=Get-Sha256 $authorizationPath;$raw=[IO.File]::ReadAllText($authorizationPath,$utf8);$o=$raw|ConvertFrom-Json;$expected=Get-ExpectedAuthorizationJson $i.Length $h;if((ConvertTo-JsonTokenStream $raw)-cne(ConvertTo-JsonTokenStream $expected)){throw 'Authorization exact semantic replay rejected'};if($o.runner.size-ne$i.Length-or$o.runner.sha256-cne$h){throw 'Runner self-pin rejected'};return [ordered]@{runner_item=$i;runner_sha256=$h;authorization=$o;authorization_sha256=$ah}}

function Get-LegacyRows{$source=[IO.File]::ReadAllText($testsPath,$utf8);$matches=[regex]::Matches($source,'(?m)^\s*"(?<path>/tmp/planora[^"\r\n]+)":\s*"(?<hash>[0-9a-f]{64})",?$');$rows=@(foreach($m in $matches){$p=$m.Groups['path'].Value;$leaf=$p.Substring(5);[pscustomobject]@{source=$p;leaf=$leaf;sha256=$m.Groups['hash'].Value;staged="$root/legacy/$leaf"}});if($rows.Count-ne48-or@($rows.leaf|Sort-Object -Unique).Count-ne48){throw 'Legacy closure is not 48 unique rows'};foreach($v in 12,13,14,15){if(@($rows|Where-Object{$_.leaf-match"v$v"}).Count-ne12){throw "Legacy v$v count rejected"}};if(@($rows|Where-Object{$_.leaf-match'(?i)official|input|progress|checkpoint|solution|probe|derivation-audit'}).Count-ne0){throw 'Forbidden legacy payload'};return $rows}

function Invoke-LocalStaticAdversarialChecks{
    $unsafe=@('two words',"tab`tvalue",'double"quote','back\slash','shell&value','pipe|value','$expand','`tick');foreach($w in $unsafe){if(Test-SafeNativeAtom $w){throw "Unsafe quoting witness accepted: $w"}}
    $safe=@('-d','Ubuntu','--exec','/usr/bin/python3.12','-c',"exec(compile(open(0,'rb').read(),'<stdin>','exec'))",'YWJjZA==');foreach($w in $safe){if(-not(Test-SafeNativeAtom $w)){throw "Safe atom rejected: $w"}}
    $hardlink=[pscustomobject]@{nlink=2};$rejected=$false;try{if($hardlink.nlink-ne1){throw'nlink'}}catch{$rejected=$true};if(-not$rejected){throw 'Hardlink witness accepted'}
    $ps='20 10 1000 ps ps -eo pid=,ppid=,uid=,comm=,args=';$base=@('1 0 0 init /init','10 1 0 init /init',$ps);[void](Convert-WslProcessCensus $base)
    $witnesses=@('30 1 1000 stress-ng stress-ng --vm 1','30 1 1000 pytest pytest -q','30 1 1000 python python test.py','30 1 1000 java java Main','30 1 1000 scip scip model','30 1 1000 ninja ninja build','30 1 1000 docker docker ps','30 1 1000 bash bash');foreach($w in $witnesses){$bad=$false;try{[void](Convert-WslProcessCensus(@($base)+$w))}catch{$bad=$true};if(-not$bad){throw "Census witness accepted: $w"}}
    $skip=@{'__main__.FixtureTests.test_skip'='exact heavy skip'};$fixtureRows=@(('__main__.FixtureTests.test_a|ok|'+"`n"),('__main__.FixtureTests.test_b|ok|'+"`n"),('__main__.FixtureTests.test_skip|skip|exact heavy skip'+"`n"));$fixtureDigest=Get-TranscriptDigest $fixtureRows
    $fixture="test_a (__main__.FixtureTests.test_a) ... ok`ntest_b (__main__.FixtureTests.test_b) ... ok`ntest_skip (__main__.FixtureTests.test_skip) ... skipped 'exact heavy skip'`n`n$('-'*70)`nRan 3 tests in 0.125s`n`nOK (skipped=1)`n"
    [void](Assert-CanonicalUnittestTranscript $fixture 3 2 $skip $fixtureDigest)
    $transcriptMutations=@(($fixture+"diagnostic`n"),($fixture.Replace('test_a (__main__.FixtureTests.test_a) ... ok','test_a  (__main__.FixtureTests.test_a) ... ok')),($fixture.Replace('Ran 3 tests in 0.125s','Ran 3 tests in 0.12s')),($fixture.Replace("skipped 'exact heavy skip'","skipped 'wrong reason'")),($fixture.Replace("test_a (__main__.FixtureTests.test_a) ... ok`ntest_b (__main__.FixtureTests.test_b) ... ok","test_b (__main__.FixtureTests.test_b) ... ok`ntest_a (__main__.FixtureTests.test_a) ... ok")),($fixture.Replace('test_b (__main__.FixtureTests.test_b) ... ok','test_a (__main__.FixtureTests.test_a) ... ok')))
    foreach($mutation in $transcriptMutations){$bad=$false;try{[void](Assert-CanonicalUnittestTranscript $mutation 3 2 $skip $fixtureDigest)}catch{$bad=$true};if(-not$bad){throw 'Adversarial unittest transcript accepted'}}
    [void](Assert-WatcherStateModel $false $false $false @('ARMED','READY'));$watcherMutations=@(@($true,$false,$false,@('ARMED','READY')),@($false,$true,$false,@('ARMED','READY')),@($false,$false,$true,@('ARMED','READY')),@($false,$false,$false,@('READY')),@($false,$false,$false,@('ARMED','READY','DONE')),@($false,$false,$false,@('ARMED','EVENT')),@($false,$false,$false,@('DONE')))
    foreach($state in $watcherMutations){$bad=$false;try{[void](Assert-WatcherStateModel $state[0] $state[1] $state[2] $state[3])}catch{$bad=$true};if(-not$bad){throw 'Adversarial watcher state accepted'}}
    [void](Assert-ResourceStateModel $false $false $false $true @('READY','SAMPLE'));$resourceMutations=@(@($true,$false,$false,$true,@('READY','SAMPLE')),@($false,$true,$false,$true,@('READY','SAMPLE')),@($false,$false,$true,$true,@('READY','SAMPLE')),@($false,$false,$false,$false,@('READY','SAMPLE')),@($false,$false,$false,$true,@('READY','DONE')),@($false,$false,$false,$true,@('SAMPLE')))
    foreach($state in $resourceMutations){$bad=$false;try{[void](Assert-ResourceStateModel $state[0] $state[1] $state[2] $state[3] $state[4])}catch{$bad=$true};if(-not$bad){throw 'Adversarial resource monitor state accepted'}}
    $lineage=@([pscustomobject]@{pid=101;ppid=100;launch_namespace='sealed';launch_identity_bound=$true;previously_frozen=$false;minimal_infrastructure=$false},[pscustomobject]@{pid=102;ppid=101;launch_namespace='sealed';launch_identity_bound=$true;previously_frozen=$false;minimal_infrastructure=$false});$lineageResult=Assert-CanonicalDescendantModel $lineage 100 'sealed';if($lineageResult.descendants-ne2){throw 'Legitimate child/grandchild lineage was not admitted'}
    $reparented=@($lineage)+[pscustomobject]@{pid=103;ppid=1;launch_namespace='sealed';launch_identity_bound=$true;previously_frozen=$true;minimal_infrastructure=$false};if((Assert-CanonicalDescendantModel $reparented 100 'sealed').descendants-ne3){throw 'Previously frozen reparented descendant was not admitted'}
    $hostileSiblingRejected=$false;try{[void](Assert-CanonicalDescendantModel (@($lineage)+[pscustomobject]@{pid=200;ppid=1;launch_namespace='sealed';launch_identity_bound=$true;previously_frozen=$false;minimal_infrastructure=$false}) 100 'sealed')}catch{$hostileSiblingRejected=$true};if(-not$hostileSiblingRejected){throw 'Hostile same-namespace sibling witness accepted'}
    $unrelatedRejected=$false;try{[void](Assert-CanonicalDescendantModel (@($lineage)+[pscustomobject]@{pid=201;ppid=1;launch_namespace='host';launch_identity_bound=$false;previously_frozen=$false;minimal_infrastructure=$false}) 100 'sealed')}catch{$unrelatedRejected=$true};if(-not$unrelatedRejected){throw 'Unrelated workload lineage witness accepted'}
    $target=$root.Split('/')[-1];$parentWd=7;$stageEvents=@([pscustomobject]@{sequence=1;scope='ambient_parent';path='unrelated-before-root';mask=0x00000100;wd=$parentWd},[pscustomobject]@{sequence=2;scope='snapshot';path=$target;mask=0x40000100;wd=$parentWd},[pscustomobject]@{sequence=3;scope='snapshot';path=$target;mask=0x00000004;wd=$parentWd});[void](Assert-StagingEventModel $stageEvents $target $parentWd)
    $stagingRenameRejected=$false;$renamed=@($stageEvents)+[pscustomobject]@{sequence=4;scope='snapshot';path=$target;mask=0x00000040;wd=$parentWd};try{[void](Assert-StagingEventModel $renamed $target $parentWd)}catch{$stagingRenameRejected=$true};if(-not$stagingRenameRejected){throw 'Staging rename-away event witness accepted'}
    $parentLossRejected=0;foreach($lossMask in @(0x00008000,0x00002000)){try{[void](Assert-StagingEventModel (@($stageEvents)+[pscustomobject]@{sequence=4;scope='ambient_parent';path='.';mask=$lossMask;wd=$parentWd}) $target $parentWd)}catch{$parentLossRejected++}};if($parentLossRejected-ne2){throw 'Parent watch loss witness accepted'}
    [void](Assert-PostflightWatcherModel @('CLEANED') @('boundary'));$postflightMutationRejected=$false;try{[void](Assert-PostflightWatcherModel @('CLEANED_EVENT','CLEANED') @('snapshot','boundary'))}catch{$postflightMutationRejected=$true};if(-not$postflightMutationRejected){throw 'Postflight mutation witness accepted'}
    $cadenceReady=[pscustomobject]@{kind='READY';target_interval_ms=100;maximum_gap_ms=750;pinned_subprocess_sites=16;cadence_claim='bounded_maximum_gap_not_exact_interval';descendant_policy='live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace'};$cadenceGood=@($cadenceReady,[pscustomobject]@{kind='SAMPLE';sequence=1;memavailable_kib=1900000;monotonic_ns=1000000000;gap_ns=0},[pscustomobject]@{kind='SAMPLE';sequence=2;memavailable_kib=1900000;monotonic_ns=1100000000;gap_ns=100000000});[void](Assert-ResourceCadenceRows $cadenceGood $false)
    $gapRejected=$false;$cadenceBad=@($cadenceReady,[pscustomobject]@{kind='SAMPLE';sequence=1;memavailable_kib=1900000;monotonic_ns=1000000000;gap_ns=0},[pscustomobject]@{kind='SAMPLE';sequence=2;memavailable_kib=1900000;monotonic_ns=1800000001;gap_ns=800000001});try{[void](Assert-ResourceCadenceRows $cadenceBad $false)}catch{$gapRejected=$true};if(-not$gapRejected){throw 'Oversized monitor cadence gap accepted'}
    $testLines=[IO.File]::ReadAllLines($testsPath,$utf8);$subprocessSites=@(379,407,993,1005,1017,1029,1087,1375,2155,2633,2721,3285,3390,3421,3455,3517);foreach($line in $subprocessSites){if($testLines[$line-1]-cnotmatch'subprocess\.(?:run|Popen)\('){throw "Pinned subprocess site drift: $line"}}
    [void](Assert-HostDeadlineModel 629999 630000 $false);[void](Assert-HostDeadlineModel 630000 630000 $true);$deadlineRejected=$false;try{[void](Assert-HostDeadlineModel 630000 630000 $false)}catch{$deadlineRejected=$true};if(-not$deadlineRejected){throw 'Host deadline expiry witness accepted'}
    $identity=[pscustomobject]@{device=1;inode=2;nlink=1;mode='0400';size=3;sha256=('a'*64)};[void](Assert-IdentityReplayModel $identity $identity);$identityMutations=0;foreach($property in @('device','inode','nlink','mode','size','sha256')){$copy=[pscustomobject]@{device=1;inode=2;nlink=1;mode='0400';size=3;sha256=('a'*64)};$copy.$property=if($property-ceq'sha256'){'b'*64}elseif($property-ceq'mode'){'0600'}else{9};$bad=$false;try{[void](Assert-IdentityReplayModel $identity $copy)}catch{$bad=$true};if(-not$bad){throw "Identity mutation accepted: $property"};$identityMutations++}
    [void](Assert-SemanticReplayModel '{"a":1,"b":[true]}' " { `"a`" : 1, `"b`" : [ true ] } ");$semanticRejected=$false;try{[void](Assert-SemanticReplayModel '{"a":2}' '{"a":1}')}catch{$semanticRejected=$true};if(-not$semanticRejected){throw 'Semantic replay mutation accepted'}
    $runnerPin=Get-LocalEvidencePin $runnerPath;[void](Assert-LocalEvidencePin $runnerPin);$pinMutation=[ordered]@{};foreach($key in $runnerPin.Keys){$pinMutation[$key]=$runnerPin[$key]};$pinMutation.sha256='0'*64;$pinRejected=$false;try{[void](Assert-LocalEvidencePin ([pscustomobject]$pinMutation))}catch{$pinRejected=$true};if(-not$pinRejected){throw 'Evidence pin mutation accepted'}
    $claimFailures=0;foreach($fault in @('constructor','immediate_after_create','write','flush','immediate_after_publish')){$claimResult=Assert-ClaimFailureModel $fault;if(-not$claimResult.claim_attempted-or-not$claimResult.durable_rejection_required-or-not$claimResult.detailed_rejection_required){throw "Claim failure was not rejection-covered: $fault"};if($fault-ceq'constructor' -and $claimResult.claim_created){throw 'Constructor-failure model incorrectly created a claim'};if($fault-cne'constructor' -and -not$claimResult.claim_created){throw "Post-create failure model lacks a claim: $fault"};$claimFailures++}
    $publication=[ordered]@{canonical_exited=$true;watcher_live_cleaned=$true;parent_watch_active=$true;resource_monitor_exited=$true;resource_monitor_clean=$true;snapshot_absent=$true;shared_lock_absent=$true;cleanup_evidence_present=$true;lock_release_evidence_present=$true;acceptance_commitment_present=$true;postflight_census_clean=$true;protected_evidence_replayed=$true};[void](Assert-PassPublicationReady $publication);$publicationMutations=0;foreach($property in @($publication.Keys)){$copy=[ordered]@{};foreach($key in $publication.Keys){$copy[$key]=$publication[$key]};$copy[$property]=$false;$bad=$false;try{[void](Assert-PassPublicationReady ([pscustomobject]$copy))}catch{$bad=$true};if(-not$bad){throw "PASS publication mutation accepted: $property"};$publicationMutations++}
    $final=[ordered]@{canonical_exited=$true;watcher_exited=$true;watcher_clean=$true;resource_monitor_exited=$true;resource_monitor_clean=$true;snapshot_absent=$true;shared_lock_absent=$true;cleanup_evidence_present=$true;lock_release_evidence_present=$true;acceptance_commitment_present=$true;postflight_census_clean=$true;final_evidence_replayed=$true;pass_receipt_present=$true;final_pass_seal_absent_before_publication=$true};[void](Assert-FinalizationReady $final)
    foreach($property in @($final.Keys)){$copy=[ordered]@{};foreach($key in $final.Keys){$copy[$key]=$final[$key]};$copy[$property]=$false;$bad=$false;try{[void](Assert-FinalizationReady ([pscustomobject]$copy))}catch{$bad=$true};if(-not$bad){throw "Finalization mutation accepted: $property"}}
    return [ordered]@{schema='planora.muni-v30.local-static-adversarial.v5';safe_atom_roundtrip='PASS';unsafe_quoting_witnesses=$unsafe.Count;hardlink_nlink2='REJECTED';census_allowed_minimal='PASS';census_rejection_witnesses=$witnesses.Count;legitimate_child_grandchild='ADMITTED';previously_frozen_reparented_descendant='ADMITTED';hostile_same_namespace_sibling='REJECTED';unrelated_workload='REJECTED';pinned_subprocess_sites=$subprocessSites.Count;staging_events_preserved='PASS';staging_rename_away='REJECTED';parent_watch_loss_witnesses_rejected=$parentLossRejected;postflight_mutation='REJECTED';cadence_target_ms=100;cadence_maximum_gap_ms=750;oversized_cadence_gap='REJECTED';claim_failure_points_rejected=$claimFailures;pass_publication_mutations_rejected=$publicationMutations;unittest_transcript_mutations_rejected=$transcriptMutations.Count;watcher_lifetime_mutations_rejected=$watcherMutations.Count;resource_monitor_mutations_rejected=$resourceMutations.Count;host_deadline_expiry='REJECTED';identity_mutations_rejected=$identityMutations;semantic_mutation='REJECTED';evidence_pin_mutation='REJECTED';finalization_mutations_rejected=$final.Count;live_repo_execution_path='MUST_BE_REJECTED'}
}

function Assert-LocalFrozenClosure{
    $contract=$snapshotContractJson|ConvertFrom-Json;if($contract.schema-cne'planora.muni-v30.snapshot-closure.v4'){throw 'Static closure schema rejected'}
    if(@($contract.historical.versions).Count-ne12-or@($contract.historical.name_templates).Count-ne13-or@($contract.v28_tree.names).Count-ne14-or@($contract.source_files.rows).Count-ne17){throw 'Explicit frozen closure cardinality rejected'}
    $rows=@($contract.source_files.rows);$total=0;foreach($row in $rows){$total+=[long]$row[1]};if($total-ne854835){throw 'Frozen source byte total rejected'}
    $factorized=@($rows|Where-Object{$_[0]-ceq'benchmarks/itc2019_factorized.py'});if($factorized.Count-ne1-or$factorized[0][3]-cne'frozen-git-object'){throw 'Frozen factorized origin rejected'}
    foreach($row in $rows){if($row[3]-ceq'frozen-hash-source'){Assert-LocalPin (Join-Path $repo ($row[0].Replace('/','\'))) ([long]$row[1]) ([string]$row[2])}elseif($row[3]-cne'frozen-git-object'){throw 'Unknown frozen source origin'}}
    $object=$contract.source_files.frozen_git_object;$objectPath=Join-Path $repo ($object.path.Replace('/','\'));Assert-LocalPin $objectPath $object.size $object.sha256
    $packed=[IO.File]::ReadAllBytes($objectPath);$input=New-Object IO.MemoryStream(,$packed[2..($packed.Length-5)]);$deflate=New-Object IO.Compression.DeflateStream($input,[IO.Compression.CompressionMode]::Decompress);$output=New-Object IO.MemoryStream
    try{$deflate.CopyTo($output);$expanded=$output.ToArray()}finally{$deflate.Dispose();$input.Dispose();$output.Dispose()}
    $nul=[Array]::IndexOf($expanded,[byte]0);if($nul-lt1){throw 'Frozen Git blob header rejected'};$header=[Text.Encoding]::ASCII.GetString($expanded,0,$nul);$payload=New-Object byte[] ($expanded.Length-$nul-1);[Array]::Copy($expanded,$nul+1,$payload,0,$payload.Length)
    $sha1=[Security.Cryptography.SHA1]::Create();$sha256=[Security.Cryptography.SHA256]::Create();try{$objectId=([BitConverter]::ToString($sha1.ComputeHash($expanded))-replace'-','').ToLowerInvariant();$payloadHash=([BitConverter]::ToString($sha256.ComputeHash($payload))-replace'-','').ToLowerInvariant()}finally{$sha1.Dispose();$sha256.Dispose()}
    if($header-cne"blob $($object.decoded_size)"-or$objectId-cne$object.git_object_id-or$payload.Length-ne$object.decoded_size-or$payloadHash-cne$object.decoded_sha256){throw 'Frozen Git blob payload pin rejected'}
    if((Get-Sha256 (Join-Path $repo 'benchmarks\itc2019_factorized.py'))-ceq$object.decoded_sha256){throw 'Live-worktree drift witness unexpectedly absent'}
    $source=[IO.File]::ReadAllText($runnerPath,$utf8);$match=[regex]::Match($source,'(?s)\$stagingSource = @''\r?\n(.*?)\r?\n''@')
    if(-not$match.Success-or$match.Groups[1].Value-cmatch'os\.listdir|copytree\('){throw 'Recursive or enumerated staging source remains'}
    foreach($name in @($contract.historical.name_templates)+@($contract.v28_tree.names)+@($rows|ForEach-Object{$_[0]})){if($name-cmatch'__pycache__|\.py[co]$'){throw 'Cache artifact exists in explicit closure'}}
    return 'PASS'
}

function Invoke-LocalArgumentBoundaryWitness{
    $child=if($PSVersionTable.PSEdition-ceq'Desktop'){Join-Path $PSHOME 'powershell.exe'}else{Join-Path $PSHOME 'pwsh.exe'}
    $code='$raw=[Console]::In.ReadToEnd();if($raw-cne''BOUNDARY_WITNESS''){exit 41};[Console]::Out.Write(''BOUNDARY_PASS'')'
    $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($code))
    $result=Invoke-SafeStdinProcess $child @('-NoProfile','-NonInteractive','-EncodedCommand',$encoded) 'BOUNDARY_WITNESS' 'local encoded-command boundary witness'
    if($result.stdout-cne'BOUNDARY_PASS'-or$result.stderr.Length-ne0){throw 'Local encoded-command boundary witness rejected'}
    return 'PASS'
}

$stagingSource = @'
import base64,csv,hashlib,json,os,stat,sys,zlib
from pathlib import PurePosixPath
c=json.loads(base64.b64decode(sys.argv[1])); root=c['root']; repo=c['repo']; out=c['out']; contract=c['contract']; seen=set()
def ident(s): return (s.st_dev,s.st_ino,s.st_size,stat.S_IFMT(s.st_mode),stat.S_IMODE(s.st_mode),s.st_uid,s.st_gid,s.st_nlink,s.st_mtime_ns,s.st_ctime_ns)
def valid_rel(rel):
 p=PurePosixPath(rel)
 if not rel or p.is_absolute() or '..' in p.parts or '\\' in rel or p.as_posix()!=rel: raise RuntimeError('relative path rejected: '+rel)
 return p
def read_source(path,maximum=8<<20):
 fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
 try:
  before=os.fstat(fd)
  if not stat.S_ISREG(before.st_mode) or before.st_size<0 or before.st_size>maximum: raise RuntimeError('source metadata rejected: '+path)
  chunks=[]; h=hashlib.sha256(); total=0
  while total<before.st_size:
   b=os.pread(fd,min(1<<20,before.st_size-total),total)
   if not b: raise RuntimeError('source short read: '+path)
   chunks.append(b);h.update(b);total+=len(b)
  if os.pread(fd,1,total) or ident(os.fstat(fd))!=ident(before): raise RuntimeError('source identity drift: '+path)
  return b''.join(chunks),h.hexdigest(),total
 finally: os.close(fd)
def mkdirs(rel):
 current=root
 for part in valid_rel(rel).parts[:-1]:
  current=current+'/'+part
  try: os.mkdir(current,0o700)
  except FileExistsError:
   s=os.lstat(current)
   if not stat.S_ISDIR(s.st_mode) or stat.S_ISLNK(s.st_mode): raise RuntimeError('snapshot directory rejected: '+current)
def copy_verified(src,rel,expected,size):
 valid_rel(rel)
 if rel in seen: raise RuntimeError('duplicate snapshot target: '+rel)
 seen.add(rel);mkdirs(rel);dst=root+'/'+rel
 infd=os.open(src,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
 try:
  before=os.fstat(infd)
  if not stat.S_ISREG(before.st_mode) or before.st_size!=size: raise RuntimeError('copy source metadata rejected: '+src)
  outfd=os.open(dst,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o400)
  try:
   h=hashlib.sha256();off=0
   while off<size:
    b=os.pread(infd,min(1<<20,size-off),off)
    if not b: raise RuntimeError('copy source short read: '+src)
    view=memoryview(b)
    while view:
     n=os.write(outfd,view)
     if n<=0: raise RuntimeError('snapshot write failed')
     view=view[n:]
    h.update(b);off+=len(b)
   if os.pread(infd,1,off) or ident(os.fstat(infd))!=ident(before) or h.hexdigest()!=expected: raise RuntimeError('copy source hash or identity rejected: '+src)
   os.fchmod(outfd,0o400);os.fsync(outfd)
  finally: os.close(outfd)
 finally: os.close(infd)
 s=os.lstat(dst)
 if not stat.S_ISREG(s.st_mode) or stat.S_IMODE(s.st_mode)!=0o400 or s.st_nlink!=1: raise RuntimeError('staged file metadata rejected: '+rel)
def copy_bytes(raw,rel,expected,size):
 valid_rel(rel)
 if rel in seen or len(raw)!=size or hashlib.sha256(raw).hexdigest()!=expected: raise RuntimeError('embedded frozen bytes rejected: '+rel)
 seen.add(rel);mkdirs(rel);dst=root+'/'+rel;fd=os.open(dst,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o400)
 try:
  view=memoryview(raw)
  while view:
   n=os.write(fd,view)
   if n<=0: raise RuntimeError('embedded snapshot write failed')
   view=view[n:]
  os.fchmod(fd,0o400);os.fsync(fd)
 finally: os.close(fd)
 s=os.lstat(dst)
 if not stat.S_ISREG(s.st_mode) or stat.S_IMODE(s.st_mode)!=0o400 or s.st_nlink!=1: raise RuntimeError('embedded staged metadata rejected: '+rel)
def group(base,names):
 rows=[]
 for name in sorted(names):
  raw,h,n=read_source(base+'/'+name,256<<20);rows.append((name,h,n))
 return rows
def group_digest(rows): return hashlib.sha256(b''.join(n.encode()+b'\0'+h.encode()+b'\0'+str(s).encode()+b'\n' for n,h,s in sorted(rows))).hexdigest()
def require_group(rows,count,total,digest,label):
 if len(rows)!=count or sum(x[2] for x in rows)!=total or group_digest(rows)!=digest: raise RuntimeError(label+' closure digest rejected')
def inventory():
 dirs=[];files=[];total=0
 for current,names,leaves in os.walk(root,topdown=True,followlinks=False):
  rel=os.path.relpath(current,root).replace(os.sep,'/');s=os.lstat(current);mode=stat.S_IMODE(s.st_mode)
  if not stat.S_ISDIR(s.st_mode) or stat.S_ISLNK(s.st_mode) or mode!=(0o700 if rel=='.' else 0o500): raise RuntimeError('inventory directory rejected: '+rel)
  dirs.append({'path':rel,'mode':format(mode,'04o'),'device':s.st_dev,'inode':s.st_ino,'nlink':s.st_nlink})
  for name in names:
   child=os.lstat(current+'/'+name)
   if not stat.S_ISDIR(child.st_mode) or stat.S_ISLNK(child.st_mode): raise RuntimeError('inventory child directory rejected: '+name)
  for name in sorted(leaves):
   path=current+'/'+name;r=(name if rel=='.' else rel+'/'+name);s=os.lstat(path)
   if not stat.S_ISREG(s.st_mode) or stat.S_ISLNK(s.st_mode) or stat.S_IMODE(s.st_mode)!=0o400 or s.st_nlink!=1: raise RuntimeError('inventory file metadata rejected: '+r)
   h=hashlib.sha256()
   with open(path,'rb',buffering=0) as f:
    while True:
     b=f.read(1<<20)
     if not b: break
     h.update(b)
   files.append({'path':r,'type':'regular file','mode':'0400','device':s.st_dev,'inode':s.st_ino,'nlink':1,'size':s.st_size,'sha256':h.hexdigest()});total+=s.st_size
 return {'schema':'planora.muni-v30.snapshot-inventory.v1','root':root,'directory_count':len(dirs),'file_count':len(files),'total_bytes':total,'directories':sorted(dirs,key=lambda x:x['path']),'files':sorted(files,key=lambda x:x['path'])}
if contract.get('schema')!='planora.muni-v30.snapshot-closure.v4': raise RuntimeError('snapshot contract schema rejected')
if os.path.lexists(root): raise RuntimeError('snapshot root already exists')
os.mkdir(root,0o700)
for version in contract['historical']['versions']:
 version=str(version);base=repo+'/benchmarks/probe_diagnostics/muni_v'+version
 names=sorted(x.replace('{v}',version) for x in contract['historical']['name_templates'])
 if len(names)!=13 or len(set(names))!=13: raise RuntimeError('historical explicit name set rejected: v'+version)
 rows=group(base,names)
 if group_digest(rows)!=contract['historical']['tree_digests'][version]: raise RuntimeError('historical tree digest rejected: v'+version)
 for name,h,n in rows: copy_verified(base+'/'+name,'repo/benchmarks/probe_diagnostics/muni_v'+version+'/'+name,h,n)
base=repo+'/benchmarks/probe_diagnostics/muni_v28';names=sorted(contract['v28_tree']['names']);rows=group(base,names)
require_group(rows,contract['v28_tree']['files'],contract['v28_tree']['bytes'],contract['v28_tree']['digest'],'v28 tree')
for name,h,n in rows: copy_verified(base+'/'+name,'repo/benchmarks/probe_diagnostics/muni_v28/'+name,h,n)
rows=[]
for name,n,h,origin in contract['source_files']['rows']:
 if origin=='frozen-git-object':
  obj=contract['source_files']['frozen_git_object'];packed,obj_h,obj_n=read_source(repo+'/'+obj['path'],32<<20)
  if obj_n!=obj['size'] or obj_h!=obj['sha256']: raise RuntimeError('frozen git object pin rejected')
  expanded=zlib.decompress(packed);header=('blob '+str(obj['decoded_size'])+'\0').encode()
  if not expanded.startswith(header) or hashlib.sha1(expanded).hexdigest()!=obj['git_object_id']: raise RuntimeError('frozen git object identity rejected')
  raw=expanded[len(header):]
  if len(raw)!=n or hashlib.sha256(raw).hexdigest()!=h or n!=obj['decoded_size'] or h!=obj['decoded_sha256']: raise RuntimeError('frozen git object payload rejected')
  copy_bytes(raw,'repo/'+name,h,n)
 elif origin=='frozen-hash-source': copy_verified(repo+'/'+name,'repo/'+name,h,n)
 else: raise RuntimeError('source origin rejected: '+origin)
 rows.append((name,h,n))
require_group(rows,contract['source_files']['files'],contract['source_files']['bytes'],contract['source_files']['digest'],'source files')
site=repo+'/.venv/lib/python3.12/site-packages';record_names=list(contract['runtime_records']['paths']);record_rows=group(site,record_names)
require_group(record_rows,contract['runtime_records']['files'],contract['runtime_records']['bytes'],contract['runtime_records']['digest'],'runtime records')
records={}
for name,h,n in record_rows:
 copy_verified(site+'/'+name,'repo/.venv/lib/python3.12/site-packages/'+name,h,n)
 raw,_,_=read_source(site+'/'+name)
 for row in csv.reader(raw.decode('utf-8').splitlines()):
  if len(row)!=3: raise RuntimeError('runtime RECORD row malformed')
  path,encoded,size=row;p=PurePosixPath(path)
  if not path or p.is_absolute() or '..' in p.parts or '\\' in path or p.as_posix()!=path or not encoded.startswith('sha256=') or not size or p.suffix=='.pyc' or '__pycache__' in p.parts: continue
  if path in records: raise RuntimeError('duplicate runtime RECORD path: '+path)
  digest=base64.urlsafe_b64decode(encoded[7:]+'='*(-len(encoded[7:])%4)).hex();n=int(size)
  if n<0 or n>contract['runtime_policy']['max_file_bytes']: raise RuntimeError('runtime file size rejected')
  records[path]=(digest,n)
if len(records)>contract['runtime_policy']['max_files'] or sum(x[1] for x in records.values())>contract['runtime_policy']['max_total_bytes']: raise RuntimeError('runtime closure limit rejected')
for name,(h,n) in sorted(records.items()): copy_verified(site+'/'+name,'repo/.venv/lib/python3.12/site-packages/'+name,h,n)
for row in c['legacy']: copy_verified(row['source'],'legacy/'+row['leaf'],row['sha256'],os.lstat(row['source']).st_size)
for current,names,_ in os.walk(root,topdown=False,followlinks=False):
 if current!=root: os.chmod(current,0o500)
os.chmod(root,0o700)
inv=inventory();raw=json.dumps(inv,sort_keys=True,separators=(',',':')).encode()
actual_files=[x['path'] for x in inv['files']];expected_files=sorted(seen)
expected_dirs={'.'}
for rel in seen:
 parts=rel.split('/')[:-1]
 for i in range(1,len(parts)+1): expected_dirs.add('/'.join(parts[:i]))
actual_dirs=[x['path'] for x in inv['directories']]
if actual_files!=expected_files or actual_dirs!=sorted(expected_dirs): raise RuntimeError('snapshot exact file/directory set rejected')
if any('__pycache__' in PurePosixPath(x).parts or x.endswith(('.pyc','.pyo')) for x in seen): raise RuntimeError('cache artifact admitted to snapshot')
fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
try: os.write(fd,raw);os.fsync(fd)
finally: os.close(fd)
print(json.dumps({'status':'STAGED','files':inv['file_count'],'directories':inv['directory_count'],'bytes':inv['total_bytes'],'inventory_sha256':hashlib.sha256(raw).hexdigest(),'runtime_files':len(records)},sort_keys=True,separators=(',',':')))
'@

$inventorySource = @'
import hashlib,json,os,stat,sys
c=json.loads(__import__('base64').b64decode(sys.argv[1]));root=c['root'];out=c['out']
dirs=[];files=[];total=0
for current,names,leaves in os.walk(root,topdown=True,followlinks=False):
 rel=os.path.relpath(current,root).replace(os.sep,'/');s=os.lstat(current);mode=stat.S_IMODE(s.st_mode)
 if not stat.S_ISDIR(s.st_mode) or stat.S_ISLNK(s.st_mode) or mode!=(0o700 if rel=='.' else 0o500): raise RuntimeError('inventory directory rejected: '+rel)
 dirs.append({'path':rel,'mode':format(mode,'04o'),'device':s.st_dev,'inode':s.st_ino,'nlink':s.st_nlink})
 for name in names:
  child=os.lstat(current+'/'+name)
  if not stat.S_ISDIR(child.st_mode) or stat.S_ISLNK(child.st_mode): raise RuntimeError('inventory child directory rejected: '+name)
 for name in sorted(leaves):
  path=current+'/'+name;r=(name if rel=='.' else rel+'/'+name);s=os.lstat(path)
  if not stat.S_ISREG(s.st_mode) or stat.S_ISLNK(s.st_mode) or stat.S_IMODE(s.st_mode)!=0o400 or s.st_nlink!=1: raise RuntimeError('inventory file nlink/type/mode rejected: '+r)
  h=hashlib.sha256()
  with open(path,'rb',buffering=0) as f:
   while True:
    b=f.read(1<<20)
    if not b: break
    h.update(b)
  files.append({'path':r,'type':'regular file','mode':'0400','device':s.st_dev,'inode':s.st_ino,'nlink':1,'size':s.st_size,'sha256':h.hexdigest()});total+=s.st_size
inv={'schema':'planora.muni-v30.snapshot-inventory.v1','root':root,'directory_count':len(dirs),'file_count':len(files),'total_bytes':total,'directories':sorted(dirs,key=lambda x:x['path']),'files':sorted(files,key=lambda x:x['path'])}
raw=json.dumps(inv,sort_keys=True,separators=(',',':')).encode();fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
try: os.write(fd,raw);os.fsync(fd)
finally: os.close(fd)
print(json.dumps({'status':'INVENTORIED','files':len(files),'directories':len(dirs),'bytes':total,'all_nlink_one':all(x['nlink']==1 for x in files),'sha256':hashlib.sha256(raw).hexdigest()},sort_keys=True,separators=(',',':')))
'@

$watcherSource = @'
import ctypes,errno,hashlib,json,os,select,stat,struct,sys,time,traceback
c=json.loads(__import__('base64').b64decode(sys.argv[1]));root=c['root'];stop=c['stop'];cleanup_path=c['cleanup'];log_path=c['log'];error_path=c['error'];expected_path=c['expected'];run_id=c['run_id'];target=os.path.basename(root)
def reserve(path):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
 try: os.fsync(fd);s=os.fstat(fd)
 finally: os.close(fd)
 if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1: raise RuntimeError('reserved log identity rejected')
 return (s.st_dev,s.st_ino)
def append_bytes(path,identity,payload):
 deadline=time.monotonic()+2.0
 while True:
  try: fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CLOEXEC|os.O_NOFOLLOW)
  except OSError as exc:
   if exc.errno in (errno.EACCES,errno.EBUSY,errno.ETXTBSY,errno.EPERM) and time.monotonic()<deadline: time.sleep(0.01);continue
   raise
  try:
   before=os.fstat(fd);linked=os.lstat(path)
   if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or (before.st_dev,before.st_ino)!=identity or (linked.st_dev,linked.st_ino)!=identity: raise RuntimeError('append log identity rejected')
   offset=0
   while offset<len(payload):
    written=os.write(fd,payload[offset:])
    if written<=0: raise RuntimeError('append log short write')
    offset+=written
   os.fsync(fd);after=os.fstat(fd);linked_after=os.lstat(path)
   if not stat.S_ISREG(after.st_mode) or after.st_nlink!=1 or (after.st_dev,after.st_ino)!=identity or (linked_after.st_dev,linked_after.st_ino)!=identity: raise RuntimeError('append log identity drift')
   return
  finally: os.close(fd)
def publish_error(payload): append_bytes(error_path,error_identity,payload.encode())
log_identity=reserve(log_path);error_identity=reserve(error_path)
def encode(row): return (json.dumps(row,sort_keys=True,separators=(',',':'))+'\n').encode()
def emit(row): append_bytes(log_path,log_identity,encode(row))
def stable_json(path):
 fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0));before=os.fstat(fd)
 try:
  raw=b''
  while len(raw)<before.st_size:
   b=os.pread(fd,min(1<<20,before.st_size-len(raw)),len(raw))
   if not b: raise RuntimeError('control short read')
   raw+=b
  after=os.fstat(fd)
  if (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns) or not stat.S_ISREG(before.st_mode) or before.st_nlink!=1: raise RuntimeError('control identity rejected')
 finally: os.close(fd)
 return json.loads(raw),hashlib.sha256(raw).hexdigest()
def inventory():
 dirs=[];files=[];total=0
 for current,names,leaves in os.walk(root,topdown=True,followlinks=False):
  rel=os.path.relpath(current,root).replace(os.sep,'/');s=os.lstat(current);mode=stat.S_IMODE(s.st_mode)
  if not stat.S_ISDIR(s.st_mode) or stat.S_ISLNK(s.st_mode) or mode!=(0o700 if rel=='.' else 0o500): raise RuntimeError('watch inventory directory rejected: '+rel)
  dirs.append({'path':rel,'mode':format(mode,'04o'),'device':s.st_dev,'inode':s.st_ino,'nlink':s.st_nlink})
  for name in names:
   child=os.lstat(current+'/'+name)
   if not stat.S_ISDIR(child.st_mode) or stat.S_ISLNK(child.st_mode): raise RuntimeError('watch inventory child directory rejected: '+name)
  for name in sorted(leaves):
   path=current+'/'+name;r=(name if rel=='.' else rel+'/'+name);s=os.lstat(path)
   if not stat.S_ISREG(s.st_mode) or stat.S_ISLNK(s.st_mode) or stat.S_IMODE(s.st_mode)!=0o400 or s.st_nlink!=1: raise RuntimeError('watch inventory nlink/type/mode rejected: '+r)
   h=hashlib.sha256()
   with open(path,'rb',buffering=0) as f:
    while True:
     b=f.read(1<<20)
     if not b: break
     h.update(b)
   files.append({'path':r,'type':'regular file','mode':'0400','device':s.st_dev,'inode':s.st_ino,'nlink':1,'size':s.st_size,'sha256':h.hexdigest()});total+=s.st_size
 return {'schema':'planora.muni-v30.snapshot-inventory.v1','root':root,'directory_count':len(dirs),'file_count':len(files),'total_bytes':total,'directories':sorted(dirs,key=lambda x:x['path']),'files':sorted(files,key=lambda x:x['path'])}
try:
 MASK=0x00000002|0x00000004|0x00000008|0x00000040|0x00000080|0x00000100|0x00000200|0x00000400|0x00000800|0x00002000|0x00004000|0x00008000
 CREATE=0x00000100;UNMOUNT=0x00002000;Q_OVERFLOW=0x00004000;IGNORED=0x00008000;ISDIR=0x40000000;PARENT_LOSS=UNMOUNT|IGNORED;STAGING_FORBIDDEN=0x00000040|0x00000080|0x00000200|0x00000400|0x00000800|UNMOUNT|Q_OVERFLOW|IGNORED;CLEANUP_FORBIDDEN=0x00000002|0x00000004|0x00000008|0x00000040|0x00000080|0x00000100
 libc=ctypes.CDLL(None,use_errno=True);watch=int(libc.inotify_init1(os.O_NONBLOCK|os.O_CLOEXEC))
 if watch<0: raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))
 parent=os.path.dirname(root);parent_wd=int(libc.inotify_add_watch(watch,ctypes.c_char_p(os.fsencode(parent)),ctypes.c_uint32(MASK)))
 if parent_wd<0: raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()),parent)
 emit({'kind':'ARMED','pid':os.getpid(),'parent':parent,'parent_watch_descriptor':parent_wd,'root':root,'parent_watch_active':True,'root_absent':not os.path.lexists(root),'event_preservation':'lossless_from_armed'})
 if os.path.lexists(root): raise RuntimeError('staging root existed before watcher arm')
 wd_paths={parent_wd:None};path_wds={};staging_events=[];cleanup_events=[];event_sequence=0;parent_watch_checks=0
 def assert_parent_watch():
  global parent_watch_checks
  current=int(libc.inotify_add_watch(watch,ctypes.c_char_p(os.fsencode(parent)),ctypes.c_uint32(MASK)))
  if current!=parent_wd: raise RuntimeError('parent watch descriptor continuity rejected')
  parent_watch_checks+=1
 def add_watch(path,rel):
  if rel in path_wds:return
  wd=int(libc.inotify_add_watch(watch,ctypes.c_char_p(os.fsencode(path)),ctypes.c_uint32(MASK)))
  if wd<0: raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()),path)
  wd_paths[wd]=rel;path_wds[rel]=wd
 def drain(phase):
  nonlocal_event_count=0
  global event_sequence
  while True:
   try:data=os.read(watch,1<<20)
   except BlockingIOError:return nonlocal_event_count
   off=0
   while off<len(data):
    wd,mask,cookie,length=struct.unpack_from('iIII',data,off);off+=16;name=data[off:off+length].split(b'\0',1)[0].decode('utf-8','backslashreplace');off+=length
    base=wd_paths.get(wd,'UNKNOWN');scope='parent_watch_loss' if wd==parent_wd and mask&PARENT_LOSS else ('ambient_parent' if base is None and name!=target else 'snapshot');rel=(name if base in (None,'.') else base+'/'+name) if name else ('.' if base is None else base)
    event_sequence+=1;row={'kind':phase+'_EVENT','sequence':event_sequence,'phase':phase,'scope':scope,'wd':wd,'mask':mask,'cookie':cookie,'name':name,'path':rel};emit(row);nonlocal_event_count+=1
    if mask&Q_OVERFLOW: raise RuntimeError('inotify queue overflow rejected: '+json.dumps(row,sort_keys=True,separators=(',',':')))
    if wd==parent_wd and mask&PARENT_LOSS: raise RuntimeError('parent watch loss rejected: '+json.dumps(row,sort_keys=True,separators=(',',':')))
    if phase=='STAGING':
     staging_events.append(row)
     if scope=='snapshot' and mask&STAGING_FORBIDDEN: raise RuntimeError('forbidden staging mutation event: '+json.dumps(row,sort_keys=True,separators=(',',':')))
     if base is None and name==target and mask&CREATE and mask&ISDIR: add_watch(root,'.')
     elif scope=='snapshot' and base not in (None,'UNKNOWN') and name and mask&CREATE and mask&ISDIR: add_watch(root+'/'+rel,rel)
    elif phase in ('PROTECTED','CLEANED'):
     if scope=='snapshot': raise RuntimeError('postflight protected mutation event: '+json.dumps(row,sort_keys=True,separators=(',',':')))
    elif phase=='CLEANUP':
     cleanup_events.append(row)
     if scope=='snapshot' and mask&CLEANUP_FORBIDDEN: raise RuntimeError('forbidden cleanup mutation event: '+json.dumps(row,sort_keys=True,separators=(',',':')))
 deadline=time.monotonic()+120.0
 while not (os.path.exists(expected_path) and os.path.lexists(root)):
  assert_parent_watch()
  if os.path.exists(stop): raise RuntimeError('watcher stopped before staging completed')
  if time.monotonic()>=deadline: raise RuntimeError('watcher staging readiness deadline exceeded')
  if select.select([watch],[],[],0.1)[0]:drain('STAGING')
 assert_parent_watch();drain('STAGING');expected,expected_sha=stable_json(expected_path)
 for row in expected['directories']:
  path=root if row['path']=='.' else root+'/'+row['path'];add_watch(path,row['path'])
 assert_parent_watch();drain('STAGING');current=inventory();current_raw=json.dumps(current,sort_keys=True,separators=(',',':')).encode();drain('STAGING');assert_parent_watch()
 target_creates=sum(1 for x in staging_events if x['scope']=='snapshot' and x['wd']==parent_wd and x['name']==target and x['mask']&CREATE and x['mask']&ISDIR)
 if current!=expected or hashlib.sha256(current_raw).hexdigest()!=expected_sha or target_creates!=1: raise RuntimeError('pre-ready identity inventory or staging event history rejected')
 staging_digest=hashlib.sha256(b''.join(encode(x) for x in staging_events)).hexdigest()
 emit({'kind':'READY','pid':os.getpid(),'root':root,'inventory_sha256':expected_sha,'file_count':current['file_count'],'all_nlink_one':all(x['nlink']==1 for x in current['files']),'device_inode_frozen':True,'watch_started_before_staging':True,'parent_watch_descriptor':parent_wd,'parent_watch_active':True,'parent_watch_loss_events':0,'parent_watch_checks':parent_watch_checks,'staging_event_count':len(staging_events),'staging_events_sha256':staging_digest,'target_create_events':target_creates,'staging_events_preserved':True})
 def await_control(path,phase,deadline):
  while time.monotonic()<deadline:
   assert_parent_watch()
   if phase!='CLEANED' and os.path.exists(stop): raise RuntimeError('watcher stopped before cleanup authorization')
   if select.select([watch],[],[],0.05)[0]:drain(phase)
   if os.path.exists(path):
    try:
     first,first_sha=stable_json(path);time.sleep(0.05);drain(phase);second,second_sha=stable_json(path)
     if first_sha==second_sha and first==second:return second,second_sha
    except (OSError,ValueError,UnicodeError):pass
  raise RuntimeError('stable create-only control deadline exceeded: '+path)
 control,control_sha=await_control(cleanup_path,'PROTECTED',time.monotonic()+120.0)
 if os.path.exists(stop): raise RuntimeError('watcher stopped before cleanup authorization')
 if control.get('schema')!='planora.muni-v30.watcher-cleanup-authorization.v1' or control.get('run_id')!=run_id or control.get('inventory_sha256')!=expected_sha or not isinstance(control.get('acceptance_commitment_sha256'),str) or len(control['acceptance_commitment_sha256'])!=64: raise RuntimeError('watcher cleanup authorization rejected')
 emit({'kind':'CLEANUP_AUTHORIZED','control_sha256':control_sha,'inventory_sha256':expected_sha,'acceptance_commitment_sha256':control['acceptance_commitment_sha256'],'parent_watch_descriptor':parent_wd,'parent_watch_active':True,'parent_watch_loss_events':0,'parent_watch_checks':parent_watch_checks})
 cleanup_deadline=time.monotonic()+60.0
 while os.path.lexists(root):
  assert_parent_watch()
  if os.path.exists(stop): raise RuntimeError('watcher stopped during cleanup')
  if time.monotonic()>=cleanup_deadline: raise RuntimeError('watcher cleanup observation deadline exceeded')
  if select.select([watch],[],[],0.1)[0]:drain('CLEANUP')
 drain('CLEANUP');cleanup_digest=hashlib.sha256(b''.join(encode(x) for x in cleanup_events)).hexdigest()
 assert_parent_watch();emit({'kind':'CLEANED','root_absent':not os.path.lexists(root),'cleanup_event_count':len(cleanup_events),'cleanup_events_sha256':cleanup_digest,'control_sha256':control_sha,'acceptance_commitment_sha256':control['acceptance_commitment_sha256'],'parent_watch_descriptor':parent_wd,'parent_watch_active':True,'parent_watch_loss_events':0,'parent_watch_checks':parent_watch_checks})
 shutdown,shutdown_sha=await_control(stop,'CLEANED',time.monotonic()+120.0);drain('CLEANED')
 if shutdown.get('schema')!='planora.muni-v30.watcher-shutdown-control.v2' or shutdown.get('run_id')!=run_id or shutdown.get('inventory_sha256')!=expected_sha or shutdown.get('acceptance_commitment_sha256')!=control['acceptance_commitment_sha256'] or not isinstance(shutdown.get('cleanup_evidence_sha256'),str) or len(shutdown['cleanup_evidence_sha256'])!=64 or not isinstance(shutdown.get('protected_replay_sha256'),str) or len(shutdown['protected_replay_sha256'])!=64 or not isinstance(shutdown.get('pass_receipt_sha256'),str) or len(shutdown['pass_receipt_sha256'])!=64: raise RuntimeError('watcher shutdown control rejected')
 assert_parent_watch();emit({'kind':'DONE','root_absent':not os.path.lexists(root),'staging_event_count':len(staging_events),'staging_events_sha256':staging_digest,'cleanup_event_count':len(cleanup_events),'cleanup_events_sha256':cleanup_digest,'control_sha256':control_sha,'acceptance_commitment_sha256':control['acceptance_commitment_sha256'],'shutdown_control_sha256':shutdown_sha,'cleanup_evidence_sha256':shutdown['cleanup_evidence_sha256'],'protected_replay_sha256':shutdown['protected_replay_sha256'],'pass_receipt_sha256':shutdown['pass_receipt_sha256'],'parent_watch_descriptor':parent_wd,'parent_watch_active':True,'parent_watch_loss_events':0,'parent_watch_checks':parent_watch_checks,'protected_through_pass_publication':True})
except BaseException:
 publish_error(traceback.format_exc());raise
'@

$resourceMonitorSource = @'
import errno,hashlib,json,os,stat,sys,time,traceback
c=json.loads(__import__('base64').b64decode(sys.argv[1]));stop=c['stop'];log_path=c['log'];error_path=c['error'];watcher_pid=int(c['watcher_pid']);timeout_argv=c['timeout_argv'];bwrap_argv=c['bwrap_argv'];test_argv=c['test_argv'];minimum=int(c['minimum_kib']);target_ns=int(c['target_interval_ms'])*1000000;max_gap_ns=int(c['maximum_gap_ms'])*1000000;subprocess_sites=int(c['subprocess_sites'])
def reserve(path):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
 try: os.fsync(fd);s=os.fstat(fd)
 finally: os.close(fd)
 if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1: raise RuntimeError('reserved log identity rejected')
 return (s.st_dev,s.st_ino)
def append_bytes(path,identity,payload):
 deadline=time.monotonic()+2.0
 while True:
  try: fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CLOEXEC|os.O_NOFOLLOW)
  except OSError as exc:
   if exc.errno in (errno.EACCES,errno.EBUSY,errno.ETXTBSY,errno.EPERM) and time.monotonic()<deadline: time.sleep(0.01);continue
   raise
  try:
   before=os.fstat(fd);linked=os.lstat(path)
   if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or (before.st_dev,before.st_ino)!=identity or (linked.st_dev,linked.st_ino)!=identity: raise RuntimeError('append log identity rejected')
   offset=0
   while offset<len(payload):
    written=os.write(fd,payload[offset:])
    if written<=0: raise RuntimeError('append log short write')
    offset+=written
   os.fsync(fd);after=os.fstat(fd);linked_after=os.lstat(path)
   if not stat.S_ISREG(after.st_mode) or after.st_nlink!=1 or (after.st_dev,after.st_ino)!=identity or (linked_after.st_dev,linked_after.st_ino)!=identity: raise RuntimeError('append log identity drift')
   return
  finally: os.close(fd)
def publish_error(payload): append_bytes(error_path,error_identity,payload.encode())
log_identity=reserve(log_path);error_identity=reserve(error_path)
def emit(row): append_bytes(log_path,log_identity,(json.dumps(row,sort_keys=True,separators=(',',':'))+'\n').encode())
def nsid(path):
 s=os.stat(path);return [s.st_dev,s.st_ino]
def rows():
 out={}
 for name in os.listdir('/proc'):
  if not name.isdigit(): continue
  pid=int(name);base='/proc/'+name
  try:
   raw=open(base+'/stat','rb').read();right=raw.rfind(b')');left=raw.find(b'(')
   if left<0 or right<=left: raise RuntimeError('proc stat shape rejected')
   rest=raw[right+2:].split();ppid=int(rest[1]);pgrp=int(rest[2]);session=int(rest[3]);starttime=int(rest[19]);comm=raw[left+1:right].decode('utf-8','backslashreplace')
   status=open(base+'/status','rt',encoding='utf-8').read().splitlines();uid_rows=[x for x in status if x.startswith('Uid:')]
   if len(uid_rows)!=1: raise RuntimeError('proc uid shape rejected')
   uid=int(uid_rows[0].split()[1]);cmd=open(base+'/cmdline','rb').read().split(b'\0');argv=[x.decode('utf-8','surrogateescape') for x in cmd if x]
   try:exe=nsid(base+'/exe')
   except (FileNotFoundError,PermissionError):exe=None
   out[pid]={'pid':pid,'ppid':ppid,'pgrp':pgrp,'session':session,'starttime':starttime,'uid':uid,'comm':comm,'argv':argv,'mnt_ns':nsid(base+'/ns/mnt'),'pid_ns':nsid(base+'/ns/pid'),'exe':exe}
  except FileNotFoundError: continue
  except ProcessLookupError: continue
 return out
infra={'init','systemd','systemd-journal','systemd-udevd','systemd-network','systemd-resolve','systemd-timesyn','systemd-logind','dbus-daemon','cron','rsyslogd','wsl-pro-service'}
seen=False;sequence=0;anchor_ns=None;anchor_start=None;anchor_uid=None;admitted={};last_monotonic_ns=None;maximum_observed_gap_ns=0;max_canonical_processes=0
def ident(row):return [row['pid'],row['starttime'],row['mnt_ns'],row['pid_ns'],row['exe']]
def descends(pid,anchor,table):
 visited=set()
 while pid and pid not in visited:
  if pid==anchor:return True
  visited.add(pid);row=table.get(pid)
  if row is None:return False
  pid=row['ppid']
 return False
def sample():
 global seen,sequence,anchor_ns,anchor_start,anchor_uid,last_monotonic_ns,maximum_observed_gap_ns,max_canonical_processes
 now=time.monotonic_ns();gap=0 if last_monotonic_ns is None else now-last_monotonic_ns
 if last_monotonic_ns is not None and (gap<=0 or gap>max_gap_ns): raise RuntimeError('resource monitor cadence gap rejected: '+str(gap))
 last_monotonic_ns=now;maximum_observed_gap_ns=max(maximum_observed_gap_ns,gap)
 table=rows();mine=os.getpid()
 if mine not in table or watcher_pid not in table: raise RuntimeError('monitor or watcher process identity disappeared')
 allowed=set();cursor=mine
 while cursor:
  if cursor in allowed: raise RuntimeError('monitor ancestry cycle')
  allowed.add(cursor);row=table.get(cursor)
  if row is None: raise RuntimeError('monitor ancestry incomplete')
  cursor=row['ppid']
 allowed.add(watcher_pid)
 timeout_rows=[r for r in table.values() if r['argv']==timeout_argv];bwrap_rows=[r for r in table.values() if r['argv']==bwrap_argv];test_rows=[r for r in table.values() if r['argv']==test_argv]
 if len(timeout_rows)>1 or len(bwrap_rows)>1 or len(test_rows)>1: raise RuntimeError('duplicate canonical process chain rejected')
 if bwrap_rows and (not timeout_rows or bwrap_rows[0]['ppid']!=timeout_rows[0]['pid']): raise RuntimeError('canonical bwrap ancestry rejected')
 if timeout_rows: allowed.add(timeout_rows[0]['pid']);seen=True
 if test_rows:
  parents={timeout_rows[0]['pid']} if timeout_rows else set()
  if bwrap_rows: parents.add(bwrap_rows[0]['pid'])
  if not parents or test_rows[0]['ppid'] not in parents: raise RuntimeError('canonical test ancestry rejected')
  test=test_rows[0];launch_ns=[test['mnt_ns'],test['pid_ns']]
  if anchor_ns is None:anchor_ns=launch_ns;anchor_start=test['starttime'];anchor_uid=test['uid']
  elif anchor_ns!=launch_ns or anchor_start!=test['starttime'] or anchor_uid!=test['uid']:raise RuntimeError('canonical launch identity drift')
  allowed.add(test['pid']);seen=True
 if bwrap_rows:allowed.add(bwrap_rows[0]['pid']);seen=True
 scoped=[]
 if anchor_ns is not None:
  for row in table.values():
   if [row['mnt_ns'],row['pid_ns']]==anchor_ns and row['uid']==anchor_uid and row['starttime']>=anchor_start:
    identity=ident(row);prior=admitted.get(row['pid'])
    if prior is not None and prior['identity']!=identity:raise RuntimeError('canonical descendant PID identity drift')
    test_pid=test_rows[0]['pid'] if test_rows else -1
    if prior is not None:binding='previously_frozen_descendant_identity'
    elif row['pid']==test_pid:binding='exact_test'
    elif test_pid>0 and descends(row['pid'],test_pid,table):binding='live_ancestry_plus_launch_identity'
    else:continue
    if prior is None:admitted[row['pid']]={'pid':row['pid'],'identity':identity,'first_ppid':row['ppid'],'first_sequence':sequence+1,'binding':binding}
    allowed.add(row['pid']);scoped.append(row)
 max_canonical_processes=max(max_canonical_processes,len(scoped))
 unknown=[]
 for row in table.values():
  if row['pid'] in allowed: continue
  if row['uid']==0 and row['comm'] in infra: continue
  unknown.append({'pid':row['pid'],'ppid':row['ppid'],'uid':row['uid'],'comm':row['comm'],'argv':row['argv']})
 if unknown: raise RuntimeError('unknown concurrent WSL workload rejected: '+json.dumps(unknown,sort_keys=True,separators=(',',':')))
 mem_rows=[x for x in open('/proc/meminfo','rt',encoding='ascii').read().splitlines() if x.startswith('MemAvailable:')]
 if len(mem_rows)!=1: raise RuntimeError('MemAvailable shape rejected')
 parts=mem_rows[0].split();mem=int(parts[1])
 if len(parts)!=3 or parts[2]!='kB' or mem<minimum: raise RuntimeError('continuous MemAvailable floor rejected')
 sequence+=1;return {'kind':'SAMPLE','sequence':sequence,'monotonic_ns':now,'gap_ns':gap,'memavailable_kib':mem,'process_rows':len(table),'canonical_present':bool(timeout_rows or bwrap_rows or scoped),'canonical_processes':len(scoped),'admitted_descendant_identities':len(admitted),'launch_namespace_bound':anchor_ns is not None}
try:
 first=sample();emit({'kind':'READY','pid':os.getpid(),'watcher_pid':watcher_pid,'minimum_kib':minimum,'sequence':first['sequence'],'target_interval_ms':target_ns//1000000,'maximum_gap_ms':max_gap_ns//1000000,'cadence_claim':'bounded_maximum_gap_not_exact_interval','descendant_policy':'live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace','pinned_subprocess_sites':subprocess_sites});emit(first)
 next_tick=time.monotonic_ns()+target_ns
 while not os.path.exists(stop):
  delay=next_tick-time.monotonic_ns()
  if delay>0:time.sleep(delay/1000000000)
  emit(sample());next_tick+=target_ns
 final=sample();emit(final)
 if not seen: raise RuntimeError('canonical process chain was never observed')
 admitted_rows=sorted(admitted.values(),key=lambda x:(x['pid'],x['identity'][1]));admitted_raw=json.dumps(admitted_rows,sort_keys=True,separators=(',',':')).encode()
 emit({'kind':'DONE','samples':sequence,'canonical_seen':seen,'minimum_kib':minimum,'target_interval_ms':target_ns//1000000,'maximum_gap_ms':max_gap_ns//1000000,'maximum_observed_gap_ns':maximum_observed_gap_ns,'admitted_descendant_identities':len(admitted),'admitted_identity_rows':admitted_rows,'admitted_identities_sha256':hashlib.sha256(admitted_raw).hexdigest(),'max_canonical_processes':max_canonical_processes,'launch_namespace_bound':anchor_ns is not None,'pinned_subprocess_sites':subprocess_sites})
except BaseException:
 publish_error(traceback.format_exc());raise
'@


$legacyLogBridgeSource = @'
import json,os,sys,time
c=json.loads(__import__('base64').b64decode(sys.argv[1]));log=open(c['log'],'x',encoding='utf-8',buffering=1);log.write('{"kind":"LEGACY_OPEN"}\n');log.flush();os.fsync(log.fileno());fd=os.open(c['ready'],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
try:
 while not os.path.exists(c['stop']): time.sleep(0.01)
finally: log.close()
'@
$fixedLogBridgeSource = @'
import errno,hashlib,json,os,stat,sys,time
c=json.loads(__import__('base64').b64decode(sys.argv[1]));path=c['log']
def reserve(path):
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC,0o600)
 try: os.fsync(fd);s=os.fstat(fd)
 finally: os.close(fd)
 if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1: raise RuntimeError('reserve rejected')
 return (s.st_dev,s.st_ino)
identity=reserve(path);encoded=[]
def emit(row):
 payload=(json.dumps(row,sort_keys=True,separators=(',',':'))+'\n').encode();deadline=time.monotonic()+2
 while True:
  try: fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_CLOEXEC|os.O_NOFOLLOW)
  except OSError as exc:
   if exc.errno in (errno.EACCES,errno.EBUSY,errno.ETXTBSY,errno.EPERM) and time.monotonic()<deadline: time.sleep(.005);continue
   raise
  try:
   before=os.fstat(fd);linked=os.lstat(path)
   if (before.st_dev,before.st_ino)!=identity or (linked.st_dev,linked.st_ino)!=identity or before.st_nlink!=1: raise RuntimeError('identity rejected')
   offset=0
   while offset<len(payload):
    count=os.write(fd,payload[offset:]);offset+=count
   os.fsync(fd);after=os.fstat(fd)
   if (after.st_dev,after.st_ino)!=identity or after.st_nlink!=1: raise RuntimeError('identity drift')
  finally: os.close(fd)
  encoded.append(payload);return
emit({'kind':'READY','rows':12})
for sequence in range(1,13): emit({'kind':'SAMPLE','sequence':sequence,'payload':'bridge'});time.sleep(.4)
emit({'kind':'DONE','prior_sha256':hashlib.sha256(b''.join(encoded)).hexdigest(),'samples':12})
'@
$cleanupSource = @'
import hashlib,json,os,stat,sys
c=json.loads(__import__('base64').b64decode(sys.argv[1]));root=c['root'];expected_path=c['expected'];prefix='/tmp/planora-muni-v30-canonical-tests-'
if not root.startswith(prefix) or len(root)!=len(prefix)+32 or '/' in root[len(prefix):]: raise RuntimeError('cleanup target rejected')
raw=open(expected_path,'rb').read()
if hashlib.sha256(raw).hexdigest()!=c['expected_sha256']: raise RuntimeError('cleanup inventory hash rejected')
expected=json.loads(raw)
def digest(path):
 h=hashlib.sha256()
 with open(path,'rb',buffering=0) as f:
  while True:
   b=f.read(1<<20)
   if not b: break
   h.update(b)
 return h.hexdigest()
actual=[];actual_dirs=[]
for current,names,leaves in os.walk(root,topdown=True,followlinks=False):
 rel=os.path.relpath(current,root).replace(os.sep,'/');s=os.lstat(current);mode=stat.S_IMODE(s.st_mode)
 if not stat.S_ISDIR(s.st_mode) or stat.S_ISLNK(s.st_mode) or mode!=(0o700 if rel=='.' else 0o500): raise RuntimeError('cleanup directory rejected')
 actual_dirs.append({'path':rel,'mode':format(mode,'04o'),'device':s.st_dev,'inode':s.st_ino,'nlink':s.st_nlink})
 for name in names:
  child=os.lstat(current+'/'+name)
  if not stat.S_ISDIR(child.st_mode) or stat.S_ISLNK(child.st_mode): raise RuntimeError('cleanup child directory rejected')
 for name in sorted(leaves):
  path=current+'/'+name;r=name if rel=='.' else rel+'/'+name;s=os.lstat(path)
  if not stat.S_ISREG(s.st_mode) or stat.S_ISLNK(s.st_mode) or stat.S_IMODE(s.st_mode)!=0o400 or s.st_nlink!=1: raise RuntimeError('cleanup file metadata rejected: '+r)
  actual.append({'path':r,'type':'regular file','mode':'0400','device':s.st_dev,'inode':s.st_ino,'nlink':1,'size':s.st_size,'sha256':digest(path)})
actual=sorted(actual,key=lambda x:x['path'])
actual_dirs=sorted(actual_dirs,key=lambda x:x['path'])
if actual!=expected['files'] or actual_dirs!=expected['directories']: raise RuntimeError('cleanup exact identity inventory rejected')
for row in reversed(expected['files']):
 path=root+'/'+row['path'];s=os.lstat(path)
 if not stat.S_ISREG(s.st_mode) or stat.S_ISLNK(s.st_mode) or s.st_dev!=row['device'] or s.st_ino!=row['inode'] or s.st_nlink!=1 or stat.S_IMODE(s.st_mode)!=0o400 or s.st_size!=row['size'] or digest(path)!=row['sha256']: raise RuntimeError('cleanup replay rejected: '+row['path'])
 os.unlink(path)
for row in sorted((x for x in expected['directories'] if x['path']!='.'),key=lambda x:(x['path'].count('/'),x['path']),reverse=True): os.rmdir(root+'/'+row['path'])
os.rmdir(root)
if os.path.lexists(root): raise RuntimeError('cleanup root remains')
print(json.dumps({'status':'CLEANUP_PASS','deleted_files':len(expected['files']),'deleted_directories':len(expected['directories']),'root_absent':True},sort_keys=True,separators=(',',':')))
'@

function Get-PythonStdinTokens([string]$ConfigEncoded){return @('-d','Ubuntu','--exec','/usr/bin/python3.12','-I','-S','-B','-c',"exec(compile(open(0,'rb').read(),'<stdin>','exec'))",$ConfigEncoded)}
function Convert-ConfigToBase64([object]$Config){$raw=$Config|ConvertTo-Json -Depth 20 -Compress;return [Convert]::ToBase64String($utf8.GetBytes($raw))}
function Invoke-Inventory([string]$OutputPath,[string]$OutputWsl){$cfg=Convert-ConfigToBase64 ([ordered]@{root=$root;out=$OutputWsl});$result=Invoke-SafeStdinProcess $wsl (Get-PythonStdinTokens $cfg) $inventorySource 'snapshot inventory';$lines=@($result.stdout.Trim()-split"`r?`n"|Where-Object{$_});if($lines.Count-ne1){throw 'Inventory summary ambiguous'};return($lines[0]|ConvertFrom-Json)}

function Stop-Watcher([object]$Watcher,[string]$ExpectedInventoryHash='',[string]$ExpectedAcceptanceHash='',[string]$ExpectedCleanupHash='',[string]$ExpectedProtectedReplayHash='',[string]$ExpectedPassReceiptHash=''){
    if($null-eq$Watcher){return}
    if(-not(Test-Path -LiteralPath $watchStopFile)){
        if($ExpectedInventoryHash-and$ExpectedAcceptanceHash-and$ExpectedCleanupHash-and$ExpectedProtectedReplayHash-and$ExpectedPassReceiptHash){$shutdown=[ordered]@{schema='planora.muni-v30.watcher-shutdown-control.v2';run_id=$runId;inventory_sha256=$ExpectedInventoryHash;acceptance_commitment_sha256=$ExpectedAcceptanceHash;cleanup_evidence_sha256=$ExpectedCleanupHash;protected_replay_sha256=$ExpectedProtectedReplayHash;pass_receipt_sha256=$ExpectedPassReceiptHash;created_at_utc=[DateTime]::UtcNow.ToString('o')}}else{$shutdown=[ordered]@{schema='planora.muni-v30.watcher-abort-control.v1';run_id=$runId;created_at_utc=[DateTime]::UtcNow.ToString('o')}}
        Write-NewUtf8 $watchStopFile ($shutdown|ConvertTo-Json -Depth 6 -Compress)
    }
    if(-not$Watcher.Process.WaitForExit(10000)){try{$Watcher.Process.Kill()}catch{};throw 'Watcher stop timeout'}
    if(-not$Watcher.OutTask.Wait(10000)-or-not$Watcher.ErrTask.Wait(10000)){try{$Watcher.Process.Kill()}catch{};throw 'Watcher stream drain timeout'}
    $out=$Watcher.OutTask.GetAwaiter().GetResult();$err=$Watcher.ErrTask.GetAwaiter().GetResult();$code=$Watcher.Process.ExitCode;$Watcher.Process.Dispose()
    if(-not(Test-Path -LiteralPath $watchWrapperOutFile)){Write-NewUtf8 $watchWrapperOutFile $out};if(-not(Test-Path -LiteralPath $watchWrapperErrFile)){Write-NewUtf8 $watchWrapperErrFile $err}
    if($code-ne0-or$out.Length-ne0-or$err.Length-ne0){throw "Watcher wrapper rejected: exit=$code"}
}

function Get-Utf8StringSha256([string]$Value){$sha=[Security.Cryptography.SHA256]::Create();try{return([BitConverter]::ToString($sha.ComputeHash($utf8.GetBytes($Value)))-replace'-','').ToLowerInvariant()}finally{$sha.Dispose()}}
if(-not('PlanoraV30NativeFileIdentity'-as[type])){
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
[StructLayout(LayoutKind.Sequential)]
public struct PlanoraV30FileInformation {
 public uint FileAttributes;
 public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
 public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
 public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
 public uint VolumeSerialNumber;
 public uint FileSizeHigh;
 public uint FileSizeLow;
 public uint NumberOfLinks;
 public uint FileIndexHigh;
 public uint FileIndexLow;
}
public static class PlanoraV30NativeFileIdentity {
 [DllImport("kernel32.dll", SetLastError=true)]
 public static extern bool GetFileInformationByHandle(SafeFileHandle handle, out PlanoraV30FileInformation information);
}
"@
}
function Get-HeldFileIdentity([IO.FileStream]$Stream,[string]$Label){
    $information=New-Object PlanoraV30FileInformation;if(-not[PlanoraV30NativeFileIdentity]::GetFileInformationByHandle($Stream.SafeFileHandle,[ref]$information)){$code=[Runtime.InteropServices.Marshal]::GetLastWin32Error();throw [IO.IOException]::new("$Label GetFileInformationByHandle failed: $code")}
    $index=([uint64]$information.FileIndexHigh*4294967296)+[uint64]$information.FileIndexLow;$size=([uint64]$information.FileSizeHigh*4294967296)+[uint64]$information.FileSizeLow
    if(($information.FileAttributes-band0x10)-ne0-or($information.FileAttributes-band0x400)-ne0-or$information.NumberOfLinks-ne1){throw [IO.InvalidDataException]::new("$Label handle type, reparse, or nlink rejected")}
    return [ordered]@{volume=[uint32]$information.VolumeSerialNumber;index=$index;size=$size;links=[uint32]$information.NumberOfLinks}
}
function Test-WriterProcessLive([object]$WriterProcess){if($null-eq$WriterProcess){return $false};try{return(-not$WriterProcess.HasExited)}catch{return $false}}
function Read-StableUtf8Log([string]$Path,[string]$Label,[object]$WriterProcess){
    $deadline=[DateTime]::UtcNow.AddSeconds(3);$strictUtf8=New-Object Text.UTF8Encoding($false,$true)
    while($true){
        $wasLive=Test-WriterProcessLive $WriterProcess
        try{
            if(-not(Test-Path -LiteralPath $Path)){if($wasLive-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};return ''}
            $share=[IO.FileShare]::ReadWrite-bor[IO.FileShare]::Delete;$stream=New-Object IO.FileStream($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,$share)
            try{$before=Get-HeldFileIdentity $stream $Label;$length=$stream.Length;if($length-ne$before.size-or$length-gt[ int ]::MaxValue){throw [IO.InvalidDataException]::new("$Label log length rejected")};$bytes=New-Object byte[] ([int]$length);$offset=0;while($offset-lt$bytes.Length){$count=$stream.Read($bytes,$offset,$bytes.Length-$offset);if($count-le0){throw [IO.IOException]::new("$Label log short read")};$offset+=$count};$after=Get-HeldFileIdentity $stream $Label;if($stream.Length-ne$length-or$after.volume-ne$before.volume-or$after.index-ne$before.index-or$after.size-ne$before.size){throw [IO.IOException]::new("$Label log identity or length drift during read")};$probe=New-Object IO.FileStream($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,$share);try{$pathIdentity=Get-HeldFileIdentity $probe ($Label+' path replay');if($pathIdentity.volume-ne$before.volume-or$pathIdentity.index-ne$before.index){throw [IO.IOException]::new("$Label log path identity drift")}}finally{$probe.Dispose()}}finally{$stream.Dispose()}
            $raw=$strictUtf8.GetString($bytes);if($raw.Length-ne0-and($raw.Contains("`r")-or-not$raw.EndsWith("`n",[StringComparison]::Ordinal))){throw [IO.InvalidDataException]::new("$Label log incomplete framing")};return $raw
        }catch [Text.DecoderFallbackException]{throw "$Label log UTF-8 rejected"}catch [IO.InvalidDataException]{if($wasLive-and[DateTime]::UtcNow-lt$deadline-and$_.Exception.Message-clike'*incomplete framing*'){Start-Sleep -Milliseconds 10;continue};throw}catch [IO.IOException]{if($wasLive-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};throw}catch [UnauthorizedAccessException]{if($wasLive-and[DateTime]::UtcNow-lt$deadline){Start-Sleep -Milliseconds 10;continue};throw}
    }
}
function Get-WatcherLogState([object]$WriterProcess=$null){
    $raw=Read-StableUtf8Log $watchLogFile 'Watcher' $WriterProcess;if($raw.Length-eq0){return [ordered]@{lines=@();rows=@()}}
    if($raw.Contains("`r")-or-not$raw.EndsWith("`n",[StringComparison]::Ordinal)){throw 'Watcher log framing rejected'}
    $lines=@($raw.Substring(0,$raw.Length-1).Split("`n"));$rows=@($lines|ForEach-Object{if($_.Length-eq0){throw 'Empty watcher log row rejected'};$_|ConvertFrom-Json});return [ordered]@{lines=$lines;rows=$rows}
}
function Get-WatcherRows([object]$WriterProcess=$null){return @((Get-WatcherLogState $WriterProcess).rows)}
function Assert-WatcherArmedBeforeStaging([object]$Watcher){
    if($null-eq$Watcher-or$Watcher.Process.HasExited-or-not(Test-Path -LiteralPath $watchErrorFile)-or(Get-Item -LiteralPath $watchErrorFile).Length-ne0){throw 'Mutation watcher unavailable before staging'};$rows=@(Get-WatcherRows $Watcher.Process)
    if($rows.Count-lt1-or$rows[0].kind-cne'ARMED'-or-not$rows[0].parent_watch_active-or$rows[0].parent_watch_descriptor-lt0-or-not$rows[0].root_absent-or$rows[0].event_preservation-cne'lossless_from_armed'){throw 'Mutation watcher ARMED state rejected'}
    for($i=1;$i-lt$rows.Count;$i++){if($rows[$i].kind-cne'STAGING_EVENT'-or$rows[$i].sequence-ne$i-or$rows[$i].scope-cne'ambient_parent'-or(($rows[$i].mask-band0x00004000)-ne0)-or($rows[$i].wd-eq$rows[0].parent_watch_descriptor-and(($rows[$i].mask-band0x0000A000)-ne0))){throw 'Pre-staging event history rejected'}};return $rows[0]
}
function Assert-WatcherHistory([object]$WriterProcess,[string]$ExpectedInventoryHash,[int]$ExpectedFiles,[ValidateSet('READY','CLEANUP_AUTHORIZED','CLEANED','DONE')][string]$ExpectedState,[string]$ExpectedAcceptanceHash='',[string]$ExpectedControlHash='',[string]$ExpectedShutdownHash='',[string]$ExpectedCleanupHash='',[string]$ExpectedProtectedReplayHash='',[string]$ExpectedPassReceiptHash=''){
    $state=Get-WatcherLogState $WriterProcess;$rows=@($state.rows);$lines=@($state.lines);if($rows.Count-lt2-or$rows[0].kind-cne'ARMED'-or-not$rows[0].parent_watch_active-or$rows[0].parent_watch_descriptor-lt0-or-not$rows[0].root_absent-or$rows[0].event_preservation-cne'lossless_from_armed'){throw 'Mutation watcher ARMED evidence rejected'};$parentWd=[int]$rows[0].parent_watch_descriptor
    $readyIndexes=@(for($i=0;$i-lt$rows.Count;$i++){if($rows[$i].kind-ceq'READY'){$i}});if($readyIndexes.Count-ne1){throw 'Mutation watcher READY cardinality rejected'};$readyIndex=$readyIndexes[0];$ready=$rows[$readyIndex]
    $stageRows=@();$stageLines=@();$expectedSequence=1;for($i=1;$i-lt$readyIndex;$i++){if($rows[$i].kind-cne'STAGING_EVENT'-or$rows[$i].sequence-ne$expectedSequence-or(($rows[$i].mask-band0x00004000)-ne0)-or($rows[$i].wd-eq$parentWd-and(($rows[$i].mask-band0x0000A000)-ne0))){throw 'Staging event preservation or parent-watch continuity grammar rejected'};$stageRows+=$rows[$i];$stageLines+=($lines[$i]+"`n");$expectedSequence++}
    $targetCreates=@($stageRows|Where-Object{$_.scope-ceq'snapshot'-and$_.path-ceq([IO.Path]::GetFileName($root))-and(($_.mask-band0x00000100)-ne0)-and(($_.mask-band0x40000000)-ne0)})
    if($targetCreates.Count-ne1-or$ready.kind-cne'READY'-or-not$ready.all_nlink_one-or-not$ready.device_inode_frozen-or-not$ready.watch_started_before_staging-or-not$ready.parent_watch_active-or$ready.parent_watch_descriptor-ne$parentWd-or$ready.parent_watch_loss_events-ne0-or$ready.parent_watch_checks-lt1-or-not$ready.staging_events_preserved-or$ready.inventory_sha256-cne$ExpectedInventoryHash-or$ready.file_count-ne$ExpectedFiles-or$ready.staging_event_count-ne$stageRows.Count-or$ready.target_create_events-ne1-or$ready.staging_events_sha256-cne(Get-Utf8StringSha256 ($stageLines-join''))){throw 'Mutation watcher READY/event-history evidence rejected'}
    $cleanupAuth=$null;$cleaned=$null;$done=$null;$cleanupRows=@();$cleanupLines=@()
    for($i=$readyIndex+1;$i-lt$rows.Count;$i++){
        $row=$rows[$i]
        if($row.kind-clike'*_EVENT'){if($row.sequence-ne$expectedSequence-or(($row.mask-band0x00004000)-ne0)-or($row.wd-eq$parentWd-and(($row.mask-band0x0000A000)-ne0))){throw 'Watcher event sequence, overflow, or parent-watch continuity rejected'};$expectedSequence++}
        switch -CaseSensitive($row.kind){
            'PROTECTED_EVENT' {if($null-ne$cleanupAuth-or$row.scope-cne'ambient_parent'){throw 'Protected snapshot mutation event detected'}}
            'CLEANUP_AUTHORIZED' {if($null-ne$cleanupAuth-or$null-ne$cleaned-or$null-ne$done){throw 'Watcher cleanup authorization order rejected'};$cleanupAuth=$row}
            'CLEANUP_EVENT' {if($null-eq$cleanupAuth-or$null-ne$cleaned-or$null-ne$done){throw 'Watcher cleanup event order rejected'};$cleanupRows+=$row;$cleanupLines+=($lines[$i]+"`n")}
            'CLEANED' {if($null-eq$cleanupAuth-or$null-ne$cleaned-or$null-ne$done){throw 'Watcher CLEANED order rejected'};$cleaned=$row}
            'CLEANED_EVENT' {if($null-eq$cleaned-or$null-ne$done-or$row.scope-cne'ambient_parent'){throw 'Postflight snapshot mutation event detected'}}
            'DONE' {if($null-eq$cleaned-or$null-ne$done-or$i-ne$rows.Count-1){throw 'Watcher DONE order rejected'};$done=$row}
            default {throw "Unexpected watcher row kind: $($row.kind)"}
        }
    }
    if($ExpectedState-ceq'READY'-and($null-ne$cleanupAuth-or$null-ne$cleaned-or$null-ne$done)){throw 'Watcher advanced past READY unexpectedly'}
    if($ExpectedState-in@('CLEANUP_AUTHORIZED','CLEANED','DONE')){if($null-eq$cleanupAuth-or$cleanupAuth.inventory_sha256-cne$ExpectedInventoryHash-or$cleanupAuth.acceptance_commitment_sha256-cne$ExpectedAcceptanceHash-or$cleanupAuth.parent_watch_descriptor-ne$parentWd-or-not$cleanupAuth.parent_watch_active-or$cleanupAuth.parent_watch_loss_events-ne0-or$cleanupAuth.parent_watch_checks-le$ready.parent_watch_checks-or($ExpectedControlHash-and$cleanupAuth.control_sha256-cne$ExpectedControlHash)){throw 'Watcher cleanup authorization binding rejected'}}
    if($ExpectedState-in@('CLEANED','DONE')){if($null-eq$cleaned-or-not$cleaned.root_absent-or$cleaned.cleanup_event_count-ne$cleanupRows.Count-or$cleaned.cleanup_events_sha256-cne(Get-Utf8StringSha256 ($cleanupLines-join''))-or$cleaned.acceptance_commitment_sha256-cne$ExpectedAcceptanceHash-or$cleaned.parent_watch_descriptor-ne$parentWd-or-not$cleaned.parent_watch_active-or$cleaned.parent_watch_loss_events-ne0-or$cleaned.parent_watch_checks-le$cleanupAuth.parent_watch_checks){throw 'Watcher CLEANED evidence rejected'}}
    if($ExpectedState-ceq'CLEANUP_AUTHORIZED'-and($null-ne$cleaned-or$null-ne$done)){throw 'Watcher advanced past CLEANUP_AUTHORIZED unexpectedly'}
    if($ExpectedState-ceq'CLEANED'-and$null-ne$done){throw 'Watcher advanced past CLEANED unexpectedly'}
    if($ExpectedState-ceq'DONE'){if($null-eq$done-or-not$done.root_absent-or-not$done.protected_through_pass_publication-or$done.parent_watch_descriptor-ne$parentWd-or-not$done.parent_watch_active-or$done.parent_watch_loss_events-ne0-or$done.parent_watch_checks-le$cleaned.parent_watch_checks-or$done.staging_events_sha256-cne$ready.staging_events_sha256-or$done.cleanup_events_sha256-cne$cleaned.cleanup_events_sha256-or$done.acceptance_commitment_sha256-cne$ExpectedAcceptanceHash-or$done.shutdown_control_sha256-cne$ExpectedShutdownHash-or$done.cleanup_evidence_sha256-cne$ExpectedCleanupHash-or$done.protected_replay_sha256-cne$ExpectedProtectedReplayHash-or$done.pass_receipt_sha256-cne$ExpectedPassReceiptHash){throw 'Watcher DONE/shutdown evidence rejected'}}
    return [ordered]@{rows=$rows;armed=$rows[0];ready=$ready;cleanup_authorized=$cleanupAuth;cleaned=$cleaned;done=$done;staging_events=$stageRows.Count;cleanup_events=$cleanupRows.Count}
}
function Assert-WatcherLiveReady([object]$Watcher,[string]$ExpectedInventoryHash,[int]$ExpectedFiles){
    if($null-eq$Watcher-or$Watcher.Process.HasExited){throw 'Mutation watcher exited before authorized stop'}
    if(Test-Path -LiteralPath $watchStopFile){throw 'Mutation watcher stop appeared before authorized stop'}
    if(-not(Test-Path -LiteralPath $watchErrorFile)){throw 'Mutation watcher error evidence path missing'};$e=Get-Item -LiteralPath $watchErrorFile;if(($e.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0-or$e.Length-ne0){throw 'Mutation watcher error evidence appeared or changed type'}
    return (Assert-WatcherHistory $Watcher.Process $ExpectedInventoryHash $ExpectedFiles 'READY').ready
}
function Assert-WatcherLiveCleanupAuthorized([object]$Watcher,[string]$ExpectedInventoryHash,[int]$ExpectedFiles,[string]$ExpectedAcceptanceHash,[string]$ExpectedControlHash){
    if($null-eq$Watcher-or$Watcher.Process.HasExited-or(Test-Path -LiteralPath $watchStopFile)-or(Get-Item -LiteralPath $watchErrorFile).Length-ne0){throw 'Mutation watcher unavailable during cleanup authorization'}
    return Assert-WatcherHistory $Watcher.Process $ExpectedInventoryHash $ExpectedFiles 'CLEANUP_AUTHORIZED' $ExpectedAcceptanceHash $ExpectedControlHash
}
function Assert-WatcherLiveCleaned([object]$Watcher,[string]$ExpectedInventoryHash,[int]$ExpectedFiles,[string]$ExpectedAcceptanceHash,[string]$ExpectedControlHash){
    if($null-eq$Watcher-or$Watcher.Process.HasExited-or(Test-Path -LiteralPath $watchStopFile)-or(Get-Item -LiteralPath $watchErrorFile).Length-ne0){throw 'Mutation watcher unavailable after cleanup'}
    return Assert-WatcherHistory $Watcher.Process $ExpectedInventoryHash $ExpectedFiles 'CLEANED' $ExpectedAcceptanceHash $ExpectedControlHash
}
function Assert-WatcherStateModel([bool]$HasExited,[bool]$StopPresent,[bool]$ErrorPresent,[string[]]$Kinds){if($HasExited-or$StopPresent-or$ErrorPresent-or$Kinds.Count-lt2-or$Kinds[0]-cne'ARMED'-or$Kinds[-1]-notin@('READY','CLEANUP_AUTHORIZED','CLEANED')){throw 'Watcher state-model rejected'};return $true}
function Assert-FinalWatcherEvidence([string]$ExpectedInventoryHash,[int]$ExpectedFiles,[string]$ExpectedAcceptanceHash,[string]$ExpectedControlHash,[string]$ExpectedShutdownHash,[string]$ExpectedCleanupHash,[string]$ExpectedProtectedReplayHash,[string]$ExpectedPassReceiptHash){
    $summary=Assert-WatcherHistory $null $ExpectedInventoryHash $ExpectedFiles 'DONE' $ExpectedAcceptanceHash $ExpectedControlHash $ExpectedShutdownHash $ExpectedCleanupHash $ExpectedProtectedReplayHash $ExpectedPassReceiptHash
    foreach($path in @($watchErrorFile,$watchWrapperOutFile,$watchWrapperErrFile)){if(-not(Test-Path -LiteralPath $path)-or(Get-Item -LiteralPath $path).Length-ne0){throw 'Mutation watcher error/output evidence is not empty'}}
    return $summary
}

function Get-ResourceMonitorRows([object]$WriterProcess=$null){
    $raw=Read-StableUtf8Log $resourceLogFile 'Resource monitor' $WriterProcess
    if($raw.Length-eq0){return @()};if($raw.Contains("`r")-or-not$raw.EndsWith("`n",[StringComparison]::Ordinal)){throw 'Resource monitor log framing rejected'}
    return @($raw.Substring(0,$raw.Length-1).Split("`n")|ForEach-Object{if($_.Length-eq0){throw 'Empty resource monitor row rejected'};$_|ConvertFrom-Json})
}
function Assert-ResourceCadenceRows([object[]]$Rows,[bool]$Final){
    if($Rows.Count-lt2-or$Rows[0].kind-cne'READY'-or$Rows[0].target_interval_ms-ne100-or$Rows[0].maximum_gap_ms-ne750-or$Rows[0].pinned_subprocess_sites-ne16-or$Rows[0].cadence_claim-cne'bounded_maximum_gap_not_exact_interval'-or$Rows[0].descendant_policy-cne'live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace'){throw 'Resource monitor cadence contract rejected'}
    $last=0L;$maximum=0L;$end=if($Final){$Rows.Count-1}else{$Rows.Count}
    for($i=1;$i-lt$end;$i++){
        $row=$Rows[$i];if($row.kind-cne'SAMPLE'-or$row.sequence-ne$i-or$row.memavailable_kib-lt1900000-or$row.monotonic_ns-le0-or$row.gap_ns-lt0-or$row.gap_ns-gt750000000){throw 'Resource monitor sample/cadence grammar rejected'}
        if($i-eq1){if($row.gap_ns-ne0){throw 'Resource monitor first gap rejected'}}else{if($row.monotonic_ns-le$last-or$row.gap_ns-ne($row.monotonic_ns-$last)){throw 'Resource monitor monotonic timestamp/gap replay rejected'}}
        $last=[long]$row.monotonic_ns;$maximum=[Math]::Max($maximum,[long]$row.gap_ns)
    }
    if($Final){
        $done=$Rows[-1];$identityRows=@($done.admitted_identity_rows)
        if($done.kind-cne'DONE'-or-not$done.canonical_seen-or-not$done.launch_namespace_bound-or$done.samples-ne($Rows.Count-2)-or$done.target_interval_ms-ne100-or$done.maximum_gap_ms-ne750-or$done.pinned_subprocess_sites-ne16-or$done.maximum_observed_gap_ns-ne$maximum-or$done.admitted_descendant_identities-lt1-or$identityRows.Count-ne$done.admitted_descendant_identities){throw 'Resource monitor final cadence/descendant evidence rejected'}
        $seenPids=@{};foreach($identityRow in $identityRows){if($identityRow.pid-lt1-or$identityRow.first_sequence-lt1-or@($identityRow.identity).Count-ne5-or$identityRow.identity[0]-ne$identityRow.pid-or$identityRow.binding-cnotin@('exact_test','live_ancestry_plus_launch_identity')-or$seenPids.ContainsKey([int]$identityRow.pid)){throw 'Resource monitor admitted identity evidence rejected'};$seenPids[[int]$identityRow.pid]=$true}
        $identityJson=ConvertTo-Json -InputObject $identityRows -Depth 10 -Compress;if((Get-Utf8StringSha256 $identityJson)-cne$done.admitted_identities_sha256){throw 'Resource monitor admitted identity digest rejected'}
    }
    return [ordered]@{samples=$end-1;last_sequence=$end-1;last_monotonic_ns=$last;maximum_observed_gap_ns=$maximum;target_interval_ms=100;maximum_gap_ms=750;cadence_claim='bounded_maximum_gap_not_exact_interval'}
}
function Assert-ResourceMonitorLive([object]$Monitor,[int]$PreviousSequence){
    if($null-eq$Monitor-or$Monitor.Process.HasExited){throw 'Resource monitor exited before authorized stop'}
    if(Test-Path -LiteralPath $resourceStopFile){throw 'Resource monitor stop appeared before authorized stop'}
    if(-not(Test-Path -LiteralPath $resourceErrorFile)){throw 'Resource monitor error evidence path missing'};$errorItem=Get-Item -LiteralPath $resourceErrorFile;if(($errorItem.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0-or$errorItem.Length-ne0){throw 'Resource monitor error evidence appeared or changed type'}
    $rows=@(Get-ResourceMonitorRows $Monitor.Process);$cadence=Assert-ResourceCadenceRows $rows $false;$last=[int]$cadence.last_sequence;if($last-le$PreviousSequence){throw 'Resource monitor sample sequence stalled'}
    if(([DateTime]::UtcNow-(Get-Item -LiteralPath $resourceLogFile).LastWriteTimeUtc).TotalSeconds-gt2){throw 'Resource monitor freshness deadline exceeded'}
    return $last
}
function Stop-ResourceMonitor([object]$Monitor){
    if($null-eq$Monitor){return $null};if(-not(Test-Path -LiteralPath $resourceStopFile)){Write-NewAscii $resourceStopFile "stop $runId`n"}
    if(-not$Monitor.Process.WaitForExit(10000)){try{$Monitor.Process.Kill()}catch{};throw 'Resource monitor stop timeout'}
    if(-not$Monitor.OutTask.Wait(10000)-or-not$Monitor.ErrTask.Wait(10000)){try{$Monitor.Process.Kill()}catch{};throw 'Resource monitor stream drain timeout'}
    $out=$Monitor.OutTask.GetAwaiter().GetResult();$err=$Monitor.ErrTask.GetAwaiter().GetResult();$code=$Monitor.Process.ExitCode;$Monitor.Process.Dispose()
    Write-NewUtf8 $resourceWrapperOutFile $out;Write-NewUtf8 $resourceWrapperErrFile $err
    if($code-ne0-or$out.Length-ne0-or$err.Length-ne0){throw "Resource monitor wrapper rejected: exit=$code"}
    $summary=Assert-FinalResourceEvidence;return $summary
}
function Assert-FinalResourceEvidence{
    $rows=@(Get-ResourceMonitorRows);if($rows.Count-lt4){throw 'Resource monitor final evidence rejected'};$cadence=Assert-ResourceCadenceRows $rows $true
    foreach($path in @($resourceErrorFile,$resourceWrapperOutFile,$resourceWrapperErrFile)){if(-not(Test-Path -LiteralPath $path)-or(Get-Item -LiteralPath $path).Length-ne0){throw 'Resource monitor output evidence is not empty'}}
    return [ordered]@{rows=$rows.Count;samples=$rows[-1].samples;canonical_seen=$rows[-1].canonical_seen;minimum_kib=$rows[-1].minimum_kib;target_interval_ms=$cadence.target_interval_ms;maximum_gap_ms=$cadence.maximum_gap_ms;maximum_observed_gap_ns=$cadence.maximum_observed_gap_ns;cadence_claim=$cadence.cadence_claim;admitted_descendant_identities=$rows[-1].admitted_descendant_identities;admitted_identities_sha256=$rows[-1].admitted_identities_sha256;max_canonical_processes=$rows[-1].max_canonical_processes;launch_namespace_bound=$rows[-1].launch_namespace_bound}
}
function Assert-ResourceStateModel([bool]$HasExited,[bool]$StopPresent,[bool]$ErrorPresent,[bool]$Fresh,[string[]]$Kinds){if($HasExited-or$StopPresent-or$ErrorPresent-or-not$Fresh-or$Kinds.Count-lt2-or$Kinds[0]-cne'READY'-or@($Kinds|Where-Object{$_-cne'SAMPLE'-and$_-cne'READY'}).Count-ne0){throw 'Resource state-model rejected'};return $true}
function Assert-CanonicalDescendantModel([object[]]$Rows,[int]$AnchorPid,[string]$LaunchNamespace){
    $allowed=@{$AnchorPid=$true};$changed=$true;while($changed){$changed=$false;foreach($row in $Rows){if(-not$allowed.ContainsKey([int]$row.pid)-and[string]$row.launch_namespace-ceq$LaunchNamespace-and[bool]$row.launch_identity_bound-and($allowed.ContainsKey([int]$row.ppid)-or[bool]$row.previously_frozen)){$allowed[[int]$row.pid]=$true;$changed=$true}}}
    $unknown=@($Rows|Where-Object{-not$allowed.ContainsKey([int]$_.pid)-and-not[bool]$_.minimal_infrastructure});if($unknown.Count){throw 'Unrelated competing workload model rejected'};return [ordered]@{allowed=@($allowed.Keys|Sort-Object);descendants=$allowed.Count-1}
}
function Assert-StagingEventModel([object[]]$Rows,[string]$Target,[int]$ParentWatchDescriptor){$sequence=1;$creates=0;foreach($row in $Rows){if($row.sequence-ne$sequence-or(($row.mask-band0x00004000)-ne0)-or($row.wd-eq$ParentWatchDescriptor-and(($row.mask-band0x0000A000)-ne0))){throw 'Staging event model sequence/parent-watch continuity rejected'};$sequence++;if($row.scope-ceq'snapshot'-and(($row.mask-band(0x40+0x80+0x200+0x400+0x800+0x2000+0x4000+0x8000))-ne0)){throw 'Staging event model destructive mutation rejected'};if($row.scope-ceq'snapshot'-and$row.path-ceq$Target-and(($row.mask-band0x100)-ne0)-and(($row.mask-band0x40000000)-ne0)){$creates++}};if($creates-ne1){throw 'Staging event model target creation rejected'};return $true}
function Assert-PostflightWatcherModel([string[]]$Kinds,[string[]]$Scopes){if($Kinds.Count-ne$Scopes.Count-or$Kinds.Count-lt1){throw 'Postflight watcher model shape rejected'};for($i=0;$i-lt$Kinds.Count;$i++){if($Kinds[$i]-cin@('PROTECTED_EVENT','CLEANED_EVENT')-and$Scopes[$i]-cne'ambient_parent'){throw 'Postflight mutation model rejected'}};if($Kinds[-1]-cne'CLEANED'){throw 'Postflight watcher model boundary rejected'};return $true}
function Assert-HostDeadlineModel([long]$ElapsedMilliseconds,[long]$LimitMilliseconds,[bool]$HasExited){if($LimitMilliseconds-lt1-or(-not$HasExited-and$ElapsedMilliseconds-ge$LimitMilliseconds)){throw 'Host canonical deadline model rejected'};return $true}
function Assert-IdentityReplayModel([object]$Before,[object]$After){foreach($name in @('device','inode','nlink','mode','size','sha256')){if([string]$Before.$name-cne[string]$After.$name){throw "Identity replay model rejected: $name"}};return $true}
function Assert-SemanticReplayModel([string]$Actual,[string]$Expected){if((ConvertTo-JsonTokenStream $Actual)-cne(ConvertTo-JsonTokenStream $Expected)){throw 'Semantic replay model rejected'};return $true}

function Get-BytesSha256([byte[]]$Bytes){
    $sha=[Security.Cryptography.SHA256]::Create();try{return([BitConverter]::ToString($sha.ComputeHash($Bytes))-replace'-','').ToLowerInvariant()}finally{$sha.Dispose()}
}
function Read-HeldStreamExact([IO.FileStream]$Stream,[int]$ExpectedLength){
    if($null-eq$Stream-or-not$Stream.CanRead-or-not$Stream.CanSeek){throw 'Held stream is not readable and seekable'}
    $original=$Stream.Position;try{[void]$Stream.Seek(0,[IO.SeekOrigin]::Begin);$bytes=New-Object byte[] $ExpectedLength;$offset=0;while($offset-lt$ExpectedLength){$count=$Stream.Read($bytes,$offset,$ExpectedLength-$offset);if($count-le0){throw 'Held stream ended before expected length'};$offset+=$count};if($Stream.ReadByte()-ne-1){throw 'Held stream exceeds expected length'};return ,$bytes}finally{[void]$Stream.Seek($original,[IO.SeekOrigin]::Begin)}
}
function Assert-HeldStreamBytes([IO.FileStream]$Stream,[byte[]]$ExpectedBytes,[string]$ExpectedHash,[string]$Context){
    [byte[]]$actual=Read-HeldStreamExact $Stream $ExpectedBytes.Length;$actualHash=Get-BytesSha256 $actual
    if($actualHash-cne$ExpectedHash-or$actual.Length-ne$ExpectedBytes.Length){throw "$Context held-byte replay rejected"}
    return $actualHash
}
function Assert-HeldLockPath([IO.FileStream]$Stream,[byte[]]$ExpectedBytes,[string]$ExpectedHash){
    $full=[IO.Path]::GetFullPath($sharedLockPath);if([IO.Path]::GetFullPath($Stream.Name)-cne$full){throw 'Held lock stream path rejected'}
    $item=Get-Item -LiteralPath $sharedLockPath;if(($item.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0-or$item.PSIsContainer-or$item.Length-ne$ExpectedBytes.Length-or$Stream.Length-ne$ExpectedBytes.Length){throw 'Held lock path identity rejected'}
    return(Assert-HeldStreamBytes $Stream $ExpectedBytes $ExpectedHash 'Shared heavy lock')
}
function Assert-OwnerPidAbsent([int]$OwnerPid,[string]$Phase){
    if($OwnerPid-le0-or$OwnerPid-eq$PID){throw "Stale owner PID safeguard rejected: $Phase"}
    $existing=$null;try{$existing=[Diagnostics.Process]::GetProcessById($OwnerPid)}catch [ArgumentException]{}
    if($null-ne$existing){try{$name=$existing.ProcessName}catch{$name='unreadable'};try{$started=$existing.StartTime.ToUniversalTime().ToString('o')}catch{$started='unreadable'};try{$existing.Dispose()}catch{};throw "Stale owner PID exists and is rejected regardless of identity: pid=$OwnerPid name=$name start=$started phase=$Phase"}
    return [ordered]@{phase=$Phase;pid=$OwnerPid;absent=$true;observed_at_utc=[DateTime]::UtcNow.ToString('o');reuse_policy='any_existing_pid_rejected_regardless_process_name_or_start_time'}
}
function New-ExpectedCombinedPredecessorEvidence{
    $contract=$predecessorContractJson|ConvertFrom-Json
    return [ordered]@{schema='planora.muni-v30.complete-v28-v29-predecessor-evidence.v1';status='EXPECTED_UNVALIDATED';contract=$contract;v28_evidence=$null;v29_evidence=$null;runtime=[ordered]@{validation_phase='not_started';validated_pins=@();pass_absence=$null;shared_lock_absent=$null}}
}
function Assert-V28V29PassEvidenceAbsent([string]$Phase){
    $result=[ordered]@{phase=$Phase;v28_receipt_absent=(-not(Test-Path -LiteralPath $v28ReceiptPath));v28_seal_absent=(-not(Test-Path -LiteralPath $v28PassSealPath));v29_receipt_absent=(-not(Test-Path -LiteralPath $v29ReceiptPath));v29_seal_absent=(-not(Test-Path -LiteralPath $v29PassSealPath));observed_at_utc=[DateTime]::UtcNow.ToString('o')}
    if(-not$result.v28_receipt_absent-or-not$result.v28_seal_absent-or-not$result.v29_receipt_absent-or-not$result.v29_seal_absent){throw "v28/v29 PASS evidence unexpectedly exists: $Phase"};return $result
}
function Assert-RetainedArchivePin([string]$Path,[object]$ExpectedPin,[byte[]]$ExpectedBytes,[string]$ExpectedHash,[string]$Phase){
    $full=[IO.Path]::GetFullPath($Path);$relative=$full.Replace($repo+'\','').Replace('\','/');if($ExpectedPin.path-cne$relative-or[long]$ExpectedPin.size-ne$ExpectedBytes.Length-or$ExpectedPin.sha256-cne$ExpectedHash){throw "Retained archive expected pin rejected: $Phase"}
    [void](Assert-LocalEvidencePin $ExpectedPin);$probe=New-Object IO.FileStream($full,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    try{if([IO.Path]::GetFullPath($probe.Name)-cne$full){throw "Retained archive stream path rejected: $Phase"};$item=Get-Item -LiteralPath $full;if(($item.Attributes-band[IO.FileAttributes]::ReparsePoint)-ne0-or$item.PSIsContainer-or$item.Length-ne$ExpectedBytes.Length-or$probe.Length-ne$ExpectedBytes.Length){throw "Retained archive path identity rejected: $Phase"};[void](Assert-HeldStreamBytes $probe $ExpectedBytes $ExpectedHash "Retained archive $Phase")}finally{$probe.Dispose()}
    [void](Assert-LocalEvidencePin $ExpectedPin);return [ordered]@{phase=$Phase;status='IDENTITY_AND_EXCLUSIVE_SAME_HANDLE_BYTES_REPLAYED';archive_pin=$ExpectedPin;observed_at_utc=[DateTime]::UtcNow.ToString('o')}
}
function Assert-FinalArchivedStaleLockIdentity([object]$ExpectedPin,[string]$Phase,[bool]$RequireSharedLockAbsent){
    $bytes=$utf8.GetBytes('{"schema":"planora.shared-heavy-wsl-lock.v1","run_id":"e7cf1df162074402994a9d0ad763c824","authorization_sha256":"1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d","runner_sha256":"fbf0a2f4449806cec331c71efc79417553f2d1cd6b060f5d481a32dbfc896d60","created_at_utc":"2026-08-28T08:38:37.2109195Z","mechanism":"FileMode.CreateNew_held_open","owner_pid":1140}')
    $result=Assert-RetainedArchivePin $staleArchivePath $ExpectedPin $bytes 'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98' $Phase
    if($RequireSharedLockAbsent-and(Test-Path -LiteralPath $sharedLockPath)){throw "Shared heavy lock unexpectedly present during archived-lock replay: $Phase"};$result['shared_lock_absence_required']=$RequireSharedLockAbsent;$result['shared_lock_absent']=(-not(Test-Path -LiteralPath $sharedLockPath));$result['predecessor_pass_absence']=Assert-V28V29PassEvidenceAbsent $Phase;return $result
}
function Open-TerminalArchivedStaleLockGuard([object]$ExpectedPin,[string]$Phase){
    $preGuardReplay=Assert-FinalArchivedStaleLockIdentity $ExpectedPin $Phase $true;$bytes=$utf8.GetBytes('{"schema":"planora.shared-heavy-wsl-lock.v1","run_id":"e7cf1df162074402994a9d0ad763c824","authorization_sha256":"1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d","runner_sha256":"fbf0a2f4449806cec331c71efc79417553f2d1cd6b060f5d481a32dbfc896d60","created_at_utc":"2026-08-28T08:38:37.2109195Z","mechanism":"FileMode.CreateNew_held_open","owner_pid":1140}');$guard=$null
    try{$guard=New-Object IO.FileStream($staleArchivePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read);if([IO.Path]::GetFullPath($guard.Name)-cne[IO.Path]::GetFullPath($staleArchivePath)){throw 'Terminal archived-lock guard path rejected'};[void](Assert-HeldStreamBytes $guard $bytes 'dcde7ccade35f6d8a3c9072bfd0ff75bade2c05d479277b42c5ffc2e7ea03b98' 'Terminal archived stale lock guard');[void](Assert-LocalEvidencePin $ExpectedPin);if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared heavy lock unexpectedly present while terminal archive guard held'};$passAbsence=Assert-V28V29PassEvidenceAbsent ($Phase+'_guard_held');$evidence=[ordered]@{schema='planora.muni-v30.terminal-archived-lock-guard.v1';phase=$Phase;status='IDENTITY_REPLAYED_AND_READ_GUARD_HELD_THROUGH_FINAL_PASS_FLUSH';archive_pin=$ExpectedPin;pre_guard_replay=$preGuardReplay;guard_access='Read';guard_share='Read_only_blocks_write_and_delete';same_handle_bytes_replayed=$true;shared_lock_absent=$true;predecessor_pass_absence=$passAbsence;acquired_at_utc=[DateTime]::UtcNow.ToString('o')};return [pscustomobject]@{Stream=$guard;Evidence=$evidence}}catch{if($null-ne$guard){$guard.Dispose()};throw}
}
function Get-ValidatedCombinedPredecessorEvidence([bool]$RequireSharedLockAbsent){
    $e=New-ExpectedCombinedPredecessorEvidence;$c=$e.contract;$pins=@()
    foreach($group in @($c.v29.sources,$c.v29.artifacts)){foreach($property in $group.PSObject.Properties){[void](Assert-LocalEvidencePin $property.Value);$pins+=,$property.Value}}
    $rejection=[IO.File]::ReadAllText($v29RejectionPath,$utf8)|ConvertFrom-Json;$claim=[IO.File]::ReadAllText((Join-Path $repo $c.v29.artifacts.claim.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$release=[IO.File]::ReadAllText((Join-Path $repo $c.v29.artifacts.heavy_lock_release.path.Replace('/','\')),$utf8)|ConvertFrom-Json;$authorization=[IO.File]::ReadAllText((Join-Path $repo $c.v29.sources.authorization.path.Replace('/','\')),$utf8)|ConvertFrom-Json
    if($claim.run_id-cne'ca79220da7db46b6996fe1f05785dde7'-or$claim.status-cne'CLAIMED_FAIL_CLOSED_UNLESS_VALID_PASS_PUBLICATION_SHUTDOWN_SEAL_EXISTS'-or-not[bool]$claim.failure_consumes_authorization){throw 'v29 claim semantics rejected'}
    if($rejection.run_id-cne'ca79220da7db46b6996fe1f05785dde7'-or$rejection.status-cne'REJECTED_AUTHORIZATION_CONSUMED'-or[bool]$rejection.pass_receipt_present-or-not[bool]$rejection.pass_shutdown_seal_absent-or$rejection.failure-cnotmatch'ReadAllText'-or$rejection.failure-cnotmatch'being used by another process'-or$rejection.failure-cnotmatch'watcher_stop=Watcher wrapper rejected'){throw 'v29 consumed failure semantics rejected'}
    if($release.run_id-cne'ca79220da7db46b6996fe1f05785dde7'-or$release.decision-cne'REJECTED'-or-not[bool]$release.same_handle_verified-or-not[bool]$release.delete_on_close-or-not[bool]$release.lock_path_absent){throw 'v29 lock release semantics rejected'}
    if($authorization.test_id-cne'ca79220da7db46b6996fe1f05785dde7'-or$authorization.candidate-cne'muni_v29'-or[bool]$authorization.automatic_retry_authorized-or$authorization.runner.sha256-cne$c.v29.sources.runner.sha256-or$authorization.successor_admission.builder.sha256-cne$c.v29.sources.builder.sha256-or$authorization.successor_admission.tests.sha256-cne$c.v29.sources.tests.sha256){throw 'v29 authorization binding rejected'}
    $watchRaw=[IO.File]::ReadAllText((Join-Path $repo $c.v29.artifacts.watch_log.path.Replace('/','\')),$utf8);$watchRows=@($watchRaw.TrimEnd("`n").Split("`n")|ForEach-Object{$_|ConvertFrom-Json});if($watchRows.Count-ne1-or$watchRows[0].kind-cne'ARMED'-or-not$watchRows[0].root_absent){throw 'v29 pre-staging watcher evidence rejected'}
    if((Get-Item -LiteralPath (Join-Path $repo $c.v29.artifacts.watch_error.path.Replace('/','\'))).Length-eq0-or(Get-Item -LiteralPath (Join-Path $repo $c.v29.artifacts.watch_wrapper_stderr.path.Replace('/','\'))).Length-eq0-or(Get-Item -LiteralPath (Join-Path $repo $c.v29.artifacts.watch_wrapper_stdout.path.Replace('/','\'))).Length-ne0){throw 'v29 watcher terminal artifact shape rejected'}
    $embedded=$rejection.predecessor_v28_evidence;$embeddedJson=$embedded|ConvertTo-Json -Depth 35 -Compress;$embeddedHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream $embeddedJson)
    if($embedded.schema-cne$c.v28.embedded_evidence_schema-or$rejection.predecessor_v28_evidence_sha256-cne$c.v28.embedded_evidence_sha256-or$embedded.status-cne'VALIDATED_AFTER_STALE_LOCK_RECONCILIATION'-or$embedded.runtime.stale_lock_reconciliation_sha256-cne$c.v28.reconciliation_sha256){throw 'v28 carried predecessor evidence rejected'}
    foreach($property in $embedded.runtime.live_file_pins.PSObject.Properties){[void](Assert-LocalEvidencePin $property.Value);$pins+=,$property.Value}
    if((ConvertTo-JsonTokenStream ($embedded.runtime.retained_lock_archive_pin|ConvertTo-Json -Depth 8 -Compress))-cne(ConvertTo-JsonTokenStream ($c.v28.archive|ConvertTo-Json -Depth 8 -Compress))){throw 'v28 carried archive identity rejected'}
    [void](Assert-FinalArchivedStaleLockIdentity $c.v28.archive 'combined_predecessor_validation' $RequireSharedLockAbsent);$pins+=,$c.v28.archive;$pass=Assert-V28V29PassEvidenceAbsent 'combined_predecessor_validation'
    if($RequireSharedLockAbsent-and(Test-Path -LiteralPath $sharedLockPath)){throw 'Shared lock present before v30 acquisition'}
    $e.status='VALIDATED_EXACT_V28_V29_PREDECESSOR_CUSTODY';$e.v28_evidence=$embedded;$e.v29_evidence=[ordered]@{run_id=$c.v29.run_id;authorization=$authorization;claim=$claim;rejection=$rejection;lock_release=$release;failure=$c.v29.failure};$e.runtime.validation_phase=$(if($RequireSharedLockAbsent){'before_v30_lock_acquisition'}else{'rejection_replay'});$e.runtime.validated_pins=$pins;$e.runtime.pass_absence=$pass;$e.runtime.shared_lock_absent=(-not(Test-Path -LiteralPath $sharedLockPath));return $e
}
function Get-CombinedPredecessorPinArray([object]$Evidence){if($null-eq$Evidence-or$Evidence.status-cne'VALIDATED_EXACT_V28_V29_PREDECESSOR_CUSTODY'){throw 'Combined predecessor evidence is not replay-ready'};return @($Evidence.runtime.validated_pins)}
function Get-NonThrowingCombinedPredecessorReplay([object]$Evidence,[object]$ArchivePin){try{$replayed=Get-ValidatedCombinedPredecessorEvidence $false;return [ordered]@{phase='rejection_publication';status='REPLAYED';evidence=$replayed;errors=@()}}catch{return [ordered]@{phase='rejection_publication';status='REPLAY_ERRORS_RECORDED';evidence=$Evidence;errors=@($_.Exception.Message)}}}
function Invoke-LockSelfReadRegressionModel{
    $oldPath=Join-Path ([IO.Path]::GetTempPath()) ("planora-v28-self-read-"+[Guid]::NewGuid().ToString('N')+'.lock');$newPath=Join-Path ([IO.Path]::GetTempPath()) ("planora-v29-same-handle-"+[Guid]::NewGuid().ToString('N')+'.lock');$moveSource=Join-Path $repo ("tmp\planora-v29-stale-source-"+[Guid]::NewGuid().ToString('N')+'.lock');$moveTarget=$moveSource+'.retained';$replacement=$moveSource+'.replacement';$bytes=$utf8.GetBytes('{"lock":"regression"}');$expected=Get-BytesSha256 $bytes;$oldFailure=$false;$replacementRejected=$false
    $old=New-Object IO.FileStream($oldPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);try{$old.Write($bytes,0,$bytes.Length);$old.Flush($true);try{[void](Get-Sha256 $oldPath)}catch{$oldFailure=$true};if((Assert-HeldStreamBytes $old $bytes $expected 'v28 regression')-cne$expected){throw 'v28 held-handle witness rejected'}}finally{$old.Dispose();if(Test-Path -LiteralPath $oldPath){Remove-Item -LiteralPath $oldPath -Force}}
    if(-not$oldFailure){throw 'v28 path-reopen self-sharing failure was not reproduced'}
    $successor=New-Object IO.FileStream($newPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None,4096,[IO.FileOptions]::DeleteOnClose);try{$successor.Write($bytes,0,$bytes.Length);$successor.Flush($true);if((Assert-HeldStreamBytes $successor $bytes $expected 'v29 successor')-cne$expected){throw 'v29 same-handle witness rejected'}}finally{$successor.Dispose()}
    if(Test-Path -LiteralPath $newPath){throw 'v29 DeleteOnClose witness rejected'}
    try{
        [IO.File]::WriteAllBytes($moveSource,$bytes);$sourcePin=Get-LocalEvidencePin $moveSource;$targetRelative=([IO.Path]::GetFullPath($moveTarget)).Replace($repo+'\','').Replace('\','/');$targetPin=[ordered]@{path=$targetRelative;size=$sourcePin.size;sha256=$sourcePin.sha256;file_id=$sourcePin.file_id;last_write_utc_ticks=$sourcePin.last_write_utc_ticks}
        $move=New-Object IO.FileStream($moveSource,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::Delete);try{[void](Assert-HeldStreamBytes $move $bytes $expected 'stale archive move witness');[IO.File]::Move($moveSource,$moveTarget);[void](Assert-HeldStreamBytes $move $bytes $expected 'retained stale archive witness');if((Test-Path -LiteralPath $moveSource)-or(-not(Test-Path -LiteralPath $moveTarget))){throw 'Held stale archive move state rejected'}}finally{$move.Dispose()}
        [void](Assert-RetainedArchivePin $moveTarget $targetPin $bytes $expected 'static_original_archive');[IO.File]::WriteAllBytes($replacement,$bytes);Remove-Item -LiteralPath $moveTarget -Force;[IO.File]::Move($replacement,$moveTarget)
        try{[void](Assert-LocalEvidencePin $targetPin)}catch{$replacementRejected=$true};if(-not$replacementRejected){throw 'Identical-byte retained archive replacement was not rejected'}
    }finally{foreach($p in @($moveSource,$moveTarget,$replacement)){if(Test-Path -LiteralPath $p){Remove-Item -LiteralPath $p -Force}}}
    return [ordered]@{v28_path_reopen_self_sharing_failure='REPRODUCED';v29_same_handle_seek_read_hash='PASS';v29_delete_on_close='PASS';stale_lock_atomic_move_while_held='PASS';identical_bytes_archive_replacement_rejected='PASS'}
}
function Invoke-StaleLockAdversarialModel{
    $contract=$predecessorContractJson|ConvertFrom-Json;[void](Assert-LocalEvidencePin $contract.v28.archive);$raw=[IO.File]::ReadAllText($staleArchivePath,$utf8)|ConvertFrom-Json
    if($raw.schema-cne'planora.shared-heavy-wsl-lock.v1'-or$raw.run_id-cne'e7cf1df162074402994a9d0ad763c824'-or$raw.authorization_sha256-cne'1e2ac9d1edfe7ee5191c631834eaa36b7b59d6886e94887aedc189e3c098026d'-or$raw.runner_sha256-cne'fbf0a2f4449806cec331c71efc79417553f2d1cd6b060f5d481a32dbfc896d60'-or$raw.owner_pid-ne1140){throw 'Retained v28 archive record rejected'}
    if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared lock unexpectedly present in archive model'};return [ordered]@{archive_exact_identity='PASS';archive_record='PASS';shared_lock_absent='PASS';archive_mutation_performed=$false}
}

function Release-HeavyLock([IO.FileStream]$Stream,[string]$ExpectedHash,[string]$Decision,[string]$AcceptanceHash,[string]$CleanupHash){
    if($null-eq$Stream){return};$expectedBytes=$utf8.GetBytes(($lockBody|ConvertTo-Json -Depth 6 -Compress));[void](Assert-HeldLockPath $Stream $expectedBytes $ExpectedHash);$Stream.Flush($true);$Stream.Dispose()
    if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared heavy lock DeleteOnClose release rejected'}
    $row=[ordered]@{schema='planora.shared-heavy-wsl-lock-release.v3';run_id=$runId;decision=$Decision;lock_sha256=$ExpectedHash;same_handle_verified=$true;delete_on_close=$true;acceptance_commitment_sha256=$AcceptanceHash;cleanup_sha256=$CleanupHash;released_at_utc=[DateTime]::UtcNow.ToString('o');lock_path_absent=$true}
    Write-NewUtf8 $lockReleaseFile ($row|ConvertTo-Json -Depth 6)
}

function Get-TranscriptDigest([string[]]$Rows){
    $body=$Rows-join'';$sha=[Security.Cryptography.SHA256]::Create();try{return ([BitConverter]::ToString($sha.ComputeHash($utf8.GetBytes($body)))-replace'-','').ToLowerInvariant()}finally{$sha.Dispose()}
}
function Assert-CanonicalUnittestTranscript([string]$Text,[int]$ExpectedTests,[int]$ExpectedPasses,[hashtable]$ExpectedSkips,[string]$ExpectedIdentityResultDigest){
    if($Text.Contains("`r")-or-not$Text.EndsWith("`n",[StringComparison]::Ordinal)){throw 'Unittest transcript newline framing rejected'}
    $lines=@($Text.Split("`n"));if($lines.Count-ne($ExpectedTests+6)){throw 'Unittest transcript line count rejected'}
    $digestRows=@();$seen=@{};$passes=0;$skips=0
    for($i=0;$i-lt$ExpectedTests;$i++){
        $line=$lines[$i]
        if($line-cnotmatch'^([A-Za-z_][A-Za-z0-9_]*) \(__main__\.([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\) \.\.\. (ok|skipped ''([^'']+)'')$'){throw "Unittest result grammar/order rejected at row $i"}
        $method=$Matches[1];$class=$Matches[2];$identityMethod=$Matches[3];$outcome=$Matches[4];$reason=$Matches[5]
        if($method-cne$identityMethod){throw 'Unittest method identity mismatch'};$identity="__main__.$class.$identityMethod";if($seen.ContainsKey($identity)){throw 'Duplicate unittest identity rejected'};$seen[$identity]=$true
        if($outcome-ceq'ok'){if($ExpectedSkips.ContainsKey($identity)){throw 'Expected skip reported ok'};$passes++;$digestRows+=("$identity|ok|`n")}
        else{if(-not$ExpectedSkips.ContainsKey($identity)-or$ExpectedSkips[$identity]-cne$reason){throw 'Unexpected unittest skip identity or reason'};$skips++;$digestRows+=("$identity|skip|$reason`n")}
    }
    if($passes-ne$ExpectedPasses-or$skips-ne$ExpectedSkips.Count-or$seen.Count-ne$ExpectedTests){throw 'Unittest exact result cardinality rejected'}
    if($lines[$ExpectedTests].Length-ne0-or$lines[$ExpectedTests+1]-cne('-'*70)-or$lines[$ExpectedTests+2]-cnotmatch("^Ran $ExpectedTests tests in [0-9]+\.[0-9]{3}s$")-or$lines[$ExpectedTests+3].Length-ne0-or$lines[$ExpectedTests+4]-cne("OK (skipped=$($ExpectedSkips.Count))")-or$lines[$ExpectedTests+5].Length-ne0){throw 'Unittest exact summary grammar rejected'}
    $digest=Get-TranscriptDigest $digestRows;if($digest-cne$ExpectedIdentityResultDigest){throw 'Unittest identity/result order digest rejected'}
    return [ordered]@{tests=$ExpectedTests;passes=$passes;skips=$skips;failures=0;errors=0;identity_result_digest=$digest}
}

function Assert-EvidenceSemantics([object[]]$Pins,[string]$ExpectedAcceptanceJson,[string]$ExpectedCleanupJson,[hashtable]$ExpectedSkips,[string]$ExpectedIdentityResultDigest,[string]$ExpectedAcceptanceHash){
    foreach($pin in $Pins){[void](Assert-LocalEvidencePin $pin)}
    $stdout=[IO.File]::ReadAllText($stdoutFile,$utf8);if($stdout.Length-ne0){throw 'Final stdout semantic replay rejected'}
    $stderr=[IO.File]::ReadAllText($stderrFile,$utf8);$transcript=Assert-CanonicalUnittestTranscript $stderr 119 117 $ExpectedSkips $ExpectedIdentityResultDigest
    $resource=Assert-FinalResourceEvidence
    $acceptanceRaw=[IO.File]::ReadAllText($acceptanceFile,$utf8);$cleanupRaw=[IO.File]::ReadAllText($cleanupFile,$utf8)
    if((ConvertTo-JsonTokenStream $acceptanceRaw)-cne(ConvertTo-JsonTokenStream $ExpectedAcceptanceJson)){throw 'Final acceptance semantic replay rejected'}
    if((ConvertTo-JsonTokenStream $cleanupRaw)-cne(ConvertTo-JsonTokenStream $ExpectedCleanupJson)){throw 'Final cleanup semantic replay rejected'}
    $acceptance=$acceptanceRaw|ConvertFrom-Json;$cleanup=$cleanupRaw|ConvertFrom-Json
    if($acceptance.status-cne'CANONICAL_ACCEPTED_PENDING_CLEANUP_NOT_PASS'-or$acceptance.run_id-cne$runId-or$cleanup.run_id-cne$runId-or-not$cleanup.root_absent-or$cleanup.acceptance_commitment_sha256-cne$ExpectedAcceptanceHash){throw 'Final acceptance/cleanup binding replay rejected'}
    $pinJson=$Pins|ConvertTo-Json -Depth 12 -Compress;$pinDigest=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream $pinJson)
    return [ordered]@{pins=$Pins.Count;pins_sha256=$pinDigest;transcript=$transcript;resource_samples=$resource.samples;acceptance_semantics=$true;cleanup_semantics=$true}
}
function Assert-ProtectedEvidenceReplay([object]$Watcher,[object[]]$Pins,[string]$ExpectedAcceptanceJson,[string]$ExpectedCleanupJson,[string]$ExpectedInventoryHash,[int]$ExpectedFiles,[hashtable]$ExpectedSkips,[string]$ExpectedIdentityResultDigest,[string]$ExpectedAcceptanceHash,[string]$ExpectedControlHash){
    [void](Assert-WatcherLiveCleaned $Watcher $ExpectedInventoryHash $ExpectedFiles $ExpectedAcceptanceHash $ExpectedControlHash)
    $summary=Assert-EvidenceSemantics $Pins $ExpectedAcceptanceJson $ExpectedCleanupJson $ExpectedSkips $ExpectedIdentityResultDigest $ExpectedAcceptanceHash
    [void](Assert-WatcherLiveCleaned $Watcher $ExpectedInventoryHash $ExpectedFiles $ExpectedAcceptanceHash $ExpectedControlHash);return $summary
}
function Assert-FinalEvidenceReplay([object[]]$Pins,[string]$ExpectedAcceptanceJson,[string]$ExpectedCleanupJson,[string]$ExpectedInventoryHash,[int]$ExpectedFiles,[hashtable]$ExpectedSkips,[string]$ExpectedIdentityResultDigest,[string]$ExpectedAcceptanceHash,[string]$ExpectedControlHash,[string]$ExpectedShutdownHash,[string]$ExpectedCleanupHash,[string]$ExpectedProtectedReplayHash,[string]$ExpectedPassReceiptHash){
    $summary=Assert-EvidenceSemantics $Pins $ExpectedAcceptanceJson $ExpectedCleanupJson $ExpectedSkips $ExpectedIdentityResultDigest $ExpectedAcceptanceHash
    $watch=Assert-FinalWatcherEvidence $ExpectedInventoryHash $ExpectedFiles $ExpectedAcceptanceHash $ExpectedControlHash $ExpectedShutdownHash $ExpectedCleanupHash $ExpectedProtectedReplayHash $ExpectedPassReceiptHash;$summary['watcher_rows']=$watch.rows.Count;$summary['staging_events']=$watch.staging_events;$summary['cleanup_events']=$watch.cleanup_events;$summary['watcher_shutdown_control_sha256']=$ExpectedShutdownHash;$summary['pass_receipt_sha256']=$ExpectedPassReceiptHash;return $summary
}

function Assert-ClaimFailureModel([ValidateSet('constructor','immediate_after_create','write','flush','immediate_after_publish')][string]$Fault){
    $attempted=$true;$created=$false;$complete=$false;try{if($Fault-ceq'constructor'){throw 'fault'};$created=$true;if($Fault-ceq'immediate_after_create'){throw 'fault'};if($Fault-ceq'write'){throw 'fault'};if($Fault-ceq'flush'){throw 'fault'};$complete=$true;if($Fault-ceq'immediate_after_publish'){throw 'fault'}}catch{return [ordered]@{claim_attempted=$attempted;claim_created=$created;claim_complete=$complete;durable_rejection_required=$attempted;detailed_rejection_required=$attempted}};throw 'Claim failure model did not fail'
}
function Assert-PassPublicationReady([object]$State){
    foreach($name in @('canonical_exited','watcher_live_cleaned','parent_watch_active','resource_monitor_exited','resource_monitor_clean','snapshot_absent','shared_lock_absent','cleanup_evidence_present','lock_release_evidence_present','acceptance_commitment_present','postflight_census_clean','protected_evidence_replayed')){if(-not[bool]$State.$name){throw "PASS publication prerequisite rejected: $name"}}
    return $true
}
function Assert-FinalizationReady([object]$State){
    foreach($name in @('canonical_exited','watcher_exited','watcher_clean','resource_monitor_exited','resource_monitor_clean','snapshot_absent','shared_lock_absent','cleanup_evidence_present','lock_release_evidence_present','acceptance_commitment_present','postflight_census_clean','final_evidence_replayed','pass_receipt_present','final_pass_seal_absent_before_publication')){if(-not[bool]$State.$name){throw "Finalization prerequisite rejected: $name"}}
    return $true
}

function Get-CanonicalArguments([object[]]$Legacy){
    if($Legacy.Count-ne48){throw 'Canonical legacy bind count rejected'}
    $args=@('-d','Ubuntu','--exec','/usr/bin/timeout','--signal=TERM','--kill-after=15s','600s','/usr/bin/bwrap','--die-with-parent','--new-session','--unshare-all','--tmpfs','/','--ro-bind','/usr','/usr','--ro-bind','/bin','/bin','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--ro-bind','/etc','/etc','--ro-bind',$root,'/snapshot','--dir','/mnt','--dir','/mnt/d','--dir','/mnt/d/Stuff','--dir','/mnt/d/Stuff/Projects','--dir','/mnt/d/Stuff/Projects/Sites','--dir',$repoWsl,'--ro-bind',$snapshotRepo,$repoWsl,'--dir','/mnt/c','--tmpfs','/mnt/c','--dir','/mnt/wsl','--tmpfs','/mnt/wsl','--tmpfs','/tmp','--tmpfs','/run','--dir','/run/desktop','--tmpfs','/run/desktop','--dir','/media','--dir','/media/host','--tmpfs','/media/host','--dir','/media/windows','--tmpfs','/media/windows')
    foreach($row in $Legacy){$args+=@('--ro-bind',"/snapshot/legacy/$($row.leaf)","/tmp/$($row.leaf)")}
    $args+=@('--dev','/dev','--proc','/proc','--remount-ro','/','--clearenv','--setenv','PATH','/usr/bin:/bin','--setenv','LANG','C.UTF-8','--setenv','LC_ALL','C.UTF-8','--setenv','TMPDIR','/tmp','--setenv','PYTHONDONTWRITEBYTECODE','1','--setenv','PYTHONHASHSEED','0','--setenv','PLANORA_MUNI_V28_SKIP_HEAVY','1','--cap-drop','ALL','--chdir',$snapshotRepo,'/usr/bin/python3.12','-I','-S','-B',"$snapshotRepo/$testsRelative")
    foreach($atom in $args){if(-not(Test-SafeNativeAtom $atom)){throw "Unsafe canonical argument atom: $atom"}}
    if(@($args|Where-Object{$_-ceq$testsPath}).Count-ne0-or@($args|Where-Object{$_-ceq"$snapshotRepo/$testsRelative"}).Count-ne1){throw 'Live or ambiguous canonical test path rejected'}
    Assert-CanonicalArguments $args $Legacy
    return $args
}
function Assert-CanonicalArguments([string[]]$Arguments,[object[]]$Legacy){
    $prefix=@('-d','Ubuntu','--exec','/usr/bin/timeout','--signal=TERM','--kill-after=15s','600s','/usr/bin/bwrap','--die-with-parent','--new-session','--unshare-all','--tmpfs','/','--ro-bind','/usr','/usr','--ro-bind','/bin','/bin','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--ro-bind','/etc','/etc','--ro-bind',$root,'/snapshot','--dir','/mnt','--dir','/mnt/d','--dir','/mnt/d/Stuff','--dir','/mnt/d/Stuff/Projects','--dir','/mnt/d/Stuff/Projects/Sites','--dir',$repoWsl,'--ro-bind',$snapshotRepo,$repoWsl,'--dir','/mnt/c','--tmpfs','/mnt/c','--dir','/mnt/wsl','--tmpfs','/mnt/wsl','--tmpfs','/tmp','--tmpfs','/run','--dir','/run/desktop','--tmpfs','/run/desktop','--dir','/media','--dir','/media/host','--tmpfs','/media/host','--dir','/media/windows','--tmpfs','/media/windows')
    if($Arguments.Count-lt$prefix.Count){throw 'Canonical argv shorter than fixed mount prefix'};for($i=0;$i-lt$prefix.Count;$i++){if($Arguments[$i]-cne$prefix[$i]){throw "Canonical bwrap mount/argv order rejected at index $i"}}
    if(@($Arguments|Where-Object{$_-ceq$root}).Count-ne1-or@($Arguments|Where-Object{$_-ceq'/snapshot'}).Count-ne1){throw 'Snapshot host/root bind cardinality rejected'}
    if(@($Arguments|Where-Object{$_-ceq$repoWsl}).Count-ne2-or@($Arguments|Where-Object{$_-ceq$snapshotRepo}).Count-ne2){throw 'Repository overlay/chdir cardinality rejected'}
    $legacySources=@($Arguments|Where-Object{$_-clike'/snapshot/legacy/*'});if($legacySources.Count-ne48){throw 'Legacy bind cardinality rejected'}
    $cursor=$prefix.Count;foreach($row in $Legacy){$expected=@('--ro-bind',"/snapshot/legacy/$($row.leaf)","/tmp/$($row.leaf)");foreach($atom in $expected){if($cursor-ge$Arguments.Count-or$Arguments[$cursor]-cne$atom){throw "Canonical legacy mount order rejected at index $cursor"};$cursor++}}
    $suffix=@('--dev','/dev','--proc','/proc','--remount-ro','/','--clearenv','--setenv','PATH','/usr/bin:/bin','--setenv','LANG','C.UTF-8','--setenv','LC_ALL','C.UTF-8','--setenv','TMPDIR','/tmp','--setenv','PYTHONDONTWRITEBYTECODE','1','--setenv','PYTHONHASHSEED','0','--setenv','PLANORA_MUNI_V28_SKIP_HEAVY','1','--cap-drop','ALL','--chdir',$snapshotRepo,'/usr/bin/python3.12','-I','-S','-B',"$snapshotRepo/$testsRelative")
    foreach($atom in $suffix){if($cursor-ge$Arguments.Count-or$Arguments[$cursor]-cne$atom){throw "Canonical suffix argv order rejected at index $cursor"};$cursor++};if($cursor-ne$Arguments.Count){throw 'Canonical argv contains trailing atoms'}
    if(@($Arguments|Where-Object{$_-ceq'PLANORA_MUNI_V28_SKIP_HEAVY'}).Count-ne1){throw 'Heavy-skip environment cardinality rejected'}
    if(@($Arguments|Where-Object{$_-ceq'--kill-after=15s'}).Count-ne1-or@($Arguments|Where-Object{$_-ceq'--remount-ro'}).Count-ne1){throw 'Timeout or root-remount contract rejected'}
    $maskedRoutes=@('/mnt/c','/mnt/wsl','/run/desktop','/media/host','/media/windows');foreach($route in $maskedRoutes){if(@($Arguments|Where-Object{$_-ceq$route}).Count-ne2){throw "Alternate host route mask cardinality rejected: $route"}}
    foreach($atom in $Arguments){if(($atom-cmatch'(?i)^/mnt/c/'-or$atom-cmatch'(?i)^/mnt/wsl/'-or$atom-cmatch'(?i)^/run/desktop/'-or$atom-cmatch'(?i)^/media/(?:host|windows)/')-and$maskedRoutes-cnotcontains$atom){throw 'Alternate host route descendant admitted'}}
    for($i=0;$i-lt$Arguments.Count-2;$i++){if($Arguments[$i]-cne'--ro-bind'){continue};$source=$Arguments[$i+1];if(@('/usr','/bin','/lib','/lib64','/etc',$root,$snapshotRepo)-ccontains$source){continue};if($source-clike'/snapshot/legacy/*'){continue};throw "Unapproved read-only bind source rejected: $source"}
    if($Arguments[-1]-cne"$snapshotRepo/$testsRelative"-or$Arguments[-7]-cne'--chdir'-or$Arguments[-6]-cne$snapshotRepo-or$Arguments[-5]-cne'/usr/bin/python3.12'-or$Arguments[-4]-cne'-I'-or$Arguments[-3]-cne'-S'-or$Arguments[-2]-cne'-B'){throw 'Canonical staged test argv tail rejected'}
    return $true
}

if($LogBridgeSelfTest){
    $auth=Get-AuthorizationState;$name='muni-v30-log-bridge-'+[Guid]::NewGuid().ToString('N');$dir=Join-Path $repo ('tmp\'+$name);$dirWsl=$repoWsl+'/tmp/'+$name
    if(-not(Test-Path -LiteralPath (Join-Path $repo 'tmp'))){[void](New-Item -ItemType Directory -Path (Join-Path $repo 'tmp'))};[void](New-Item -ItemType Directory -Path $dir)
    $legacy=$null;$fixed=$null;$legacyFailure=$false;$stableReads=0
    try{
        $legacyCfg=[ordered]@{log=$dirWsl+'/legacy.jsonl';ready=$dirWsl+'/legacy.ready';stop=$dirWsl+'/legacy.stop'};$legacy=Start-SafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $legacyCfg)) $legacyLogBridgeSource;$deadline=[DateTime]::UtcNow.AddSeconds(10);while(-not(Test-Path -LiteralPath (Join-Path $dir 'legacy.ready'))-and[DateTime]::UtcNow-lt$deadline){if($legacy.Process.HasExited){throw 'Legacy bridge writer exited early'};Start-Sleep -Milliseconds 10};if(-not(Test-Path -LiteralPath (Join-Path $dir 'legacy.ready'))){throw 'Legacy bridge ready deadline'}
        try{[void][IO.File]::ReadAllText((Join-Path $dir 'legacy.jsonl'),$utf8)}catch [IO.IOException]{$legacyFailure=$true};if(-not$legacyFailure){throw 'Legacy lifetime-open DrvFS sharing failure was not reproduced'};Write-NewAscii (Join-Path $dir 'legacy.stop') "stop`n";if(-not$legacy.Process.WaitForExit(10000)){throw 'Legacy bridge stop deadline'};$legacyOut=$legacy.OutTask.GetAwaiter().GetResult();$legacyErr=$legacy.ErrTask.GetAwaiter().GetResult();if($legacy.Process.ExitCode-ne0-or$legacyOut.Length-ne0-or$legacyErr.Length-ne0){throw 'Legacy bridge wrapper rejected'};$legacy.Process.Dispose();$legacy=$null
        $fixedCfg=[ordered]@{log=$dirWsl+'/fixed.jsonl'};$fixed=Start-SafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $fixedCfg)) $fixedLogBridgeSource;$raw='';while(-not$fixed.Process.HasExited){$raw=Read-StableUtf8Log (Join-Path $dir 'fixed.jsonl') 'Bridge fixed' $fixed.Process;if($raw.Length-ne0){$stableReads++};Start-Sleep -Milliseconds 2};if(-not$fixed.OutTask.Wait(10000)-or-not$fixed.ErrTask.Wait(10000)){throw 'Fixed bridge stream drain deadline'};$fixedOut=$fixed.OutTask.GetAwaiter().GetResult();$fixedErr=$fixed.ErrTask.GetAwaiter().GetResult();if($fixed.Process.ExitCode-ne0-or$fixedOut.Length-ne0-or$fixedErr.Length-ne0){throw 'Fixed bridge wrapper rejected'};$fixed.Process.Dispose();$fixed=$null;$raw=Read-StableUtf8Log (Join-Path $dir 'fixed.jsonl') 'Bridge fixed final' $null;$lines=@($raw.Substring(0,$raw.Length-1).Split("`n"));$rows=@($lines|ForEach-Object{$_|ConvertFrom-Json});if($rows.Count-ne14-or$rows[0].kind-cne'READY'-or$rows[-1].kind-cne'DONE'-or$rows[-1].samples-ne12){throw 'Fixed bridge row grammar rejected'};for($i=1;$i-le12;$i++){if($rows[$i].kind-cne'SAMPLE'-or$rows[$i].sequence-ne$i){throw 'Fixed bridge sequence rejected'}};$prior=($lines[0..12]|ForEach-Object{$_+"`n"})-join'';if((Get-Utf8StringSha256 $prior)-cne$rows[-1].prior_sha256){throw 'Fixed bridge digest rejected'}
        if($stableReads-lt3){throw 'Fixed bridge did not overlap at least three stable host reads'};[Console]::Out.WriteLine(([ordered]@{schema='planora.muni-v30.log-bridge-self-test.v1';status='PASS';run_id=$runId;runner_sha256=$auth.runner_sha256;legacy_lifetime_open_sharing_failure='REPRODUCED';short_lived_append_stable_reads=$stableReads;rows=$rows.Count;samples=12;duplicates=0;canonical_suite_executed=$false;shared_lock_used=$false}|ConvertTo-Json -Compress));return
    }finally{if($null-ne$legacy){try{$legacy.Process.Kill()}catch{};try{$legacy.Process.Dispose()}catch{}};if($null-ne$fixed){try{$fixed.Process.Kill()}catch{};try{$fixed.Process.Dispose()}catch{}};if(Test-Path -LiteralPath $dir){Remove-Item -LiteralPath $dir -Recurse -Force}}
}

if($StaticSelfTest){
    $auth=Get-AuthorizationState
    $rows=@(Get-LegacyRows)
    $checks=Invoke-LocalStaticAdversarialChecks
    $lockRegression=Invoke-LockSelfReadRegressionModel
    $staleModel=Invoke-StaleLockAdversarialModel
    $predecessorModel=Get-ValidatedCombinedPredecessorEvidence $true;if(@($predecessorModel.runtime.validated_pins).Count-ne25-or@($predecessorModel.contract.v29.sources.PSObject.Properties).Count-ne4-or@($predecessorModel.contract.v29.artifacts.PSObject.Properties).Count-ne11-or-not$predecessorModel.runtime.pass_absence.v28_receipt_absent-or-not$predecessorModel.runtime.pass_absence.v29_receipt_absent){throw 'Complete combined predecessor static model rejected'}
    $boundary=Invoke-LocalArgumentBoundaryWitness
    $canonical=@(Get-CanonicalArguments $rows)
    $closure=Assert-LocalFrozenClosure
    $argvMutations=@();$rootIndex=[Array]::IndexOf($canonical,[string]$root);$killIndex=[Array]::IndexOf($canonical,[string]'--kill-after=15s');$maskIndex=[Array]::IndexOf($canonical,[string]'/mnt/c');$firstBind=[Array]::IndexOf($canonical,[string]'--ro-bind');$firstLegacy=[Array]::IndexOf($canonical,[string]"/snapshot/legacy/$($rows[0].leaf)")
    $m=@($canonical);$m[$rootIndex]='/wrong-snapshot';$argvMutations+=,@($m);$m=@($canonical);$m[$killIndex]='--kill-after=0s';$argvMutations+=,@($m);$m=@($canonical);$m[$maskIndex]='/mnt/c/mnt/d/Stuff/Projects/Sites/Planora';$argvMutations+=,@($m);$m=@($canonical);$m[$firstBind+1]='/';$argvMutations+=,@($m);$m=@($canonical)+@($root);$argvMutations+=,@($m);$m=@($canonical);$swap=$m[$firstLegacy];$m[$firstLegacy]=$m[$firstLegacy+3];$m[$firstLegacy+3]=$swap;$argvMutations+=,@($m)
    foreach($mutation in $argvMutations){$bad=$false;try{[void](Assert-CanonicalArguments $mutation $rows)}catch{$bad=$true};if(-not$bad){throw 'Adversarial bwrap mount/argv mutation accepted'}}
    $source=[IO.File]::ReadAllText($runnerPath,$utf8)
    $forbiddenLauncher='Start'+'-Process'
    if($source.IndexOf($forbiddenLauncher,[StringComparison]::OrdinalIgnoreCase)-ge0){throw 'Forbidden process launcher invocation remains'}
    if($source-cnotmatch'ProcessStartInfo_safe_atoms_plus_stdin_source'){throw 'Argument-boundary-safe watcher contract missing'}
    if($source-cnotmatch's\.st_nlink!=1'){throw 'Python nlink gate missing'}
    foreach($required in @('--kill-after=15s','Stop-CanonicalProcess $executionHandle','Assert-ResourceMonitorLive $resourceMonitor','live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace','bounded_maximum_gap_not_exact_interval','parent watch loss rejected','parent_watch_descriptor','watcher-shutdown-control.v2','PASS_PUBLISHED_REQUIRES_AUTHENTICATED_POST_PUBLICATION_GUARD_SHUTDOWN_SEAL','pass-publication-shutdown-seal.v1','CLAIMED_FAIL_CLOSED_UNLESS_VALID_PASS_PUBLICATION_SHUTDOWN_SEAL_EXISTS','claimPublicationStarted=$true;$claimPublicationPhase=''create_attempted_before_return''','Assert-ProtectedEvidenceReplay','Stop-Watcher $watcher','Assert-FinalEvidenceReplay','/mnt/c/mnt/d/Stuff/Projects/Sites/Planora','planora.muni-v30.complete-v28-v29-predecessor-evidence.v1','Get-NonThrowingCombinedPredecessorReplay','complete-v28-v29-predecessor-evidence.v1','Read-StableUtf8Log','short_lived_append','LogBridgeSelfTest','terminal_before_create_only_final_pass_seal','pass-publication-shutdown-seal.v2','Open-TerminalArchivedStaleLockGuard','Read_only_blocks_write_and_delete','Write-FinalPassSeal')){if($source-cnotmatch[regex]::Escape($required)){throw "Static blocker repair witness missing: $required"}}
    $censusIndex=$source.LastIndexOf('$after=[ordered]',[StringComparison]::Ordinal);$releaseIndex=$source.LastIndexOf("Release-HeavyLock `$lockStream `$lockHash 'ACCEPTED_PENDING_FINALIZATION'",[StringComparison]::Ordinal);$publicationReplayIndex=$source.LastIndexOf('$publicationReplay=Assert-ProtectedEvidenceReplay',[StringComparison]::Ordinal);$receiptWriteIndex=$source.LastIndexOf('Write-NewUtf8 $receiptFile $receiptJson',[StringComparison]::Ordinal);$postPublicationReplayIndex=$source.LastIndexOf('$postPublicationReplay=Assert-ProtectedEvidenceReplay',[StringComparison]::Ordinal);$watcherStopIndex=$source.LastIndexOf('Stop-Watcher $watcher $postHash $acceptanceHash $cleanupHash $postPublicationReplayHash $receiptHash',[StringComparison]::Ordinal);$finalReplayIndex=$source.LastIndexOf('$finalReplay=Assert-FinalEvidenceReplay',[StringComparison]::Ordinal);$sealWriteIndex=$source.LastIndexOf('Write-FinalPassSeal $passSealFile',[StringComparison]::Ordinal);$terminalArchiveIndex=$source.LastIndexOf('terminal_before_create_only_final_pass_seal',[StringComparison]::Ordinal);if($censusIndex-lt0-or$releaseIndex-le$censusIndex-or$publicationReplayIndex-le$releaseIndex-or$receiptWriteIndex-le$publicationReplayIndex-or$postPublicationReplayIndex-le$receiptWriteIndex-or$watcherStopIndex-le$postPublicationReplayIndex-or$finalReplayIndex-le$watcherStopIndex-or$terminalArchiveIndex-le$finalReplayIndex-or$sealWriteIndex-le$terminalArchiveIndex){throw 'Watcher census/lock/replay/PASS-publication/archive-terminal/create-only-final-seal order rejected'}
    $claimAttemptIndex=$source.IndexOf('$claimPublicationStarted=$true;$claimPublicationPhase=''create_attempted_before_return''',[StringComparison]::Ordinal);$claimTryIndex=if($claimAttemptIndex-ge0){$source.LastIndexOf('try{',$claimAttemptIndex,[StringComparison]::Ordinal)}else{-1};$claimCreateIndex=if($claimAttemptIndex-ge0){$source.IndexOf('$claimStream=New-Object IO.FileStream',$claimAttemptIndex,[StringComparison]::Ordinal)}else{-1};$outerCatchIndex=$source.LastIndexOf('catch{',[StringComparison]::Ordinal);if($claimTryIndex-lt0-or$claimAttemptIndex-le$claimTryIndex-or$claimCreateIndex-le$claimAttemptIndex-or$outerCatchIndex-le$claimCreateIndex){throw 'Claim constructor attempt is not covered by outer rejection try before CreateNew'}
    $result=[ordered]@{schema='planora.muni-v30.static-self-test.v6';status='PASS_FOR_FRESH_INDEPENDENT_STATIC_REVIEW';runner_sha256=$auth.runner_sha256;authorization_sha256=$auth.authorization_sha256;legacy_rows=$rows.Count;argument_boundary_witness=$boundary;canonical_argument_count=$canonical.Count;exact_bwrap_mount_order='PASS';bwrap_mount_mutations_rejected=$argvMutations.Count;frozen_closure=$closure;host_deadline_and_kill_after='PASS';resource_descendant_tree='LIVE_ANCESTRY_OR_PREVIOUSLY_FROZEN_IDENTITY_HOSTILE_SIBLING_REJECTED';resource_cadence='TARGET_100MS_MAXIMUM_GAP_750MS';staging_events='LOSSLESS_PARENT_WATCH_LOSS_REJECTED_AND_DIGEST_BOUND';watcher_lifetime='THROUGH_CENSUS_LOCK_RELEASE_REPLAYS_AND_PASS_PUBLICATION_WITH_RECEIPT_BOUND_SHUTDOWN_SEAL';claim_failure_rejection='CONSTRUCTOR_CREATE_WRITE_FLUSH_IMMEDIATE_FAILURES_COVERED';final_semantic_identity_hash_replay='PASS';complete_predecessor_evidence_binding='PASS';cross_boundary_log_protocol='SHORT_LIVED_IDENTITY_CHECKED_APPEND_AND_STABLE_HOST_READ';authoritative_archived_lock_terminal_replay='PASS';alternate_host_routes_masked='PASS';live_repo_execution_reference='REJECTED';staged_test_execution_reference='PASS';adversarial=$checks;canonical_suite_executed=$false;lock_regression=$lockRegression;archived_predecessor_model=$staleModel;predecessor_evidence_model='25_EXACT_IDENTITY_PINS_V28_V29_PLUS_DUAL_PASS_ABSENCE_VALIDATED';wsl_executed=$false}
    [Console]::Out.WriteLine(($result|ConvertTo-Json -Depth 8 -Compress))
    return
}

$lockStream=$null;$lockHash='';$lockBody=$null;$predecessorCustodyHash='';$staleArchivePin=$null;$predecessorEvidence=New-ExpectedCombinedPredecessorEvidence;$predecessorEvidenceHash='';$predecessorPins=@();$archiveReplayAtPass=$null;$archiveReplayBeforeFinalization=$null;$archiveReplayTerminal=$null;$terminalArchiveGuard=$null;$watcher=$null;$resourceMonitor=$null;$executionHandle=$null;$claimStream=$null;$claimPublicationStarted=$false;$claimCreateReturned=$false;$claimPublicationComplete=$false;$claimPublicationPhase='before_create';$snapshotCreated=$false;$snapshotDeleted=$false;$acceptanceHash='';$cleanupHash='';$decision='REJECTED';$runnerHash='';$authorizationHash=''
try{
    # Mark the irreversible attempt before CreateNew so constructor failure still enters durable rejection publication.
    $claim=[ordered]@{schema='planora.muni-v30.atomic-run-claim.v2';status='CLAIMED_FAIL_CLOSED_UNLESS_VALID_PASS_PUBLICATION_SHUTDOWN_SEAL_EXISTS';run_id=$runId;authorization=$authorizationRelative;claimed_at_utc=[DateTime]::UtcNow.ToString('o');mechanism='FileMode.CreateNew_FileShare.None_write_FlushTrue';irreversible=$true;failure_consumes_authorization=$true;default_outcome_on_any_unsealed_failure='REJECTED_AUTHORIZATION_CONSUMED'}
    $claimBytes=$utf8.GetBytes(($claim|ConvertTo-Json -Depth 6 -Compress));$claimPublicationStarted=$true;$claimPublicationPhase='create_attempted_before_return';$claimStream=New-Object IO.FileStream($claimFile,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None);$claimCreateReturned=$true;$claimPublicationPhase='create_succeeded_before_write'
    try{$claimStream.Write($claimBytes,0,$claimBytes.Length);$claimPublicationPhase='write_completed_before_flush';$claimStream.Flush($true);$claimPublicationComplete=$true;$claimPublicationPhase='durably_published'}finally{$claimStream.Dispose();$claimStream=$null}
    $claimRaw=[IO.File]::ReadAllText($claimFile,$utf8);if((ConvertTo-JsonTokenStream $claimRaw)-cne(ConvertTo-JsonTokenStream ($claim|ConvertTo-Json -Depth 6 -Compress))){throw 'Atomic claim immediate semantic replay rejected'}

    $reserved=@($lockEvidenceFile,$lockReleaseFile,$stagingInventoryFile,$preInventoryFile,$postInventoryFile,$staticEvidenceFile,$watchLogFile,$watchErrorFile,$watchWrapperOutFile,$watchWrapperErrFile,$watchStopFile,$watchCleanupFile,$resourceLogFile,$resourceErrorFile,$resourceStopFile,$resourceWrapperOutFile,$resourceWrapperErrFile,$stdoutFile,$stderrFile,$exitFile,$planFile,$acceptanceFile,$receiptFile,$passSealFile,$cleanupFile,$rejectionFile,$rejectionEmergencyFile,$predecessorCustodyFile)
    foreach($p in $reserved){if(Test-Path -LiteralPath $p){throw "Pre-existing evidence path rejected: $p"}}

    $auth=Get-AuthorizationState;$runnerHash=$auth.runner_sha256;$authorizationHash=$auth.authorization_sha256
    Assert-LocalPin $successorBuilderPath 59115 'c33cafd5260b79365ce434c086cf4e31c4333c904480b7ae445f15970201cb25'
    Assert-LocalPin $admissionTestsPath 17533 'a0f7cad0ff955827f061a5f6228a45e1f8b9c09b22fa378318f4aea3793c621e'
    $predecessorEvidence=Get-ValidatedCombinedPredecessorEvidence $true;$staleArchivePin=$predecessorEvidence.contract.v28.archive;$predecessorPins=@(Get-CombinedPredecessorPinArray $predecessorEvidence);if($predecessorPins.Count-ne25){throw 'Combined predecessor pin cardinality rejected'}
    $predecessorEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence|ConvertTo-Json -Depth 40 -Compress))
    $legacy=@(Get-LegacyRows);$static=Invoke-LocalStaticAdversarialChecks;$lockRegression=Invoke-LockSelfReadRegressionModel;$staleModel=Invoke-StaleLockAdversarialModel
    Write-NewUtf8 $staticEvidenceFile (([ordered]@{run_id=$runId;runner_sha256=$runnerHash;authorization_sha256=$authorizationHash;legacy_rows=$legacy.Count;checks=$static;lock_regression=$lockRegression;archived_predecessor_model=$staleModel;log_protocol='create_close_short_lived_identity_checked_append_plus_stable_host_reader'}|ConvertTo-Json -Depth 12))
    $custody=[ordered]@{schema='planora.muni-v30.predecessor-custody.v1';status='EXACT_V28_V29_CUSTODY_VALIDATED_BEFORE_V30_LOCK';run_id=$runId;predecessor_evidence=$predecessorEvidence;predecessor_evidence_sha256=$predecessorEvidenceHash;archive_identity_replay=(Assert-FinalArchivedStaleLockIdentity $staleArchivePin 'before_predecessor_custody_publication' $true);shared_lock_absent=$true;created_at_utc=[DateTime]::UtcNow.ToString('o')};Write-NewUtf8 $predecessorCustodyFile ($custody|ConvertTo-Json -Depth 42);$predecessorCustodyHash=Get-Sha256 $predecessorCustodyFile
    if(Test-Path -LiteralPath $sharedLockPath){throw 'Shared lock appeared before v30 acquisition'}
    $lockBody=[ordered]@{schema='planora.shared-heavy-wsl-lock.v2';run_id=$runId;authorization_sha256=$authorizationHash;runner_sha256=$runnerHash;predecessor_custody_sha256=$predecessorCustodyHash;created_at_utc=[DateTime]::UtcNow.ToString('o');mechanism='CreateNew_ReadWrite_FileShareNone_DeleteOnClose_same_handle_seek_read_hash';owner_pid=$PID}
    $lockBytes=$utf8.GetBytes(($lockBody|ConvertTo-Json -Depth 6 -Compress));$lockHash=Get-BytesSha256 $lockBytes
    $lockStream=New-Object IO.FileStream($sharedLockPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None,4096,[IO.FileOptions]::DeleteOnClose)
    $lockStream.Write($lockBytes,0,$lockBytes.Length);$lockStream.Flush($true);[void](Assert-HeldLockPath $lockStream $lockBytes $lockHash)
    Write-NewUtf8 $lockEvidenceFile (([ordered]@{lock=$lockBody;lock_sha256=$lockHash;held_open=$true;same_handle_verified=$true;delete_on_close=$true;predecessor_custody_sha256=$predecessorCustodyHash;stale_archive_pin=$staleArchivePin;predecessor_evidence_sha256=$predecessorEvidenceHash}|ConvertTo-Json -Depth 12))

    $sample1=[ordered]@{sample=1;at_utc=[DateTime]::UtcNow.ToString('o');memavailable_kib=(Get-MemAvailable);census=(Get-WslProcessCensus)}
    if($sample1.memavailable_kib-lt1900000){throw 'First MemAvailable sample below 1900000 KiB'}
    $sampleTicks=[Diagnostics.Stopwatch]::StartNew();Start-Sleep -Seconds 5
    $sample2=[ordered]@{sample=2;at_utc=[DateTime]::UtcNow.ToString('o');memavailable_kib=(Get-MemAvailable);census=(Get-WslProcessCensus);separation_milliseconds=$sampleTicks.ElapsedMilliseconds}
    if($sample2.separation_milliseconds-lt5000-or$sample2.memavailable_kib-lt1900000){throw 'Second memory sample or separation rejected'}

    $canonical=@(Get-CanonicalArguments $legacy)
    $watchCfg=[ordered]@{root=$root;stop="$prefixWsl.mutation-watch.stop";cleanup="$prefixWsl.mutation-watch.cleanup.json";log="$prefixWsl.mutation-watch.jsonl";error="$prefixWsl.mutation-watch.error.log";expected="$prefixWsl.staging-inventory.json";run_id=$runId}
    $watcher=Start-SafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $watchCfg)) $watcherSource
    $watchArmed=$false;$watchArmDeadline=[DateTime]::UtcNow.AddSeconds(15)
    while([DateTime]::UtcNow-lt$watchArmDeadline){
        if($watcher.Process.HasExited){throw 'Mutation watcher exited before pre-staging arm'}
        if((Test-Path -LiteralPath $watchLogFile)-and(Test-Path -LiteralPath $watchErrorFile)){
            if((Get-Item -LiteralPath $watchErrorFile).Length-ne0){throw 'Pre-staging watcher error evidence was not empty'}
            $armedRows=@(Get-WatcherRows $watcher.Process);if($armedRows.Count-ge1){[void](Assert-WatcherArmedBeforeStaging $watcher);$watchArmed=$true;break}
        }
        Start-Sleep -Milliseconds 100
    }
    if(-not$watchArmed){throw 'Watcher was not armed before staging root creation'}

    $stageCfg=[ordered]@{root=$root;repo=$repoWsl;out="$prefixWsl.staging-inventory.json";contract=($snapshotContractJson|ConvertFrom-Json);legacy=@($legacy|ForEach-Object{[ordered]@{source=$_.source;leaf=$_.leaf;sha256=$_.sha256}})}
    $snapshotCreated=$true
    $stageResult=Invoke-SafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $stageCfg)) $stagingSource 'immutable snapshot staging'
    $stageLines=@($stageResult.stdout.Trim()-split"`r?`n"|Where-Object{$_});if($stageLines.Count-ne1-or$stageResult.stderr.Length-ne0){throw 'Staging summary or stderr rejected'}
    $stageSummary=$stageLines[0]|ConvertFrom-Json;if($stageSummary.status-cne'STAGED'){throw 'Staging status rejected'}
    $stagingHash=Get-Sha256 $stagingInventoryFile;if($stagingHash-cne$stageSummary.inventory_sha256){throw 'Staging inventory hash rejected'}

    $ready=$null;$deadline=[DateTime]::UtcNow.AddSeconds(60)
    while([DateTime]::UtcNow-lt$deadline){
        if(Test-Path -LiteralPath $watchErrorFile-and(Get-Item -LiteralPath $watchErrorFile).Length-ne0){throw 'Mutation watcher emitted readiness error'}
        if(Test-Path -LiteralPath $watchLogFile){$lines=@(Get-WatcherRows $watcher.Process);if(@($lines|Where-Object{$_.kind-ceq'READY'}).Count-eq1){$ready=Assert-WatcherLiveReady $watcher $stagingHash $stageSummary.files;break}}
        if($watcher.Process.HasExited){throw 'Mutation watcher exited before READY'}
        Start-Sleep -Milliseconds 100
    }
    if($null-eq$ready-or-not$ready.all_nlink_one-or-not$ready.device_inode_frozen-or-not$ready.watch_started_before_staging-or-not$ready.parent_watch_active-or$ready.inventory_sha256-cne$stagingHash-or$ready.file_count-ne$stageSummary.files){throw 'Watcher readiness/identity/inventory rejected'}

    $pre=Invoke-Inventory $preInventoryFile "$prefixWsl.pre-inventory.json";$preHash=Get-Sha256 $preInventoryFile
    if($pre.status-cne'INVENTORIED'-or-not$pre.all_nlink_one-or$preHash-cne$pre.sha256-or$preHash-cne$stagingHash){throw 'Pre-execution recursive identity/hash replay rejected'}
    if((ConvertTo-JsonTokenStream ([IO.File]::ReadAllText($stagingInventoryFile,$utf8)))-cne(ConvertTo-JsonTokenStream ([IO.File]::ReadAllText($preInventoryFile,$utf8)))){throw 'Staging and pre-execution inventories differ'}
    [void](Assert-WatcherLiveReady $watcher $preHash $pre.files)

    $timeoutIndex=[Array]::IndexOf($canonical,[string]'/usr/bin/timeout');$bwrapIndex=[Array]::IndexOf($canonical,[string]'/usr/bin/bwrap');$testIndex=$canonical.Count-5
    if($timeoutIndex-ne3-or$bwrapIndex-ne7-or$testIndex-le$bwrapIndex){throw 'Canonical monitor argv boundaries rejected'}
    $resourceCfg=[ordered]@{stop="$prefixWsl.resource-exclusivity.stop";log="$prefixWsl.resource-exclusivity.jsonl";error="$prefixWsl.resource-exclusivity.error.log";watcher_pid=$ready.pid;timeout_argv=@($canonical[$timeoutIndex..($canonical.Count-1)]);bwrap_argv=@($canonical[$bwrapIndex..($canonical.Count-1)]);test_argv=@($canonical[$testIndex..($canonical.Count-1)]);minimum_kib=1900000;target_interval_ms=100;maximum_gap_ms=750;subprocess_sites=16}
    $resourceMonitor=Start-SafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $resourceCfg)) $resourceMonitorSource
    $resourceSequence=0;$resourceDeadline=[DateTime]::UtcNow.AddSeconds(15)
    while([DateTime]::UtcNow-lt$resourceDeadline){
        if($resourceMonitor.Process.HasExited){throw 'Resource monitor exited before READY'}
        if(Test-Path -LiteralPath $resourceErrorFile-and(Get-Item -LiteralPath $resourceErrorFile).Length-ne0){throw 'Resource monitor emitted readiness error'}
        if(Test-Path -LiteralPath $resourceLogFile){try{$resourceSequence=Assert-ResourceMonitorLive $resourceMonitor $resourceSequence;break}catch{if($_.Exception.Message-cnotmatch'readiness grammar|sequence stalled'){throw}}}
        Start-Sleep -Milliseconds 100
    }
    if($resourceSequence-lt1){throw 'Resource monitor did not reach READY with a sample'}

    $plan=[ordered]@{schema='planora.muni-v30.canonical-immutable-plan.v7';run_id=$runId;claim_sha256=(Get-Sha256 $claimFile);runner=[ordered]@{path=$runnerRelative;size=$auth.runner_item.Length;sha256=$runnerHash};authorization=[ordered]@{path=$authorizationRelative;sha256=$authorizationHash};shared_heavy_lock=[ordered]@{path='output/diagnostic-receipts/planora-shared-heavy-wsl.lock';sha256=$lockHash;held_open=$true};snapshot=[ordered]@{host_root=$root;namespace_root='/snapshot';contract_sha256=([BitConverter]::ToString(([Security.Cryptography.SHA256]::Create()).ComputeHash($utf8.GetBytes((ConvertTo-JsonTokenStream $snapshotContractJson))))-replace'-','').ToLowerInvariant();staging_inventory_sha256=$stagingHash;pre_inventory_sha256=$preHash;file_count=$pre.files;all_nlink_one=$pre.all_nlink_one;device_inode_frozen=$ready.device_inode_frozen;watcher_started_before_staging=$ready.watch_started_before_staging;parent_watch_active=$ready.parent_watch_active;staging_events_preserved=$ready.staging_events_preserved;staging_events_sha256=$ready.staging_events_sha256;explicit_read_only_root_bind=$true;synthetic_namespace_root=$true;alternate_host_routes_masked=@('/mnt/c','/mnt/wsl','/run/desktop','/media/host','/media/windows');exact_file_and_directory_set=$true};preflight_samples=@($sample1,$sample2);watcher_ready=$ready;watcher_lifetime='armed_before_staging_through_final_census_lock_release_replays_and_conditional_PASS_publication_then_receipt_bound_shutdown_seal';resource_monitor=[ordered]@{ready=$true;initial_sequence=$resourceSequence;minimum_kib=1900000;target_interval_ms=100;maximum_gap_ms=750;cadence_claim='bounded_maximum_gap_not_exact_interval';descendant_policy='live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace';pinned_subprocess_sites=16};timeouts=[ordered]@{gnu_term_seconds=600;gnu_kill_after_seconds=15;host_wsl_deadline_seconds=$hostDeadlineSeconds;host_termination='taskkill_tree_then_ProcessKill'};canonical_argv=$canonical;canonical_execute_sites=1;automatic_retry=$false;unittest_identity_result_digest='d4dbb5189bcf65870954e5159efbe1ce52208d3b3a0cabc734f7b3f380266afa';official_input=$false;solver=$false;probe=$false;publication=$false}
    $plan.schema='planora.muni-v30.canonical-immutable-plan.v7';$plan.watcher_lifetime='armed_before_staging_through_final_census_lock_release_replays_and_conditional_PASS_publication_then_receipt_bound_shutdown_seal';$plan.snapshot['parent_watch_descriptor']=$ready.parent_watch_descriptor;$plan.snapshot['parent_watch_loss_events']=0;$plan.resource_monitor.descendant_policy='live_ancestry_or_previously_frozen_descendant_identity_with_exact_launch_namespace';$plan['claim_failure_policy']='claim_v2_attempt_marked_before_constructor_default_fail_closed_outer_try_durable_rejection_with_emergency_fallback';$plan['pass_publication_policy']='conditional_receipt_requires_post_publication_authenticated_watcher_shutdown_seal'
    $plan['predecessor_evidence']=$predecessorEvidence;$plan['predecessor_evidence_sha256']=$predecessorEvidenceHash;$plan['predecessor_custody']=[ordered]@{sha256=$predecessorCustodyHash;pin=(Get-LocalEvidencePin $predecessorCustodyFile);archive_pin=$staleArchivePin};$plan['new_lock_verification']='same_held_handle_seek_read_hash_DeleteOnClose'
    Write-NewUtf8 $planFile ($plan|ConvertTo-Json -Depth 15)
    $planHash=Get-Sha256 $planFile

    $replay=Get-AuthorizationState;if($replay.runner_sha256-cne$runnerHash-or$replay.authorization_sha256-cne$authorizationHash){throw 'Final pre-launch self-pin replay rejected'}
    [void](Assert-WatcherLiveReady $watcher $preHash $pre.files)
    $resourceSequence=Assert-ResourceMonitorLive $resourceMonitor $resourceSequence
    $executionHandle=Start-SafeLoggedProcess $wsl $canonical $stdoutFile $stderrFile
    $executionClock=[Diagnostics.Stopwatch]::StartNew()
    try{
        while(-not$executionHandle.Process.HasExited){
            if($executionClock.Elapsed.TotalSeconds-ge$hostDeadlineSeconds){Stop-CanonicalProcess $executionHandle;throw "Canonical outer wsl.exe host deadline exceeded: $hostDeadlineSeconds seconds"}
            $remaining=[long]($hostDeadlineSeconds*1000-$executionClock.ElapsedMilliseconds);$wait=[int][Math]::Max(1,[Math]::Min(250,$remaining));if($executionHandle.Process.WaitForExit($wait)){break}
            if($executionClock.Elapsed.TotalSeconds-ge$hostDeadlineSeconds){Stop-CanonicalProcess $executionHandle;throw "Canonical outer wsl.exe host deadline exceeded: $hostDeadlineSeconds seconds"}
            [void](Assert-WatcherLiveReady $watcher $preHash $pre.files);$resourceSequence=Assert-ResourceMonitorLive $resourceMonitor $resourceSequence
        }
        [void](Assert-WatcherLiveReady $watcher $preHash $pre.files);$resourceSequence=Assert-ResourceMonitorLive $resourceMonitor $resourceSequence
    }catch{try{Stop-CanonicalProcess $executionHandle}catch{};try{[void](Complete-SafeLoggedProcess $executionHandle)}catch{};$executionHandle=$null;throw}
    $execution=Complete-SafeLoggedProcess $executionHandle;$executionHandle=$null
    Write-NewAscii $exitFile "$($execution.ExitCode)`n"
    $resourceSummary=Stop-ResourceMonitor $resourceMonitor;$resourceMonitor=$null

    [void](Assert-WatcherLiveReady $watcher $preHash $pre.files)
    $post=Invoke-Inventory $postInventoryFile "$prefixWsl.post-inventory.json";$postHash=Get-Sha256 $postInventoryFile
    if($post.status-cne'INVENTORIED'-or-not$post.all_nlink_one-or$postHash-cne$post.sha256-or$postHash-cne$preHash){throw 'Post-execution recursive nlink/hash replay rejected'}
    [void](Assert-WatcherLiveReady $watcher $preHash $pre.files)
    $stdout=[IO.File]::ReadAllText($stdoutFile,$utf8);$stderr=[IO.File]::ReadAllText($stderrFile,$utf8)
    $expectedSkips=@{'__main__.RuntimeClosureTests.test_real_sealed_runtime_imports_ortools_without_live_site_packages'='heavy sealed-runtime import probe disabled by test contract';'__main__.SealedImportProbeTests.test_real_chain_reaches_probe_admission_without_opening_inputs'='real sealed chain admission disabled by test contract'}
    if($execution.ExitCode-ne0-or$stdout.Length-ne0){throw 'Canonical exit or stdout rejected'}
    $transcript=Assert-CanonicalUnittestTranscript $stderr 119 117 $expectedSkips 'd4dbb5189bcf65870954e5159efbe1ce52208d3b3a0cabc734f7b3f380266afa'
    [void](Assert-WatcherLiveReady $watcher $postHash $post.files)
    if((Get-AuthorizationState).authorization_sha256-cne$authorizationHash){throw 'Post-run authorization/runner replay rejected'}
    [void](Assert-WatcherLiveReady $watcher $postHash $post.files)

    $preAcceptancePins=@($predecessorPins)+@(@($runnerPath,$authorizationPath,$claimFile,$predecessorCustodyFile,$lockEvidenceFile,$stagingInventoryFile,$preInventoryFile,$postInventoryFile,$staticEvidenceFile,$planFile,$stdoutFile,$stderrFile,$exitFile,$resourceLogFile,$resourceErrorFile,$resourceWrapperOutFile,$resourceWrapperErrFile)|ForEach-Object{Get-LocalEvidencePin $_})
    $acceptance=[ordered]@{schema='planora.muni-v30.canonical-acceptance-commitment.v3';status='CANONICAL_ACCEPTED_PENDING_CLEANUP_NOT_PASS';run_id=$runId;runner_sha256=$runnerHash;authorization_sha256=$authorizationHash;claim_sha256=(Get-Sha256 $claimFile);plan_sha256=$planHash;shared_lock_sha256=$lockHash;staging_inventory_sha256=$stagingHash;pre_inventory_sha256=$preHash;post_inventory_sha256=$postHash;watcher=[ordered]@{phase='READY_PROTECTED';staging_event_count=$ready.staging_event_count;staging_events_sha256=$ready.staging_events_sha256;shutdown_pending=$true};resource_monitor=$resourceSummary;host_deadline=[ordered]@{limit_seconds=$hostDeadlineSeconds;elapsed_milliseconds=$executionClock.ElapsedMilliseconds;expired=$false};evidence_pins=$preAcceptancePins;transcript=$transcript;postflight_census_pending_until_watcher_shutdown=$true;created_at_utc=[DateTime]::UtcNow.ToString('o')}
    $acceptanceJson=$acceptance|ConvertTo-Json -Depth 20;Write-NewUtf8 $acceptanceFile $acceptanceJson;$acceptanceHash=Get-Sha256 $acceptanceFile
    [void](Assert-WatcherLiveReady $watcher $postHash $post.files)

    $watchCleanup=[ordered]@{schema='planora.muni-v30.watcher-cleanup-authorization.v1';run_id=$runId;inventory_sha256=$postHash;acceptance_commitment_sha256=$acceptanceHash;created_at_utc=[DateTime]::UtcNow.ToString('o')};Write-NewUtf8 $watchCleanupFile ($watchCleanup|ConvertTo-Json -Depth 6 -Compress);$watchControlHash=Get-Sha256 $watchCleanupFile
    $watchCleanupReady=$null;$watchCleanupDeadline=[DateTime]::UtcNow.AddSeconds(15)
    while([DateTime]::UtcNow-lt$watchCleanupDeadline){try{$watchCleanupReady=Assert-WatcherLiveCleanupAuthorized $watcher $postHash $post.files $acceptanceHash $watchControlHash;break}catch{if($watcher.Process.HasExited-or(Get-Item -LiteralPath $watchErrorFile).Length-ne0){throw};Start-Sleep -Milliseconds 100}}
    if($null-eq$watchCleanupReady){throw 'Watcher did not authenticate cleanup control'}

    $cleanupCfg=[ordered]@{root=$root;expected="$prefixWsl.post-inventory.json";expected_sha256=$postHash}
    $cleanResult=Invoke-SafeStdinProcess $wsl (Get-PythonStdinTokens (Convert-ConfigToBase64 $cleanupCfg)) $cleanupSource 'verified snapshot cleanup'
    $cleanLines=@($cleanResult.stdout.Trim()-split"`r?`n"|Where-Object{$_});if($cleanLines.Count-ne1-or$cleanResult.stderr.Length-ne0){throw 'Cleanup summary rejected'};$cleanSummary=$cleanLines[0]|ConvertFrom-Json
    if($cleanSummary.status-cne'CLEANUP_PASS'-or-not$cleanSummary.root_absent-or$cleanSummary.deleted_files-ne$post.files){throw 'Verified cleanup result rejected'}
    $snapshotDeleted=$true
    $watchCleaned=$null;$watchCleanedDeadline=[DateTime]::UtcNow.AddSeconds(15)
    while([DateTime]::UtcNow-lt$watchCleanedDeadline){try{$watchCleaned=Assert-WatcherLiveCleaned $watcher $postHash $post.files $acceptanceHash $watchControlHash;break}catch{if($watcher.Process.HasExited-or(Get-Item -LiteralPath $watchErrorFile).Length-ne0){throw};Start-Sleep -Milliseconds 100}}
    if($null-eq$watchCleaned){throw 'Watcher did not attest cleaned protected state'}
    if((Get-AuthorizationState).authorization_sha256-cne$authorizationHash){throw 'Pre-cleanup-receipt self-pin replay rejected'}
    $cleanup=[ordered]@{schema='planora.muni-v30.verified-cleanup.v3';run_id=$runId;acceptance_commitment_sha256=$acceptanceHash;post_inventory_sha256=$postHash;root=$root;exact_files_deleted=$cleanSummary.deleted_files;exact_directories_deleted=$cleanSummary.deleted_directories;root_absent=$cleanSummary.root_absent;cleanup_helper='descriptor_replay_nofollow_device_inode_nlink1_mode_size_sha256';completed_at_utc=[DateTime]::UtcNow.ToString('o')}
    $cleanupJson=$cleanup|ConvertTo-Json -Depth 10;Write-NewUtf8 $cleanupFile $cleanupJson;$cleanupHash=Get-Sha256 $cleanupFile
    if((Get-AuthorizationState).authorization_sha256-cne$authorizationHash){throw 'Final self-pin replay rejected'}
    $protectedPins=@($preAcceptancePins)+@((Get-LocalEvidencePin $acceptanceFile),(Get-LocalEvidencePin $cleanupFile),(Get-LocalEvidencePin $watchCleanupFile))
    [void](Assert-ProtectedEvidenceReplay $watcher $protectedPins $acceptanceJson $cleanupJson $postHash $post.files $expectedSkips 'd4dbb5189bcf65870954e5159efbe1ce52208d3b3a0cabc734f7b3f380266afa' $acceptanceHash $watchControlHash)
    [void](Assert-WatcherLiveCleaned $watcher $postHash $post.files $acceptanceHash $watchControlHash)
    $after=[ordered]@{at_utc=[DateTime]::UtcNow.ToString('o');memavailable_kib=(Get-MemAvailable);census=(Get-WslProcessCensus)};$finalCensus=$after.census
    if(@($finalCensus.rejected_workloads).Count-ne0){throw 'Final WSL census rejected'}
    [void](Assert-WatcherLiveCleaned $watcher $postHash $post.files $acceptanceHash $watchControlHash)
    Release-HeavyLock $lockStream $lockHash 'ACCEPTED_PENDING_FINALIZATION' $acceptanceHash $cleanupHash;$lockStream=$null;$releaseHash=Get-Sha256 $lockReleaseFile
    [void](Assert-WatcherLiveCleaned $watcher $postHash $post.files $acceptanceHash $watchControlHash)
    $publicationPins=@($protectedPins)+@((Get-LocalEvidencePin $lockReleaseFile))
    $publicationReplay=Assert-ProtectedEvidenceReplay $watcher $publicationPins $acceptanceJson $cleanupJson $postHash $post.files $expectedSkips 'd4dbb5189bcf65870954e5159efbe1ce52208d3b3a0cabc734f7b3f380266afa' $acceptanceHash $watchControlHash
    $publicationState=[ordered]@{canonical_exited=$true;watcher_live_cleaned=$true;parent_watch_active=$watchCleaned.cleaned.parent_watch_active;resource_monitor_exited=$true;resource_monitor_clean=$true;snapshot_absent=[bool]$cleanSummary.root_absent;shared_lock_absent=(-not(Test-Path -LiteralPath $sharedLockPath));cleanup_evidence_present=(Test-Path -LiteralPath $cleanupFile);lock_release_evidence_present=(Test-Path -LiteralPath $lockReleaseFile);acceptance_commitment_present=(Test-Path -LiteralPath $acceptanceFile);postflight_census_clean=(@($finalCensus.rejected_workloads).Count-eq0);protected_evidence_replayed=$true}
    [void](Assert-PassPublicationReady ([pscustomobject]$publicationState))
    if((Get-AuthorizationState).authorization_sha256-cne$authorizationHash){throw 'Pre-pass self-pin replay rejected'}
    $receipt=[ordered]@{schema='planora.muni-v30.canonical-immutable-receipt.v7';status='PASS_PUBLISHED_REQUIRES_AUTHENTICATED_POST_PUBLICATION_GUARD_SHUTDOWN_SEAL';run_id=$runId;runner_sha256=$runnerHash;authorization_sha256=$authorizationHash;claim_sha256=(Get-Sha256 $claimFile);plan_sha256=$planHash;acceptance_commitment_sha256=$acceptanceHash;cleanup_sha256=$cleanupHash;lock_release_sha256=$releaseHash;shared_lock_sha256=$lockHash;staging_inventory_sha256=$stagingHash;pre_inventory_sha256=$preHash;post_inventory_sha256=$postHash;all_staged_file_identities_frozen=[ordered]@{watcher_started_before_staging=$watchCleaned.ready.watch_started_before_staging;parent_watch_active_through_publication=$true;parent_watch_descriptor=$watchCleaned.armed.parent_watch_descriptor;parent_watch_loss_events=0;device_inode=$watchCleaned.ready.device_inode_frozen;nlink_one_ready=$watchCleaned.ready.all_nlink_one;nlink_one_after=$post.all_nlink_one;retained_inventory_rows=$true};watcher=[ordered]@{phase_at_publication='CLEANED_LIVE';staging_event_count=$watchCleaned.staging_events;staging_events_sha256=$watchCleaned.ready.staging_events_sha256;cleanup_event_count=$watchCleaned.cleanup_events;cleanup_events_sha256=$watchCleaned.cleaned.cleanup_events_sha256;cleanup_control_sha256=$watchControlHash;publication_guard_live=$true;post_publication_shutdown_seal_required=$true;post_publication_shutdown_seal_path=($passSealFile.Substring($repo.Length+1).Replace('\','/'))};resource_monitor=$resourceSummary;host_deadline=[ordered]@{limit_seconds=$hostDeadlineSeconds;elapsed_milliseconds=$executionClock.ElapsedMilliseconds;expired=$false};protected_publication_replay=$publicationReplay;evidence_pins=$publicationPins;execution=[ordered]@{sites=1;subprocess_sites=16;retries=0;exit_code=$execution.ExitCode;stdout_sha256=(Get-Sha256 $stdoutFile);stderr_sha256=(Get-Sha256 $stderrFile);tests=$transcript.tests;passes=$transcript.passes;skips=$transcript.skips;failures=0;errors=0;identity_result_digest=$transcript.identity_result_digest;exact_skip_identities=@($expectedSkips.Keys|Sort-Object)};postflight=$after;publication_prerequisites=$publicationState;official_input_used=$false;solver_used=$false;probe_used=$false;progress_or_checkpoint_used=$false;publication_used=$false;snapshot_absent_at_pass_publication=$true}
    $archiveReplayAtPass=Assert-FinalArchivedStaleLockIdentity $staleArchivePin 'immediately_before_pass_receipt_publication' $true;$receipt['predecessor_evidence']=$predecessorEvidence;$receipt['predecessor_evidence_sha256']=$predecessorEvidenceHash;$receipt['predecessor_pass_absence_at_publication']=$archiveReplayAtPass.predecessor_pass_absence;$receipt['predecessor_custody_sha256']=$predecessorCustodyHash;$receipt['predecessor_custody_pin']=Get-LocalEvidencePin $predecessorCustodyFile;$receipt['stale_lock_archive_pin']=$staleArchivePin;$receipt['stale_lock_archive_identity_replay']=$archiveReplayAtPass;$receipt['new_lock_verification']='same_held_handle_seek_read_hash_DeleteOnClose'
    $receiptJson=$receipt|ConvertTo-Json -Depth 22;Write-NewUtf8 $receiptFile $receiptJson;$receiptHash=Get-Sha256 $receiptFile;if((ConvertTo-JsonTokenStream ([IO.File]::ReadAllText($receiptFile,$utf8)))-cne(ConvertTo-JsonTokenStream $receiptJson)){throw 'Conditional PASS receipt immediate semantic replay rejected'}
    [void](Assert-WatcherLiveCleaned $watcher $postHash $post.files $acceptanceHash $watchControlHash);if((Get-AuthorizationState).authorization_sha256-cne$authorizationHash){throw 'Post-pass-publication self-pin replay rejected'}
    $postPublicationPins=@($publicationPins)+@((Get-LocalEvidencePin $receiptFile));$postPublicationReplay=Assert-ProtectedEvidenceReplay $watcher $postPublicationPins $acceptanceJson $cleanupJson $postHash $post.files $expectedSkips 'd4dbb5189bcf65870954e5159efbe1ce52208d3b3a0cabc734f7b3f380266afa' $acceptanceHash $watchControlHash
    $postPublicationReplayHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($postPublicationReplay|ConvertTo-Json -Depth 20 -Compress))
    Stop-Watcher $watcher $postHash $acceptanceHash $cleanupHash $postPublicationReplayHash $receiptHash;$watcher=$null;$watchStopHash=Get-Sha256 $watchStopFile
    $watchSummary=Assert-FinalWatcherEvidence $postHash $post.files $acceptanceHash $watchControlHash $watchStopHash $cleanupHash $postPublicationReplayHash $receiptHash
    $finalPins=@($postPublicationPins)+@(@($watchLogFile,$watchErrorFile,$watchWrapperOutFile,$watchWrapperErrFile,$watchStopFile)|ForEach-Object{Get-LocalEvidencePin $_})
    $finalReplay=Assert-FinalEvidenceReplay $finalPins $acceptanceJson $cleanupJson $postHash $post.files $expectedSkips 'd4dbb5189bcf65870954e5159efbe1ce52208d3b3a0cabc734f7b3f380266afa' $acceptanceHash $watchControlHash $watchStopHash $cleanupHash $postPublicationReplayHash $receiptHash
    $archiveReplayBeforeFinalization=Assert-FinalArchivedStaleLockIdentity $staleArchivePin 'after_final_evidence_replay_before_finalization' $true
    $finalState=[ordered]@{canonical_exited=$true;watcher_exited=$true;watcher_clean=$true;resource_monitor_exited=$true;resource_monitor_clean=$true;snapshot_absent=[bool]$watchSummary.done.root_absent;shared_lock_absent=(-not(Test-Path -LiteralPath $sharedLockPath));cleanup_evidence_present=(Test-Path -LiteralPath $cleanupFile);lock_release_evidence_present=(Test-Path -LiteralPath $lockReleaseFile);acceptance_commitment_present=(Test-Path -LiteralPath $acceptanceFile);postflight_census_clean=(@($finalCensus.rejected_workloads).Count-eq0);final_evidence_replayed=$true;pass_receipt_present=(Test-Path -LiteralPath $receiptFile);final_pass_seal_absent_before_publication=(-not(Test-Path -LiteralPath $passSealFile))}
    [void](Assert-FinalizationReady ([pscustomobject]$finalState));if((Get-AuthorizationState).authorization_sha256-cne$authorizationHash){throw 'Pre-final-seal self-pin replay rejected'};$receiptPin=Get-LocalEvidencePin $receiptFile;[void](Assert-LocalEvidencePin $receiptPin)
    $watchLogHash=Get-Sha256 $watchLogFile;$watchWrapperOutHash=Get-Sha256 $watchWrapperOutFile;$watchWrapperErrHash=Get-Sha256 $watchWrapperErrFile;$sealedAtUtc=[DateTime]::UtcNow.ToString('o')
    $terminalArchiveGuard=Open-TerminalArchivedStaleLockGuard $staleArchivePin 'terminal_before_create_only_final_pass_seal';$archiveReplayTerminal=$terminalArchiveGuard.Evidence
    $seal=[ordered]@{schema='planora.muni-v30.pass-publication-shutdown-seal.v2';status='PASS_FOR_FRESH_INDEPENDENT_EVIDENCE_REVIEW_ONLY';run_id=$runId;publication_mechanism='FileMode.CreateNew_write_FlushTrue_as_last_fallible_operation_with_archived_lock_read_guard';pass_receipt_sha256=$receiptHash;pass_receipt_pin=$receiptPin;watcher_shutdown_control_sha256=$watchStopHash;watcher_log_sha256=$watchLogHash;watcher_wrapper_stdout_sha256=$watchWrapperOutHash;watcher_wrapper_stderr_sha256=$watchWrapperErrHash;cleanup_evidence_sha256=$cleanupHash;post_publication_protected_replay_sha256=$postPublicationReplayHash;parent_watch_active_through_pass_publication=$watchSummary.done.parent_watch_active;parent_watch_loss_events=$watchSummary.done.parent_watch_loss_events;root_absent_at_bound_shutdown=$watchSummary.done.root_absent;protected_through_pass_publication=$watchSummary.done.protected_through_pass_publication;finalization_prerequisites=$finalState;final_evidence_replay=$finalReplay;evidence_pins=$finalPins;predecessor_evidence=$predecessorEvidence;predecessor_evidence_sha256=$predecessorEvidenceHash;predecessor_custody_sha256=$predecessorCustodyHash;stale_lock_archive_pin=$staleArchivePin;stale_lock_archive_identity_replay_before_finalization=$archiveReplayBeforeFinalization;terminal_stale_lock_archive_identity_replay=$archiveReplayTerminal;sealed_at_utc=$sealedAtUtc}
    $sealJson=$seal|ConvertTo-Json -Depth 22
    Write-FinalPassSeal $passSealFile $sealJson $terminalArchiveGuard.Stream
}
catch{
    $failure=$_.Exception.Message
    if($null-ne$terminalArchiveGuard){try{$terminalArchiveGuard.Stream.Dispose()}catch{};$terminalArchiveGuard=$null}
    if($null-ne$claimStream){try{$claimStream.Dispose()}catch{};$claimStream=$null}
    if($null-ne$executionHandle){try{Stop-CanonicalProcess $executionHandle}catch{$failure+="; canonical_stop=$($_.Exception.Message)"};try{[void](Complete-SafeLoggedProcess $executionHandle)}catch{$failure+="; canonical_complete=$($_.Exception.Message)"};$executionHandle=$null}
    if($null-ne$resourceMonitor){try{[void](Stop-ResourceMonitor $resourceMonitor)}catch{$failure+="; resource_monitor_stop=$($_.Exception.Message)"};$resourceMonitor=$null}
    if($null-ne$watcher){try{Stop-Watcher $watcher}catch{$failure+="; watcher_stop=$($_.Exception.Message)"};$watcher=$null}
    if($claimPublicationStarted){
        $claimSize=-1L;$claimHash='';$claimReadable=$false;try{$claimItem=Get-Item -LiteralPath $claimFile;$claimSize=$claimItem.Length;$claimHash=Get-Sha256 $claimFile;$claimReadable=$true}catch{$failure+="; claim_replay=$($_.Exception.Message)"}
        $predecessorRejectionReplay=$null;try{$predecessorRejectionReplay=Get-NonThrowingCombinedPredecessorReplay $predecessorEvidence $staleArchivePin}catch{$predecessorRejectionReplay=[ordered]@{phase='rejection_publication';status='REPLAY_HELPER_FAILED';errors=@($_.Exception.Message)}};$predecessorEvidence['rejection_replay']=$predecessorRejectionReplay;$predecessorEvidenceHash=Get-Utf8StringSha256 (ConvertTo-JsonTokenStream ($predecessorEvidence|ConvertTo-Json -Depth 18 -Compress))
        $rejectEvidence=[ordered]@{schema='planora.muni-v30.overall-rejection.v6';status='REJECTED_AUTHORIZATION_CONSUMED';run_id=$runId;failure=$failure;claim_publication_started=$claimPublicationStarted;claim_create_returned=$claimCreateReturned;claim_publication_complete=$claimPublicationComplete;claim_publication_phase=$claimPublicationPhase;claim_readable=$claimReadable;claim_size=$claimSize;claim_sha256=$claimHash;claim_default_fail_closed=$true;pass_receipt_present=(Test-Path -LiteralPath $receiptFile);pass_receipt_sha256=$(if(Test-Path -LiteralPath $receiptFile){Get-Sha256 $receiptFile}else{''});pass_shutdown_seal_absent=(-not(Test-Path -LiteralPath $passSealFile));acceptance_commitment_sha256=$(if(Test-Path -LiteralPath $acceptanceFile){Get-Sha256 $acceptanceFile}else{''});predecessor_evidence=$predecessorEvidence;predecessor_evidence_sha256=$predecessorEvidenceHash;predecessor_custody_sha256=$predecessorCustodyHash;stale_lock_archive_pin=$staleArchivePin;predecessor_rejection_replay=$predecessorRejectionReplay;snapshot_root=$root;snapshot_retained_for_forensics=($snapshotCreated-and-not$snapshotDeleted);recorded_at_utc=[DateTime]::UtcNow.ToString('o')}
        try{Write-NewUtf8 $rejectionFile ($rejectEvidence|ConvertTo-Json -Depth 22 -Compress)}catch{$primaryRejectionFailure=$_.Exception.Message;$emergency=[ordered]@{schema='planora.muni-v30.emergency-rejection.v3';status='REJECTED_AUTHORIZATION_CONSUMED';run_id=$runId;claim_sha256=$claimHash;claim_create_returned=$claimCreateReturned;claim_publication_phase=$claimPublicationPhase;primary_rejection_failure=$primaryRejectionFailure;original_failure=$failure;predecessor_evidence=$predecessorEvidence;predecessor_evidence_sha256=$predecessorEvidenceHash;predecessor_custody_sha256=$predecessorCustodyHash;stale_lock_archive_pin=$staleArchivePin;predecessor_rejection_replay=$predecessorRejectionReplay;recorded_at_utc=[DateTime]::UtcNow.ToString('o')};Write-NewUtf8 $rejectionEmergencyFile ($emergency|ConvertTo-Json -Depth 22 -Compress);$failure+="; primary_rejection=$primaryRejectionFailure; emergency_rejection=$rejectionEmergencyFile"}
    }
    if($null-ne$lockStream){try{Release-HeavyLock $lockStream $lockHash 'REJECTED' $acceptanceHash $cleanupHash; $lockStream=$null}catch{$failure+="; lock_release=$($_.Exception.Message)"}}
    throw $failure
}
