# External CB-CTT corpus

Planora's external CB-CTT slice contains 34 distinct archived ECTT files from
four institutional families: DDS (7), EasyAcademy (12), Udine (9), and
Erlangen (6). These are distinct source-content SHA-256 values, not repeated
seeds presented as additional instances.

## Immutable source pin

The fetcher resolves the archived Bitbucket origin
`https://bitbucket.org/satt/public-cb-ctt` at revision
`ea30189c5e3a670bc5d27920606d1bd8f820adec`. It verifies that the revision
is the `branch-tip/default` target of immutable snapshot
`swh:1:snp:06781b9cfe1f47ef10619b73d992c96abf267d76` from the origin's
successful Mercurial visit 43. It then verifies that the revision
points to root directory SWHID
`swh:1:dir:befbaef87d7a3bb00d387075515e26be47b95ead`, whose `instances`
entry points to
`swh:1:dir:5df6e8cb61b9b05a3323ab75f48aa9c323178072`. Every selected file is
then checked against its archived length, SHA-1, Git-blob SHA-1, and SHA-256.
This follows Software Heritage's content-addressed identifier and directory
APIs ([SWHID documentation](https://docs.softwareheritage.org/devel/swh-web/uri-scheme-api-swhids.html)).

The pinned archive root has no `LICENSE`, `LICENCE`, or `COPYING` file.
Consequently, Planora does not assert redistribution rights and does not
vendor the source instances. The default cache is under the repository's
ignored `data/` tree, and the fetcher rejects repository-local destinations
outside that tree.

`PROVENANCE.json` records the complete source, selection, projection-loss,
and per-instance evidence. `PROVENANCE.sha256` detects byte-level artifact
tampering, while offline verification also reconstructs and compares all
material provenance fields from the immutable manifest and cached bytes.

## Canonical Erlangen selection

The archived Erlangen directory contains eight `.ectt` files representing six
semesters. Planora selects exactly one canonical source for each semester in
Bellio et al. Table 8: `2011-2`, `2012-1`, `2012-2`, `2013-1`, `2013-2`, and
`2014-1`. The selected six reproduce the Table 3 aggregate ranges exactly:
705-850 courses, 788-930 lectures, 110-176 rooms, 30 periods, and 1,949-3,691
curricula ([Bellio et al.](https://arxiv.org/abs/1409.7186)).

Two alternate reduced-curricula representations are recorded but excluded,
so they cannot be silently counted as additional institutional cases:

- `erlangen-2013-2.ectt`, SHA-256
  `06274217a279930d1839ce238c31dd1a6d2e42cfdcbc69ef169473f750f8dbb2`,
  has archived name `test_instance` and 705 curricula.
- `erlangen-2014-1.ectt`, SHA-256
  `8d8e7f293c66e21231f4201a8669bea97239c0130bfb61cb7afeae55aecc79e9`,
  has archived name `test_instance` and 730 curricula.

Both curriculum counts fall outside the paper's Erlangen range. The complete
selection rule, selected hashes, and excluded-variant hashes are written to
the local `PROVENANCE.json` artifact. The fetcher also downloads these two
alternates into the ignored `excluded-archive-variants/` cache, verifies all
four archived checksums, parses them, and reproduces the archived name and
curriculum counts. They are not projected or counted among the 34 cases.

## Archive revision versus the paper

The selected family names, filenames, and counts agree with Bellio et al.
Tables 7 and 8. The immutable archive revision does not reproduce every
Table 3 extremum, however. The observed differences are:

- DDS courses: paper 50-201; pinned revision 49-217.
- EasyAcademy rooms: paper 12-65; pinned revision 8-65.
- EasyAcademy curricula: paper 12-65; pinned revision 19-65.
- Udine rooms: paper 16-25; pinned revision 16-23.

All other reported course, lecture, room, period, and curriculum ranges agree,
including every Erlangen range used to distinguish its six canonical files.
The provenance records both sides of every comparison. Results must identify
the Software Heritage revision as the evaluated corpus and must not describe
it as a byte-for-byte reconstruction of the paper's unpublished snapshot.

## Explicit four-term projection

ECTT is not treated as interchangeable with the standard ITC-2007
formulation. Planora emits a deliberately lossy projection retaining the four
official soft terms: room capacity, minimum working days, curriculum
compactness, and room stability. Each instance records the excluded ECTT
semantics:

- double-lecture course preferences;
- room-location attributes, including the non-zero subset;
- course-room constraint rows;
- the two daily-load bounds.

Across the pinned 34 files, the current projection evidence records 1,499
double-lecture preferences, 1,446 room-location attributes (324 non-zero),
471,464 course-room constraint rows, and 68 daily-load bound values. These
loss counts are part of the benchmark artifact and must accompany any result
reported on the projections.

## Reproduction

Fetch, verify, parse, and project the corpus:

```bash
.venv/bin/python scripts/fetch_cbctt_corpus.py --timeout-seconds 30 --workers 4
```

Verify the cache without network access:

```bash
.venv/bin/python scripts/fetch_cbctt_corpus.py --verify-only
```

The current immutable source-manifest SHA-256 is
`83d108b89322d46e2ca385652ca6dca4fa9cf569ea5df7bed9e24b4884e47747`.
The deterministic projection-set SHA-256 is
`e98b15921969d234ec5324ab039762d1a7abcfb143a45f331c1469dc0b79a2e8`.

When the official ITC-2007 validator is available, check every projected input
and its independently predictable empty-solution components:

```bash
.venv/bin/python scripts/validate_cbctt_projection_compatibility.py \
  --validator /tmp/planora-itc2007-validator
```

The local official-validator binary with SHA-256
`6b991efa2195ed59f9e514532d9add65b4790791bd6de054ce6f5cbdc19546b3`
accepted all 34 projected inputs and agreed on every independently predicted
empty-solution lecture violation and minimum-working-day component. The probe
hashes every resolvable executable and script artifact in the validator
command and fails closed for interpreter commands whose validator logic is not
a file artifact. This establishes parser compatibility plus agreement for
those two non-zero components only. Its zero baselines do not exercise
conflicts, availability, room occupation, room capacity, curriculum
compactness, or room stability. It is not feasible-solver evidence, full
four-term agreement, ECTT-validator agreement, or a solution-quality
comparison.
