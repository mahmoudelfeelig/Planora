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
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from benchmarks.itc2019 import (
    ITC2019Problem,
    inspect_itc2019_xml,
    parse_itc2019_solution,
    parse_itc2019_xml,
    summarize_itc2019_problem,
    validate_itc2019_solution,
)


ITC2019_PUBLIC_CORPUS_SCHEMA = "planora.itc2019-public-corpus.v1"
ITC2019_PUBLIC_REPOSITORY = "https://github.com/ADDALemos/MPPTimetables"
ITC2019_PUBLIC_COMMIT = "c33d15797686a27c192eabb90948baa54d3ddef5"
ITC2019_PUBLIC_ROOT_TREE = "85d223752d27d041e1f8f9cf3d869ed232628f3b"
ITC2019_PUBLIC_COMMITTED_AT = "2020-07-19T14:38:42Z"
ITC2019_PUBLIC_COMMIT_MESSAGE = "Domain reduction stats"
ITC2019_REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
ITC2019_PUBLIC_DEFAULT_CACHE = (
    ITC2019_REPOSITORY_ROOT
    / "data"
    / "external"
    / f"itc2019-mpp-{ITC2019_PUBLIC_COMMIT[:12]}"
)


class ITC2019PublicCorpusError(RuntimeError):
    """Raised when the pinned mirror or ignored local cache fails verification."""


@dataclass(frozen=True, order=True)
class ITC2019PublicCorpusFile:
    kind: str
    phase: str
    instance: str
    relative_path: str
    byte_length: int
    git_blob_sha1: str
    sha256: str


@dataclass(frozen=True, order=True)
class ITC2019PublicEvidenceFile:
    relative_path: str
    byte_length: int
    git_blob_sha1: str
    sha256: str


@dataclass(frozen=True, order=True)
class ITC2019OfficialCorrection:
    instance: str
    relative_path: str
    organizer_instance_id: str
    organizer_data_id: str
    byte_length: int
    git_blob_sha1: str
    sha256: str
    notice_url: str


@dataclass(frozen=True)
class ITC2019PublicCorpusPin:
    repository: str
    commit: str
    root_tree: str
    committed_at: str
    commit_message: str
    files: tuple[ITC2019PublicCorpusFile, ...]
    evidence_files: tuple[ITC2019PublicEvidenceFile, ...]
    expected_problem_count: int
    expected_solution_count: int


# Checked-in, redistributable metadata only.  The 308.6 MiB XML payload remains
# in data/, which is ignored, and is retrieved only from immutable commit URLs.
_PINNED_FILE_ROWS = """\
problem|early|agh-fis-spr17|data/input/ITC-2019/agh-fis-spr17.xml|15488915|ef3ab6bc80510b5612dac3594db7c5a3cc11c5d1|208d19ef809a5fa1be197be5f13eea7fd5d84b15d7844d6bb58fbd7122789e1a
problem|early|agh-ggis-spr17|data/input/ITC-2019/agh-ggis-spr17.xml|6104124|cd65580c6e1f034d36f70e69fedbe04aa823358e|8b081a1ba0d649109e272718633d7da6c3705841ae7bbdbee51abcc27570ee5b
problem|early|bet-fal17|data/input/ITC-2019/bet-fal17.xml|4255863|5d1fe1d90f689be44acd6d5abd6f2a0fb78cb624|f6ef3e4fb49d3ff1f886dfcf3b2609568c311248839ebae7807b6ec64c88557a
problem|early|iku-fal17|data/input/ITC-2019/iku-fal17.xml|13232703|10927346a6158c370bc901e3536116205cb4d4a2|738036a1fd8e4dd6415d8554e672241a39939923b14a28953520815207628d66
problem|early|mary-spr17|data/input/ITC-2019/mary-spr17.xml|3089281|aa2d721856c77ec93e2611f3562c44ce89a3938d|2362253334a5a38ddb56d7aeb9cea36f5dc0850df93fbbe1c04b17175ae06a4e
problem|early|muni-fi-spr16|data/input/ITC-2019/muni-fi-spr16.xml|1728554|3e51ff7ebc1bb4ce279f1d897ac8b65f6fb153c2|99c55ed9977362b7df777a9aab428f0d8e5f5fc887532c45fa9ac66e2ab85761
problem|early|muni-fsps-spr17|data/input/ITC-2019/muni-fsps-spr17.xml|1787369|13a8da3f2260d04986c0c5cc2de70abf7b24e3ae|d6956a01e65231087805e5bcc164b75834ab811898b1b0935005a2ddbe2450be
problem|early|muni-pdf-spr16c|data/input/ITC-2019/muni-pdf-spr16c.xml|16708999|bbe079655e0f6980cac55361cb9628f2936d168f|2c57dc3d5ec8958fe867643ecffe17632fd5fb6f4ec39522523067868c5c4ef1
problem|early|pu-llr-spr17|data/input/ITC-2019/pu-llr-spr17.xml|4924933|7d1bd6f7cba45f7518e8f9640b59739b58f18b67|27d8e289bc5c211596a82ce669edfe26852a3bdd05e3bff643b29c1f628e883f
problem|early|tg-fal17|data/input/ITC-2019/tg-fal17.xml|2341492|4606999b2ef8989b9948ad6cab7510c50c7f044b|ef6b5e0b4532ec4d5b60be33a2f5a8767fc46644d86eb64496bc6d1111bcf859
problem|late|agh-fal17|data/input/ITC-2019/agh-fal17.xml|44961985|6450c71710bf1b19e94dbc8d2a5510d752a17544|bae3363ed68e895280cd33bc20686bf396932f532c2b197f7b863f4167437528
problem|late|bet-spr18|data/input/ITC-2019/bet-spr18.xml|4365256|7142e8af852c9b9eae4b01e1725c2eae541bc8d5|ebf688b465fcc59197c6490d027f6e0cc8a78b1f8ddc5636f7752ea36654bf1f
problem|late|iku-spr18|data/input/ITC-2019/iku-spr18.xml|12919172|dfcf88b70420fd724410e67dab2801c93f6ce82d|1bb39842f04172cad5f6f758e63dbf460fab40705fb25dca221d0c953fa72138
problem|late|lums-fal17|data/input/ITC-2019/lums-fal17.xml|3256404|5753ade36ec8c905c5fc091b324bb971d725dfbe|adac22bc2922ffae7363c3aae35ac40399a93e30604c0a6f5b31c05fef55c242
problem|late|mary-fal18|data/input/ITC-2019/mary-fal18.xml|2610009|1cde5caf83198b5377aa8bda808109fc7be420c2|cf3c60edd73c6f82c8bbde7d8c29e6793dff3640128392582763f681567c4036
problem|late|muni-fi-fal17|data/input/ITC-2019/muni-fi-fal17.xml|1679150|b9c2205dae5d32f9a41eb2f081643abcc8f1b630|9a1a977653820e9c93589e1b56ccd1a9b761348e781123fefa88a6bc29e7c8c0
problem|late|muni-fspsx-fal17|data/input/ITC-2019/muni-fspsx-fal17.xml|12088665|dd31b73a53369562e3bfcc341c452f2e0ab6f6fc|151664dfc27f377e5048cf0bf8ad48fac350c46a7db6ca7181fed6d1933960b6
problem|late|muni-pdfx-fal17|data/input/ITC-2019/muni-pdfx-fal17.xml|28600948|39cc62a2fe417b32307fd93a3bad32e42597fc77|579f4c4359a8bed478ead694da9db25d10457151c29ac52578a460412505a574
problem|late|pu-d9-fal19|data/input/ITC-2019/pu-d9-fal19.xml|11367770|f7b3a0788b251cc19ec139a96911d3ef498da72c|5a93257c4d237239354605e275f9643e2494c8f2bdfed534f37eaf03a4ab2299
problem|late|tg-spr18|data/input/ITC-2019/tg-spr18.xml|2100958|ad01bc251bca8d556b02ffab065102d471fcd439|b43129276f426d80ac61e3d3ef4dc2996037d22834fe0bb72b2bfac4cc30035e
problem|middle|agh-ggos-spr17|data/input/ITC-2019/agh-ggos-spr17.xml|11729904|c0ceed214e87d84a9bdee778038464f10082825f|a945791560f74d42e16ffc8ec30bb6edc87ce16b826752e0d47bf3e8992f5c35
problem|middle|agh-h-spr17|data/input/ITC-2019/agh-h-spr17.xml|11270093|4f7c35e6a8cf8579f8ad2c8b92db51d4e7d2ef5b|aba9469b10d77732b6c646910171d76cf6da6f6342f4de4ff03fd45e547ea074
problem|middle|lums-spr18|data/input/ITC-2019/lums-spr18.xml|3183899|34ed74e6bb007f940942c8d8c6abc1fb908c0ce9|ea9ec5ebcaf4e8d46a5c26af03d59e99b3d4e47be10cc0eff583cb83227edc23
problem|middle|muni-fi-spr17|data/input/ITC-2019/muni-fi-spr17.xml|1461518|98645f63eb04c618a565cecc40971d0fdaa7298d|a0e6956c30bf302fa618e4c832a648b35589cb6e6771ddecdfaffd44d4f0bfd7
problem|middle|muni-fsps-spr17c|data/input/ITC-2019/muni-fsps-spr17c.xml|8078587|44d5e7c476484ca95a9e41fa5ddf7fe1dfda5480|d77c127589b244266075a1c2bd946e33b0d4eb4f41d8ef401a388d4a29903538
problem|middle|muni-pdf-spr16|data/input/ITC-2019/muni-pdf-spr16.xml|7039714|1948ae51853807afed35cbc0d1c6b91302035d26|4dcbfec6fa8afbb191e75a123bd6081bf980c6c95980b2d5f8fd36eb02b6f4e9
problem|middle|nbi-spr18|data/input/ITC-2019/nbi-spr18.xml|3701942|5b232d5ef4a3079c866dd83f31a4e6cfe83ef7af|7f6a7b19e2f5a8f02ea72bcac7ad8c3c98f0d86605b8defbc6ba11a5733caa95
problem|middle|pu-d5-spr17|data/input/ITC-2019/pu-d5-spr17.xml|2958579|827054369f1c5ad913109eedc1ac1f43937cdd9c|f20c3a2ab0ea046626b466ead8941405af9f907223e12fafd63f46329142fad2
problem|middle|pu-proj-fal19|data/input/ITC-2019/pu-proj-fal19.xml|33705472|7dac8afd0fa2c7ffdfb36840714e6172d213fe73|2fa848bf039f8ef86f65e280b5302afd37c48a03e1bc7e09364cf91bebd86e42
problem|middle|yach-fal17|data/input/ITC-2019/yach-fal17.xml|2149561|734042cbcc6d7a60ba6f177d81b08239303c84fc|9c4bf766be0fb8b689f14c240b212d0839bf53e5594b56f0b425740f812bfa82
problem|test|bet-sum18|data/input/ITC-2019/bet-sum18.xml|176853|8a52edc920a4b79bf8ec9ec2e3a2bbc7fd6fa542|569311ffb7f1bad0a9026c05ac0c0152d9fbf017639b4ab94691cea19473fea8
problem|test|lums-sum17|data/input/ITC-2019/lums-sum17.xml|205278|98babe62edf41759fed8f1bc2f6fb61a5bcea336|c055ded38574dc6765334326fdcd9c1c832f9b18955680668edd89e8521afd77
problem|test|pu-c8-spr07|data/input/ITC-2019/pu-c8-spr07.xml|8970399|902a26f0d9df152b39f74c505d61480154c6eda0|b33ef7dfd8a10649ba6bf67fe7dc758fe4e356a1853de94eaa73c20820a454d2
problem|test|pu-cs-fal07|data/input/ITC-2019/pu-cs-fal07.xml|464582|ed1f55141cc743f90e655b4f87cd67f95b824847|e9f1b7941e6b06919db69d80e1c326a02224aa5305d6bb9ebcfbdfa987e2b0db
problem|test|pu-llr-spr07|data/input/ITC-2019/pu-llr-spr07.xml|4718834|6b6b94f3aa1d8d94a02abda4d6663bbfad2e2453|914724764a1d2f46d5aefa69fa764e63c14959557f78067bb9b63d2b8386ed4c
problem|test|wbg-fal10|data/input/ITC-2019/wbg-fal10.xml|489167|99040decefd816276c3cdafb240aed4118ec5ab0|dcfca95a4fdc34cdb85d2b84dd072e2bdfed05747abb5dfd0afc61dfe7514ed4
solution|early|agh-fis-spr17|data/output/ITC-2019/solution-agh-fis-spr17.xml|861930|1a5c0bbc052bc07a5793413ad026e33723eebb56|1142637d9409574cedc3ce5650118593bd1eadde25c2dfaad24274741ca8ca07
solution|early|agh-ggis-spr17|data/output/ITC-2019/solution-agh-ggis-spr17.xml|1975502|a3d40ccf9f185ada43e45e70941df23fdded0563|687b2ffff67ced83c15e3e9bb74671fdc80d0ef30d08f2ccef9d705c5c29f553
solution|early|mary-spr17|data/output/ITC-2019/solution-mary-spr17.xml|7787614|5c5cc2c557026921597c64f29820aea2d6039a3d|927384849f42816c4dc807cd9573617ccaaf58641c33d2b46995b037c567c8d6
solution|early|muni-fi-spr16|data/output/ITC-2019/solution-muni-fi-spr16.xml|8003269|e1c94c2d8cea660b5bb47bf5777f3d7dd1ce799e|c5b86108d19387e15cf1da3e7a3b36db8ce19d2b1342c4645b4d5af63da0f0a9
solution|early|muni-fsps-spr17|data/output/ITC-2019/solution-muni-fsps-spr17.xml|1731703|166273355420c7394a95ea4f1d315e2da3636472|e6485904ede1e6b32eb068bb78743995c92c23722d985bd828470e4112cf1a45
solution|early|pu-llr-spr17|data/output/ITC-2019/solution-pu-llr-spr17.xml|2818554|4cb47d8558de6398289b3c0c25415edec6865a09|228ff26b3ca30efef00a9bcfb08aa525ca5700364bde6ab370b099cc0023a1b0
solution|early|tg-fal17|data/output/ITC-2019/solution-tg-fal17.xml|57792|81f95f1ad82dfd318f31524e7d550b5f4233e902|ccb3503578737181d4fee2ee83f5e346bed83d62614ccd03f91dda9fc13aea4e
solution|late|lums-fal17|data/output/ITC-2019/solution-lums-fal17.xml|44190|d3f977120c275db2d87cd0f8512d5cf321443520|74813e5308c7ec37aeb4c330a4779d186f8cc9fababefcaafa4dad57bc4b1662
solution|late|mary-fal18|data/output/ITC-2019/solution-mary-fal18.xml|695438|8d1f61764a6cb8f3578c625c81f8874d7484db13|ec840da3bbca2af230cd8d2d4578d9a4b6438212be30f2d5a035bad17f12b876
solution|late|tg-spr18|data/output/ITC-2019/solution-tg-spr18.xml|56588|0c3be481e53614a1bab377c5985c443cd858d4ad|a52efc0eae91b75f16f2827ce8c234673f7b2110f6e5bec36456131ca40e0733
solution|middle|agh-ggos-spr17|data/output/ITC-2019/solution-agh-ggos-spr17.xml|1007379|a418c6d4723ee8318f26c23f6094697a34ba0dcd|c1a59402b0d45ff7d076a655e57ba2cff3adf3dc50ccf3422de0f39111bcf1a1
solution|middle|lums-spr18|data/output/ITC-2019/solution-lums-spr18.xml|42836|5ba0ab79f0f2aa3359aa93bd1c82a98e63984c5c|138c09d1ee3e1fa17d66a93a8b50b493d0edb28d7803bd1f6631d54ce30c6c2c
solution|middle|muni-fi-spr17|data/output/ITC-2019/solution-muni-fi-spr17.xml|475457|a814892b60ffb14c547e6279e26c073be31f7629|e4cc43b17b6800b8d4e436a42ab9df224f86724721eb29242302b561e0c349d0
solution|middle|muni-fsps-spr17c|data/output/ITC-2019/solution-muni-fsps-spr17c.xml|2587668|a907cf0ac2e001bb68b78f765dc7b42a735b0aca|9d9a6f67ef7b69e31418f3b6335f63879908dfde02d15502157bb66d394a5ed5
solution|middle|muni-pdf-spr16|data/output/ITC-2019/solution-muni-pdf-spr16.xml|1130671|7c6c29e8b40b58e46979e05038c20166071d129c|2ded4273ca7c7790f6f28b7815080555f7f07ae46d05daaad172f67b5dd4c8cc
solution|middle|yach-fal17|data/output/ITC-2019/solution-yach-fal17.xml|342792|81f35dc1895f22392000ce0ece6717d96f8b07ad|7d56c0007271946b91e399ba70165faf19c7ae7ef833027c855271684c209b8f
solution|test|lums-sum17|data/output/ITC-2019/solution-lums-sum17.xml|1712|7f659ef69dcbc23a384f787512392351900deebc|0749476cf5df3c5cc995f001e8e5f502f42240533c932290b215a271981db610
solution|test|wbg-fal10|data/output/ITC-2019/wbg-fal10.xml|581|98b262b25d5054c88e0cc384d737ef1625f10813|03d317c9ef37a6e426924a9b12b2dadcbb84e1cda9b8e848ec6224483acbddc3
"""


def _parse_pinned_rows() -> tuple[ITC2019PublicCorpusFile, ...]:
    files: list[ITC2019PublicCorpusFile] = []
    for line in _PINNED_FILE_ROWS.splitlines():
        kind, phase, instance, relative_path, length, git_sha1, sha256 = line.split("|")
        files.append(
            ITC2019PublicCorpusFile(
                kind=kind,
                phase=phase,
                instance=instance,
                relative_path=relative_path,
                byte_length=int(length),
                git_blob_sha1=git_sha1,
                sha256=sha256,
            )
        )
    return tuple(files)


ITC2019_PUBLIC_CORPUS_FILES = _parse_pinned_rows()
ITC2019_OFFICIAL_CORRECTIONS = (
    ITC2019OfficialCorrection(
        instance="muni-pdf-spr16",
        relative_path="data/input/ITC-2019/muni-pdf-spr16.xml",
        organizer_instance_id="5d813ec3df7e617c3bd2ad9d",
        organizer_data_id="5da20639df7e6155649fb58a",
        byte_length=7_039_713,
        git_blob_sha1="ee2aab18414c2c62478178a5fef690b9713eb309",
        sha256="72e851f204de6a74841ac998ecba71ef2a5a913578f5020f9be26d8f62bf9933",
        notice_url="https://groups.google.com/g/itc-2019/c/Fr9ijWWhY-Q",
    ),
    ITC2019OfficialCorrection(
        instance="pu-d5-spr17",
        relative_path="data/input/ITC-2019/pu-d5-spr17.xml",
        organizer_instance_id="5d813eccdf7e617c3bd2ada3",
        organizer_data_id="5da20643df7e6155649fb58e",
        byte_length=2_958_576,
        git_blob_sha1="69c533c0b19d62582ac8c2bbf35529e089aecb54",
        sha256="8bdaf9d09a736f1fe8b202c29b270a9351fbc99cb7737d4abc34944f074e1547",
        notice_url="https://groups.google.com/g/itc-2019/c/Fr9ijWWhY-Q",
    ),
)
ITC2019_OFFICIAL_CORRECTED_INPUT_SHA256 = {
    correction.instance: correction.sha256
    for correction in ITC2019_OFFICIAL_CORRECTIONS
}
ITC2019_PUBLIC_EVIDENCE_FILES = (
    ITC2019PublicEvidenceFile(
        relative_path="LICENSE",
        byte_length=1496,
        git_blob_sha1="4a99b9ae7fcf3f3ef21f8f8b3dbeff2d0b2b48c0",
        sha256="9426e456337dd79631e2e1366065e03622c995629ed4d9009904a472f0e428f9",
    ),
    ITC2019PublicEvidenceFile(
        relative_path="README.md",
        byte_length=4021,
        git_blob_sha1="e33e1d1b39b2030936e513058af86bbe1a83a682",
        sha256="509e88adec76d855426df257ab254d798393553b89bb159dabbb676396dcba57",
    ),
)
ITC2019_PUBLIC_CORPUS_PIN = ITC2019PublicCorpusPin(
    repository=ITC2019_PUBLIC_REPOSITORY,
    commit=ITC2019_PUBLIC_COMMIT,
    root_tree=ITC2019_PUBLIC_ROOT_TREE,
    committed_at=ITC2019_PUBLIC_COMMITTED_AT,
    commit_message=ITC2019_PUBLIC_COMMIT_MESSAGE,
    files=ITC2019_PUBLIC_CORPUS_FILES,
    evidence_files=ITC2019_PUBLIC_EVIDENCE_FILES,
    expected_problem_count=36,
    expected_solution_count=18,
)

FetchBytes = Callable[[str, float], bytes]


def _default_fetch_bytes(url: str, timeout_seconds: float) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json, application/octet-stream;q=0.9",
            "User-Agent": "Planora-ITC2019-reproducibility-fetcher/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
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
    raise ITC2019PublicCorpusError(
        f"Could not retrieve pinned repository URL {url}: {last_error}"
    )


def _load_json(fetch_bytes: FetchBytes, url: str, timeout_seconds: float) -> Any:
    payload = _fetch_with_retries(fetch_bytes, url, timeout_seconds)
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ITC2019PublicCorpusError(
            f"Repository endpoint returned invalid JSON: {url}"
        ) from exc


def _valid_hex(value: str, length: int) -> bool:
    return len(value) == length and all(character in "0123456789abcdef" for character in value)


def _safe_relative_path(value: str) -> bool:
    path = Path(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def _validate_pin(pin: ITC2019PublicCorpusPin) -> None:
    if not _valid_hex(pin.commit, 40) or not _valid_hex(pin.root_tree, 40):
        raise ValueError("ITC-2019 commit and root tree must be lowercase SHA-1 values")
    if not pin.repository.startswith("https://github.com/"):
        raise ValueError("ITC-2019 repository must be an HTTPS GitHub origin")
    paths = [row.relative_path for row in pin.files]
    paths.extend(row.relative_path for row in pin.evidence_files)
    if len(paths) != len(set(paths)):
        raise ValueError("ITC-2019 source descriptor contains duplicate paths")
    problems = [row for row in pin.files if row.kind == "problem"]
    solutions = [row for row in pin.files if row.kind == "solution"]
    if len(problems) != pin.expected_problem_count:
        raise ValueError("ITC-2019 source descriptor has the wrong problem count")
    if len(solutions) != pin.expected_solution_count:
        raise ValueError("ITC-2019 source descriptor has the wrong solution count")
    problem_instances = {row.instance for row in problems}
    if any(row.instance not in problem_instances for row in solutions):
        raise ValueError("ITC-2019 source descriptor has an orphan solution")
    for row in (*pin.files, *pin.evidence_files):
        if not _safe_relative_path(row.relative_path) or row.byte_length <= 0:
            raise ValueError(f"Unsafe ITC-2019 source row: {row.relative_path!r}")
        if not _valid_hex(row.git_blob_sha1, 40) or not _valid_hex(row.sha256, 64):
            raise ValueError(f"Malformed digest for {row.relative_path}")
    for row in pin.files:
        if row.kind not in {"problem", "solution"}:
            raise ValueError(f"Unknown ITC-2019 file kind {row.kind!r}")
        if row.phase not in {"test", "early", "middle", "late"}:
            raise ValueError(f"Unknown ITC-2019 phase {row.phase!r}")


def _source_manifest_sha256(files: Sequence[ITC2019PublicCorpusFile]) -> str:
    rows = [asdict(row) for row in sorted(files, key=lambda item: item.relative_path)]
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


ITC2019_PUBLIC_SOURCE_MANIFEST_SHA256 = _source_manifest_sha256(
    ITC2019_PUBLIC_CORPUS_FILES
)


def _effective_competition_files() -> tuple[ITC2019PublicCorpusFile, ...]:
    corrections = {
        correction.relative_path: correction
        for correction in ITC2019_OFFICIAL_CORRECTIONS
    }
    effective: list[ITC2019PublicCorpusFile] = []
    for row in ITC2019_PUBLIC_CORPUS_FILES:
        correction = corrections.get(row.relative_path)
        if correction is None:
            effective.append(row)
            continue
        effective.append(
            ITC2019PublicCorpusFile(
                kind=row.kind,
                phase=row.phase,
                instance=row.instance,
                relative_path=row.relative_path,
                byte_length=correction.byte_length,
                git_blob_sha1=correction.git_blob_sha1,
                sha256=correction.sha256,
            )
        )
    return tuple(effective)


ITC2019_EFFECTIVE_COMPETITION_FILES = _effective_competition_files()
ITC2019_EFFECTIVE_COMPETITION_MANIFEST_SHA256 = _source_manifest_sha256(
    ITC2019_EFFECTIVE_COMPETITION_FILES
)
ITC2019_EFFECTIVE_COMPETITION_PIN = ITC2019PublicCorpusPin(
    repository=ITC2019_PUBLIC_CORPUS_PIN.repository,
    commit=ITC2019_PUBLIC_CORPUS_PIN.commit,
    root_tree=ITC2019_PUBLIC_CORPUS_PIN.root_tree,
    committed_at=ITC2019_PUBLIC_CORPUS_PIN.committed_at,
    commit_message=ITC2019_PUBLIC_CORPUS_PIN.commit_message,
    files=ITC2019_EFFECTIVE_COMPETITION_FILES,
    evidence_files=ITC2019_PUBLIC_CORPUS_PIN.evidence_files,
    expected_problem_count=ITC2019_PUBLIC_CORPUS_PIN.expected_problem_count,
    expected_solution_count=ITC2019_PUBLIC_CORPUS_PIN.expected_solution_count,
)


def _hashes(data: bytes) -> dict[str, str | int]:
    git_header = f"blob {len(data)}\0".encode("ascii")
    return {
        "byte_length": len(data),
        "git_blob_sha1": hashlib.sha1(git_header + data).hexdigest(),  # noqa: S324
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _verify_bytes(
    data: bytes,
    expected: ITC2019PublicCorpusFile | ITC2019PublicEvidenceFile,
) -> None:
    observed = _hashes(data)
    wanted: dict[str, str | int] = {
        "byte_length": expected.byte_length,
        "git_blob_sha1": expected.git_blob_sha1,
        "sha256": expected.sha256,
    }
    if observed != wanted:
        raise ITC2019PublicCorpusError(
            f"Content hash mismatch for {expected.relative_path}: "
            f"expected={wanted}, observed={observed}"
        )


def _atomic_write(path: Path, data: bytes, *, cache_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.resolve().relative_to(cache_root.resolve())
    except ValueError as exc:
        raise ITC2019PublicCorpusError(f"Cache path escapes its root: {path}") from exc
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
        relative = cache.relative_to(ITC2019_REPOSITORY_ROOT)
    except ValueError:
        return cache
    if not relative.parts or relative.parts[0] != "data":
        raise ValueError(
            "A repository-local ITC-2019 cache must be under the ignored data/ tree"
        )
    return cache


def _github_urls(pin: ITC2019PublicCorpusPin) -> dict[str, str]:
    slug = pin.repository.removeprefix("https://github.com/").removesuffix(".git")
    return {
        "commit_api_url": f"https://api.github.com/repos/{slug}/commits/{pin.commit}",
        "tree_api_url": (
            f"https://api.github.com/repos/{slug}/git/trees/{pin.root_tree}?recursive=1"
        ),
        "raw_base_url": f"https://raw.githubusercontent.com/{slug}/{pin.commit}",
    }


def _validate_remote_metadata(
    pin: ITC2019PublicCorpusPin,
    *,
    fetch_bytes: FetchBytes,
    timeout_seconds: float,
) -> dict[str, object]:
    _validate_pin(pin)
    urls = _github_urls(pin)
    commit = _load_json(fetch_bytes, urls["commit_api_url"], timeout_seconds)
    if not isinstance(commit, Mapping):
        raise ITC2019PublicCorpusError("Pinned GitHub commit response is not an object")
    commit_details = commit.get("commit")
    tree = commit_details.get("tree") if isinstance(commit_details, Mapping) else None
    committer = commit_details.get("committer") if isinstance(commit_details, Mapping) else None
    observed_commit = {
        "commit": commit.get("sha"),
        "root_tree": tree.get("sha") if isinstance(tree, Mapping) else None,
        "committed_at": committer.get("date") if isinstance(committer, Mapping) else None,
        "message": commit_details.get("message") if isinstance(commit_details, Mapping) else None,
    }
    expected_commit = {
        "commit": pin.commit,
        "root_tree": pin.root_tree,
        "committed_at": pin.committed_at,
        "message": pin.commit_message,
    }
    if observed_commit != expected_commit:
        raise ITC2019PublicCorpusError(
            "Pinned GitHub commit metadata drifted: "
            f"expected={expected_commit}, observed={observed_commit}"
        )

    tree_payload = _load_json(fetch_bytes, urls["tree_api_url"], timeout_seconds)
    if not isinstance(tree_payload, Mapping):
        raise ITC2019PublicCorpusError("Pinned GitHub tree response is not an object")
    if tree_payload.get("sha") != pin.root_tree or tree_payload.get("truncated") is not False:
        raise ITC2019PublicCorpusError("Pinned GitHub root tree is mismatched or truncated")
    entries = tree_payload.get("tree")
    if not isinstance(entries, list):
        raise ITC2019PublicCorpusError("Pinned GitHub root tree has no entries")
    by_path = {
        str(entry.get("path")): entry
        for entry in entries
        if isinstance(entry, Mapping) and isinstance(entry.get("path"), str)
    }
    for expected in (*pin.files, *pin.evidence_files):
        observed = by_path.get(expected.relative_path)
        wanted = {
            "type": "blob",
            "sha": expected.git_blob_sha1,
            "size": expected.byte_length,
        }
        comparable = (
            {
                "type": observed.get("type"),
                "sha": observed.get("sha"),
                "size": observed.get("size"),
            }
            if isinstance(observed, Mapping)
            else None
        )
        if comparable != wanted:
            raise ITC2019PublicCorpusError(
                f"Pinned GitHub tree mismatch for {expected.relative_path}: "
                f"expected={wanted}, observed={comparable}"
            )
    return urls


def _fetch_one(
    cache: Path,
    expected: ITC2019PublicCorpusFile | ITC2019PublicEvidenceFile,
    *,
    raw_base_url: str,
    fetch_bytes: FetchBytes,
    timeout_seconds: float,
) -> bool:
    destination = cache / "raw" / expected.relative_path
    if destination.is_file():
        try:
            _verify_bytes(destination.read_bytes(), expected)
            return True
        except ITC2019PublicCorpusError:
            pass
    encoded_path = quote(expected.relative_path, safe="/")
    data = _fetch_with_retries(
        fetch_bytes,
        f"{raw_base_url}/{encoded_path}",
        timeout_seconds,
    )
    _verify_bytes(data, expected)
    _atomic_write(destination, data, cache_root=cache)
    return False


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].lower()


def _nonpositive_time_anomalies(path: Path) -> list[dict[str, object]]:
    root = ElementTree.parse(path).getroot()
    anomalies: list[dict[str, object]] = []
    for class_element in root.iter():
        if _local_name(class_element.tag) != "class":
            continue
        for time_element in class_element:
            if _local_name(time_element.tag) != "time":
                continue
            raw_length = time_element.attrib.get("length")
            try:
                length = int(raw_length) if raw_length is not None else None
            except ValueError:
                length = None
            if length is not None and length <= 0:
                anomalies.append(
                    {
                        "class_id": class_element.attrib.get("id"),
                        "class_limit": class_element.attrib.get("limit"),
                        "time_attributes": dict(sorted(time_element.attrib.items())),
                    }
                )
    return anomalies


def _error_category(error: str) -> str:
    if "duplicate classes" in error:
        return "duplicate_student_class_entries"
    if "load " in error and "exceeds limit" in error:
        return "class_limit_exceeded"
    if "placements are missing classes" in error:
        return "missing_class_placements"
    if "placement is outside its time domain" in error:
        return "outside_time_domain"
    if "outside its room domain" in error:
        return "outside_room_domain"
    if "overlap in room" in error:
        return "room_overlap"
    if "uses unavailable room" in error:
        return "room_unavailability"
    if "sectioning is missing students" in error:
        return "missing_students"
    if "unrequested courses" in error:
        return "unrequested_courses"
    if "exactly one configuration" in error:
        return "configuration_selection"
    if "exactly one class from" in error:
        return "subpart_selection"
    if "requires parent" in error:
        return "parent_linkage"
    if "solution name" in error:
        return "instance_name_mismatch"
    return "other"


def _error_list_sha256(errors: Sequence[str]) -> str:
    canonical = json.dumps(list(errors), separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(canonical).hexdigest()


def _analyze_cached_corpus(
    cache: Path,
    pin: ITC2019PublicCorpusPin,
) -> dict[str, object]:
    problems: dict[str, ITC2019Problem] = {}
    problem_records: list[dict[str, object]] = []
    for source_file in sorted(
        (row for row in pin.files if row.kind == "problem"),
        key=lambda row: row.relative_path,
    ):
        source = cache / "raw" / source_file.relative_path
        record: dict[str, object] = {
            "instance": source_file.instance,
            "phase": source_file.phase,
            "relative_path": source_file.relative_path,
            "structural_xml_parse": "passed",
            "nonpositive_time_anomalies": [],
        }
        try:
            problem = parse_itc2019_xml(source)
        except (ElementTree.ParseError, ValueError) as exc:
            # A strict semantic rejection is not a structural XML rejection.
            # Reparse only the rejected inputs to preserve the exact malformed
            # attributes and generic XML inspection evidence without tripling
            # the cost for every accepted multi-megabyte problem.
            inspection = inspect_itc2019_xml(source)
            record.update(
                {
                    "semantic_parse": "rejected",
                    "semantic_parse_error": f"{type(exc).__name__}: {exc}",
                    "inspection": inspection.to_dict(),
                    "nonpositive_time_anomalies": _nonpositive_time_anomalies(source),
                }
            )
        else:
            if problem.name != source_file.instance:
                raise ITC2019PublicCorpusError(
                    f"Problem name mismatch for {source_file.relative_path}: {problem.name!r}"
                )
            problems[source_file.instance] = problem
            record.update(
                {
                    "semantic_parse": "passed",
                    "summary": summarize_itc2019_problem(problem).to_dict(),
                }
            )
        problem_records.append(record)

    solution_records: list[dict[str, object]] = []
    for source_file in sorted(
        (row for row in pin.files if row.kind == "solution"),
        key=lambda row: row.relative_path,
    ):
        source = cache / "raw" / source_file.relative_path
        record: dict[str, object] = {
            "instance": source_file.instance,
            "phase": source_file.phase,
            "relative_path": source_file.relative_path,
            "mirror_role": (
                "minimal_perturbation_baseline_candidate"
                if Path(source_file.relative_path).name.startswith("solution-")
                else "repository_example_or_generated_output"
            ),
        }
        try:
            solution = parse_itc2019_solution(source)
        except (ElementTree.ParseError, ValueError) as exc:
            record.update(
                {
                    "solution_parse": "rejected",
                    "local_combined_validation": "not_run",
                    "solution_parse_error": f"{type(exc).__name__}: {exc}",
                }
            )
            solution_records.append(record)
            continue
        record["solution_parse"] = "passed"
        problem = problems.get(source_file.instance)
        metadata = dict(solution.metadata)
        errors: list[str] = []
        if metadata.get("name") != source_file.instance:
            errors.append(
                f"solution name {metadata.get('name')!r} does not match "
                f"problem {source_file.instance!r}"
            )
        if problem is None:
            record.update(
                {
                    "local_combined_validation": "not_run_problem_semantic_parse_rejected",
                    "metadata": metadata,
                    "placements": len(solution.placements),
                    "sectioned_students": len(solution.student_classes),
                }
            )
            solution_records.append(record)
            continue
        errors.extend(
            validate_itc2019_solution(
                problem,
                solution.placements,
                solution.student_classes,
            )
        )
        categories = Counter(_error_category(error) for error in errors)
        record.update(
            {
                "local_combined_validation": "passed" if not errors else "failed",
                "metadata": metadata,
                "placements": len(solution.placements),
                "problem_classes": len(problem.classes),
                "sectioned_students": len(solution.student_classes),
                "problem_students": len(problem.students),
                "student_class_assignments": sum(
                    len(class_ids) for class_ids in solution.student_classes.values()
                ),
                "validation_error_count": len(errors),
                "validation_error_categories": dict(sorted(categories.items())),
                "validation_errors_sha256": _error_list_sha256(errors),
                "validation_errors": errors,
            }
        )
        solution_records.append(record)

    semantic_passed = sum(
        record["semantic_parse"] == "passed" for record in problem_records
    )
    locally_valid = sum(
        record.get("local_combined_validation") == "passed"
        for record in solution_records
    )
    locally_invalid = sum(
        record.get("local_combined_validation") == "failed"
        for record in solution_records
    )
    return {
        "problem_parsing": {
            "structural_xml_passed": len(problem_records),
            "semantic_passed": semantic_passed,
            "semantic_rejected": len(problem_records) - semantic_passed,
            "instances": problem_records,
        },
        "solution_validation": {
            "solution_xml_parsed": sum(
                record.get("solution_parse") == "passed" for record in solution_records
            ),
            "locally_valid_for_implemented_scope": locally_valid,
            "locally_invalid_for_implemented_scope": locally_invalid,
            "not_run_due_to_problem_parse": sum(
                str(record.get("local_combined_validation", "")).startswith("not_run_problem")
                for record in solution_records
            ),
            "instances": solution_records,
        },
    }


def _base_report(
    cache: Path,
    pin: ITC2019PublicCorpusPin,
    analysis: Mapping[str, object],
) -> dict[str, object]:
    problems = [row for row in pin.files if row.kind == "problem"]
    solutions = [row for row in pin.files if row.kind == "solution"]
    return {
        "schema_version": ITC2019_PUBLIC_CORPUS_SCHEMA,
        "cache_directory": str(cache),
        "source": {
            "repository": pin.repository,
            "commit": pin.commit,
            "root_tree": pin.root_tree,
            "committed_at": pin.committed_at,
            "commit_message": pin.commit_message,
            "source_manifest_sha256": _source_manifest_sha256(pin.files),
            "files": [asdict(row) for row in pin.files],
            "evidence_files": [asdict(row) for row in pin.evidence_files],
        },
        "licensing": {
            "repository_license_path": "LICENSE",
            "repository_license_identifier": "MIT",
            "dataset_specific_upstream_license": "not_separately_identified",
            "redistribution_policy": (
                "checked_in_metadata_only; XML and repository evidence stay in ignored cache"
            ),
        },
        "corpus": {
            "problem_files": len(problems),
            "solution_files": len(solutions),
            "distinct_problem_contents": len({row.sha256 for row in problems}),
            "distinct_solution_contents": len({row.sha256 for row in solutions}),
            "problem_phases": dict(sorted(Counter(row.phase for row in problems).items())),
            "total_xml_bytes": sum(row.byte_length for row in pin.files),
        },
        "validation_scope": {
            "local_combined_validator_includes": [
                "complete class placement",
                "time and room domain membership",
                "room unavailability and collision checks",
                "course configuration and subpart sectioning",
                "parent linkage and class enrollment limits",
            ],
            "excluded": [
                "hard and soft distribution-constraint validation",
                "time, room, distribution, and total objective agreement",
                "official website validator agreement",
                "provenance claim that mirrored outputs are competition submissions",
            ],
            "official_validator": "not_run; website validation requires authenticated upload",
        },
        **analysis,
    }


def fetch_itc2019_public_corpus(
    cache_directory: str | Path = ITC2019_PUBLIC_DEFAULT_CACHE,
    *,
    pin: ITC2019PublicCorpusPin = ITC2019_PUBLIC_CORPUS_PIN,
    timeout_seconds: float = 60.0,
    workers: int = 4,
    fetch_bytes: FetchBytes | None = None,
) -> dict[str, object]:
    """Fetch, hash-check, parse, and locally classify the pinned public mirror.

    This is evidence about a public finalist-repository mirror.  It is not an
    official ITC-2019 corpus download and never establishes official-validator
    or objective agreement.
    """

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if workers <= 0:
        raise ValueError("workers must be positive")
    cache = _ensure_non_vendored_cache(Path(cache_directory))
    cache.mkdir(parents=True, exist_ok=True)
    downloader = fetch_bytes or _default_fetch_bytes
    urls = _validate_remote_metadata(
        pin,
        fetch_bytes=downloader,
        timeout_seconds=timeout_seconds,
    )
    all_files = (*pin.files, *pin.evidence_files)
    with ThreadPoolExecutor(max_workers=min(workers, len(all_files))) as executor:
        reused = list(
            executor.map(
                lambda expected: _fetch_one(
                    cache,
                    expected,
                    raw_base_url=urls["raw_base_url"],
                    fetch_bytes=downloader,
                    timeout_seconds=timeout_seconds,
                ),
                all_files,
            )
        )
    analysis = _analyze_cached_corpus(cache, pin)
    report = _base_report(cache, pin, analysis)
    report["created_at_utc"] = datetime.now(UTC).isoformat()
    report["source"]["commit_api_url"] = urls["commit_api_url"]  # type: ignore[index]
    report["source"]["tree_api_url"] = urls["tree_api_url"]  # type: ignore[index]
    report["cache"] = {
        "reused_verified_files": sum(reused),
        "downloaded_files": sum(not value for value in reused),
    }
    _atomic_write(
        cache / "PROVENANCE.json",
        (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        cache_root=cache,
    )
    return report


def verify_cached_itc2019_public_corpus(
    cache_directory: str | Path = ITC2019_PUBLIC_DEFAULT_CACHE,
    *,
    pin: ITC2019PublicCorpusPin = ITC2019_PUBLIC_CORPUS_PIN,
) -> dict[str, object]:
    """Verify all pinned bytes, then rerun semantic parsing and local validation."""

    _validate_pin(pin)
    cache = _ensure_non_vendored_cache(Path(cache_directory))
    for expected in (*pin.files, *pin.evidence_files):
        source = cache / "raw" / expected.relative_path
        if not source.is_file():
            raise ITC2019PublicCorpusError(f"Cached source file is missing: {source}")
        _verify_bytes(source.read_bytes(), expected)
    analysis = _analyze_cached_corpus(cache, pin)
    return _base_report(cache, pin, analysis)


def verify_cached_itc2019_competition_corpus(
    cache_directory: str | Path = ITC2019_PUBLIC_DEFAULT_CACHE,
) -> dict[str, object]:
    """Verify the mirror plus the organizer's two withdrawn-input corrections.

    The pinned GitHub mirror remains useful provenance, but its middle PU-D5 and
    MUNI-PDF inputs were withdrawn by the organizers. Competition runs must use
    the corrected organizer bytes. This verifier binds the effective 30-case
    corpus without pretending those replacement blobs exist in the mirror
    commit.
    """

    _validate_pin(ITC2019_EFFECTIVE_COMPETITION_PIN)
    cache = _ensure_non_vendored_cache(Path(cache_directory))
    for expected in (
        *ITC2019_EFFECTIVE_COMPETITION_PIN.files,
        *ITC2019_EFFECTIVE_COMPETITION_PIN.evidence_files,
    ):
        source = cache / "raw" / expected.relative_path
        if not source.is_file():
            raise ITC2019PublicCorpusError(f"Cached source file is missing: {source}")
        _verify_bytes(source.read_bytes(), expected)
    analysis = _analyze_cached_corpus(cache, ITC2019_EFFECTIVE_COMPETITION_PIN)
    report = _base_report(cache, ITC2019_EFFECTIVE_COMPETITION_PIN, analysis)
    report["source"]["effective_competition_manifest_sha256"] = (  # type: ignore[index]
        ITC2019_EFFECTIVE_COMPETITION_MANIFEST_SHA256
    )
    report["source"]["official_corrections"] = [  # type: ignore[index]
        asdict(correction) for correction in ITC2019_OFFICIAL_CORRECTIONS
    ]
    return report


__all__ = [
    "ITC2019_EFFECTIVE_COMPETITION_FILES",
    "ITC2019_EFFECTIVE_COMPETITION_MANIFEST_SHA256",
    "ITC2019_EFFECTIVE_COMPETITION_PIN",
    "ITC2019_OFFICIAL_CORRECTED_INPUT_SHA256",
    "ITC2019_OFFICIAL_CORRECTIONS",
    "ITC2019_PUBLIC_COMMIT",
    "ITC2019_PUBLIC_CORPUS_FILES",
    "ITC2019_PUBLIC_CORPUS_PIN",
    "ITC2019_PUBLIC_DEFAULT_CACHE",
    "ITC2019_PUBLIC_REPOSITORY",
    "ITC2019_PUBLIC_ROOT_TREE",
    "ITC2019_PUBLIC_SOURCE_MANIFEST_SHA256",
    "ITC2019PublicCorpusError",
    "ITC2019PublicCorpusFile",
    "ITC2019PublicCorpusPin",
    "ITC2019PublicEvidenceFile",
    "ITC2019OfficialCorrection",
    "fetch_itc2019_public_corpus",
    "verify_cached_itc2019_public_corpus",
    "verify_cached_itc2019_competition_corpus",
]
