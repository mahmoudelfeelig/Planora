# ITC-2019 public-mirror evidence

## Claim boundary

Planora has a deterministic, non-vendoring ingestion layer for the 36 ITC-2019
problem XML files and 18 output XML files present in the public
[`ADDALemos/MPPTimetables`](https://github.com/ADDALemos/MPPTimetables)
finalist repository. The source is pinned to commit
[`c33d15797686a27c192eabb90948baa54d3ddef5`](https://github.com/ADDALemos/MPPTimetables/tree/c33d15797686a27c192eabb90948baa54d3ddef5)
and root tree `85d223752d27d041e1f8f9cf3d869ed232628f3b`.

This is public-repository-mirror evidence. It is not a download from the
authenticated ITC-2019 instance portal, and local validation is not official
validator agreement.

## Immutable source descriptor

`benchmarks/itc2019_corpus.py` contains exact repository-relative paths, byte
lengths, Git blob SHA-1 identifiers, and SHA-256 content hashes for every XML.
The canonical 54-row descriptor SHA-256 is
`d4e8e694892c11d8c7ebb998feccd404ddcd2b5cc60a3780ed808b7eca2a35bb`.

The descriptor covers:

- 36 distinct problem contents: 6 test, 10 early, 10 middle, and 10 late
  instances, matching the names published on the official
  [test](https://www.itc2019.org/test-instances),
  [early](https://www.itc2019.org/early-instances),
  [middle](https://www.itc2019.org/middle-instances), and
  [late](https://www.itc2019.org/late-instances) pages;
- 18 distinct output contents found in the pinned mirror;
- 323,538,608 XML bytes in total;
- the repository `LICENSE` and `README.md`, each pinned by path, byte length,
  Git blob SHA-1, and SHA-256.

The repository root contains an MIT license. No separate upstream dataset
license was identified, so Planora checks in metadata only. XML, README, and
license bytes remain in the ignored
`data/external/itc2019-mpp-c33d15797686/` cache. This is a conservative storage
policy, not a legal conclusion about upstream dataset rights.

## Reproduction

Fetch the immutable commit, verify the GitHub commit and root-tree metadata,
hash-check all 56 cached files, then run parsing and local validation:

```bash
.venv/bin/python scripts/fetch_itc2019_public_corpus.py \
  --report output/itc2019-public-corpus/report.json
```

Repeat the byte verification and semantic analysis without network access:

```bash
.venv/bin/python scripts/fetch_itc2019_public_corpus.py \
  --verify-only \
  --report output/itc2019-public-corpus/report.json
```

The full report includes every validation error and a SHA-256 of each ordered
error list. A successful command means the source pin, cache, parser, and stated
local checks executed. It does not mean that every mirrored input or output is
valid.

The GitHub mirror is not the effective competition corpus for two middle
instances. The organizers withdrew and replaced `muni-pdf-spr16` and
`pu-d5-spr17`. Planora keeps the immutable mirror manifest for provenance and a
separate effective-competition overlay for the corrected organizer bytes:

- `muni-pdf-spr16`: SHA-256
  `72e851f204de6a74841ac998ecba71ef2a5a913578f5020f9be26d8f62bf9933`;
- `pu-d5-spr17`: SHA-256
  `8bdaf9d09a736f1fe8b202c29b270a9351fbc99cb7737d4abc34944f074e1547`.

The effective manifest SHA-256 is
`1ca1558f69d3a9be60ae44dcc2661f440fe6679b13754b709c491a889ff91f3a`.
Competition runs fail closed if either withdrawn mirror hash is present. The
organizer correction notice is
[archived in the ITC-2019 group](https://groups.google.com/g/itc-2019/c/Fr9ijWWhY-Q).
`verify_cached_itc2019_competition_corpus` verifies the mirror evidence and the
two corrected local inputs as one effective, hash-bound corpus.

## Observed problem conversion

Fresh verification on 2026-08-11 produced this exact result:

- all 36 files are well-formed XML and were structurally inspected;
- 34 pass Planora's strict semantic parser;
- 2 are rejected, without normalization, because the mirror contains a
  negative meeting length.

The rejected rows are:

| Instance | Class | Class limit | Preserved anomalous time |
| --- | ---: | ---: | --- |
| `pu-c8-spr07` | `1338` | `0` | `days=1000000`, `start=228`, `length=-2`, `weeks=100000000000000`, `penalty=0` |
| `pu-llr-spr07` | `448` | `0` | `days=1000000`, `start=228`, `length=-2`, `weeks=100000000000000`, `penalty=0` |

The official [format description](https://www.itc2019.org/format) defines
meeting length as a duration used to compute class end times; it does not
document a negative sentinel. Planora therefore fails closed instead of
silently changing `-2` to another duration. This leaves semantic conversion at
34/36 for this particular mirror, with exact evidence for the two residual
source anomalies.

## Observed output classification

All 18 output XML files parse as solution XML. Twelve pass the currently
implemented local hard-placement and student-sectioning scope:

`agh-fis-spr17`, `agh-ggis-spr17`, `agh-ggos-spr17`, `lums-fal17`,
`lums-spr18`, `lums-sum17`, `mary-fal18`, `muni-fi-spr17`,
`pu-llr-spr17`, `tg-fal17`, `tg-spr18`, and `yach-fal17`.

Six fail locally with these exact error counts:

| Instance | Local errors | Classification |
| --- | ---: | --- |
| `mary-spr17` | 3,666 | one duplicate-class-enrollment error for each of 3,666 students |
| `muni-fi-spr16` | 1,543 | one duplicate-class-enrollment error for each of 1,543 students |
| `muni-fsps-spr17` | 865 | one duplicate-class-enrollment error for each of 865 students |
| `muni-fsps-spr17c` | 395 | one duplicate-class-enrollment error for each of 395 students |
| `muni-pdf-spr16` | 26 | 1 duplicate-class-enrollment error and 25 class-limit overruns |
| `wbg-fal10` | 28 | 1 incomplete-placement error, 3 out-of-domain times, 1 missing-students error, 4 unrequested-course errors, and 19 configuration-selection errors; the file contains only 3 of 150 classes and 4 of 19 students |

The mirror README describes `solution-*` files as prerequisite original
solutions for minimal-perturbation runs. They are therefore classified as
mirror baseline candidates, not assumed competition submissions. The tiny
`wbg-fal10.xml` output reproduces the official format's illustrative three-class
solution shape and is not a complete solution for the mirrored 150-class
problem.

During this audit, the local validator was corrected to follow the official
[ITC-2019 FAQ](https://www.itc2019.org/faq): a room listed in a class domain is
already considered suitable, so neither class limit nor assigned enrollment is
compared with the informational room capacity. The 12 passing results above use
that corrected rule.

## What local validation proves

For the 12 passing files, Planora checked complete class placement, time and
room domain membership, room unavailability, room collisions, course
configuration selection, one class per selected subpart, parent linkage, and
class enrollment limits.

It did not check required or soft distribution constraints. It did not
reproduce time, room, distribution, student, or total objective values. The
official [rules](https://www.itc2019.org/rules) and
[FAQ](https://www.itc2019.org/faq) route validation through authenticated
website upload; that external validation was not available in this run.
Consequently:

- `12/18 locally valid for implemented scope` must not be restated as
  `12 official valid solutions`;
- this corpus does not establish official-validator agreement;
- distribution and objective conversion remain open research and release
  gates;
- the two negative-duration inputs prevent an honest 36/36 strict semantic
  conversion claim for this mirror.
