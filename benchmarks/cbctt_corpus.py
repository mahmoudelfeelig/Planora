from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from benchmarks.cbctt import (
    CBCTT_ARCHIVE_DIRECTORY_SWHID,
    CBCTT_ARCHIVE_ORIGIN,
    CBCTT_ARCHIVE_REVISION,
    CBCTT_ARCHIVE_REVISION_SWHID,
    CBCTT_INSTANCES_DIRECTORY_SWHID,
    parse_cbctt_ectt,
    project_cbctt_to_itc2007,
    render_projected_itc2007_ctt,
)
from benchmarks.itc2007 import parse_itc2007_ctt, run_itc2007_validator


SWH_API_BASE_URL = "https://archive.softwareheritage.org/api/1"
CBCTT_CORPUS_SCHEMA = "planora.cbctt-external-corpus.v2"
CBCTT_ARCHIVE_ORIGIN_VISIT = 43
CBCTT_ARCHIVE_ORIGIN_VISIT_TYPE = "hg"
CBCTT_ARCHIVE_SNAPSHOT_SWHID = "swh:1:snp:06781b9cfe1f47ef10619b73d992c96abf267d76"
CBCTT_ARCHIVE_SNAPSHOT_BRANCH = "branch-tip/default"
CBCTT_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
CBCTT_DEFAULT_CACHE = (
    CBCTT_REPOSITORY_ROOT / "data" / "external" / f"cbctt-{CBCTT_ARCHIVE_REVISION[:12]}"
)


class CBCTTArchiveError(RuntimeError):
    """Raised when the pinned archive or local cache fails verification."""


@dataclass(frozen=True, order=True)
class CBCTTArchiveFile:
    family: str
    filename: str
    length: int
    sha1_git: str
    sha1: str
    sha256: str

    @property
    def relative_path(self) -> str:
        return f"{self.family}/{self.filename}"

    @property
    def content_swhid(self) -> str:
        return f"swh:1:cnt:{self.sha1_git}"


@dataclass(frozen=True)
class CBCTTArchivePin:
    origin: str
    revision: str
    revision_swhid: str
    root_directory_swhid: str
    instances_directory_swhid: str
    origin_visit: int
    origin_visit_type: str
    snapshot_swhid: str
    snapshot_branch: str
    family_directory_swhids: Mapping[str, str]
    root_license_filenames: tuple[str, ...]
    files: tuple[CBCTTArchiveFile, ...]
    excluded_variants: tuple[CBCTTExcludedArchiveVariant, ...] = ()


@dataclass(frozen=True)
class CBCTTExcludedArchiveVariant:
    archive_file: CBCTTArchiveFile
    archived_problem_name: str
    archived_curricula: int
    reason: str


def _file(
    family: str,
    filename: str,
    length: int,
    sha1_git: str,
    sha1: str,
    sha256: str,
) -> CBCTTArchiveFile:
    return CBCTTArchiveFile(
        family=family,
        filename=filename,
        length=length,
        sha1_git=sha1_git,
        sha1=sha1,
        sha256=sha256,
    )


CBCTT_FAMILY_DIRECTORY_SWHIDS: dict[str, str] = {
    "DDS": "swh:1:dir:3eb7fe6be23e4ce768605cc9716af12ee713d4c6",
    "EasyAcademy": "swh:1:dir:a6e36d3283bc8356487572ffe7f64a4f6c9e36ff",
    "Erlangen": "swh:1:dir:6379103439704ae9f68231d22558e8683ff45d85",
    "Udine": "swh:1:dir:e1c3fe971dacfc83f95961b0cdb92664feb81a5f",
}

CBCTT_BELLIO_TABLE_3_RANGES: dict[str, dict[str, int | list[int]]] = {
    "DDS": {
        "instances": 7,
        "courses_range": [50, 201],
        "lectures_range": [146, 972],
        "rooms_range": [8, 31],
        "periods_range": [25, 75],
        "curricula_range": [9, 105],
    },
    "EasyAcademy": {
        "instances": 12,
        "courses_range": [50, 159],
        "lectures_range": [139, 688],
        "rooms_range": [12, 65],
        "periods_range": [25, 72],
        "curricula_range": [12, 65],
    },
    "Erlangen": {
        "instances": 6,
        "courses_range": [705, 850],
        "lectures_range": [788, 930],
        "rooms_range": [110, 176],
        "periods_range": [30, 30],
        "curricula_range": [1949, 3691],
    },
    "Udine": {
        "instances": 9,
        "courses_range": [62, 152],
        "lectures_range": [201, 400],
        "rooms_range": [16, 25],
        "periods_range": [25, 25],
        "curricula_range": [54, 101],
    },
}


CBCTT_CORPUS_FILES: tuple[CBCTTArchiveFile, ...] = (
    _file(
        "DDS",
        "DDS1.ectt",
        189005,
        "fe1e6dd2f387cf74dd0851e942c38ea2cb6cd7d6",
        "c8a2a387b8e90f2c46657027b01ed4f6cc5e5339",
        "0aa3f987efbb6d60520e3e73b576ba171c764a7be6a037257e181082a5736528",
    ),
    _file(
        "DDS",
        "DDS2.ectt",
        49926,
        "cf213dc8fdec7bc61b3faaf328c28ad005819ea9",
        "2e0b898810829a42b9fb5532ccc21bd9f8d75103",
        "e3829e3bad55759be532914d69ed12cd80beaefafc9d0ce3bd79356fca45be4b",
    ),
    _file(
        "DDS",
        "DDS3.ectt",
        15614,
        "6d9ec101f3f4d01fbbdd2e931b53c6d6a2fe794c",
        "6f9491d13c3deaf2160e9b649350a3756a9fb8eb",
        "f288d12d9bc50bf22ca86e880f8542b634a8b9469534021dc73d64939fa0e0b5",
    ),
    _file(
        "DDS",
        "DDS4.ectt",
        41102,
        "1562cdfc05c7f039dcab635c6f62db4c47fd554c",
        "5e9f55f57235844b0356e75315a018e42989383d",
        "b3ffcdb36b955fc5f069bb48c6dc6ec04145eed56cbc2e17c6d5d472cbb3521e",
    ),
    _file(
        "DDS",
        "DDS5.ectt",
        46852,
        "aeb01f86097cf2d632a09dce550e8522579a0544",
        "156096bbe10168270ae2986ab849d75f2834c6c7",
        "601f0eedd24db64b8cfb7decb3e02cdc16cf8b30ab90acbc6daec8f3da91b009",
    ),
    _file(
        "DDS",
        "DDS6.ectt",
        13280,
        "5ecae7ae8336b07a48fac6af1d69e54e94e8a11b",
        "3a829171d85bbdc32a6840118bf30dc68ed4b292",
        "5985c78aafc5c20c42bbfbc1aae182b4ade31aafdbae3e537427b3a77df9c3df",
    ),
    _file(
        "DDS",
        "DDS7.ectt",
        8773,
        "f226a4a656900a6a0ac967f943fc6632f37328ae",
        "11d39d76986bec381d044fc17e900aa223bfc372",
        "d238c30c2ccca35ce0f079c9b99fa5d3aab99293bff492d748d6d1d458b4d466",
    ),
    _file(
        "EasyAcademy",
        "EA01.ectt",
        4916,
        "6bef889dccfc12390620adf48d70890a09f40511",
        "c6546c333cf7280bc9586aa7e7d1642c5bd1287e",
        "9e37a52e803b673e299e710323a8e5bbfc31fc46b4a8b96b215c2d3dd8c1bb8e",
    ),
    _file(
        "EasyAcademy",
        "EA02.ectt",
        13462,
        "876e1b3c5c84c0aea25a35a1bea72ca16954513f",
        "898e2115986d4b4c46853afcd24f85a86a353abe",
        "3cb391a59e6732c49753e7fb2fd288735d21c7ad35adf28b5c99b0d077927e97",
    ),
    _file(
        "EasyAcademy",
        "EA03.ectt",
        46919,
        "9667aaf08078eec805426a2a02bac12b941fecd4",
        "0ef2a788fd2db0a598f4c2b46f1a5d68c47a6d76",
        "6925d7457ac2cf1d18de3fe5dc2c5fffddbec58138b211f17184ef0a87964d6f",
    ),
    _file(
        "EasyAcademy",
        "EA04.ectt",
        4233,
        "9dee33d6f7d89af8237bcb2a94e57a3bdce3358b",
        "cca745963036075d78a4a423b71b3f584126232e",
        "199b7a5253012098fd68aa4c6011e0667bd03286427e47381d036374a6b657a6",
    ),
    _file(
        "EasyAcademy",
        "EA05.ectt",
        21723,
        "69d0066d2f69553af82e8a05a725129d5fc11227",
        "8c79ca96dc6502a5f943e76926897066c738a26d",
        "93a855d518f9c98dd38beeb500d77f19e0bfab5517742f1024b2390cac0ff56c",
    ),
    _file(
        "EasyAcademy",
        "EA06.ectt",
        9831,
        "eb3b44756d51a616bbd6e3197157be81b1392dbd",
        "ed28961c4cfe7f9ab0ecb401eb1dc41516e78a3f",
        "d0790c5c8750bb5f522f12ec1ca1b89d6ef7cc43e330a174966885954236ef67",
    ),
    _file(
        "EasyAcademy",
        "EA07.ectt",
        27579,
        "cb18f15e8e29b1988ea2a7489f1b4ebae9faecc0",
        "ec11371114bed511c17cea59be4b9dd67c4479b0",
        "033855e1fe7193b56d4e28e2758ea333e7ec10a46a6072def8a44b715a4edefb",
    ),
    _file(
        "EasyAcademy",
        "EA08.ectt",
        4630,
        "837b0ff3be158f90d76efde368a1e01f3d1af098",
        "60ed20025b4fd39d63d819422f1243653e96c396",
        "0d046ddebd0801e3ef9612254da0657fa6e03c6da23314d3e97c693f3d238314",
    ),
    _file(
        "EasyAcademy",
        "EA09.ectt",
        24341,
        "6da7c677046dfe9f93cc7f4b03501c8dca987b33",
        "f2f8c35f05305b47ca88431e30400b31c65edfd3",
        "41d04f22e1fe5c025687e6730a279afe4b4fd414dd417629644916dd4d9dc9a5",
    ),
    _file(
        "EasyAcademy",
        "EA10.ectt",
        15523,
        "bb097278d286469234707eb17181464fa1ea923d",
        "3e871931e93d05ddcf8de1078e40255a1bbee92e",
        "06ce52bd1cc6f0ee6530659179dd6d6b8af735df7f50bf3e23eff6e86e727fb0",
    ),
    _file(
        "EasyAcademy",
        "EA11.ectt",
        10774,
        "309e2df1c4ab999193e7a99212344b1d942276b3",
        "0adbdc62aba1db4fc8d05370879404565d3fc2a9",
        "c338bb5e9b5c42ac12ecce0af23023eb5b0f78b0dd30a597774cacce281ecf1f",
    ),
    _file(
        "EasyAcademy",
        "EA12.ectt",
        10043,
        "dfb1511f50f4d8ac76bf07b3a41561fd5f60826b",
        "35b635693cf3b34e2ecda6120c658fa10524b9b7",
        "f2a50e197de02a48d17fcab66b3b30a8143ecad43e6775228a6401d114eefe05",
    ),
    _file(
        "Erlangen",
        "erlangen2011_2.ectt",
        2061309,
        "fb1a3cb917dea546b43ade0195e40f50eefa3cec",
        "6e6b42f3aff4927022f7521935c9ff41d3948b12",
        "c5345d8c635ddec50c2cc8807b29150d15433986157ece665593612d05bdb006",
    ),
    _file(
        "Erlangen",
        "erlangen2012_1.ectt",
        1203785,
        "4efc392aa5ad107d812ffa09ac04d42a0931ebcb",
        "c9de0d6e8abc63a116d068378320f59ef55e3c73",
        "78cadd9a0d52a353bf44fd561d5c218a126be0531533ef3c020f91c419d44525",
    ),
    _file(
        "Erlangen",
        "erlangen2012_2.ectt",
        1671080,
        "61b5aad5716220ec148318a05385c8dd51593be8",
        "e0facc188d5b9cf31591f158b16a2b6c6b35fadc",
        "a5d35192086a686bd87a73a2b4e1caa779f394f70eb62faff817a03540c61694",
    ),
    _file(
        "Erlangen",
        "erlangen2013_1.ectt",
        1530124,
        "96c9db9ed4100b29877d46c07dbcf02eff51bf3f",
        "e6dcbfd5180311ada3a5e75c71373c2326cc6cbc",
        "e7a9d695decc26318fcdc1afadc9b411578b908326261f9e0a925ac89d16df18",
    ),
    _file(
        "Erlangen",
        "erlangen2013_2.ectt",
        1465864,
        "613c53f67576d106b6f1abaaa7cac67099732373",
        "52c78fea871646a3ca643fb09016a496c1007456",
        "9fdaf0724d20bb73a8d3b677a1e2c1f192847dc16801e8823d6d5384d31d3953",
    ),
    _file(
        "Erlangen",
        "erlangen2014_1.ectt",
        1489458,
        "00e9e704a6754b7d9846586f5f76b38fe402a45d",
        "9a1407a8bc1f84cdf9043dcaa51fc47931320371",
        "27e2e204dc892623a26af813b28edc73e4ff86ac1fa9e4c55ea414bc677712ae",
    ),
    _file(
        "Udine",
        "Udine1.ectt",
        19399,
        "54591acad1cd89be4698f3bc7e438273e5121ae7",
        "b158b9caebde7b1abd4ff9dff936613c13f379b7",
        "fdeaba7c2627968cc8e2981ea5a7467021a3d35bed5a7dfc1638953d37879b28",
    ),
    _file(
        "Udine",
        "Udine2.ectt",
        19896,
        "9c79111660a1bbea46c9f5219c3b2f899ea4fe57",
        "da7381475ed27cdcd83a97ea64c706ae92196b4c",
        "0389d0433aed9c9ac55a28b42a38528133507e7718d7e522f4f23504e5bc0a09",
    ),
    _file(
        "Udine",
        "Udine3.ectt",
        10872,
        "178fd10edd7dee2cd96f861dd01eb51b3c437311",
        "29fabda538c3d015163ae1245caf587992d9d243",
        "bf952e4c101842dd68fdaa83fd735382493d5e687f8079f386f48c2ab8e6cc8e",
    ),
    _file(
        "Udine",
        "Udine4.ectt",
        8835,
        "1b6ec067da71880fdda3f83d2fc7076f6d15e23f",
        "c47366bed1dff6e44532ab06ad5a41506184b918",
        "49d61e11ba29ee2852299a905d35c2778b8765e2e75231e5a57aa1607296206f",
    ),
    _file(
        "Udine",
        "Udine5.ectt",
        12057,
        "1371f3b39b2a133c12cb54a448401036206b8470",
        "a11525a47b98c0c4a3f28bc6ab3158c5d813f47f",
        "1cf7c1ed459c89d89a68569a33e71410723b08c9b6cd89a2c37166ad4ce79b61",
    ),
    _file(
        "Udine",
        "Udine6.ectt",
        15206,
        "c266d600f863cc71975dbd78597ae91d33e24e4c",
        "8345eda3190ce72534936a9d072cdeb4387b0147",
        "3c6ec296fb87459defbaba4827395a2b01324cc427cf18421ba2e4105a6912e6",
    ),
    _file(
        "Udine",
        "Udine7.ectt",
        15234,
        "28e2fb53a076cd52b455fbb5201656e7e234ed5e",
        "43fc071407ee86efa00494fc0bac5a7487f8b09a",
        "7f43aa78c90a96c43b663346d937e6ccb92a2442e55d169255357596202034d4",
    ),
    _file(
        "Udine",
        "Udine8.ectt",
        17231,
        "066aa20fce4a01097dc12350fb3fa817334b547e",
        "00e3e62fea3a2d5a8050f9c1283be7970197f698",
        "4e4b13e4476dded680af2e607c175334ae0f98529e6c4eb51a77f24cee3d99b6",
    ),
    _file(
        "Udine",
        "Udine9.ectt",
        17295,
        "0119209ed5939d1f3504cda61f07247995d3f2fb",
        "fcb33c2935ea8dda518b82a115659890db4c09d8",
        "f29fe51e9a65acd82a678d1097bb61fe9c57b88684b5110af4539d9bc0b94f78",
    ),
)


CBCTT_EXCLUDED_ARCHIVE_VARIANTS: tuple[CBCTTExcludedArchiveVariant, ...] = (
    CBCTTExcludedArchiveVariant(
        archive_file=_file(
            "Erlangen",
            "erlangen-2013-2.ectt",
            815149,
            "007741fbc79801d50f75b5653cf2a70ca3ee497a",
            "732bd0819d2fec2000fe19da286a679450f362fe",
            "06274217a279930d1839ce238c31dd1a6d2e42cfdcbc69ef169473f750f8dbb2",
        ),
        archived_problem_name="test_instance",
        archived_curricula=705,
        reason=(
            "Alternate reduced-curricula representation for semester 2013-2; "
            "its 705 curricula fall outside the 1,949-3,691 Erlangen range in "
            "Bellio et al. Table 3."
        ),
    ),
    CBCTTExcludedArchiveVariant(
        archive_file=_file(
            "Erlangen",
            "erlangen-2014-1.ectt",
            867917,
            "c22830c3bb54b054c82484bd548d2bd07b9510a6",
            "ac3dea7e3a753cf72ba257ec724ae6b6905a1131",
            "8d8e7f293c66e21231f4201a8669bea97239c0130bfb61cb7afeae55aecc79e9",
        ),
        archived_problem_name="test_instance",
        archived_curricula=730,
        reason=(
            "Alternate reduced-curricula representation for semester 2014-1; "
            "its 730 curricula fall outside the 1,949-3,691 Erlangen range in "
            "Bellio et al. Table 3."
        ),
    ),
)


CBCTT_ARCHIVE_PIN = CBCTTArchivePin(
    origin=CBCTT_ARCHIVE_ORIGIN,
    revision=CBCTT_ARCHIVE_REVISION,
    revision_swhid=CBCTT_ARCHIVE_REVISION_SWHID,
    root_directory_swhid=CBCTT_ARCHIVE_DIRECTORY_SWHID,
    instances_directory_swhid=CBCTT_INSTANCES_DIRECTORY_SWHID,
    origin_visit=CBCTT_ARCHIVE_ORIGIN_VISIT,
    origin_visit_type=CBCTT_ARCHIVE_ORIGIN_VISIT_TYPE,
    snapshot_swhid=CBCTT_ARCHIVE_SNAPSHOT_SWHID,
    snapshot_branch=CBCTT_ARCHIVE_SNAPSHOT_BRANCH,
    family_directory_swhids=CBCTT_FAMILY_DIRECTORY_SWHIDS,
    root_license_filenames=(),
    files=CBCTT_CORPUS_FILES,
    excluded_variants=CBCTT_EXCLUDED_ARCHIVE_VARIANTS,
)

FetchBytes = Callable[[str, float], bytes]


def _swh_object_id(swhid: str, expected_kind: str) -> str:
    prefix = f"swh:1:{expected_kind}:"
    if not swhid.startswith(prefix):
        raise ValueError(f"Expected a {expected_kind} SWHID, got {swhid!r}")
    object_id = swhid.removeprefix(prefix)
    if len(object_id) != 40 or any(
        char not in "0123456789abcdef" for char in object_id
    ):
        raise ValueError(f"Malformed {expected_kind} SWHID: {swhid!r}")
    return object_id


def _default_fetch_bytes(url: str, timeout_seconds: float) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/json, application/octet-stream;q=0.9",
            "User-Agent": "Planora-CBCTT-reproducibility-fetcher/1.0",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        return response.read()


def _fetch_with_retries(
    fetch_bytes: FetchBytes,
    url: str,
    timeout_seconds: float,
    *,
    attempts: int = 3,
) -> bytes:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return fetch_bytes(url, timeout_seconds)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.25 * (2**attempt))
    raise CBCTTArchiveError(
        f"Could not retrieve pinned archive URL {url}: {last_error}"
    )


def _load_json(
    fetch_bytes: FetchBytes,
    url: str,
    timeout_seconds: float,
) -> Any:
    payload = _fetch_with_retries(fetch_bytes, url, timeout_seconds)
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CBCTTArchiveError(
            f"Archive endpoint returned invalid JSON: {url}"
        ) from exc


def _entries_by_name(payload: Any, *, context: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(payload, list):
        raise CBCTTArchiveError(f"{context} must be a Software Heritage directory list")
    result: dict[str, Mapping[str, Any]] = {}
    for row in payload:
        if not isinstance(row, Mapping) or not isinstance(row.get("name"), str):
            raise CBCTTArchiveError(f"{context} contains a malformed directory entry")
        name = str(row["name"])
        if name in result:
            raise CBCTTArchiveError(f"{context} contains duplicate entry {name!r}")
        result[name] = row
    return result


def _verify_manifest_shape(pin: CBCTTArchivePin) -> None:
    revision_id = _swh_object_id(pin.revision_swhid, "rev")
    if pin.revision != revision_id:
        raise ValueError(
            "CB-CTT revision and revision SWHID identify different objects"
        )
    _swh_object_id(pin.snapshot_swhid, "snp")
    if pin.origin_visit <= 0:
        raise ValueError("CB-CTT origin visit must be positive")
    if not pin.origin_visit_type or not pin.snapshot_branch:
        raise ValueError("CB-CTT origin visit type and snapshot branch are required")
    if len(pin.root_license_filenames) != len(set(pin.root_license_filenames)):
        raise ValueError("CB-CTT root license filenames must be unique")
    if not pin.files:
        raise ValueError("CB-CTT archive pin must include files")
    paths = [row.relative_path for row in pin.files]
    if len(paths) != len(set(paths)):
        raise ValueError("CB-CTT archive pin contains duplicate relative paths")
    if len({row.sha256 for row in pin.files}) != len(pin.files):
        raise ValueError("CB-CTT archive pin does not identify distinct file contents")
    excluded_paths = [row.archive_file.relative_path for row in pin.excluded_variants]
    if len(excluded_paths) != len(set(excluded_paths)):
        raise ValueError("CB-CTT archive pin contains duplicate excluded variants")
    overlap = sorted(set(paths) & set(excluded_paths))
    if overlap:
        raise ValueError(f"Selected and excluded CB-CTT paths overlap: {overlap}")
    archived_rows = [*pin.files, *(row.archive_file for row in pin.excluded_variants)]
    for row in archived_rows:
        if row.family not in pin.family_directory_swhids:
            raise ValueError(f"Missing family directory pin for {row.family}")
        if Path(row.filename).name != row.filename or row.filename in {".", ".."}:
            raise ValueError(f"Unsafe archived filename: {row.filename!r}")
        if Path(row.family).name != row.family or row.family in {".", ".."}:
            raise ValueError(f"Unsafe archived family: {row.family!r}")
        if row.length <= 0:
            raise ValueError(
                f"Archived file length must be positive: {row.relative_path}"
            )
        for algorithm, digest, expected_length in (
            ("sha1_git", row.sha1_git, 40),
            ("sha1", row.sha1, 40),
            ("sha256", row.sha256, 64),
        ):
            if len(digest) != expected_length or any(
                char not in "0123456789abcdef" for char in digest
            ):
                raise ValueError(
                    f"Malformed {algorithm} for archived file {row.relative_path}"
                )


def _validate_archive_metadata(
    pin: CBCTTArchivePin,
    *,
    fetch_bytes: FetchBytes,
    timeout_seconds: float,
) -> dict[str, object]:
    _verify_manifest_shape(pin)
    root_id = _swh_object_id(pin.root_directory_swhid, "dir")
    instances_id = _swh_object_id(pin.instances_directory_swhid, "dir")
    snapshot_id = _swh_object_id(pin.snapshot_swhid, "snp")

    encoded_origin = quote(pin.origin, safe="")
    origin_url = f"{SWH_API_BASE_URL}/origin/{encoded_origin}/get/"
    origin = _load_json(fetch_bytes, origin_url, timeout_seconds)
    visit_types = origin.get("visit_types") if isinstance(origin, Mapping) else None
    if (
        not isinstance(origin, Mapping)
        or origin.get("url") != pin.origin
        or not isinstance(visit_types, list)
        or pin.origin_visit_type not in visit_types
    ):
        raise CBCTTArchiveError(
            "Pinned Software Heritage origin does not expose the expected visit type"
        )

    visit_url = f"{SWH_API_BASE_URL}/origin/{encoded_origin}/visit/{pin.origin_visit}/"
    visit = _load_json(fetch_bytes, visit_url, timeout_seconds)
    wanted_visit = {
        "origin": pin.origin,
        "visit": pin.origin_visit,
        "status": "full",
        "snapshot": snapshot_id,
        "type": pin.origin_visit_type,
    }
    if not isinstance(visit, Mapping) or any(
        visit.get(key) != value for key, value in wanted_visit.items()
    ):
        raise CBCTTArchiveError(
            "Pinned Software Heritage origin visit does not resolve to the "
            "expected full snapshot"
        )

    snapshot_url = f"{SWH_API_BASE_URL}/snapshot/{snapshot_id}/"
    snapshot = _load_json(fetch_bytes, snapshot_url, timeout_seconds)
    if not isinstance(snapshot, Mapping) or snapshot.get("id") != snapshot_id:
        raise CBCTTArchiveError("Pinned Software Heritage snapshot is malformed")
    branches = snapshot.get("branches")
    branch = (
        branches.get(pin.snapshot_branch) if isinstance(branches, Mapping) else None
    )
    if (
        not isinstance(branch, Mapping)
        or branch.get("target_type") != "revision"
        or branch.get("target") != pin.revision
    ):
        raise CBCTTArchiveError(
            "Pinned Software Heritage origin snapshot branch does not resolve "
            "to the expected revision"
        )

    revision_url = f"{SWH_API_BASE_URL}/revision/{pin.revision}/"
    revision = _load_json(fetch_bytes, revision_url, timeout_seconds)
    if not isinstance(revision, Mapping):
        raise CBCTTArchiveError("Pinned revision response is not an object")
    if revision.get("id") != pin.revision or revision.get("directory") != root_id:
        raise CBCTTArchiveError(
            "Pinned revision does not resolve to the expected root directory SWHID"
        )

    root_url = f"{SWH_API_BASE_URL}/directory/{root_id}/"
    root_entries = _entries_by_name(
        _load_json(fetch_bytes, root_url, timeout_seconds),
        context="Pinned CB-CTT root",
    )
    instances_entry = root_entries.get("instances")
    if (
        instances_entry is None
        or instances_entry.get("type") != "dir"
        or instances_entry.get("target") != instances_id
    ):
        raise CBCTTArchiveError(
            "Pinned root does not contain the expected instances directory SWHID"
        )

    instances_url = f"{SWH_API_BASE_URL}/directory/{instances_id}/"
    instances_entries = _entries_by_name(
        _load_json(fetch_bytes, instances_url, timeout_seconds),
        context="Pinned CB-CTT instances directory",
    )
    for family, family_swhid in pin.family_directory_swhids.items():
        expected_id = _swh_object_id(family_swhid, "dir")
        archived = instances_entries.get(family)
        if (
            archived is None
            or archived.get("type") != "dir"
            or archived.get("target") != expected_id
        ):
            raise CBCTTArchiveError(
                f"Pinned instances directory does not match family {family}"
            )

    family_payloads: dict[str, dict[str, Mapping[str, Any]]] = {}
    for family, family_swhid in pin.family_directory_swhids.items():
        family_id = _swh_object_id(family_swhid, "dir")
        family_url = f"{SWH_API_BASE_URL}/directory/{family_id}/"
        family_payloads[family] = _entries_by_name(
            _load_json(fetch_bytes, family_url, timeout_seconds),
            context=f"Pinned CB-CTT family {family}",
        )

    expected_ectt_names: dict[str, set[str]] = {
        family: set() for family in pin.family_directory_swhids
    }
    for row in [*pin.files, *(item.archive_file for item in pin.excluded_variants)]:
        expected_ectt_names[row.family].add(row.filename)
    archived_ectt_names = {
        family: sorted(
            name
            for name, entry in entries.items()
            if name.casefold().endswith(".ectt") and entry.get("type") == "file"
        )
        for family, entries in family_payloads.items()
    }
    for family, expected_names in expected_ectt_names.items():
        observed_names = set(archived_ectt_names[family])
        if observed_names != expected_names:
            raise CBCTTArchiveError(
                f"Pinned archive ECTT selection is incomplete for {family}: "
                f"expected={sorted(expected_names)}, observed={sorted(observed_names)}"
            )

    archived_files = [
        *pin.files,
        *(row.archive_file for row in pin.excluded_variants),
    ]
    for expected in archived_files:
        archived = family_payloads[expected.family].get(expected.filename)
        if archived is None or archived.get("type") != "file":
            raise CBCTTArchiveError(
                f"Pinned archive is missing {expected.relative_path}"
            )
        checksums = archived.get("checksums")
        if not isinstance(checksums, Mapping):
            raise CBCTTArchiveError(
                f"Pinned archive omitted checksums for {expected.relative_path}"
            )
        observed = {
            "length": archived.get("length"),
            "sha1_git": checksums.get("sha1_git"),
            "sha1": checksums.get("sha1"),
            "sha256": checksums.get("sha256"),
        }
        wanted = {
            "length": expected.length,
            "sha1_git": expected.sha1_git,
            "sha1": expected.sha1,
            "sha256": expected.sha256,
        }
        if observed != wanted or archived.get("target") != expected.sha1_git:
            raise CBCTTArchiveError(
                f"Pinned archive metadata mismatch for {expected.relative_path}: "
                f"expected={wanted}, observed={observed}"
            )

    license_names = sorted(
        name
        for name in root_entries
        if name.casefold().startswith(("license", "licence", "copying"))
    )
    if license_names != sorted(pin.root_license_filenames):
        raise CBCTTArchiveError(
            "Pinned archive root license-file inventory changed: "
            f"expected={sorted(pin.root_license_filenames)}, "
            f"observed={license_names}"
        )
    return {
        "origin_api_url": origin_url,
        "origin_visit_api_url": visit_url,
        "snapshot_api_url": snapshot_url,
        "revision_api_url": revision_url,
        "root_directory_api_url": root_url,
        "instances_directory_api_url": instances_url,
        "archived_family_ectt_filenames": archived_ectt_names,
        "root_license_filenames": license_names,
    }


def _hashes(data: bytes) -> dict[str, str | int]:
    git_header = f"blob {len(data)}\0".encode("ascii")
    return {
        "length": len(data),
        "sha1_git": hashlib.sha1(git_header + data).hexdigest(),  # noqa: S324
        "sha1": hashlib.sha1(data).hexdigest(),  # noqa: S324
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _verify_bytes(data: bytes, expected: CBCTTArchiveFile) -> None:
    observed = _hashes(data)
    wanted: dict[str, str | int] = {
        "length": expected.length,
        "sha1_git": expected.sha1_git,
        "sha1": expected.sha1,
        "sha256": expected.sha256,
    }
    if observed != wanted:
        raise CBCTTArchiveError(
            f"Content hash mismatch for {expected.relative_path}: "
            f"expected={wanted}, observed={observed}"
        )


def _atomic_write(path: Path, data: bytes, *, cache_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    resolved_root = cache_root.resolve()
    try:
        path.parent.resolve().relative_to(resolved_root)
    except ValueError as exc:
        raise CBCTTArchiveError(f"Cache path escapes its root: {path}") from exc
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _ensure_non_vendored_cache(cache_directory: Path) -> Path:
    cache = cache_directory.expanduser().resolve()
    try:
        relative = cache.relative_to(CBCTT_REPOSITORY_ROOT)
    except ValueError:
        return cache
    if not relative.parts or relative.parts[0] != "data":
        raise ValueError(
            "A repository-local CB-CTT cache must be under the ignored data/ tree"
        )
    return cache


def _source_manifest_sha256(files: Sequence[CBCTTArchiveFile]) -> str:
    rows = [
        {
            "relative_path": row.relative_path,
            "sha256": row.sha256,
            "sha1_git": row.sha1_git,
            "length": row.length,
        }
        for row in sorted(files)
    ]
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _fetch_one_archive_file(
    cache: Path,
    expected: CBCTTArchiveFile,
    *,
    storage_directory: str,
    fetch_bytes: FetchBytes,
    timeout_seconds: float,
) -> tuple[CBCTTArchiveFile, bool]:
    destination = cache / storage_directory / expected.family / expected.filename
    if destination.is_file():
        current = destination.read_bytes()
        try:
            _verify_bytes(current, expected)
            return expected, True
        except CBCTTArchiveError:
            pass
    raw_url = f"{SWH_API_BASE_URL}/content/sha1_git:{expected.sha1_git}/raw/"
    data = _fetch_with_retries(fetch_bytes, raw_url, timeout_seconds)
    _verify_bytes(data, expected)
    _atomic_write(destination, data, cache_root=cache)
    return expected, False


def _fetch_one_source(
    cache: Path,
    expected: CBCTTArchiveFile,
    *,
    fetch_bytes: FetchBytes,
    timeout_seconds: float,
) -> tuple[CBCTTArchiveFile, bool]:
    return _fetch_one_archive_file(
        cache,
        expected,
        storage_directory="raw",
        fetch_bytes=fetch_bytes,
        timeout_seconds=timeout_seconds,
    )


def _fetch_one_excluded_variant(
    cache: Path,
    expected: CBCTTArchiveFile,
    *,
    fetch_bytes: FetchBytes,
    timeout_seconds: float,
) -> tuple[CBCTTArchiveFile, bool]:
    return _fetch_one_archive_file(
        cache,
        expected,
        storage_directory="excluded-archive-variants",
        fetch_bytes=fetch_bytes,
        timeout_seconds=timeout_seconds,
    )


def _inspect_excluded_variants(
    cache: Path,
    pin: CBCTTArchivePin,
) -> list[dict[str, object]]:
    observations: list[dict[str, object]] = []
    for expected in pin.excluded_variants:
        archived = expected.archive_file
        source = (
            cache / "excluded-archive-variants" / archived.family / archived.filename
        )
        if not source.is_file():
            raise CBCTTArchiveError(
                f"Excluded archive variant is missing from the local cache: {source}"
            )
        _verify_bytes(source.read_bytes(), archived)
        problem = parse_cbctt_ectt(source)
        observed_name = problem.name
        observed_curricula = len(problem.curricula)
        if (
            observed_name != expected.archived_problem_name
            or observed_curricula != expected.archived_curricula
        ):
            raise CBCTTArchiveError(
                "Excluded archive variant evidence mismatch for "
                f"{archived.relative_path}: expected name/curricula="
                f"{expected.archived_problem_name!r}/{expected.archived_curricula}, "
                f"observed={observed_name!r}/{observed_curricula}"
            )
        observations.append(
            {
                **asdict(archived),
                "relative_path": archived.relative_path,
                "cached_relative_path": (
                    f"excluded-archive-variants/{archived.relative_path}"
                ),
                "content_swhid": archived.content_swhid,
                "observed_problem_name": observed_name,
                "observed_curricula": observed_curricula,
                "reason": expected.reason,
            }
        )
    return observations


def _project_one(
    cache: Path,
    expected: CBCTTArchiveFile,
    *,
    write_projection: bool,
) -> dict[str, object]:
    source = cache / "raw" / expected.family / expected.filename
    _verify_bytes(source.read_bytes(), expected)
    ectt = parse_cbctt_ectt(source)
    projection = project_cbctt_to_itc2007(ectt)
    projected_relative = f"{expected.family}/{Path(expected.filename).stem}.ctt"
    projected = cache / "projected-itc2007" / projected_relative
    rendered = render_projected_itc2007_ctt(projection).encode("utf-8")
    if write_projection:
        _atomic_write(projected, rendered, cache_root=cache)
    elif not projected.is_file() or projected.read_bytes() != rendered:
        raise CBCTTArchiveError(
            f"Cached projection is missing or does not match source: {projected}"
        )
    round_trip = parse_itc2007_ctt(projected)
    if round_trip != projection.problem:
        raise CBCTTArchiveError(
            f"Projected ITC-2007 round trip changed {expected.relative_path}"
        )
    return {
        "family": expected.family,
        "source_relative_path": f"raw/{expected.relative_path}",
        "source_content_swhid": expected.content_swhid,
        "source_length": expected.length,
        "source_sha1": expected.sha1,
        "source_sha1_git": expected.sha1_git,
        "source_sha256": expected.sha256,
        "projected_relative_path": f"projected-itc2007/{projected_relative}",
        "projected_sha256": hashlib.sha256(rendered).hexdigest(),
        "projection": projection.to_dict(),
        "problem": {
            "name": ectt.name,
            "courses": len(ectt.courses),
            "rooms": len(ectt.rooms),
            "days": ectt.days,
            "periods_per_day": ectt.periods_per_day,
            "periods": ectt.days * ectt.periods_per_day,
            "curricula": len(ectt.curricula),
            "lectures": sum(course.lectures for course in ectt.courses),
            "unavailability_rows": len(ectt.unavailability),
            "room_constraint_rows": len(ectt.room_constraints),
        },
    }


def _projection_set_sha256(records: Sequence[Mapping[str, object]]) -> str:
    rows = [
        {
            "projected_relative_path": row["projected_relative_path"],
            "projected_sha256": row["projected_sha256"],
        }
        for row in records
    ]
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _canonical_selection_evidence(
    pin: CBCTTArchivePin,
    records: Sequence[Mapping[str, object]],
    excluded_observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if not pin.excluded_variants:
        return {
            "rule": "All files in the supplied archive pin are selected.",
            "excluded_archive_variants": [],
        }
    if set(pin.family_directory_swhids) != set(CBCTT_BELLIO_TABLE_3_RANGES):
        return {
            "rule": (
                "Select all files in the supplied custom archive pin and retain "
                "locally reproduced evidence for explicitly excluded variants."
            ),
            "excluded_archive_variants": list(excluded_observations),
        }

    features = ("courses", "lectures", "rooms", "periods", "curricula")
    archive_observed: dict[str, dict[str, int | list[int]]] = {}
    for family in sorted(CBCTT_BELLIO_TABLE_3_RANGES):
        family_records = [row for row in records if row.get("family") == family]
        observed: dict[str, int | list[int]] = {"instances": len(family_records)}
        for feature in features:
            values: list[int] = []
            for row in family_records:
                problem = row.get("problem")
                if not isinstance(problem, Mapping):
                    raise CBCTTArchiveError(
                        "Missing projected problem feature evidence"
                    )
                values.append(int(problem[feature]))
            if values:
                observed[f"{feature}_range"] = [min(values), max(values)]
        archive_observed[family] = observed

    count_mismatches = {
        family: {
            "paper": expected["instances"],
            "archive_revision": archive_observed[family]["instances"],
        }
        for family, expected in CBCTT_BELLIO_TABLE_3_RANGES.items()
        if archive_observed[family]["instances"] != expected["instances"]
    }
    if count_mismatches:
        raise CBCTTArchiveError(
            "Selected CB-CTT family counts do not reproduce Bellio et al. "
            f"Tables 3, 7, and 8: {count_mismatches}"
        )

    discrepancies: list[dict[str, object]] = []
    for family, expected in CBCTT_BELLIO_TABLE_3_RANGES.items():
        observed = archive_observed[family]
        for feature in (f"{name}_range" for name in features):
            if observed.get(feature) != expected.get(feature):
                discrepancies.append(
                    {
                        "family": family,
                        "feature": feature,
                        "paper_table_3": expected[feature],
                        "pinned_archive_revision": observed.get(feature),
                    }
                )

    expected_erlangen = CBCTT_BELLIO_TABLE_3_RANGES["Erlangen"]
    observed_erlangen = archive_observed["Erlangen"]
    if observed_erlangen != expected_erlangen:
        raise CBCTTArchiveError(
            "Selected Erlangen files do not reproduce Bellio et al. Table 3: "
            f"expected={expected_erlangen}, observed={observed_erlangen}"
        )

    for row in excluded_observations:
        if not isinstance(row, Mapping):
            raise CBCTTArchiveError("Malformed excluded-variant evidence")
        if not row.get("source_sha256") and not row.get("sha256"):
            raise CBCTTArchiveError("Excluded-variant evidence omits its SHA-256")

    selected_filenames = {
        family: sorted(
            str(row["source_relative_path"]).split("/", 2)[-1]
            for row in records
            if row.get("family") == family
        )
        for family in sorted(CBCTT_BELLIO_TABLE_3_RANGES)
    }
    return {
        "rule": (
            "Select the DDS, EasyAcademy, and Udine filenames enumerated in "
            "Bellio et al. Table 7. For Erlangen, select one canonical ECTT "
            "source for each of the six Table 8 semesters and require the "
            "selected family to reproduce the Table 3 feature ranges. Do not "
            "count alternate representations of the same semesters as new "
            "instances."
        ),
        "selected_filenames": selected_filenames,
        "paper_evidence": {
            "citation": (
                "R. Bellio et al., Feature-based tuning of simulated annealing "
                "applied to the curriculum-based course timetabling problem"
            ),
            "url": "https://arxiv.org/abs/1409.7186",
            "table_3_reported_ranges": CBCTT_BELLIO_TABLE_3_RANGES,
            "pinned_archive_revision_observed_ranges": archive_observed,
            "archive_vs_table_3_discrepancies": discrepancies,
            "interpretation": (
                "Family names and instance counts match Tables 7 and 8. The "
                "pinned archive revision differs from four Table 3 extrema; "
                "these differences are reported rather than silently corrected."
            ),
            "table_8_semesters": [
                "2011-2",
                "2012-1",
                "2012-2",
                "2013-1",
                "2013-2",
                "2014-1",
            ],
        },
        "excluded_archive_variants": list(excluded_observations),
    }


def _extension_loss_totals(
    records: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    totals: Counter[str] = Counter()
    for record in records:
        projection = record.get("projection")
        if not isinstance(projection, Mapping):
            raise CBCTTArchiveError("Projected record omits projection evidence")
        losses = projection.get("extension_losses")
        if not isinstance(losses, Mapping):
            raise CBCTTArchiveError("Projected record omits extension-loss evidence")
        totals.update({str(key): int(value) for key, value in losses.items()})
    return dict(sorted(totals.items()))


def _static_archive_evidence(pin: CBCTTArchivePin) -> dict[str, object]:
    encoded_origin = quote(pin.origin, safe="")
    snapshot_id = _swh_object_id(pin.snapshot_swhid, "snp")
    root_id = _swh_object_id(pin.root_directory_swhid, "dir")
    instances_id = _swh_object_id(pin.instances_directory_swhid, "dir")
    archived_names: dict[str, list[str]] = {
        family: [] for family in pin.family_directory_swhids
    }
    for row in [*pin.files, *(item.archive_file for item in pin.excluded_variants)]:
        archived_names[row.family].append(row.filename)
    return {
        "origin_api_url": f"{SWH_API_BASE_URL}/origin/{encoded_origin}/get/",
        "origin_visit_api_url": (
            f"{SWH_API_BASE_URL}/origin/{encoded_origin}/visit/{pin.origin_visit}/"
        ),
        "snapshot_api_url": f"{SWH_API_BASE_URL}/snapshot/{snapshot_id}/",
        "revision_api_url": f"{SWH_API_BASE_URL}/revision/{pin.revision}/",
        "root_directory_api_url": f"{SWH_API_BASE_URL}/directory/{root_id}/",
        "instances_directory_api_url": (
            f"{SWH_API_BASE_URL}/directory/{instances_id}/"
        ),
        "archived_family_ectt_filenames": {
            family: sorted(names) for family, names in archived_names.items()
        },
        "root_license_filenames": sorted(pin.root_license_filenames),
    }


def _validate_cached_provenance(
    cache: Path,
    pin: CBCTTArchivePin,
    records: Sequence[Mapping[str, object]],
    selection_evidence: Mapping[str, object],
) -> str:
    provenance_path = cache / "PROVENANCE.json"
    digest_path = cache / "PROVENANCE.sha256"
    if not provenance_path.is_file() or not digest_path.is_file():
        raise CBCTTArchiveError(
            "Cached corpus provenance or its SHA-256 sidecar is missing"
        )
    provenance_bytes = provenance_path.read_bytes()
    observed_digest = hashlib.sha256(provenance_bytes).hexdigest()
    recorded_digest = digest_path.read_text(encoding="ascii").strip()
    if recorded_digest != observed_digest:
        raise CBCTTArchiveError(
            "Cached corpus provenance SHA-256 sidecar does not match PROVENANCE.json"
        )
    try:
        provenance = json.loads(provenance_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CBCTTArchiveError("Cached corpus provenance is not valid JSON") from exc
    if not isinstance(provenance, Mapping):
        raise CBCTTArchiveError("Cached corpus provenance must be a JSON object")

    expected_source = {
        "origin": pin.origin,
        "revision": pin.revision,
        "revision_swhid": pin.revision_swhid,
        "root_directory_swhid": pin.root_directory_swhid,
        "instances_directory_swhid": pin.instances_directory_swhid,
        "origin_visit": pin.origin_visit,
        "origin_visit_type": pin.origin_visit_type,
        "snapshot_swhid": pin.snapshot_swhid,
        "snapshot_branch": pin.snapshot_branch,
        "family_directory_swhids": dict(pin.family_directory_swhids),
        "api_base_url": SWH_API_BASE_URL,
        **_static_archive_evidence(pin),
    }
    expected_licensing = {
        "root_license_filenames": sorted(pin.root_license_filenames),
        "status": "no_license_file_in_pinned_archive_root",
        "redistribution_rights": "not_established",
        "storage_policy": "ignored_local_cache_only_not_vendored",
    }
    expected_corpus = {
        "distinct_instance_files": len(pin.files),
        "distinct_sha256_contents": len({row.sha256 for row in pin.files}),
        "families": dict(sorted(Counter(row.family for row in pin.files).items())),
        "source_manifest_sha256": _source_manifest_sha256(pin.files),
        "projection_set_sha256": _projection_set_sha256(records),
        "projection_scope": "standard_itc2007_four_term_only",
        "extension_loss_totals": _extension_loss_totals(records),
        "official_validator_status": "not_run_by_fetcher",
        "excluded_archive_variant_files": len(pin.excluded_variants),
        "excluded_variant_manifest_sha256": _source_manifest_sha256(
            [row.archive_file for row in pin.excluded_variants]
        ),
    }
    checks = {
        "schema_version": CBCTT_CORPUS_SCHEMA,
        "cache_directory": str(cache),
        "source": expected_source,
        "licensing": expected_licensing,
        "corpus": expected_corpus,
        "selection": dict(selection_evidence),
        "instances": list(records),
    }
    for key, expected in checks.items():
        if provenance.get(key) != expected:
            raise CBCTTArchiveError(
                f"Cached corpus provenance field {key!r} does not match the "
                "pinned sources and regenerated projections"
            )
    return observed_digest


def fetch_cbctt_corpus(
    cache_directory: str | Path = CBCTT_DEFAULT_CACHE,
    *,
    pin: CBCTTArchivePin = CBCTT_ARCHIVE_PIN,
    timeout_seconds: float = 30.0,
    workers: int = 4,
    fetch_bytes: FetchBytes | None = None,
) -> dict[str, object]:
    """Fetch, hash-check, parse, and project the pinned 34-instance corpus.

    Source files and generated projections remain in a local ignored cache.
    The pinned archive snapshot has no root license file, so this function does
    not copy either dataset into the repository's tracked source tree and does
    not assert redistribution rights.
    """

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if workers <= 0:
        raise ValueError("workers must be positive")
    cache = _ensure_non_vendored_cache(Path(cache_directory))
    cache.mkdir(parents=True, exist_ok=True)
    downloader = fetch_bytes or _default_fetch_bytes
    archive_evidence = _validate_archive_metadata(
        pin,
        fetch_bytes=downloader,
        timeout_seconds=timeout_seconds,
    )

    with ThreadPoolExecutor(max_workers=min(workers, len(pin.files))) as executor:
        cache_results = list(
            executor.map(
                lambda expected: _fetch_one_source(
                    cache,
                    expected,
                    fetch_bytes=downloader,
                    timeout_seconds=timeout_seconds,
                ),
                pin.files,
            )
        )
    excluded_files = tuple(row.archive_file for row in pin.excluded_variants)
    excluded_cache_results: list[tuple[CBCTTArchiveFile, bool]] = []
    if excluded_files:
        with ThreadPoolExecutor(
            max_workers=min(workers, len(excluded_files))
        ) as executor:
            excluded_cache_results = list(
                executor.map(
                    lambda expected: _fetch_one_excluded_variant(
                        cache,
                        expected,
                        fetch_bytes=downloader,
                        timeout_seconds=timeout_seconds,
                    ),
                    excluded_files,
                )
            )
    excluded_observations = _inspect_excluded_variants(cache, pin)
    records = [
        _project_one(cache, expected, write_projection=True)
        for expected in sorted(pin.files)
    ]
    family_counts = dict(sorted(Counter(row.family for row in pin.files).items()))
    loss_totals = _extension_loss_totals(records)
    selection_evidence = _canonical_selection_evidence(
        pin,
        records,
        excluded_observations,
    )

    report: dict[str, object] = {
        "schema_version": CBCTT_CORPUS_SCHEMA,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "cache_directory": str(cache),
        "source": {
            "origin": pin.origin,
            "revision": pin.revision,
            "revision_swhid": pin.revision_swhid,
            "root_directory_swhid": pin.root_directory_swhid,
            "instances_directory_swhid": pin.instances_directory_swhid,
            "origin_visit": pin.origin_visit,
            "origin_visit_type": pin.origin_visit_type,
            "snapshot_swhid": pin.snapshot_swhid,
            "snapshot_branch": pin.snapshot_branch,
            "family_directory_swhids": dict(pin.family_directory_swhids),
            "api_base_url": SWH_API_BASE_URL,
            **archive_evidence,
        },
        "licensing": {
            "root_license_filenames": archive_evidence["root_license_filenames"],
            "status": "no_license_file_in_pinned_archive_root",
            "redistribution_rights": "not_established",
            "storage_policy": "ignored_local_cache_only_not_vendored",
        },
        "corpus": {
            "distinct_instance_files": len(pin.files),
            "distinct_sha256_contents": len({row.sha256 for row in pin.files}),
            "families": family_counts,
            "source_manifest_sha256": _source_manifest_sha256(pin.files),
            "projection_set_sha256": _projection_set_sha256(records),
            "projection_scope": "standard_itc2007_four_term_only",
            "extension_loss_totals": loss_totals,
            "official_validator_status": "not_run_by_fetcher",
            "excluded_archive_variant_files": len(excluded_observations),
            "excluded_variant_manifest_sha256": _source_manifest_sha256(excluded_files),
        },
        "selection": selection_evidence,
        "cache": {
            "reused_verified_source_files": sum(reused for _, reused in cache_results),
            "downloaded_source_files": sum(not reused for _, reused in cache_results),
            "reused_verified_excluded_variant_files": sum(
                reused for _, reused in excluded_cache_results
            ),
            "downloaded_excluded_variant_files": sum(
                not reused for _, reused in excluded_cache_results
            ),
        },
        "instances": records,
    }
    provenance_bytes = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    _atomic_write(cache / "PROVENANCE.json", provenance_bytes, cache_root=cache)
    provenance_sha256 = hashlib.sha256(provenance_bytes).hexdigest()
    _atomic_write(
        cache / "PROVENANCE.sha256",
        f"{provenance_sha256}\n".encode("ascii"),
        cache_root=cache,
    )
    return report


def verify_cached_cbctt_corpus(
    cache_directory: str | Path = CBCTT_DEFAULT_CACHE,
    *,
    pin: CBCTTArchivePin = CBCTT_ARCHIVE_PIN,
) -> dict[str, object]:
    """Verify cached source hashes and deterministic four-term projections."""

    _verify_manifest_shape(pin)
    cache = _ensure_non_vendored_cache(Path(cache_directory))
    records: list[dict[str, object]] = []
    for expected in sorted(pin.files):
        source = cache / "raw" / expected.family / expected.filename
        if not source.is_file():
            raise CBCTTArchiveError(f"Cached source file is missing: {source}")
        _verify_bytes(source.read_bytes(), expected)
        record = _project_one(cache, expected, write_projection=False)
        records.append(record)
    excluded_observations = _inspect_excluded_variants(cache, pin)
    selection_evidence = _canonical_selection_evidence(
        pin,
        records,
        excluded_observations,
    )
    provenance_sha256 = _validate_cached_provenance(
        cache,
        pin,
        records,
        selection_evidence,
    )
    return {
        "schema_version": CBCTT_CORPUS_SCHEMA,
        "cache_directory": str(cache),
        "distinct_instance_files": len(records),
        "distinct_sha256_contents": len({row.sha256 for row in pin.files}),
        "families": dict(sorted(Counter(row.family for row in pin.files).items())),
        "source_manifest_sha256": _source_manifest_sha256(pin.files),
        "projection_set_sha256": _projection_set_sha256(records),
        "provenance_sha256": provenance_sha256,
        "excluded_archive_variant_files": len(excluded_observations),
        "excluded_variant_manifest_sha256": _source_manifest_sha256(
            [row.archive_file for row in pin.excluded_variants]
        ),
        "selection": selection_evidence,
        "instances": records,
    }


def _validator_command_artifacts(
    command: Sequence[str],
) -> tuple[list[dict[str, object]], str, str]:
    artifacts: list[dict[str, object]] = []
    for index, token in enumerate(command):
        candidate_token = token.split("=", 1)[1] if "=" in token else token
        candidate = Path(candidate_token).expanduser()
        resolved: Path | None = None
        if candidate.is_file():
            resolved = candidate.resolve()
        elif index == 0:
            executable = shutil.which(token)
            if executable is not None and Path(executable).is_file():
                resolved = Path(executable).resolve()
        elif (
            "/" in candidate_token
            or "\\" in candidate_token
            or candidate.suffix.casefold() in {".exe", ".jar", ".js", ".py", ".sh"}
        ):
            raise CBCTTArchiveError(
                f"Validator command artifact cannot be resolved: argv[{index}]={token!r}"
            )
        if resolved is None:
            continue
        data = resolved.read_bytes()
        artifacts.append(
            {
                "argv_index": index,
                "argv_token": token,
                "resolved_path": str(resolved),
                "length": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    if not artifacts or artifacts[0]["argv_index"] != 0:
        raise CBCTTArchiveError(
            "Validator executable provenance cannot be resolved to a local file"
        )
    executable_name = Path(str(artifacts[0]["resolved_path"])).name.casefold()
    if executable_name in {"docker", "docker.exe", "podman", "podman.exe"}:
        raise CBCTTArchiveError(
            "Containerized validator commands are rejected because a runtime "
            "executable hash does not establish the validator image provenance"
        )
    interpreter = executable_name.startswith(
        ("python", "pypy", "java", "node", "bash", "sh", "pwsh", "powershell")
    )
    if interpreter and len(artifacts) == 1:
        raise CBCTTArchiveError(
            "Interpreter-based validator provenance is unresolved; provide the "
            "validator script or archive as a file argument"
        )
    primary = artifacts[-1] if interpreter else artifacts[0]
    canonical = json.dumps(
        {"command": list(command), "artifacts": artifacts},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return artifacts, str(primary["sha256"]), hashlib.sha256(canonical).hexdigest()


def validate_cbctt_projection_compatibility(
    validator_command: str | Path | Sequence[str | Path],
    cache_directory: str | Path = CBCTT_DEFAULT_CACHE,
    *,
    pin: CBCTTArchivePin = CBCTT_ARCHIVE_PIN,
    timeout_seconds: float = 30.0,
) -> dict[str, object]:
    """Check every projected input with the official validator's parser.

    The probe intentionally supplies an empty solution. Exact agreement on the
    resulting lecture violations and minimum-working-day cost demonstrates
    input/parser compatibility and those two non-zero components only. It is
    not a feasible-solver run, an ECTT validation, full four-term agreement, or
    a quality comparison.
    """

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if isinstance(validator_command, (str, Path)):
        command = [str(validator_command)]
    else:
        command = [str(part) for part in validator_command]
    if not command:
        raise ValueError("validator_command must not be empty")
    validator_artifacts, validator_sha256, command_manifest_sha256 = (
        _validator_command_artifacts(command)
    )

    cache = _ensure_non_vendored_cache(Path(cache_directory))
    verification = verify_cached_cbctt_corpus(cache, pin=pin)
    records: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="planora-cbctt-validator-") as temporary:
        empty_solution = Path(temporary) / "empty.out"
        empty_solution.write_bytes(b"")
        for expected in sorted(pin.files):
            relative = f"{expected.family}/{Path(expected.filename).stem}.ctt"
            projected = cache / "projected-itc2007" / relative
            problem = parse_itc2007_ctt(projected)
            result = run_itc2007_validator(
                command,
                projected,
                empty_solution,
                timeout_seconds=timeout_seconds,
            )
            expected_lectures = sum(course.lectures for course in problem.courses)
            expected_minimum_days = 5 * sum(
                course.minimum_working_days for course in problem.courses
            )
            observed = {
                "lecture_violations": result.lecture_violations,
                "conflict_violations": result.conflict_violations,
                "availability_violations": result.availability_violations,
                "room_occupation_violations": result.room_occupation_violations,
                "room_capacity": result.room_capacity,
                "minimum_working_days": result.minimum_working_days,
                "curriculum_compactness": result.curriculum_compactness,
                "room_stability": result.room_stability,
                "total_cost": result.total_cost,
            }
            wanted = {
                "lecture_violations": expected_lectures,
                "conflict_violations": 0,
                "availability_violations": 0,
                "room_occupation_violations": 0,
                "room_capacity": 0,
                "minimum_working_days": expected_minimum_days,
                "curriculum_compactness": 0,
                "room_stability": 0,
                "total_cost": expected_minimum_days,
            }
            if observed != wanted:
                raise CBCTTArchiveError(
                    f"Official-validator compatibility mismatch for {relative}: "
                    f"expected={wanted}, observed={observed}"
                )
            records.append(
                {
                    "projected_relative_path": relative,
                    "projected_sha256": hashlib.sha256(
                        projected.read_bytes()
                    ).hexdigest(),
                    "expected": wanted,
                    "observed": observed,
                    "returncode": result.returncode,
                    "compatible": True,
                }
            )

    return {
        "schema_version": "planora.cbctt-validator-compatibility.v2",
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "claim_boundary": (
            "Empty-solution parser plus lecture-count and minimum-working-days "
            "component agreement only; the zero baselines do not exercise "
            "conflicts, availability, room occupation, room capacity, curriculum "
            "compactness, or room stability. This is not feasible-solver evidence, "
            "ECTT-validator agreement, or a quality comparison."
        ),
        "validated_nonzero_components": [
            "lecture_violations",
            "minimum_working_days",
        ],
        "unexercised_zero_baseline_components": [
            "conflict_violations",
            "availability_violations",
            "room_occupation_violations",
            "room_capacity",
            "curriculum_compactness",
            "room_stability",
        ],
        "validator_command": command,
        "validator_sha256": validator_sha256,
        "validator_command_artifacts": validator_artifacts,
        "validator_command_manifest_sha256": command_manifest_sha256,
        "cache_directory": str(cache),
        "source_manifest_sha256": verification["source_manifest_sha256"],
        "projection_set_sha256": verification["projection_set_sha256"],
        "checked_instances": len(records),
        "compatible_instances": sum(bool(row["compatible"]) for row in records),
        "all_compatible": all(bool(row["compatible"]) for row in records),
        "instances": records,
    }


__all__ = [
    "CBCTT_ARCHIVE_PIN",
    "CBCTT_CORPUS_FILES",
    "CBCTT_CORPUS_SCHEMA",
    "CBCTT_DEFAULT_CACHE",
    "CBCTT_EXCLUDED_ARCHIVE_VARIANTS",
    "CBCTT_FAMILY_DIRECTORY_SWHIDS",
    "CBCTTArchiveError",
    "CBCTTArchiveFile",
    "CBCTTArchivePin",
    "CBCTTExcludedArchiveVariant",
    "fetch_cbctt_corpus",
    "validate_cbctt_projection_compatibility",
    "verify_cached_cbctt_corpus",
]
