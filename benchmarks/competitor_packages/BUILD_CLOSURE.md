# ITC-2019 competitor build-closure inventory

This layer inventories the toolchains and dependencies implied by the four immutable source archives. It is bound to source-custody binding `c30affdb1a8f7d2866fbdd9b41c38f6cd577f6cc6435b407945ab8c432abc0ec` and build-admission binding `56be3ad100e604ee1e858396d85e692c6a7d3ac809ec8230945c38b2ff45c2c1`.

It does not extract source trees, download packages, compile code, build images, execute competitors, or authorize benchmark claims. Archive tables are checked in memory under path, duplicate, link, type, count, size, encoding, and decompression-ratio limits. Only the nine selected MSBuild, Maven, and Make descriptor bodies are read. Three vendored UniTime JARs are confirmed by member path and size inside the already hash-bound core archive; their bodies are not opened.

## Derived build surfaces

- Gashi is an SDK-style F#/C# solution. The executable targets `netcoreapp2.1`, both libraries target `netstandard2.0`, the only explicit NuGet package is `argu` 5.2.0, and the upstream Makefile requests self-contained `linux-x64`, `win-x64`, and `osx-x64` publishes. A claim-grade Linux build still needs an era-compatible digest-pinned .NET/F# SDK, exact SDK-resolved implicit packages and runtime pack, Argu, the complete restore graph, GNU Make/coreutils if the upstream Makefile is retained, and the Linux native runtime closure.
- UniTime's extension is `org.cpsolver:cpsolver-itc2019:1.0-SNAPSHOT` and depends on the separately pinned `org.unitime:cpsolver:1.4-SNAPSHOT` source archive. The extension compiles at Java 11 and declares resources 3.3.1, jar 3.4.2, and compiler 3.13.0 plugins. The core targets Java 8, declares Log4j Core 2.25.4 and dom4j 2.1.5, ten build plugins, the SCM plugin dependency, and wagon-ftp 2.2. The core archive contains dom4j 2.1.5, Log4j API 2.25.4, and Log4j Core 2.25.4 JAR members. Maven itself, a reviewed JDK, old core plugins, plugin transitives, metadata, and an empty-repository offline resolution receipt remain missing.
- Lemos selects `VERSION=core`, `SOLVERDIR=glucose4.1`, namespace `Glucose`, output `timetabler`, and C++11 with `-O3`. The selected Make path needs GNU Make, g++, binutils, GMP C/C++ headers and runtime, zlib, pthread, glibc, libstdc++, libgcc, a POSIX shell, coreutils/findutils/sed, and a pinned Linux root filesystem. The Glucose 4.1 source is present only as a subtree of the immutable source archive.

## Local availability snapshot

The Windows host exposed mutable .NET 10, Java/Javac 25, Strawberry Perl GCC/G++, CMake, and Ninja installations. NuGet, Maven, GNU Make, and Clang commands were not found. The NuGet cache held only an unrelated `NETStandard.Library` 1.6.1 relevant entry. The Maven cache held the three extension plugin versions, but their files and transitives were not attested; the required core dependencies and old plugin set were absent. Docker's engine was unavailable, so no local image ID or repository digest was observed.

Every host tool and cache observation is classified `mutable-unverified` or `missing`. None is trusted as a closure artifact.

## Replay

Run the verifier without network access:

```powershell
.\.venv\Scripts\python.exe -B -m benchmarks.itc2019_competitor_build_closure
```

The replay must report `build_ready=false`, `claim_grade_ready=false`, and `performance_claims_authorized=false`. It recomputes the policy, predecessor, archive, descriptor, requirement, local-observation, and manifest bindings.

## Next separately authorized work

An independent reviewer should first approve this inventory and parser. A later acquisition task may then select authoritative Linux toolchain/rootfs releases, fetch each required artifact, record exact bytes and SHA-256 values, review licenses/provenance, and resolve NuGet and Maven transitives into content-addressed offline layouts. Network-disabled deterministic recipes and clean-root reproducible builds remain out of scope until that successor closure passes review.
