#!/usr/bin/env python3
"""Synthetic/adversarial gates for MUNI-FSPSX frontier v26.

This suite deliberately never opens the official instance or v35 progress.
"""

from __future__ import annotations

import ast
import base64
import contextlib
import copy
import csv
import errno
from hashlib import sha256
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
from xml.etree import ElementTree


CHAIN_ROOT = Path(__file__).resolve().parent
RUNNER = CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-runner.py"
SUPERVISOR = CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-supervisor.py"
LAUNCHER = CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-launcher.sh"
BOOTSTRAP = CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-bootstrap.py"
INLINE_TRUST = CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-inline-trust-root.txt"
STDLIB_MANIFEST = CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-stdlib.sha256"
PYTHON = Path("/usr/bin/python3.12")
V12_PRESERVED_HASHES = {
    "/tmp/planora-muni-fspsx-frontier-v12-bootstrap.py": "332ec8fd4e428098dd5199ef27668d95b048d531fe5a6520f228adfc6db45a6f",
    "/tmp/planora-muni-fspsx-frontier-v12-freeze-manifest.json": "31f8ce0fdc08046c05ed2aaf0d0f7f2ff6715d617fd04255c0b1bb6b5d4c25e1",
    "/tmp/planora-muni-fspsx-frontier-v12-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    "/tmp/planora-muni-fspsx-frontier-v12-inline-trust-root.txt": "96ddcd4dee6430b8cef56d8b595a8614ee90fad4bcdfb5e99265c0cc240857c2",
    "/tmp/planora-muni-fspsx-frontier-v12-launcher.sh": "71dd37dbb8b3195ef2397a9a8682c5a060b31176850eb79c48739d371c095e9a",
    "/tmp/planora-muni-fspsx-frontier-v12-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "/tmp/planora-muni-fspsx-frontier-v12-runner.py": "1ce9d2b98328e978aa5a09d0486ff7f323ab45dda66c0e730e3ab5ba6a07a46b",
    "/tmp/planora-muni-fspsx-frontier-v12-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "/tmp/planora-muni-fspsx-frontier-v12-supervisor.py": "cc12bcfe504f677afa03bf8dc8f37eabb85f599ac6784f3093eb8ae2053ed53b",
    "/tmp/planora-muni-fspsx-frontier-v12-tests.py": "4a603f9940b4e11029a5d93ee63841f512e82542cbbb5f69617afd996253b10d",
    "/tmp/planora_muni_v12_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    "/tmp/planora-muni-fspsx-frontier-v12-certificate.json": "175a02ea6bc14612d56293637a461430812b826890bcab97829bb841f8d77b2b",
}
V13_PRESERVED_HASHES = {
    "/tmp/planora-muni-fspsx-frontier-v13-bootstrap.py": "b2cecc1fdac3693e5609f629bcb75cf5e80ecfc7eac7af06876f918ece02ff61",
    "/tmp/planora-muni-fspsx-frontier-v13-freeze-manifest.json": "75c55c6afa4ca6a97bbdc4f224d3db4741ec87854d22e00c7ee2a53895b5fbd7",
    "/tmp/planora-muni-fspsx-frontier-v13-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    "/tmp/planora-muni-fspsx-frontier-v13-inline-trust-root.txt": "a124a1f5b4146f883b6a42d47f28f7000126cd07e20da98f9aa2bdf9ea978838",
    "/tmp/planora-muni-fspsx-frontier-v13-launcher.sh": "e16543251b163c6ea117591241c5932460935a004f0c6380060e03d2cc94916b",
    "/tmp/planora-muni-fspsx-frontier-v13-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "/tmp/planora-muni-fspsx-frontier-v13-runner.py": "3e0493d59a604dc7c99a73535662ebf868a96aa158f7c4ebdddb228f72c64051",
    "/tmp/planora-muni-fspsx-frontier-v13-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "/tmp/planora-muni-fspsx-frontier-v13-supervisor.py": "38464e78c14c901b25d9ad32a1981cfc4703607dc543fe5484d9a131a1087d0b",
    "/tmp/planora-muni-fspsx-frontier-v13-tests.py": "b77b492ba801ac1533008affe83033fb96ef52ca7f1e10e58daeeae5c515d81b",
    "/tmp/planora_muni_v13_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    "/tmp/planora-muni-fspsx-frontier-v13-certificate.json": "0ba69667fb96c02d2cd2b574e7fec7ea30f32d179058eefee4b9315256775425",
}
V14_PRESERVED_HASHES = {
    "/tmp/planora-muni-fspsx-frontier-v14-bootstrap.py": "9ae7a20b7b16ae37d72571685f1f3d0cf392b6062558704170ecf4b92fdd1d1a",
    "/tmp/planora-muni-fspsx-frontier-v14-freeze-manifest.json": "d2a4ada2b647b948299638296fb75b297b7206984ff10201bfddcb0aecee6eaf",
    "/tmp/planora-muni-fspsx-frontier-v14-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    "/tmp/planora-muni-fspsx-frontier-v14-inline-trust-root.txt": "cd0096caf80f8e0816fd21fb03b44d19680408bad818ddc0c2be148c5a1e68a0",
    "/tmp/planora-muni-fspsx-frontier-v14-launcher.sh": "1ffc6d61359724d473b302ca389bab4f4bec35f4489451751df897730af23ec0",
    "/tmp/planora-muni-fspsx-frontier-v14-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "/tmp/planora-muni-fspsx-frontier-v14-runner.py": "789f2b2d7a937a52888445f7694a1868dffb3237b138920ecb45f694be40d1fb",
    "/tmp/planora-muni-fspsx-frontier-v14-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "/tmp/planora-muni-fspsx-frontier-v14-supervisor.py": "8bc764e2619216759ceb626e4b7012df6c0d7198747729de14519886737e21e7",
    "/tmp/planora-muni-fspsx-frontier-v14-tests.py": "6d27ab4e1ace702c179bac2d50d03bfc723a0a828a9e0b6677d22c8350a8f050",
    "/tmp/planora_muni_v14_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    "/tmp/planora-muni-fspsx-frontier-v14-certificate.json": "be8a43faa45e24d11f62ad11e0491ef305be83f47c46d60000df7033a53982a2",
}
V15_PRESERVED_HASHES = {
    "/tmp/planora-muni-fspsx-frontier-v15-bootstrap.py": "241831946a30916e2900cc6b894f7a3e197bb881769b377baeca3b648d84c35f",
    "/tmp/planora-muni-fspsx-frontier-v15-freeze-manifest.json": "60a88df99a46562b951ea66e45c330a00550700155304040da2c62ac37ce009e",
    "/tmp/planora-muni-fspsx-frontier-v15-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    "/tmp/planora-muni-fspsx-frontier-v15-inline-trust-root.txt": "74584fe8e044c16aa357f7390ab5ca8b8b5d67c41f74d5bd384e26dc613d4e74",
    "/tmp/planora-muni-fspsx-frontier-v15-launcher.sh": "a447e6d2e99cc14fa097710ba08cbcae4585b5aeadca2d3349cdadd8218f7205",
    "/tmp/planora-muni-fspsx-frontier-v15-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    "/tmp/planora-muni-fspsx-frontier-v15-runner.py": "a4b8abbfea794d7192268d62722d3a29e2933900d57f8051b4301ae6be42162c",
    "/tmp/planora-muni-fspsx-frontier-v15-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    "/tmp/planora-muni-fspsx-frontier-v15-supervisor.py": "4007a788a4631d1a485121c25bc254a6fedff5755ff88fedc3c998f814f7ef2f",
    "/tmp/planora-muni-fspsx-frontier-v15-tests.py": "91c510dbd8cfb217c47004beaea1b5fa2301196d749a8588506532456789f1b9",
    "/tmp/planora_muni_v15_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    "/tmp/planora-muni-fspsx-frontier-v15-certificate.json": "42625671a2f4db85ba9d26e8898c59bc611fbc2dcd459b0019890be71c80f918",
}
V16_ROOT = CHAIN_ROOT.parent / "muni_v16"
V16_PRESERVED_HASHES = {
    V16_ROOT / "planora_muni_v16_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-bootstrap.py": "5f7f0920092c6ea8212300964086340d6c61c3c08d0c4bbfcb1a82956be1eaa2",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-certificate.json": "4fafe8e0cd5ee2c36ea226fe97daa5d950b5b7ee567e3a6f30fa4820644449be",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-freeze-manifest.json": "43eebfa7a4eebd561830b2b20b0ce684c250dd03c5d901b20993e35feb968306",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-inline-trust-root.txt": "6f4e5a357f8e4747166521764302f61a93c5f1d154529cd8cc3066b35f984203",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-launcher.sh": "471c3d7895eecff5036e48603993787b443a9f68403316ef194667f5d416ecce",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-runner.py": "7ae1cba5487fbc3cba22487f7ed16d7b99c2eaa3c7cdf5487d91b00b3258cef7",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-supervisor.py": "576d108bbc63d03353cb562d68b06d1ca5d2fac3baaa54ab55fc3e46ac638891",
    V16_ROOT / "planora-muni-fspsx-frontier-v16-tests.py": "b9f4c2b613b693cf51f56af1bfc5c5e4bfac507ddbe13d35ab8c2fbcd685af23",
    V16_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json": "aa7657d1c3e3c2362312ae0a07013373640fc5b777aa069dca107420393b8dc4",
}
V17_ROOT = CHAIN_ROOT.parent / "muni_v17"
V17_PRESERVED_HASHES = {
    V17_ROOT / "planora_muni_v17_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-bootstrap.py": "370acafcb53b5fdabfe602baec98f2cedf5fca4f581671dac219ce7d1f3ef67a",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-certificate.json": "1e3e415b361ac91307b2f5193a801f90ddf0941bfbc21a3dcfaa730291adda03",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-freeze-manifest.json": "ceb97e6d74ac7e68dcd2f22f4749870d63b384b99a13d1347b818d7d5bffe683",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-inline-trust-root.txt": "a3ea0d882a935ac119f44366bda493a4a36caada855c1df4e861c508dd8abd0b",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-launcher.sh": "54a4fa69d3d382bf0c04fde96f8f209db0e2c2770c799d3f8ef2e9193a2873da",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-runner.py": "5e10b3ad9e33d3f70212b3d44f2b691e5828997d7571588146edde4775830eb9",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-supervisor.py": "681e5fa4e16ce2210952c54c2f9a7be930fcb0808d4be7c33884473e0aa8fa9b",
    V17_ROOT / "planora-muni-fspsx-frontier-v17-tests.py": "dce9044b5562518390b846e5fbce99522d92f1603d4da02d1a093303021a2bd2",
    V17_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json": "aa7657d1c3e3c2362312ae0a07013373640fc5b777aa069dca107420393b8dc4",
}
V18_ROOT = CHAIN_ROOT.parent / "muni_v18"
V18_PRESERVED_HASHES = {
    V18_ROOT / "planora_muni_v18_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    V18_ROOT / "planora-muni-fspsx-frontier-v18-bootstrap.py": "657052a80fe238ee187b70c04968dde0fdcd31cad4e75158dfa71c552310bffe",
    V18_ROOT / "planora-muni-fspsx-frontier-v18-certificate.json": "4744f3f49a155a5389892a283f32cd788b73db543244dfd5fad9df73b755f005",
    V18_ROOT / "planora-muni-fspsx-frontier-v18-freeze-manifest.json": "459cb720d8d0b43f51f2f89e11002a678e8ff4c2ead4c516f35e685f24a79461",
    V18_ROOT / "planora-muni-fspsx-frontier-v18-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    V18_ROOT / "planora-muni-fspsx-frontier-v18-inline-trust-root.txt": "1c35235c1f805a8e58975dcda10c32c2aa78f733b5ba5dbe64bdb49829c3f0f0",
    V18_ROOT / "planora-muni-fspsx-frontier-v18-launcher.sh": "3aeee864ae029152409164c042b8191fb9e197cf0634c4a056041ca5d6124891",
    V18_ROOT / "planora-muni-fspsx-frontier-v18-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    V18_ROOT / "planora-muni-fspsx-frontier-v18-runner.py": "24e98703bc6821a57870f58271a1f62220358a7caace7d174550a86815093fb5",
    V18_ROOT / "planora-muni-fspsx-frontier-v18-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    V18_ROOT / "planora-muni-fspsx-frontier-v18-supervisor.py": "10efa114d59f3e8c9b43817acf1532873eae6d2a111146113aa1e85040812e0b",
    V18_ROOT / "planora-muni-fspsx-frontier-v18-tests.py": "4c9ad4c27ad0cb6a85085f4b68ff8333e3168673ff074552ba591887b915f558",
    V18_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json": "aa7657d1c3e3c2362312ae0a07013373640fc5b777aa069dca107420393b8dc4",
}
V19_ROOT = CHAIN_ROOT.parent / "muni_v19"
V19_PRESERVED_HASHES = {
    V19_ROOT / "planora_muni_v19_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    V19_ROOT / "planora-muni-fspsx-frontier-v19-bootstrap.py": "aee70e298b6f8f75851b3632ed917113aceb68b9bcf6a1f7a308e24fca674c55",
    V19_ROOT / "planora-muni-fspsx-frontier-v19-certificate.json": "e8afa7b099fcb7ec7539414e1e1fcb7ae5cb7635bea62ff112ae9213923904c9",
    V19_ROOT / "planora-muni-fspsx-frontier-v19-freeze-manifest.json": "d7ab89f2b424949f3099d96fe38c454a6b0f55bb93f07f8f96f60edcf914b53a",
    V19_ROOT / "planora-muni-fspsx-frontier-v19-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    V19_ROOT / "planora-muni-fspsx-frontier-v19-inline-trust-root.txt": "240bb94d28221dbd739d917496a371c4f29d5c19550efa52b803ba11dc988c44",
    V19_ROOT / "planora-muni-fspsx-frontier-v19-launcher.sh": "73e8795ae9c2e579a6322321d649080cd991422195b858f9efe258076df8d73f",
    V19_ROOT / "planora-muni-fspsx-frontier-v19-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    V19_ROOT / "planora-muni-fspsx-frontier-v19-runner.py": "9a6bad1d373bff19881b81215e035c4cdedda3948f52f64924f92b6b28cd143e",
    V19_ROOT / "planora-muni-fspsx-frontier-v19-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    V19_ROOT / "planora-muni-fspsx-frontier-v19-supervisor.py": "262ab0f56e3fb9b9a208167ff91c79f853152fb6e02569f1a99231b90347969d",
    V19_ROOT / "planora-muni-fspsx-frontier-v19-tests.py": "40a9ead91417650c10c255c49b161f356a23f63343c7ef4b09d79a291fcb9a43",
    V19_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json": "aa7657d1c3e3c2362312ae0a07013373640fc5b777aa069dca107420393b8dc4",
}
V20_ROOT = CHAIN_ROOT.parent / "muni_v20"
V20_PRESERVED_HASHES = {
    V20_ROOT / "planora_muni_v20_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    V20_ROOT / "planora-muni-fspsx-frontier-v20-bootstrap.py": "2f30ae8c2cceec635319372792e6a81cda099ea976878b63fe7854af0ce21a5a",
    V20_ROOT / "planora-muni-fspsx-frontier-v20-certificate.json": "daba9312787f7b126c9e8bc72580a99f38b18ba30e9c231988734b510129ea3c",
    V20_ROOT / "planora-muni-fspsx-frontier-v20-freeze-manifest.json": "1711609076c50d22c5610fe0c1974ef7a480ebaf133b81eb6d43a294dca64ba5",
    V20_ROOT / "planora-muni-fspsx-frontier-v20-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    V20_ROOT / "planora-muni-fspsx-frontier-v20-inline-trust-root.txt": "38b57204852abdaee70853df44a4a8d6348157f4bca9fa3c1d852e9dd78121cf",
    V20_ROOT / "planora-muni-fspsx-frontier-v20-launcher.sh": "31fa5e7ca0a45a676dfed2533b2cd7a1a2bc35cf1adc0eb67fc9c8c7059f59e7",
    V20_ROOT / "planora-muni-fspsx-frontier-v20-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    V20_ROOT / "planora-muni-fspsx-frontier-v20-runner.py": "88a83e978e831d47048034caf931269085253974e74cef15dc94a32d34fbb9eb",
    V20_ROOT / "planora-muni-fspsx-frontier-v20-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    V20_ROOT / "planora-muni-fspsx-frontier-v20-supervisor.py": "ce399b471f37b44f28d97dc30b50b63f4651a4be58327c18a96b855a5b2aa3a7",
    V20_ROOT / "planora-muni-fspsx-frontier-v20-tests.py": "974f62b283f1c50b0ae221a47d5411f11a4059cd53c1a496dc4eb45f2dfd81d1",
    V20_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json": "aa7657d1c3e3c2362312ae0a07013373640fc5b777aa069dca107420393b8dc4",
}
V21_ROOT = CHAIN_ROOT.parent / "muni_v21"
V21_PRESERVED_HASHES = {
    V21_ROOT / "planora_muni_v21_benchmarks_stub.py": "40488f0af25e5457841ef6577bfdb3fda2a65a7facd5e608e03d5be2084688f2",
    V21_ROOT / "planora-muni-fspsx-frontier-v21-bootstrap.py": "a29f73b20027a1ca6f1875da7c401b6211dea9873c2b4de5c997a5fec47a5cb8",
    V21_ROOT / "planora-muni-fspsx-frontier-v21-certificate.json": "7b0cb96b6fbeeb73b1a64f5cad5ce784d6486dff929cab8889d002d396f20ff2",
    V21_ROOT / "planora-muni-fspsx-frontier-v21-freeze-manifest.json": "feeb01747497b1f6c6eb823b28116c984fd95bdca3cfae853eed862527bade2e",
    V21_ROOT / "planora-muni-fspsx-frontier-v21-generic-validator.py": "6eabef6ba3e02297a3eb7723cf549360f1239d8e5fbc0ef48ed2b7d19ff5918a",
    V21_ROOT / "planora-muni-fspsx-frontier-v21-inline-trust-root.txt": "613f11eab64d0ebad82109efddc2e7f607b20cebf8110b62d2134dca5ab78e28",
    V21_ROOT / "planora-muni-fspsx-frontier-v21-launcher.sh": "cd0dbddbf05654c374c9315206d08e2afc4b3c0ffb41b13bed5fde2cbe9fd78f",
    V21_ROOT / "planora-muni-fspsx-frontier-v21-minimal-tcb.sha256": "825b4b6656b67d706499095b184e55a0fe132310e7a92c7700634e8f0b26ffea",
    V21_ROOT / "planora-muni-fspsx-frontier-v21-runner.py": "bf4938fcf50ec558143a0e56e97877bf2edde593ecbb3b71484219c8527b4c03",
    V21_ROOT / "planora-muni-fspsx-frontier-v21-stdlib.sha256": "355b5ec890f56f6943bafe4c2794710b9df08a85a6933ef0e6da81db96984327",
    V21_ROOT / "planora-muni-fspsx-frontier-v21-supervisor.py": "31edc9d95c0b7cf4d552cb1bc98261f4de9920d4773ff1b62fffd19b72f30e36",
    V21_ROOT / "planora-muni-fspsx-frontier-v21-tests.py": "efee6c6b58d17261a6961a5f28a864ef9b76ca3742ed1b3e30d69243c89c9777",
    V21_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json": "aa7657d1c3e3c2362312ae0a07013373640fc5b777aa069dca107420393b8dc4",
}
V21_STALE_CP_MODEL_WARNING_SHA256 = (
    "8ccd32d856725a1641048e879e833eceb2edd7beeb5bc53146d3a03aa80ec136"
)


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_windows_safe_supervisor_subset(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    wanted = {
        "ProcObservationError",
        "ProcessStatusMemoryUnavailable",
        "ProcessGroupGeneration",
        "_confirmed_proc_disappearance",
        "proc_stat_identity",
        "process_group_snapshot",
        "refresh_process_group_generation",
        "admitted_generation_snapshot",
        "read_process_memory_status_once",
        "identity_pinned_process_memory",
        "identity_pinned_process_memory_snapshot",
        "signal_process_group_snapshot",
        "stop_process_group",
        "sealed_import_probe_accepted",
    }
    body = [
        node
        for node in tree.body
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
        )
        or (
            isinstance(node, (ast.FunctionDef, ast.ClassDef))
            and node.name in wanted
        )
    ]
    selected = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    module = types.ModuleType("planora_muni_v26_supervisor_windows_static_tests")
    signal_compat = types.SimpleNamespace(
        **{name: getattr(signal, name) for name in dir(signal) if not name.startswith("__")}
    )
    if not hasattr(signal_compat, "SIGKILL"):
        signal_compat.SIGKILL = 9
    module.__dict__.update({
        "errno": errno,
        "os": os,
        "Path": Path,
        "signal": signal_compat,
        "subprocess": subprocess,
        "time": time,
        "TERMINATION_GRACE_SECONDS": 5.0,
        "SEALED_IMPORT_PROBE_WALL_SECONDS": 180.0,
        "WHOLE_LAUNCH_MEMORY_CAP_KIB": 700_000,
    })
    exec(compile(selected, str(path), "exec"), module.__dict__)
    return module


if os.name == "nt":
    runner = types.SimpleNamespace()
    supervisor = load_windows_safe_supervisor_subset(SUPERVISOR)
    bootstrap = types.SimpleNamespace()
else:
    runner = load(RUNNER, "planora_muni_v26_runner_tests")
    supervisor = load(SUPERVISOR, "planora_muni_v26_supervisor_tests")
    bootstrap = load(BOOTSTRAP, "planora_muni_v26_bootstrap_tests")


def memfd(name: str, value: bytes) -> int:
    descriptor = os.memfd_create(name, getattr(os, "MFD_ALLOW_SEALING", 2))
    os.write(descriptor, value)
    os.fchmod(descriptor, 0o400)
    import fcntl

    fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, runner.ALL_SEALS)
    return descriptor


def empty_bundle() -> runner.RuntimeBundleAdmission:
    return runner.RuntimeBundleAdmission(3, 4, "0" * 64, {}, {}, {})


def python_capture_evidence() -> dict[str, dict[str, int]]:
    row = os.stat("/proc/self/exe")
    return {
        "python_binary": {
            "device": int(row.st_dev),
            "inode": int(row.st_ino),
            "size": int(row.st_size),
            "file_type": stat.S_IFMT(row.st_mode),
            "mode": stat.S_IMODE(row.st_mode),
            "uid": int(row.st_uid),
            "nlink": int(row.st_nlink),
        }
    }


def maps_row(row: os.stat_result, path: str) -> str:
    return (
        "00400000-00401000 r-xp 00000000 "
        f"{os.major(row.st_dev):02x}:{os.minor(row.st_dev):02x} "
        f"{row.st_ino} {path}"
    )


def runtime_record(sources: dict[str, bytes]) -> bytes:
    rows: list[str] = []
    for relative, raw in sorted(sources.items()):
        encoded = base64.urlsafe_b64encode(sha256(raw).digest()).rstrip(b"=")
        rows.append(
            f"{relative},sha256={encoded.decode('ascii')},{len(raw)}\n"
        )
    return "".join(rows).encode("utf-8")


@contextlib.contextmanager
def synthetic_runtime_source_tree(sources: dict[str, bytes]):
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="muni-v26-cache-release-") as raw:
        root = Path(raw)
        site_packages = root / "site-packages"
        bundle_root = root / "bundle"
        site_packages.mkdir()
        bundle_root.mkdir()
        for relative, value in sources.items():
            source = site_packages / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(value)
            source.chmod(0o444)
        record_bytes = runtime_record(sources)
        record_fd = memfd("synthetic-runtime-record", record_bytes)
        root_fd = os.open(bundle_root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            yield site_packages, root_fd, {
                "runtime_test_record": {"fd": record_fd, "size": len(record_bytes)}
            }
        finally:
            os.close(root_fd)
            os.close(record_fd)


def descriptor_snapshot() -> dict[int, tuple[int, ...]]:
    """Return an identity-bound snapshot of every descriptor held by this process."""

    snapshot: dict[int, tuple[int, ...]] = {}
    for raw_descriptor in os.listdir("/proc/self/fd"):
        descriptor = int(raw_descriptor)
        try:
            row = os.fstat(descriptor)
        except OSError:
            continue
        snapshot[descriptor] = (
            int(row.st_dev),
            int(row.st_ino),
            stat.S_IFMT(row.st_mode),
            stat.S_IMODE(row.st_mode),
            int(row.st_uid),
            int(row.st_nlink),
        )
    return snapshot


def run_inline_trust_race(
    source: Path, expected: str, *, phase: str
) -> tuple[subprocess.Popen[bytes], int, int]:
    ready_read, ready_write = os.pipe()
    continue_read, continue_write = os.pipe()
    payload = INLINE_TRUST.read_text()
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PLANORA_V10_TRUST_TEST_PHASE": phase,
        "PLANORA_V10_TRUST_TEST_READY_FD": str(ready_write),
        "PLANORA_V10_TRUST_TEST_CONTINUE_FD": str(continue_read),
    }
    process = subprocess.Popen(
        [
            str(PYTHON), "-I", "-S", "-B", "-c", payload,
            "--inline-trust-v1", str(source), expected,
            sha256(payload.encode()).hexdigest(),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        pass_fds=(ready_write, continue_read),
        env=environment,
    )
    os.close(ready_write)
    os.close(continue_read)
    return process, ready_read, continue_write


def run_validator_bootstrap(source: bytes) -> subprocess.CompletedProcess[bytes]:
    stdlib_fd = memfd("stdlib-manifest", STDLIB_MANIFEST.read_bytes())
    runtime_manifest = json.dumps(
        {"entries": []}, sort_keys=True, separators=(",", ":")
    ).encode()
    runtime_manifest_fd = memfd("runtime-manifest", runtime_manifest)
    validator_fd = memfd("validator", source)
    with tempfile.TemporaryDirectory(dir="/tmp") as raw:
        os.chmod(raw, 0o500)
        runtime_root_fd = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
        try:
            return subprocess.run(
                [
                    str(PYTHON), "-I", "-S", "-B", "-c",
                    runner.VALIDATOR_BOOTSTRAP,
                    str(stdlib_fd), runner.EXPECTED_HASHES["stdlib_manifest"],
                    str(runtime_root_fd), str(runtime_manifest_fd),
                    sha256(runtime_manifest).hexdigest(), "{}",
                    str(validator_fd), sha256(source).hexdigest(),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                pass_fds=(
                    stdlib_fd, runtime_manifest_fd, validator_fd,
                    runtime_root_fd,
                ),
                env={
                    "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8", "TZ": "UTC",
                },
                timeout=10,
                check=False,
            )
        finally:
            os.close(runtime_root_fd)
            os.close(stdlib_fd)
            os.close(runtime_manifest_fd)
            os.close(validator_fd)


class V26ProcObservationRegressionTests(unittest.TestCase):
    @staticmethod
    def stat_text(pid: int, pgid: int, sid: int, start: int) -> str:
        return f"{pid} (cmd) S 1 {pgid} {sid} " + ("0 " * 15) + f"{start}\n"

    def test_proc_stat_identity_returns_none_only_for_confirmed_disappearance(self) -> None:
        for failure in (
            FileNotFoundError(errno.ENOENT, "gone"),
            ProcessLookupError(errno.ESRCH, "gone"),
        ):
            with self.subTest(errno=failure.errno), mock.patch.object(
                supervisor.Path, "read_text", side_effect=failure
            ):
                self.assertIsNone(supervisor.proc_stat_identity(41))

    def test_proc_stat_identity_rejects_permission_and_io_failures(self) -> None:
        for failure in (
            PermissionError(errno.EACCES, "denied"),
            OSError(errno.EIO, "io"),
        ):
            with self.subTest(errno=failure.errno), mock.patch.object(
                supervisor.Path, "read_text", side_effect=failure
            ):
                with self.assertRaises(supervisor.ProcObservationError):
                    supervisor.proc_stat_identity(42)

    def test_proc_stat_identity_rejects_every_malformed_identity_shape(self) -> None:
        malformed = (
            "42 malformed",
            "42 (cmd) S 1 42",
            "42 (cmd) S 1 bad 42 " + ("0 " * 15) + "100\n",
        )
        for value in malformed:
            with self.subTest(value=value), mock.patch.object(
                supervisor.Path, "read_text", return_value=value
            ):
                with self.assertRaises(supervisor.ProcObservationError):
                    supervisor.proc_stat_identity(42)

    def test_process_group_enumeration_failure_is_not_empty(self) -> None:
        with mock.patch.object(
            supervisor.os,
            "scandir",
            side_effect=OSError(errno.EIO, "enumeration failed"),
        ):
            with self.assertRaises(supervisor.ProcObservationError):
                supervisor.process_group_snapshot(51)

    def test_process_group_identity_read_failure_is_not_empty(self) -> None:
        entry = types.SimpleNamespace(name="51")
        with (
            mock.patch.object(supervisor.os, "scandir", return_value=(entry,)),
            mock.patch.object(
                supervisor,
                "proc_stat_identity",
                side_effect=supervisor.ProcObservationError("identity failed"),
            ),
        ):
            with self.assertRaises(supervisor.ProcObservationError):
                supervisor.process_group_snapshot(51)

    def test_memory_accounting_rejects_observation_uncertainty(self) -> None:
        identity = (61, 61, 100)
        generation = supervisor.ProcessGroupGeneration(61, 61, identity)
        with mock.patch.object(
            supervisor,
            "proc_stat_identity",
            side_effect=supervisor.ProcObservationError("memory identity uncertain"),
        ):
            with self.assertRaises(supervisor.ProcObservationError):
                supervisor.identity_pinned_process_memory_snapshot(
                    generation,
                    supervisor_pid=99,
                    supervisor_identity=(99, 99, 200),
                )

    def test_signal_continues_after_one_identity_observation_failure(self) -> None:
        first = (71, (70, 70, 100))
        second = (72, (70, 70, 200))
        with (
            mock.patch.object(
                supervisor.os, "pidfd_open", side_effect=(81, 82), create=True
            ),
            mock.patch.object(
                supervisor,
                "proc_stat_identity",
                side_effect=(
                    supervisor.ProcObservationError("first uncertain"),
                    second[1],
                ),
            ),
            mock.patch.object(supervisor.os, "close"),
            mock.patch.object(
                supervisor.signal, "pidfd_send_signal", create=True
            ) as send,
        ):
            result = supervisor.signal_process_group_snapshot(
                70, (first, second), signal.SIGTERM
            )
        self.assertEqual(
            tuple(row["pid"] for row in result["identity_observation_failures"]),
            (71,),
        )
        self.assertEqual(result["signaled_pids"], (72,))
        send.assert_called_once_with(82, signal.SIGTERM, None, 0)

    def test_cleanup_retains_admitted_members_and_rejects_false_empty(self) -> None:
        leader = (80, 80, 100)
        member = (80, 80, 200)
        generation = supervisor.ProcessGroupGeneration(80, 80, leader)
        generation.members[81] = member
        process = mock.Mock(pid=80, returncode=None)
        process.wait.side_effect = subprocess.TimeoutExpired(("child",), 0)
        signal_results = []

        def capture_signal(_pgid, snapshot, signum):
            signal_results.append((signum, snapshot))
            return {
                "identity_observation_failures": (),
                "numeric_pgid_signal_sent": False,
            }

        identities = {80: leader, 81: member}
        with (
            mock.patch.object(
                supervisor,
                "refresh_process_group_generation",
                side_effect=supervisor.ProcObservationError("enumeration uncertain"),
            ),
            mock.patch.object(
                supervisor,
                "proc_stat_identity",
                side_effect=lambda pid: identities[pid],
            ),
            mock.patch.object(
                supervisor,
                "process_group_snapshot",
                side_effect=supervisor.ProcObservationError("final scan uncertain"),
            ),
            mock.patch.object(
                supervisor, "signal_process_group_snapshot", side_effect=capture_signal
            ),
            mock.patch.object(supervisor, "TERMINATION_GRACE_SECONDS", 0.0),
        ):
            cleanup = supervisor.stop_process_group(process, generation, None)
        self.assertEqual(signal_results[0][1], ((80, leader), (81, member)))
        self.assertEqual(signal_results[1][1], ((80, leader), (81, member)))
        self.assertTrue(cleanup["observation_errors"])
        self.assertFalse(cleanup["original_pgid_asserted_empty"])
        self.assertFalse(cleanup["pid_reuse_guard_passed"])
        self.assertTrue(cleanup["errors"])

    def test_probe_acceptance_rejects_observation_uncertainty(self) -> None:
        accepted = supervisor.sealed_import_probe_accepted(
            errors=(),
            stop_reason="normal_exit",
            child_exit=0,
            cleanup={
                "errors": (),
                "observation_errors": ("proc uncertain",),
                "original_pgid_asserted_empty": True,
            },
            child_report={"status": "PASS"},
            final_elapsed_seconds=1.0,
            peak_whole_memory_kib=1,
        )
        self.assertFalse(accepted)


class StaticContractTests(unittest.TestCase):
    def test_v26_final_core_parent_and_authorization_state(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-freeze-manifest.json").read_bytes()
        )
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-certificate.json").read_bytes()
        )
        self.assertEqual(
            certificate["current_source_hashes"]["itc2019_decomposed"],
            "0b6f07a64c139f3cfdcc9d5dd8ce945be1d7278e7f52b6eee2719e1f5560debf",
        )
        self.assertEqual(manifest["parent_chain"]["version"], "v25")
        self.assertEqual(
            manifest["parent_chain"]["builder_sha256"],
            "d6b379e7307e803023d9f6726f36a4cf7d69411f1a6c9f228cc9edd51ea3c028",
        )
        finding = certificate["parent_v25_review_finding"]
        self.assertEqual(finding["status"], "FIXED_IN_V26_PENDING_STATIC_VERIFICATION")
        self.assertIn("observation uncertainty", finding["summary"])
        self.assertFalse(finding["v25_modified"])
        stale = certificate["stale_v24_evidence"]
        self.assertEqual(stale["status"], "STALE_UNAUTHORIZED_NOT_USED_AS_RUNTIME_PARENT")
        self.assertEqual(
            stale["superseded_shared_core_sha256"],
            "b4da091fae2d4d2a2400d700eddf06ce724db269a9e50fb01efd9d63c3cab66d",
        )
        self.assertEqual(
            stale["freeze_manifest_sha256"],
            "66a8560e20919cc5825c6c3dc7817b639687fe26ca1088bda21bc6d7eabf0469",
        )
        self.assertFalse(stale["retained_probe_authorized"])
        self.assertFalse(stale["official_launch_authorized"])
        shared = certificate["shared_core_verification_evidence"]
        self.assertEqual(shared["decision"], "PASS")
        self.assertEqual(shared["passed"], 457)
        self.assertEqual(shared["skipped"], 2)
        self.assertEqual(
            shared["receipt_sha256"],
            "fa12c7ac258331407f2882cd69f4ff1e5d779dc955a77971c732c45699d1ed55",
        )
        self.assertEqual(
            shared["focused_test_sha256"],
            "82eed00c7de130f5c198cbf51b2c0b0ee158fe9003ee373812473cd29b189e6d",
        )
        self.assertEqual(certificate["status"], "NO_GO_PENDING_INDEPENDENT_REVIEW")
        self.assertFalse(certificate["authorization"]["retained_probe_authorized"])
        self.assertFalse(certificate["authorization"]["official_launch_authorized"])

    def test_v26_preserves_v25_caps_and_mode_separation(self) -> None:
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-certificate.json").read_bytes()
        )
        resource = certificate["resource_contract"]
        self.assertEqual(resource["launch_memavailable_floor_kib"], 1_900_000)
        self.assertEqual(resource["runtime_memavailable_floor_kib"], 650_000)
        self.assertEqual(resource["process_group_memory_cap_kib"], 700_000)
        self.assertEqual(resource["whole_launch_memory_cap_kib"], 700_000)
        self.assertEqual(resource["runner_seconds"], 600.0)
        self.assertEqual(resource["supervisor_wall_seconds"], 630.0)
        self.assertEqual(resource["sealed_import_probe_wall_seconds"], 180.0)
        self.assertEqual(resource["probe_outer_timeout_seconds"], 210)
        self.assertEqual(resource["official_outer_timeout_seconds"], 660)
        probe = certificate["contained_bwrap_contract"]["sealed_import_probe"]
        launch = certificate["contained_bwrap_contract"]["official_launch"]
        self.assertEqual(len(probe["argv"]), 48)
        self.assertEqual(len(launch["argv"]), 48)
        self.assertNotEqual(probe["argv_nul_sha256"], launch["argv_nul_sha256"])
        self.assertIn("--sealed-import-probe", probe["argv"])
        self.assertNotIn("--launch", probe["argv"])
        self.assertIn("--launch", launch["argv"])
        self.assertNotIn("--sealed-import-probe", launch["argv"])
        probe_text = "\0".join(probe["argv"])
        for forbidden in ("muni-fspsx-fal17.xml", "progress.json", "checkpoint", "--resume"):
            self.assertNotIn(forbidden, probe_text)
    def test_v26_final_core_rejection_evidence_and_authorization_state(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-freeze-manifest.json").read_bytes()
        )
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-certificate.json").read_bytes()
        )
        self.assertEqual(
            certificate["current_source_hashes"]["itc2019_decomposed"],
            "0b6f07a64c139f3cfdcc9d5dd8ce945be1d7278e7f52b6eee2719e1f5560debf",
        )
        self.assertEqual(manifest["parent_chain"]["version"], "v23")
        self.assertEqual(
            manifest["parent_chain"]["builder_sha256"],
            "574f549bcacb773097ebf2f1ff242068f8113609127f96c26ab2e94b9a6c6df8",
        )
        rejection = certificate["parent_v23_rejection_evidence"]
        self.assertEqual(rejection["decision"], "REJECTED_FAIL_CLOSED_SOURCE_PIN_DRIFT")
        self.assertEqual(rejection["probe_id"], "492e7d9acc434363b37e222289e8e554")
        self.assertFalse(rejection["child_started"])
        self.assertFalse(rejection["official_instance_opened"])
        self.assertFalse(rejection["solver_execution_started"])
        self.assertEqual(
            rejection["rejection_context"],
            "concurrent source drift while PU optimization remained active",
        )
        self.assertEqual(
            rejection["post_exit_sha256_while_concurrent_pu_optimization_active"],
            "b4da091fae2d4d2a2400d700eddf06ce724db269a9e50fb01efd9d63c3cab66d",
        )
        self.assertEqual(
            rejection["receipt_sha256"],
            "070dea2afc4d590e1e0e4e3f25e35f9f0bbb218a5acbf71acd4de38fb2af1837",
        )
        stale = certificate["stale_v24_evidence"]
        self.assertEqual(stale["status"], "STALE_UNAUTHORIZED_NOT_USED_AS_RUNTIME_PARENT")
        self.assertEqual(
            stale["superseded_shared_core_sha256"],
            "b4da091fae2d4d2a2400d700eddf06ce724db269a9e50fb01efd9d63c3cab66d",
        )
        self.assertEqual(
            stale["freeze_manifest_sha256"],
            "66a8560e20919cc5825c6c3dc7817b639687fe26ca1088bda21bc6d7eabf0469",
        )
        self.assertFalse(stale["retained_probe_authorized"])
        self.assertFalse(stale["official_launch_authorized"])
        shared = certificate["shared_core_verification_evidence"]
        self.assertEqual(shared["decision"], "PASS")
        self.assertEqual(shared["passed"], 457)
        self.assertEqual(shared["skipped"], 2)
        self.assertEqual(
            shared["receipt_sha256"],
            "fa12c7ac258331407f2882cd69f4ff1e5d779dc955a77971c732c45699d1ed55",
        )
        self.assertEqual(
            shared["focused_test_sha256"],
            "82eed00c7de130f5c198cbf51b2c0b0ee158fe9003ee373812473cd29b189e6d",
        )
        self.assertEqual(certificate["status"], "NO_GO_PENDING_INDEPENDENT_REVIEW")
        self.assertFalse(certificate["authorization"]["retained_probe_authorized"])
        self.assertFalse(certificate["authorization"]["official_launch_authorized"])

    def test_v26_preserves_v23_caps_and_mode_separation(self) -> None:
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-certificate.json").read_bytes()
        )
        resource = certificate["resource_contract"]
        self.assertEqual(resource["launch_memavailable_floor_kib"], 1_900_000)
        self.assertEqual(resource["runtime_memavailable_floor_kib"], 650_000)
        self.assertEqual(resource["process_group_memory_cap_kib"], 700_000)
        self.assertEqual(resource["whole_launch_memory_cap_kib"], 700_000)
        self.assertEqual(resource["runner_seconds"], 600.0)
        self.assertEqual(resource["supervisor_wall_seconds"], 630.0)
        self.assertEqual(resource["sealed_import_probe_wall_seconds"], 180.0)
        self.assertEqual(resource["probe_outer_timeout_seconds"], 210)
        self.assertEqual(resource["official_outer_timeout_seconds"], 660)
        probe = certificate["contained_bwrap_contract"]["sealed_import_probe"]
        launch = certificate["contained_bwrap_contract"]["official_launch"]
        self.assertEqual(len(probe["argv"]), 48)
        self.assertEqual(len(launch["argv"]), 48)
        self.assertNotEqual(probe["argv_nul_sha256"], launch["argv_nul_sha256"])
        self.assertIn("--sealed-import-probe", probe["argv"])
        self.assertNotIn("--launch", probe["argv"])
        self.assertIn("--launch", launch["argv"])
        self.assertNotIn("--sealed-import-probe", launch["argv"])
        probe_text = "\0".join(probe["argv"])
        for forbidden in ("muni-fspsx-fal17.xml", "progress.json", "checkpoint", "--resume"):
            self.assertNotIn(forbidden, probe_text)
    def test_direct_v25_parent_and_exact_bwrap_contract(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-freeze-manifest.json").read_bytes()
        )
        parent = manifest["parent_chain"]
        self.assertEqual(parent["version"], "v25")
        self.assertEqual(
            parent["freeze_manifest_sha256"],
            "291643f45c93c31199e4b3294eb1edcc36d867abc760653375e3833dbea9d905",
        )
        self.assertEqual(
            parent["implementation_certificate_sha256"],
            "ca2324b21c89f2fea30c4ee5376796e47667b75ed4875aac34e8aae40f8083aa",
        )
        certificate = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-certificate.json").read_bytes()
        )
        for label in ("sealed_import_probe", "official_launch"):
            contract = certificate["contained_bwrap_contract"][label]
            argv = contract["argv"]
            self.assertEqual(len(argv), 48)
            encoded = ("\0".join(argv) + "\0").encode("utf-8")
            self.assertEqual(sha256(encoded).hexdigest(), contract["argv_nul_sha256"])
    def test_v21_frozen_artifacts_and_staged_audit_remain_byte_exact(self) -> None:
        for path, expected in V21_PRESERVED_HASHES.items():
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), expected)
        self.assertEqual(
            (CHAIN_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json").read_bytes(),
            (V21_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json").read_bytes(),
        )

    def test_v20_frozen_artifacts_and_staged_audit_remain_byte_exact(self) -> None:
        for path, expected in V20_PRESERVED_HASHES.items():
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), expected)
        self.assertEqual(
            (CHAIN_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json").read_bytes(),
            (V20_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json").read_bytes(),
        )

    def test_v19_frozen_artifacts_and_staged_audit_remain_byte_exact(self) -> None:
        for path, expected in V19_PRESERVED_HASHES.items():
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), expected)
        self.assertEqual(
            (CHAIN_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json").read_bytes(),
            (V19_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json").read_bytes(),
        )

    def test_v18_frozen_artifacts_and_staged_audit_remain_byte_exact(self) -> None:
        for path, expected in V18_PRESERVED_HASHES.items():
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), expected)
        self.assertEqual(
            (CHAIN_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json").read_bytes(),
            (V18_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json").read_bytes(),
        )

    def test_v17_frozen_artifacts_remain_byte_exact(self) -> None:
        for path, expected in V17_PRESERVED_HASHES.items():
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), expected)

    def test_v16_frozen_artifacts_remain_byte_exact(self) -> None:
        for path, expected in V16_PRESERVED_HASHES.items():
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), expected)

    def test_v15_frozen_artifacts_remain_byte_exact(self) -> None:
        for raw_path, expected in V15_PRESERVED_HASHES.items():
            self.assertEqual(sha256(Path(raw_path).read_bytes()).hexdigest(), expected)

    def test_v14_frozen_artifacts_remain_byte_exact(self) -> None:
        for raw_path, expected in V14_PRESERVED_HASHES.items():
            self.assertEqual(sha256(Path(raw_path).read_bytes()).hexdigest(), expected)

    def test_v13_frozen_artifacts_remain_byte_exact(self) -> None:
        for raw_path, expected in V13_PRESERVED_HASHES.items():
            self.assertEqual(sha256(Path(raw_path).read_bytes()).hexdigest(), expected)

    def test_v12_frozen_artifacts_remain_byte_exact(self) -> None:
        for raw_path, expected in V12_PRESERVED_HASHES.items():
            self.assertEqual(
                sha256(Path(raw_path).read_bytes()).hexdigest(), expected
            )

    def test_final_shared_open_hint_hashes_are_pinned(self) -> None:
        self.assertEqual(
            runner.EXPECTED_HASHES["frontier"],
            "ade6b42c3baa08a53454db3842b0c4f3cd2e2738c6eb0c54108f419a148d7793",
        )
        source = SUPERVISOR.read_text()
        self.assertIn("ef125a8c9ea64500074700fe0f6b445f5f686832f0f32bf39bc6f35430615ed0", source)

    def test_v26_preserves_all_v18_resource_floors_and_limits(self) -> None:
        self.assertEqual(supervisor.LAUNCH_MEMAVAILABLE_FLOOR_KIB, 1_900_000)
        self.assertEqual(supervisor.RUNTIME_MEMAVAILABLE_FLOOR_KIB, 650_000)
        self.assertEqual(supervisor.PROCESS_GROUP_MEMORY_CAP_KIB, 700_000)
        self.assertEqual(supervisor.WHOLE_LAUNCH_MEMORY_CAP_KIB, 700_000)
        self.assertEqual(supervisor.WALL_SECONDS, 630.0)
        self.assertEqual(supervisor.SEALED_IMPORT_PROBE_WALL_SECONDS, 180.0)
        self.assertEqual(supervisor.MAX_RUNTIME_BUNDLE_FILES, 6_000)
        self.assertEqual(supervisor.MAX_RUNTIME_BUNDLE_BYTES, 512 << 20)
        self.assertEqual(supervisor.MAX_RUNTIME_FILE_BYTES, 128 << 20)
        self.assertEqual(
            supervisor.EXPECTED_RUNTIME_CACHE_RELEASE_TELEMETRY_SHA256,
            "426a8b55f35aba4cabef808823cf9e25b3dd546dcb506a75bee6c10c4126105a",
        )
        self.assertEqual(
            runner.EXPECTED_RUNTIME_CACHE_RELEASE_TELEMETRY_SHA256,
            supervisor.EXPECTED_RUNTIME_CACHE_RELEASE_TELEMETRY_SHA256,
        )

    def test_current_quality_closure_and_certificate_paths_are_unambiguous(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-freeze-manifest.json").read_bytes()
        )
        rows = {row["label"]: row for row in manifest["files"]}
        self.assertEqual(
            rows["itc2019_violation_lns"]["sha256"],
            "9f1e4f66c4fadea2813ec86de451206102928c5c7b1dfdf786d900c8dc137343",
        )
        self.assertEqual(
            rows["test_violation_lns"]["sha256"],
            "f1e3da3e1b2727e3f62a58864fc51cf44037f236d2f4d7a894bc212724fae91e",
        )
        self.assertEqual(
            manifest["code_review_certificate_path"],
            str(CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-certificate.json"),
        )
        fairness = manifest["fairness_provenance"]
        self.assertNotIn("certificate_path", fairness)
        self.assertEqual(
            fairness["derivation_audit_path"],
            "/tmp/planora-muni-fspsx-v35-derivation-audit-v1.json",
        )
        self.assertEqual(
            rows["fairness_certificate"]["path"],
            fairness["derivation_audit_path"],
        )
        self.assertEqual(
            rows["fairness_certificate"]["sha256"],
            fairness["derivation_audit_sha256"],
        )

    def test_runtime_manifest_contract_rejects_repository_fairness_path(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-freeze-manifest.json").read_bytes()
        )
        broken = copy.deepcopy(manifest)
        repository_path = str(
            CHAIN_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json"
        )
        broken["fairness_provenance"]["derivation_audit_path"] = repository_path
        rows = {row["label"]: row for row in broken["files"]}
        rows["fairness_certificate"]["path"] = repository_path
        with self.assertRaisesRegex(
            RuntimeError, "fairness provenance certificate pin rejected"
        ):
            supervisor.validate_manifest_contract(broken)

    def test_runtime_manifest_contract_accepts_exact_staged_fairness_pin(self) -> None:
        manifest = json.loads(
            (CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-freeze-manifest.json").read_bytes()
        )
        audit_bytes = (
            CHAIN_ROOT / "planora-muni-fspsx-v35-derivation-audit-v1.json"
        ).read_bytes()
        requested: list[Path] = []

        def capture(path: Path) -> tuple[bytes, tuple[int, ...]]:
            requested.append(path)
            if path != Path("/tmp/planora-muni-fspsx-v35-derivation-audit-v1.json"):
                raise AssertionError(f"unexpected manifest-contract read: {path}")
            return audit_bytes, ()

        with mock.patch.object(supervisor, "capture_regular", side_effect=capture):
            supervisor.validate_manifest_contract(manifest)
        self.assertEqual(
            requested,
            [Path("/tmp/planora-muni-fspsx-v35-derivation-audit-v1.json")],
        )
        self.assertEqual(
            sha256(audit_bytes).hexdigest(),
            manifest["fairness_provenance"]["derivation_audit_sha256"],
        )

    def test_complete_runtime_record_closure_is_declared(self) -> None:
        expected = {
            "ortools", "numpy", "pandas", "dateutil", "six", "absl",
            "immutabledict", "google", "typing_extensions",
        }
        self.assertEqual(set(runner.RUNTIME_RECORD_LABELS), expected)
        self.assertEqual(set(supervisor.RUNTIME_RECORDS), set(runner.RUNTIME_RECORD_LABELS.values()))

    def test_fresh_planora_source_closure_is_complete_and_progress_excluded(self) -> None:
        expected_modules = {
            f"benchmarks.{label}" for label in supervisor.PLANORA_FRESH_MODULES
        }
        self.assertTrue(expected_modules <= set(runner.SEALED_SOURCE_MODULE_LABELS))
        self.assertNotIn("progress", runner.EXPECTED_CAPTURE_LABELS)
        self.assertIn("fairness_certificate", runner.EXPECTED_CAPTURE_LABELS)
        self.assertNotIn('"progress": (PROGRESS', SUPERVISOR.read_text())
        self.assertNotIn('SEALED_SOURCE_EVIDENCE["progress"]', RUNNER.read_text())
        self.assertIn("solve_itc2019_native", RUNNER.read_text())

    def test_runner_and_supervisor_import_without_repo_or_third_party_import(self) -> None:
        script = (
            "import importlib.util,sys;"
            f"paths={[str(RUNNER), str(SUPERVISOR)]!r};"
            "exec('for i,p in enumerate(paths):\\n s=importlib.util.spec_from_file_location(\"isolated_\"+str(i),p)\\n m=importlib.util.module_from_spec(s)\\n sys.modules[s.name]=m\\n s.loader.exec_module(m)');"
            "assert 'ortools' not in sys.modules and 'benchmarks' not in sys.modules "
            "and 'pandas' not in sys.modules"
        )
        completed = subprocess.run(
            [str(PYTHON), "-I", "-S", "-B", "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_direct_entries_are_inert_and_open_no_official_sources(self) -> None:
        for path in (RUNNER, SUPERVISOR):
            completed = subprocess.run(
                [str(PYTHON), "-I", "-S", "-B", str(path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["status"], "NOT_LAUNCHED")

    def test_launcher_gate_is_inert_without_irreversible_flag(self) -> None:
        completed = subprocess.run(
            [str(LAUNCHER)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "NOT_LAUNCHED")

    def test_direct_bootstrap_pathname_invocation_fails_closed(self) -> None:
        completed = subprocess.run(
            [str(PYTHON), "-I", "-S", "-B", str(BOOTSTRAP)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(
            "direct bootstrap pathname execution rejected" in completed.stderr
            or "inline trust evidence absent" in completed.stderr,
            completed.stderr,
        )


class CaptureAndBootstrapTests(unittest.TestCase):
    def test_live_file_drift_and_restore_after_capture_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            path = Path(raw) / "source.py"
            original = b"reviewed\n"
            path.write_bytes(original)
            descriptor, evidence = supervisor._stream_capture(
                path, sha256(original).hexdigest(), "synthetic"
            )
            try:
                # The WSL-backed filesystem can expose one-second ctime granularity.
                time.sleep(1.05)
                path.write_bytes(b"attacker\n")
                path.write_bytes(original)
                self.assertEqual(
                    supervisor.verify_sealed_capture(descriptor, evidence)["sha256"],
                    sha256(original).hexdigest(),
                )
                with self.assertRaisesRegex(RuntimeError, "mutation event|mutation-clock"):
                    supervisor.verify_source_contract(evidence)
            finally:
                os.close(descriptor)
                os.close(int(evidence["source_watch_fd"]))

    def test_capture_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            root = Path(raw)
            target = root / "target"
            target.write_bytes(b"x")
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaises(OSError):
                supervisor._stream_capture(link, sha256(b"x").hexdigest(), "link")

    def test_mutable_or_symlink_launcher_bootstrap_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            link = Path(raw) / "launcher.sh"
            link.symlink_to(LAUNCHER)
            with self.assertRaises(OSError):
                bootstrap.capture_launcher(
                    link, sha256(LAUNCHER.read_bytes()).hexdigest()
                )
            completed = subprocess.run(
                [
                    "/bin/bash", str(LAUNCHER), "--dry-run",
                    "--expected-launcher-sha256", sha256(LAUNCHER.read_bytes()).hexdigest(),
                    "--expected-supervisor-sha256", "0" * 64,
                    "--expected-manifest-sha256", "0" * 64,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("bootstrap-launcher-evidence", completed.stderr)

    def test_inline_trust_executes_sealed_bootstrap_after_live_restore(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            root = Path(raw)
            marker = root / "marker"
            source = root / "bootstrap.py"
            original = (
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('original')\n"
                + "#" * 4096
                + "\n"
            ).encode()
            attacker = (
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('attacker')\n"
                + "#" * 4096
                + "\n"
            ).encode()
            source.write_bytes(original)
            process, ready, proceed = run_inline_trust_race(
                source, sha256(original).hexdigest(), phase="after_seal"
            )
            try:
                self.assertEqual(os.read(ready, 1), b"1")
                source.write_bytes(attacker)
                source.write_bytes(original)
                os.write(proceed, b"1")
                stdout, stderr = process.communicate(timeout=10)
            finally:
                os.close(ready)
                os.close(proceed)
            self.assertEqual(process.returncode, 0, stderr.decode())
            self.assertEqual(stdout, b"")
            self.assertEqual(marker.read_text(), "original")

    def test_inline_trust_rejects_mutate_restore_during_capture(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            root = Path(raw)
            marker = root / "marker"
            source = root / "bootstrap.py"
            original = (
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('original')\n"
                + "#" * 4096
                + "\n"
            ).encode()
            attacker = b"# attacker\n" + b"x" * 4096
            source.write_bytes(original)
            process, ready, proceed = run_inline_trust_race(
                source, sha256(original).hexdigest(), phase="during_capture"
            )
            try:
                self.assertEqual(os.read(ready, 1), b"1")
                source.write_bytes(attacker)
                source.write_bytes(original)
                os.write(proceed, b"1")
                _stdout, stderr = process.communicate(timeout=10)
            finally:
                os.close(ready)
                os.close(proceed)
            self.assertNotEqual(process.returncode, 0)
            self.assertTrue(
                b"mutation" in stderr
                or b"identity drift" in stderr
                or b"descriptor drift" in stderr,
                stderr.decode(),
            )
            self.assertFalse(marker.exists())

    def test_interpreter_identity_or_hash_mismatch_fails_closed(self) -> None:
        raw = Path("/proc/self/exe").read_bytes()
        evidence = python_capture_evidence()
        evidence["python_binary"]["inode"] += 1
        with self.assertRaisesRegex(RuntimeError, "executing Python"):
            runner.verify_executing_python({"python_binary": raw}, evidence)

    def test_child_environment_is_exact_allowlist(self) -> None:
        env = supervisor.sanitized_child_environment(
            run_directory=Path("/tmp/synthetic-run"),
            run_directory_fd=9,
            captures={"runner": {"fd": 7}},
            runtime_binding={"root_fd": 8},
        )
        self.assertEqual(
            set(env),
            {
                "PATH", "LANG", "LC_ALL", "TZ", "TMPDIR",
                supervisor.CAPTURE_MANIFEST_ENV,
                supervisor.RUNTIME_BUNDLE_ENV,
            },
        )
        for forbidden in (
            "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD", "LD_LIBRARY_PATH",
            "OMP_NUM_THREADS", "MALLOC_ARENA_MAX",
        ):
            self.assertNotIn(forbidden, env)
        source = LAUNCHER.read_text()
        self.assertIn("exec /usr/bin/env -i", source)
        self.assertIn("/usr/bin/python3.12 -I -S -B", source)
        self.assertEqual(env["TMPDIR"], "/proc/self/fd/9")


class RuntimeClosureTests(unittest.TestCase):
    def test_cp_model_warning_hash_matches_record_and_runtime_manifest(self) -> None:
        record_path = supervisor.RUNTIME_RECORDS["runtime_ortools_record"]
        record_raw = record_path.read_bytes()
        self.assertEqual(
            sha256(record_raw).hexdigest(),
            runner.EXPECTED_HASHES["runtime_ortools_record"],
        )

        decoded_rows = {}
        for raw_path, encoded, raw_size in csv.reader(
            record_raw.decode("utf-8").splitlines()
        ):
            if not encoded.startswith("sha256=") or not raw_size:
                continue
            encoded_digest = encoded.removeprefix("sha256=")
            padding = "=" * (-len(encoded_digest) % 4)
            decoded_rows[raw_path] = (
                base64.urlsafe_b64decode(encoded_digest + padding).hex(),
                int(raw_size),
            )
        record_hash, record_size = decoded_rows[runner.CP_MODEL_SOURCE_PATH]

        record_fd = os.open(record_path, os.O_RDONLY)
        try:
            captures = {"runtime_ortools_record": {"fd": record_fd}}
            with mock.patch.object(
                supervisor,
                "RUNTIME_RECORDS",
                {"runtime_ortools_record": record_path},
            ):
                manifest_entries, _excluded = supervisor._record_runtime_entries(
                    captures
                )
        finally:
            os.close(record_fd)
        manifest_hash, manifest_size, manifest_label = manifest_entries[
            runner.CP_MODEL_SOURCE_PATH
        ]

        freeze = json.loads(
            (
                CHAIN_ROOT
                / "planora-muni-fspsx-frontier-v26-freeze-manifest.json"
            ).read_bytes()
        )
        source_rows = [
            row for row in freeze["files"] if row["label"] == "ortools_cp_model"
        ]
        self.assertEqual(len(source_rows), 1)
        self.assertEqual(
            (record_hash, record_size),
            (manifest_hash, manifest_size),
        )
        self.assertEqual(manifest_label, "runtime_ortools_record")
        self.assertEqual(source_rows[0]["sha256"], manifest_hash)
        self.assertEqual(runner.CP_MODEL_SOURCE_SHA256, manifest_hash)
        self.assertEqual(supervisor.CP_MODEL_SOURCE_SHA256, manifest_hash)
        self.assertEqual(
            freeze["sealed_import_probe"]["compile_warning_admission"][
                "source_sha256"
            ],
            manifest_hash,
        )

        frozen_v21 = json.loads(
            (
                V21_ROOT
                / "planora-muni-fspsx-frontier-v21-freeze-manifest.json"
            ).read_bytes()
        )
        stale_hash = frozen_v21["sealed_import_probe"][
            "compile_warning_admission"
        ]["source_sha256"]
        self.assertEqual(stale_hash, V21_STALE_CP_MODEL_WARNING_SHA256)
        self.assertNotEqual(stale_hash, record_hash)

    def test_sealed_loader_captures_compile_warnings_without_stderr(self) -> None:
        source = b"first = ~False\nsecond = ~True\n"
        descriptor = memfd("compile-warning-source", source)
        entry = {
            "fd": descriptor,
            "size": len(source),
            "sha256": sha256(source).hexdigest(),
        }
        bundle = runner.RuntimeBundleAdmission(
            3, 4, "0" * 64, {"synthetic.py": entry}, {}, {},
            compile_warnings=[],
        )
        try:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                runner._SealedSourceLoader(
                    "synthetic", "synthetic.py", entry, bundle, False
                ).get_code("synthetic")
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(len(bundle.compile_warnings or []), 2)
            self.assertTrue(all(
                row["category"] == "DeprecationWarning"
                and row["source_relative_path"] == "synthetic.py"
                and row["source_sha256"] == entry["sha256"]
                for row in bundle.compile_warnings or []
            ))
        finally:
            os.close(descriptor)

    def test_compile_warning_contract_accepts_only_exact_two_pinned_rows(self) -> None:
        expected = {
            "category": "DeprecationWarning",
            "message": runner.CP_MODEL_COMPILE_WARNING_MESSAGE,
            "source_relative_path": runner.CP_MODEL_SOURCE_PATH,
            "source_sha256": runner.CP_MODEL_SOURCE_SHA256,
        }

        def bundle(rows):
            return runner.RuntimeBundleAdmission(
                3, 4, "0" * 64,
                {runner.CP_MODEL_SOURCE_PATH: {
                    "sha256": runner.CP_MODEL_SOURCE_SHA256,
                }},
                {}, {}, compile_warnings=rows,
            )

        admitted = runner.admit_sealed_runtime_compile_warnings(
            bundle([dict(expected), dict(expected)])
        )
        self.assertEqual(admitted["count"], 2)
        self.assertEqual(admitted["child_stderr_bytes"], 0)
        mutations = (
            [dict(expected)],
            [dict(expected), dict(expected), dict(expected)],
            [{**expected, "category": "RuntimeWarning"}, dict(expected)],
            [{**expected, "message": "different"}, dict(expected)],
            [{**expected, "source_relative_path": "other.py"}, dict(expected)],
            [{**expected, "source_sha256": "0" * 64}, dict(expected)],
        )
        for rows in mutations:
            with self.subTest(rows=rows), self.assertRaisesRegex(
                RuntimeError, "compile-warning contract"
            ):
                runner.admit_sealed_runtime_compile_warnings(bundle(rows))

        wrong_source = bundle([dict(expected), dict(expected)])
        wrong_source.entries_by_path[runner.CP_MODEL_SOURCE_PATH]["sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "source pin"):
            runner.admit_sealed_runtime_compile_warnings(wrong_source)

        pinned_bundle = bundle([dict(expected), dict(expected)])
        with mock.patch.object(runner, "CP_MODEL_SOURCE_SHA256", "0" * 64):
            with self.assertRaisesRegex(RuntimeError, "source pin"):
                runner.admit_sealed_runtime_compile_warnings(
                    pinned_bundle
                )

        for warning_index in range(2):
            rows = [dict(expected), dict(expected)]
            rows[warning_index]["source_sha256"] = "0" * 64
            with self.subTest(warning_index=warning_index), self.assertRaisesRegex(
                RuntimeError, "compile-warning contract"
            ):
                runner.admit_sealed_runtime_compile_warnings(bundle(rows))

    def test_real_sealed_runtime_imports_ortools_without_live_site_packages(self) -> None:
        if os.environ.get("PLANORA_MUNI_V26_SKIP_HEAVY") == "1":
            self.skipTest("heavy sealed-runtime import probe disabled by test contract")
        mem_available_kib = next(
            int(line.split()[1])
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith("MemAvailable:")
        )
        if mem_available_kib < 1_900_000:
            self.skipTest(
                "heavy sealed-runtime import probe requires MemAvailable >= 1,900,000 KiB"
            )
        completed = subprocess.run(
            [
                str(PYTHON), "-I", "-S", "-B", "-X",
                "pycache_prefix=/tmp/muni-v26-probe-pyc",
                str(Path(__file__)), "--runtime-import-probe",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "SEALED_RUNTIME_IMPORT_OK")
        self.assertGreater(payload["loaded_file_count"], 0)
        self.assertNotIn("site-packages", payload["module_file"])
        self.assertEqual(payload["compile_warnings"]["count"], 2)
        self.assertEqual(payload["captured_stderr"], "")

    def test_cache_release_occurs_after_stable_read_verification_and_sealing(self) -> None:
        sources = {"example/package.py": b"value = 1\n"}
        with synthetic_runtime_source_tree(sources) as (
            site_packages,
            root_fd,
            captures,
        ):
            source_path = (site_packages / "example/package.py").resolve()
            events: list[str] = []
            runtime_fds: list[int] = []
            original_stream = supervisor._stream_source_to_sealed_memfd

            def tracked_stream(descriptor: int, **kwargs):
                self.assertEqual(
                    Path(os.readlink(f"/proc/self/fd/{descriptor}")).resolve(),
                    source_path,
                )
                result = original_stream(descriptor, **kwargs)
                events.append("stable_read_hash_and_sealed_copy_verified")
                return result

            def tracked_fadvise(
                descriptor: int, offset: int, length: int, advice: int
            ) -> None:
                self.assertEqual(Path(os.readlink(f"/proc/self/fd/{descriptor}")).resolve(), source_path)
                self.assertEqual((offset, length, advice), (0, 0, os.POSIX_FADV_DONTNEED))
                events.append("cache_release_advised")

            with (
                mock.patch.object(supervisor, "SITE_PACKAGES", site_packages),
                mock.patch.object(
                    supervisor,
                    "RUNTIME_RECORDS",
                    {"runtime_test_record": site_packages / "RECORD"},
                ),
                mock.patch.object(
                    supervisor,
                    "_stream_source_to_sealed_memfd",
                    side_effect=tracked_stream,
                ),
                mock.patch.object(os, "posix_fadvise", side_effect=tracked_fadvise),
            ):
                admitted_root, manifest_fd, files, binding, summary = (
                    supervisor.build_runtime_bundle(
                        runtime_root_fd=root_fd,
                        captures=captures,
                    )
                )
            runtime_fds.extend((admitted_root, manifest_fd, *files))
            try:
                self.assertEqual(
                    events,
                    [
                        "stable_read_hash_and_sealed_copy_verified",
                        "cache_release_advised",
                    ],
                )
                self.assertEqual(
                    summary["source_cache_release"]["phase"],
                    supervisor.CACHE_RELEASE_PHASE,
                )
                self.assertEqual(
                    binding["source_cache_release_advisory_count"], 1
                )
            finally:
                for descriptor in runtime_fds:
                    os.close(descriptor)

    def test_cache_release_is_exactly_once_per_source_and_replayed(self) -> None:
        sources = {
            "alpha/one.py": b"one = 1\n",
            "beta/two.py": b"two = 2\n",
        }
        with synthetic_runtime_source_tree(sources) as (
            site_packages,
            root_fd,
            captures,
        ):
            calls: list[str] = []
            runtime_fds: list[int] = []

            real_fadvise = os.posix_fadvise

            def call_real_fadvise(
                descriptor: int, offset: int, length: int, advice: int
            ) -> None:
                calls.append(
                    Path(os.readlink(f"/proc/self/fd/{descriptor}"))
                    .relative_to(site_packages)
                    .as_posix()
                )
                real_fadvise(descriptor, offset, length, advice)

            with (
                mock.patch.object(supervisor, "SITE_PACKAGES", site_packages),
                mock.patch.object(
                    supervisor,
                    "RUNTIME_RECORDS",
                    {"runtime_test_record": site_packages / "RECORD"},
                ),
                mock.patch.object(supervisor, "LAUNCH_MEMAVAILABLE_FLOOR_KIB", 0),
                mock.patch.object(os, "posix_fadvise", side_effect=call_real_fadvise),
            ):
                admitted_root, manifest_fd, files, binding, summary = (
                    supervisor.build_runtime_bundle(
                        runtime_root_fd=root_fd,
                        captures=captures,
                    )
                )
                runtime_fds.extend((admitted_root, manifest_fd, *files))
                replay = supervisor.verify_runtime_bundle_end(binding)
            try:
                self.assertEqual(calls, sorted(sources))
                self.assertEqual(len(calls), len(set(calls)))
                for evidence in (
                    summary["source_cache_release"],
                    replay["source_cache_release"],
                ):
                    self.assertEqual(evidence["advisory_count"], len(sources))
                    self.assertEqual(evidence["source_count"], len(sources))
                    self.assertTrue(evidence["exactly_once_per_source"])
                self.assertEqual(
                    summary["source_cache_release"]["telemetry_sha256"],
                    replay["source_cache_release"]["telemetry_sha256"],
                )
            finally:
                for descriptor in runtime_fds:
                    os.close(descriptor)

    def test_cache_release_failure_propagates_fail_closed(self) -> None:
        sources = {"example/package.py": b"value = 1\n"}
        with synthetic_runtime_source_tree(sources) as (
            site_packages,
            root_fd,
            captures,
        ):
            with (
                mock.patch.object(supervisor, "SITE_PACKAGES", site_packages),
                mock.patch.object(
                    supervisor,
                    "RUNTIME_RECORDS",
                    {"runtime_test_record": site_packages / "RECORD"},
                ),
                mock.patch.object(supervisor, "LAUNCH_MEMAVAILABLE_FLOOR_KIB", 0),
                mock.patch.object(
                    os,
                    "posix_fadvise",
                    side_effect=OSError(errno.EIO, "synthetic fadvise failure"),
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "cache-release advisory failed at index 0",
                ):
                    supervisor.build_runtime_bundle(
                        runtime_root_fd=root_fd,
                        captures=captures,
                    )

    def test_cache_release_is_not_attempted_before_stable_read_completes(self) -> None:
        sources = {"example/package.py": b"value = 1\n"}
        with synthetic_runtime_source_tree(sources) as (
            site_packages,
            root_fd,
            captures,
        ):
            with (
                mock.patch.object(supervisor, "SITE_PACKAGES", site_packages),
                mock.patch.object(
                    supervisor,
                    "RUNTIME_RECORDS",
                    {"runtime_test_record": site_packages / "RECORD"},
                ),
                mock.patch.object(
                    supervisor,
                    "_stream_source_to_sealed_memfd",
                    side_effect=RuntimeError("synthetic incomplete stable read"),
                ),
                mock.patch.object(os, "posix_fadvise") as advisory,
            ):
                with self.assertRaisesRegex(RuntimeError, "incomplete stable read"):
                    supervisor.build_runtime_bundle(
                        runtime_root_fd=root_fd,
                        captures=captures,
                    )
            advisory.assert_not_called()

    def test_cache_release_telemetry_mismatch_is_rejected(self) -> None:
        entries = [
            {"relative_path": "alpha.py", "sha256": "1" * 64, "size": 7},
            {"relative_path": "beta.py", "sha256": "2" * 64, "size": 9},
        ]
        expected = supervisor._expected_cache_release_advisories(entries)
        digest = supervisor._cache_release_telemetry_sha256(expected)
        supervisor._verify_cache_release_telemetry(
            entries,
            expected,
            expected_sha256=digest,
        )
        runner._verify_cache_release_telemetry(
            entries,
            expected,
            expected_sha256=digest,
        )
        mismatches = (
            expected[:-1],
            [*expected, dict(expected[-1])],
            list(reversed(expected)),
            [{**expected[0], "advisory_count": 2}, expected[1]],
        )
        for telemetry in mismatches:
            with self.subTest(telemetry=telemetry):
                with self.assertRaisesRegex(RuntimeError, "telemetry mismatch"):
                    supervisor._verify_cache_release_telemetry(entries, telemetry)
                with self.assertRaisesRegex(RuntimeError, "telemetry mismatch"):
                    runner._verify_cache_release_telemetry(
                        entries,
                        telemetry,
                        expected_sha256=digest,
                    )
        with self.assertRaisesRegex(RuntimeError, "telemetry hash mismatch"):
            supervisor._verify_cache_release_telemetry(
                entries,
                expected,
                expected_sha256="0" * 64,
            )

    def test_phase_boundaries_keep_initial_and_runtime_floors_distinct(self) -> None:
        self.assertEqual(
            supervisor._phase_memavailable_floor_kib(
                supervisor.INITIAL_ADMISSION_PHASE
            ),
            1_900_000,
        )
        for phase in (
            supervisor.RUNTIME_SOURCE_PHASE,
            supervisor.RUNTIME_MANIFEST_PHASE,
        ):
            self.assertEqual(
                supervisor._phase_memavailable_floor_kib(phase),
                650_000,
            )
        with self.assertRaisesRegex(RuntimeError, "unknown memory-accounting phase"):
            supervisor._phase_memavailable_floor_kib("synthetic-invalid")

    def test_page_rounding_and_exact_whole_launch_cap_accounting(self) -> None:
        self.assertEqual(supervisor._page_rounded_bytes(0), 0)
        self.assertEqual(supervisor._page_rounded_bytes(1), 4096)
        self.assertEqual(supervisor._page_rounded_bytes(4096), 4096)
        self.assertEqual(supervisor._page_rounded_bytes(4097), 8192)
        checkpoint = supervisor._runtime_resource_checkpoint(
            index=0,
            phase=supervisor.RUNTIME_SOURCE_PHASE,
            source_relative_path="one.py",
            source_logical_bytes=1,
            cumulative_logical_bytes=1,
            cumulative_runtime_sealed_page_rounded_bytes=4096,
            preexisting_sealed_page_rounded_bytes=4096,
            host={"mem_available_kib": 650_000, "shmem_kib": 17},
            process_memory={"VmRSS": 699_992, "VmSwap": 0},
        )
        self.assertEqual(checkpoint["sealed_storage_kib"], 8)
        self.assertEqual(checkpoint["whole_launch_accounted_kib"], 700_000)
        with self.assertRaisesRegex(RuntimeError, "whole-launch memory cap"):
            supervisor._runtime_resource_checkpoint(
                index=0,
                phase=supervisor.RUNTIME_SOURCE_PHASE,
                source_relative_path="one.py",
                source_logical_bytes=1,
                cumulative_logical_bytes=1,
                cumulative_runtime_sealed_page_rounded_bytes=4096,
                preexisting_sealed_page_rounded_bytes=4096,
                host={"mem_available_kib": 650_000, "shmem_kib": 17},
                process_memory={"VmRSS": 699_993, "VmSwap": 0},
            )

    def test_runtime_source_copy_never_exceeds_one_mib_chunks(self) -> None:
        value = b"x" * (2 * supervisor.STREAM_CHUNK_BYTES + 17)
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            source = Path(raw) / "source.bin"
            source.write_bytes(value)
            source_fd = os.open(source, os.O_RDONLY)
            targets: set[int] = set()
            reads: list[int] = []
            writes: list[int] = []
            real_memfd_create = os.memfd_create
            real_pread = os.pread
            real_write = os.write

            def tracked_memfd(name: str, flags: int) -> int:
                descriptor = real_memfd_create(name, flags)
                targets.add(descriptor)
                return descriptor

            def tracked_pread(descriptor: int, size: int, offset: int) -> bytes:
                if descriptor == source_fd:
                    reads.append(size)
                return real_pread(descriptor, size, offset)

            def tracked_write(descriptor: int, block) -> int:
                if descriptor in targets:
                    writes.append(len(block))
                return real_write(descriptor, block)

            target_fd = -1
            try:
                with (
                    mock.patch.object(os, "memfd_create", side_effect=tracked_memfd),
                    mock.patch.object(os, "pread", side_effect=tracked_pread),
                    mock.patch.object(os, "write", side_effect=tracked_write),
                ):
                    target_fd, *_ = supervisor._stream_source_to_sealed_memfd(
                        source_fd,
                        name="bounded-stream",
                        expected_sha256=sha256(value).hexdigest(),
                        expected_size=len(value),
                    )
                self.assertLessEqual(max(reads), supervisor.STREAM_CHUNK_BYTES)
                self.assertLessEqual(max(writes), supervisor.STREAM_CHUNK_BYTES)
                self.assertEqual(reads[:3], [1 << 20, 1 << 20, 17])
                self.assertEqual(writes, [1 << 20, 1 << 20, 17])
            finally:
                os.close(source_fd)
                if target_fd >= 0:
                    os.close(target_fd)

    def test_runtime_source_short_read_and_short_write_fail_closed(self) -> None:
        value = b"abcdefgh"
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            source = Path(raw) / "source.bin"
            source.write_bytes(value)
            source_fd = os.open(source, os.O_RDONLY)
            real_pread = os.pread

            def short_read(descriptor: int, size: int, offset: int) -> bytes:
                if descriptor == source_fd and offset == 0:
                    return real_pread(descriptor, max(0, size - 1), offset)
                return real_pread(descriptor, size, offset)

            try:
                with (
                    mock.patch.object(os, "pread", side_effect=short_read),
                    self.assertRaisesRegex(RuntimeError, "short read"),
                ):
                    supervisor._stream_source_to_sealed_memfd(
                        source_fd,
                        name="short-read",
                        expected_sha256=sha256(value).hexdigest(),
                        expected_size=len(value),
                    )
                real_write = os.write
                target_fds: set[int] = set()
                real_memfd_create = os.memfd_create

                def capture_memfd(name: str, flags: int) -> int:
                    descriptor = real_memfd_create(name, flags)
                    target_fds.add(descriptor)
                    return descriptor

                def short_write(descriptor: int, block) -> int:
                    if descriptor in target_fds:
                        return real_write(descriptor, memoryview(block)[:-1])
                    return real_write(descriptor, block)

                with (
                    mock.patch.object(os, "memfd_create", side_effect=capture_memfd),
                    mock.patch.object(os, "write", side_effect=short_write),
                    self.assertRaisesRegex(RuntimeError, "short write"),
                ):
                    supervisor._stream_source_to_sealed_memfd(
                        source_fd,
                        name="short-write",
                        expected_sha256=sha256(value).hexdigest(),
                        expected_size=len(value),
                    )
            finally:
                os.close(source_fd)

    def test_runtime_source_hash_growth_and_seal_drift_fail_closed(self) -> None:
        value = b"source"
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            source = Path(raw) / "source.bin"
            source.write_bytes(value)
            source_fd = os.open(source, os.O_RDONLY)
            try:
                with self.assertRaisesRegex(RuntimeError, "RECORD mismatch"):
                    supervisor._stream_source_to_sealed_memfd(
                        source_fd,
                        name="hash-drift",
                        expected_sha256="0" * 64,
                        expected_size=len(value),
                    )
                real_pread = os.pread
                mutated = False

                def mutate_after_read(descriptor: int, size: int, offset: int) -> bytes:
                    nonlocal mutated
                    block = real_pread(descriptor, size, offset)
                    if descriptor == source_fd and offset == 0 and not mutated:
                        source.write_bytes(value + b"x")
                        mutated = True
                    return block

                with (
                    mock.patch.object(os, "pread", side_effect=mutate_after_read),
                    self.assertRaisesRegex(RuntimeError, "grew|drift|mismatch"),
                ):
                    supervisor._stream_source_to_sealed_memfd(
                        source_fd,
                        name="source-growth",
                        expected_sha256=sha256(value).hexdigest(),
                        expected_size=len(value),
                    )
            finally:
                os.close(source_fd)
            source.write_bytes(value)
            source_fd = os.open(source, os.O_RDONLY)
            real_fcntl = supervisor.fcntl.fcntl

            def missing_seals(descriptor: int, command: int, *args):
                result = real_fcntl(descriptor, command, *args)
                if command == supervisor.fcntl.F_GET_SEALS:
                    return 0
                return result

            try:
                with (
                    mock.patch.object(
                        supervisor.fcntl, "fcntl", side_effect=missing_seals
                    ),
                    self.assertRaisesRegex(RuntimeError, "target verification"),
                ):
                    supervisor._stream_source_to_sealed_memfd(
                        source_fd,
                        name="seal-drift",
                        expected_sha256=sha256(value).hexdigest(),
                        expected_size=len(value),
                    )
            finally:
                os.close(source_fd)

    def test_resource_telemetry_mutation_and_reorder_are_rejected_both_sides(self) -> None:
        entries = [
            {"relative_path": "a.py", "size": 1},
            {"relative_path": "b.py", "size": 4097},
        ]
        checkpoints = []
        logical = 0
        sealed = 0
        for index, row in enumerate(entries):
            logical += row["size"]
            sealed += supervisor._page_rounded_bytes(row["size"])
            checkpoints.append(
                supervisor._runtime_resource_checkpoint(
                    index=index,
                    phase=supervisor.RUNTIME_SOURCE_PHASE,
                    source_relative_path=row["relative_path"],
                    source_logical_bytes=row["size"],
                    cumulative_logical_bytes=logical,
                    cumulative_runtime_sealed_page_rounded_bytes=sealed,
                    preexisting_sealed_page_rounded_bytes=4096,
                    host={"mem_available_kib": 700_000, "shmem_kib": 9},
                    process_memory={"VmRSS": 10, "VmSwap": 2},
                )
            )
        digest = supervisor._runtime_resource_telemetry_sha256(checkpoints)
        for module in (supervisor, runner):
            module._verify_runtime_resource_telemetry(
                entries,
                checkpoints,
                preexisting_sealed_page_rounded_bytes=4096,
                expected_sha256=digest,
            )
            mutations = (
                list(reversed(checkpoints)),
                [{**checkpoints[0], "shmem_kib": 10}, checkpoints[1]],
                checkpoints[:-1],
            )
            for telemetry in mutations:
                with self.subTest(module=module.__name__, telemetry=telemetry):
                    with self.assertRaisesRegex(RuntimeError, "checkpoint"):
                        module._verify_runtime_resource_telemetry(
                            entries,
                            telemetry,
                            preexisting_sealed_page_rounded_bytes=4096,
                            expected_sha256=digest,
                        )

    def test_failure_after_runtime_root_dup_closes_it_when_source_open_fails(self) -> None:
        sources = {"example/package.py": b"value = 1\n"}
        with synthetic_runtime_source_tree(sources) as (
            site_packages,
            root_fd,
            captures,
        ):
            before = descriptor_snapshot()
            duplicated: list[tuple[int, tuple[int, ...]]] = []
            real_dup = os.dup
            real_open = os.open

            def tracked_dup(descriptor: int) -> int:
                duplicate = real_dup(descriptor)
                duplicated.append((duplicate, supervisor._stable_identity(os.fstat(duplicate))))
                return duplicate

            def reject_source_root(path, flags, *args, **kwargs):
                if os.fspath(path) == os.fspath(site_packages) and not args and not kwargs:
                    raise OSError(errno.EIO, "synthetic source-root open failure")
                return real_open(path, flags, *args, **kwargs)

            with (
                mock.patch.object(supervisor, "SITE_PACKAGES", site_packages),
                mock.patch.object(
                    supervisor,
                    "RUNTIME_RECORDS",
                    {"runtime_test_record": site_packages / "RECORD"},
                ),
                mock.patch.object(supervisor.os, "dup", side_effect=tracked_dup),
                mock.patch.object(supervisor.os, "open", side_effect=reject_source_root),
                self.assertRaisesRegex(OSError, "source-root open failure"),
            ):
                supervisor.build_runtime_bundle(
                    runtime_root_fd=root_fd,
                    captures=captures,
                )
            self.assertEqual(len(duplicated), 1)
            self.assertEqual(descriptor_snapshot(), before)
            with self.assertRaises(OSError):
                os.fstat(duplicated[0][0])

    def test_first_accounting_failure_closes_both_owned_directory_descriptors(self) -> None:
        sources = {"example/package.py": b"value = 1\n"}
        with synthetic_runtime_source_tree(sources) as (
            site_packages,
            root_fd,
            captures,
        ):
            before = descriptor_snapshot()
            acquired: list[tuple[int, tuple[int, ...]]] = []
            real_dup = os.dup
            real_open = os.open

            def tracked_dup(descriptor: int) -> int:
                duplicate = real_dup(descriptor)
                acquired.append((duplicate, supervisor._stable_identity(os.fstat(duplicate))))
                return duplicate

            def tracked_open(path, flags, *args, **kwargs):
                descriptor = real_open(path, flags, *args, **kwargs)
                if os.fspath(path) == os.fspath(site_packages) and not args and not kwargs:
                    acquired.append(
                        (descriptor, supervisor._stable_identity(os.fstat(descriptor)))
                    )
                return descriptor

            with (
                mock.patch.object(supervisor, "SITE_PACKAGES", site_packages),
                mock.patch.object(
                    supervisor,
                    "RUNTIME_RECORDS",
                    {"runtime_test_record": site_packages / "RECORD"},
                ),
                mock.patch.object(supervisor.os, "dup", side_effect=tracked_dup),
                mock.patch.object(supervisor.os, "open", side_effect=tracked_open),
                mock.patch.object(
                    supervisor,
                    "_captured_memfd_page_rounded_bytes",
                    side_effect=RuntimeError("synthetic first accounting failure"),
                ),
                self.assertRaisesRegex(RuntimeError, "first accounting failure"),
            ):
                supervisor.build_runtime_bundle(
                    runtime_root_fd=root_fd,
                    captures=captures,
                )
            self.assertEqual(len(acquired), 2)
            self.assertEqual(descriptor_snapshot(), before)
            for descriptor, _identity in acquired:
                with self.assertRaises(OSError):
                    os.fstat(descriptor)

    def test_stream_failure_closes_all_bundle_owned_descriptors(self) -> None:
        sources = {"example/package.py": b"value = 1\n"}
        with synthetic_runtime_source_tree(sources) as (
            site_packages,
            root_fd,
            captures,
        ):
            before = descriptor_snapshot()
            with (
                mock.patch.object(supervisor, "SITE_PACKAGES", site_packages),
                mock.patch.object(
                    supervisor,
                    "RUNTIME_RECORDS",
                    {"runtime_test_record": site_packages / "RECORD"},
                ),
                mock.patch.object(
                    supervisor,
                    "_stream_source_to_sealed_memfd",
                    side_effect=RuntimeError("synthetic stream failure"),
                ),
                self.assertRaisesRegex(RuntimeError, "stream failure"),
            ):
                supervisor.build_runtime_bundle(
                    runtime_root_fd=root_fd,
                    captures=captures,
                )
            self.assertEqual(descriptor_snapshot(), before)

    def test_manifest_seal_failure_closes_root_source_and_runtime_descriptors(self) -> None:
        sources = {"example/package.py": b"value = 1\n"}
        with synthetic_runtime_source_tree(sources) as (
            site_packages,
            root_fd,
            captures,
        ):
            before = descriptor_snapshot()
            real_seal_bytes = supervisor._seal_bytes

            def reject_manifest(name: str, raw: bytes):
                if name == "muni-v26-runtime-manifest":
                    raise RuntimeError("synthetic manifest seal failure")
                return real_seal_bytes(name, raw)

            with (
                mock.patch.object(supervisor, "SITE_PACKAGES", site_packages),
                mock.patch.object(
                    supervisor,
                    "RUNTIME_RECORDS",
                    {"runtime_test_record": site_packages / "RECORD"},
                ),
                mock.patch.object(
                    supervisor, "_seal_bytes", side_effect=reject_manifest
                ),
                self.assertRaisesRegex(RuntimeError, "manifest seal failure"),
            ):
                supervisor.build_runtime_bundle(
                    runtime_root_fd=root_fd,
                    captures=captures,
                )
            after = descriptor_snapshot()
            self.assertEqual(set(after), set(before))
            self.assertEqual(
                {key: value for key, value in after.items() if key != root_fd},
                {key: value for key, value in before.items() if key != root_fd},
            )
            self.assertEqual(
                tuple(after[root_fd][index] for index in (0, 1, 2, 4)),
                tuple(before[root_fd][index] for index in (0, 1, 2, 4)),
            )

    def test_success_transfers_only_identity_bound_bundle_descriptors(self) -> None:
        sources = {"example/package.py": b"value = 1\n"}
        with synthetic_runtime_source_tree(sources) as (
            site_packages,
            root_fd,
            captures,
        ):
            before = descriptor_snapshot()
            with (
                mock.patch.object(supervisor, "SITE_PACKAGES", site_packages),
                mock.patch.object(
                    supervisor,
                    "RUNTIME_RECORDS",
                    {"runtime_test_record": site_packages / "RECORD"},
                ),
            ):
                admitted_root, manifest_fd, files, binding, _summary = (
                    supervisor.build_runtime_bundle(
                        runtime_root_fd=root_fd,
                        captures=captures,
                    )
                )
            transferred = {admitted_root, manifest_fd, *files}
            after = descriptor_snapshot()
            self.assertEqual(set(after) - set(before), transferred)
            self.assertEqual(len(after) - len(before), 2 + len(files))
            root_row = os.fstat(admitted_root)
            self.assertEqual(
                [
                    int(root_row.st_dev),
                    int(root_row.st_ino),
                    stat.S_IMODE(root_row.st_mode),
                    int(root_row.st_uid),
                ],
                binding["root_identity"],
            )
            self.assertEqual(
                list(supervisor._stable_identity(os.fstat(manifest_fd))),
                binding["manifest_identity"],
            )
            manifest = json.loads(os.pread(manifest_fd, binding["manifest_size"], 0))
            self.assertEqual(
                {row["fd"] for row in manifest["entries"]},
                set(files),
            )
            for descriptor in transferred:
                os.close(descriptor)
            closed = descriptor_snapshot()
            self.assertEqual(set(closed), set(before))
            self.assertEqual(
                {key: value for key, value in closed.items() if key != root_fd},
                {key: value for key, value in before.items() if key != root_fd},
            )
            self.assertEqual(
                tuple(closed[root_fd][index] for index in (0, 1, 2, 4)),
                tuple(before[root_fd][index] for index in (0, 1, 2, 4)),
            )

    def test_descriptor_oracle_detects_frozen_v20_accounting_failure_leak(self) -> None:
        v20_supervisor = V20_ROOT / "planora-muni-fspsx-frontier-v20-supervisor.py"
        script = f"""
import importlib.util, json, os, stat, tempfile
from pathlib import Path
from unittest import mock

path = Path({str(v20_supervisor)!r})
spec = importlib.util.spec_from_file_location("frozen_v20_leak_witness", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def snapshot():
    rows = {{}}
    for raw in os.listdir("/proc/self/fd"):
        descriptor = int(raw)
        try:
            row = os.fstat(descriptor)
        except OSError:
            continue
        rows[descriptor] = [
            int(row.st_dev), int(row.st_ino), stat.S_IFMT(row.st_mode),
            stat.S_IMODE(row.st_mode), int(row.st_uid), int(row.st_nlink),
        ]
    return rows

with tempfile.TemporaryDirectory(dir="/tmp") as raw:
    root_fd = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
    try:
        before = snapshot()
        with (
            mock.patch.object(module, "SITE_PACKAGES", Path("/tmp")),
            mock.patch.object(module, "_record_runtime_entries", return_value=({{}}, [])),
            mock.patch.object(
                module,
                "_captured_memfd_page_rounded_bytes",
                side_effect=RuntimeError("v20 leak witness"),
            ),
        ):
            try:
                module.build_runtime_bundle(runtime_root_fd=root_fd, captures={{}})
            except RuntimeError as exc:
                assert str(exc) == "v20 leak witness"
        after = snapshot()
        leaked = {{key: value for key, value in after.items() if key not in before}}
        print(json.dumps({{"count": len(leaked), "identities": list(leaked.values())}}))
        for descriptor in leaked:
            os.close(descriptor)
    finally:
        os.close(root_fd)
"""
        completed = subprocess.run(
            [str(PYTHON), "-I", "-S", "-B", "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        witness = json.loads(completed.stdout)
        self.assertEqual(witness["count"], 2)
        self.assertEqual(len(witness["identities"]), 2)

    def test_manifest_memfd_is_closed_on_post_seal_failure(self) -> None:
        sources = {"example/package.py": b"value = 1\n"}
        with synthetic_runtime_source_tree(sources) as (
            site_packages,
            root_fd,
            captures,
        ):
            before = set(os.listdir("/proc/self/fd"))
            original_checkpoint = supervisor._runtime_resource_checkpoint

            def fail_after_manifest(**kwargs):
                if kwargs["phase"] == supervisor.RUNTIME_MANIFEST_PHASE:
                    raise RuntimeError("synthetic post-manifest failure")
                return original_checkpoint(**kwargs)

            with (
                mock.patch.object(supervisor, "SITE_PACKAGES", site_packages),
                mock.patch.object(
                    supervisor,
                    "RUNTIME_RECORDS",
                    {"runtime_test_record": site_packages / "RECORD"},
                ),
                mock.patch.object(
                    supervisor,
                    "_runtime_resource_checkpoint",
                    side_effect=fail_after_manifest,
                ),
                self.assertRaisesRegex(RuntimeError, "post-manifest failure"),
            ):
                supervisor.build_runtime_bundle(
                    runtime_root_fd=root_fd,
                    captures=captures,
                )
            self.assertEqual(set(os.listdir("/proc/self/fd")), before)

    def test_runtime_revalidation_streams_descriptors_on_both_sides(self) -> None:
        sources = {
            "example/package.py": b"x" * (supervisor.STREAM_CHUNK_BYTES + 37)
        }
        with synthetic_runtime_source_tree(sources) as (
            site_packages,
            root_fd,
            captures,
        ):
            descriptors: list[int] = []
            with (
                mock.patch.object(supervisor, "SITE_PACKAGES", site_packages),
                mock.patch.object(
                    supervisor,
                    "RUNTIME_RECORDS",
                    {"runtime_test_record": site_packages / "RECORD"},
                ),
            ):
                admitted_root, manifest_fd, files, binding, _summary = (
                    supervisor.build_runtime_bundle(
                        runtime_root_fd=root_fd,
                        captures=captures,
                    )
                )
            descriptors.extend((admitted_root, manifest_fd, *files))
            runtime_set = set(files)
            supervisor_pread_stable = supervisor._pread_stable
            runner_pread_all = runner._pread_all

            def supervisor_manifest_only(descriptor: int, *, maximum_bytes: int):
                if descriptor in runtime_set:
                    raise AssertionError("runtime file replay used whole-file reader")
                return supervisor_pread_stable(
                    descriptor, maximum_bytes=maximum_bytes
                )

            def runner_manifest_only(descriptor: int, *, maximum_bytes: int):
                if descriptor in runtime_set:
                    raise AssertionError("runtime file replay used whole-file reader")
                return runner_pread_all(descriptor, maximum_bytes=maximum_bytes)

            try:
                with mock.patch.object(
                    supervisor,
                    "_pread_stable",
                    side_effect=supervisor_manifest_only,
                ):
                    replay = supervisor.verify_runtime_bundle_end(binding)
                self.assertEqual(replay["file_count"], 1)
                payloads = {"runtime_test_record": runtime_record(sources)}
                with (
                    mock.patch.dict(
                        os.environ,
                        {
                            runner.RUNTIME_BUNDLE_ENV: json.dumps(
                                binding, sort_keys=True, separators=(",", ":")
                            )
                        },
                    ),
                    mock.patch.object(
                        runner,
                        "RUNTIME_RECORD_LABELS",
                        {"test": "runtime_test_record"},
                    ),
                    mock.patch.object(
                        runner,
                        "EXPECTED_RUNTIME_CACHE_RELEASE_TELEMETRY_SHA256",
                        binding["source_cache_release_telemetry_sha256"],
                    ),
                    mock.patch.object(
                        runner,
                        "_pread_all",
                        side_effect=runner_manifest_only,
                    ),
                ):
                    admitted = runner.verify_runtime_bundle(payloads)
                self.assertEqual(admitted.evidence["file_count"], 1)
            finally:
                for descriptor in descriptors:
                    os.close(descriptor)

    def test_real_record_bundle_builds_and_replays_without_official_sources(self) -> None:
        captures: dict[str, dict[str, object]] = {}
        capture_fds: list[int] = []
        runtime_fds: list[int] = []
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="muni-v26-runtime-test-") as raw:
            root = Path(raw)
            root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                for label, path in supervisor.RUNTIME_RECORDS.items():
                    descriptor, evidence = supervisor._stream_capture(
                        path, runner.EXPECTED_HASHES[label], label
                    )
                    captures[label] = evidence
                    capture_fds.append(descriptor)
                    capture_fds.append(int(evidence["source_watch_fd"]))
                with mock.patch.object(
                    supervisor, "LAUNCH_MEMAVAILABLE_FLOOR_KIB", 0
                ):
                    (
                        admitted_root,
                        manifest_fd,
                        files,
                        binding,
                        summary,
                    ) = supervisor.build_runtime_bundle(
                        runtime_root_fd=root_fd,
                        captures=captures,
                    )
                runtime_fds.extend((admitted_root, manifest_fd, *files))
                replay = supervisor.verify_runtime_bundle_end(binding)
                self.assertEqual(replay["file_count"], summary["file_count"])
                self.assertEqual(replay["file_count"], 2_902)
                self.assertEqual(replay["total_bytes"], 180_259_197)
                self.assertEqual(summary["total_bytes"], 180_259_197)
                self.assertTrue(replay["all_memfds_sealed"])
                self.assertTrue(replay["all_link_targets_replayed"])
            finally:
                os.close(root_fd)
                for descriptor in runtime_fds + capture_fds:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass

    def test_omitted_runtime_record_module_is_rejected(self) -> None:
        payloads = {label: b"" for label in runner.RUNTIME_RECORD_LABELS.values()}
        payloads.pop(runner.RUNTIME_RECORD_LABELS["six"])
        with self.assertRaises(KeyError):
            runner._expected_runtime_bundle_entries(payloads)

    def test_record_path_escape_is_excluded_and_never_admitted(self) -> None:
        payloads = {label: b"" for label in runner.RUNTIME_RECORD_LABELS.values()}
        payloads[runner.RUNTIME_RECORD_LABELS["six"]] = (
            b"../evil.py,sha256=eA==,1\n"
        )
        entries, excluded = runner._expected_runtime_bundle_entries(payloads)
        self.assertEqual(entries, {})
        self.assertEqual(len(excluded), 1)

    def test_unexpected_site_packages_module_is_rejected(self) -> None:
        payloads = {label: b"" for label in runner.RUNTIME_RECORD_LABELS.values()}
        payloads["stdlib_manifest"] = STDLIB_MANIFEST.read_bytes()
        injected = types.ModuleType("injected_runtime")
        injected.__file__ = "/tmp/evil/site-packages/injected.py"
        sys.modules[injected.__name__] = injected
        old_prefix = sys.pycache_prefix
        old_dont = sys.dont_write_bytecode
        try:
            sys.pycache_prefix = "/tmp/disabled-pyc"
            sys.dont_write_bytecode = True
            with self.assertRaisesRegex(RuntimeError, "unexpected site-packages"):
                runner.verify_loaded_runtime(payloads, empty_bundle())
        finally:
            sys.pycache_prefix = old_prefix
            sys.dont_write_bytecode = old_dont
            sys.modules.pop(injected.__name__, None)

    def test_real_argparse_is_exactly_freeze_pinned(self) -> None:
        payloads = {"stdlib_manifest": STDLIB_MANIFEST.read_bytes()}
        allowed = runner._stdlib_manifest_rows(payloads)
        row = runner._stdlib_module_evidence(
            "/usr/lib/python3.12/argparse.py", allowed
        )
        self.assertEqual(row["sha256"], allowed[row["path"]])
        self.assertEqual(
            row["boundary"], "freeze_pinned_read_only_system_file"
        )

    def test_mutated_allowed_root_fixture_is_rejected_by_exact_hash(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            fixture = Path(raw) / "fixture.py"
            fixture.write_bytes(b"trusted = True\n")
            expected = sha256(fixture.read_bytes()).hexdigest()
            fixture.write_bytes(b"trusted = False\n")
            with (
                mock.patch.object(runner, "STDLIB_ROOTS", (Path(raw),)),
                mock.patch.object(
                    runner, "_verify_stdlib_ancestor_chain", return_value=None
                ),
                self.assertRaisesRegex(RuntimeError, "hash absent"),
            ):
                runner._stdlib_module_evidence(
                    str(fixture.resolve()), {str(fixture.resolve()): expected}
                )

    def test_unpinned_root_shaped_stdlib_module_is_rejected(self) -> None:
        allowed = {
            "/usr/lib/python3.12/argparse.py": sha256(
                Path("/usr/lib/python3.12/argparse.py").read_bytes()
            ).hexdigest()
        }
        with self.assertRaisesRegex(RuntimeError, "absent from frozen manifest"):
            runner._stdlib_module_evidence(
                "/usr/lib/python3.12/antigravity.py", allowed
            )

    def test_validator_admits_real_argparse_and_rejects_tmp_injection(self) -> None:
        accepted = run_validator_bootstrap(b"import argparse\n")
        self.assertEqual(
            accepted.returncode, 0,
            accepted.stderr.decode("utf-8", "replace"),
        )
        injected = run_validator_bootstrap(
            b"import argparse,sys,types\n"
            b"evil=types.ModuleType('evil')\n"
            b"evil.__file__='/tmp/evil.py'\n"
            b"sys.modules['evil']=evil\n"
        )
        self.assertNotEqual(injected.returncode, 0)
        self.assertIn(b"unexpected package runtime", injected.stderr)

    def test_unbound_native_memfd_mapping_is_rejected(self) -> None:
        python_row = os.stat("/proc/self/exe")
        synthetic = "\n".join(
            (
                maps_row(python_row, "/memfd:python (deleted)"),
                "00500000-00501000 r-xp 00000000 00:01 999999 /memfd:evil (deleted)",
            )
        )
        with mock.patch.object(Path, "read_text", return_value=synthetic):
            with self.assertRaisesRegex(RuntimeError, "mapped memfd"):
                runner.mapped_runtime_snapshot(
                    empty_bundle(), python_capture_evidence(), phase="synthetic"
                )

    def test_admitted_native_memfd_map_closure_is_accepted(self) -> None:
        descriptor = memfd("native-map", b"native")
        try:
            native = os.fstat(descriptor)
            python_row = os.stat("/proc/self/exe")
            entry = {
                "relative_path": "pkg/libnative.so",
                "fd": descriptor,
                "device": int(native.st_dev),
                "inode": int(native.st_ino),
                "sha256": sha256(b"native").hexdigest(),
                "size": 6,
            }
            bundle = runner.RuntimeBundleAdmission(
                3, 4, "0" * 64,
                {entry["relative_path"]: entry},
                {(int(native.st_dev), int(native.st_ino)): entry},
                {},
            )
            synthetic = "\n".join(
                (
                    maps_row(python_row, "/memfd:python (deleted)"),
                    maps_row(native, "/memfd:native-map (deleted)"),
                )
            )
            with mock.patch.object(Path, "read_text", return_value=synthetic):
                result = runner.mapped_runtime_snapshot(
                    bundle, python_capture_evidence(), phase="synthetic"
                )
            self.assertEqual(result["sealed_package_mappings"], ["pkg/libnative.so"])
            self.assertTrue(result["sealed_python_mapped"])
        finally:
            os.close(descriptor)

    def test_non_system_native_map_is_rejected(self) -> None:
        python_row = os.stat("/proc/self/exe")
        synthetic = "\n".join(
            (
                maps_row(python_row, "/memfd:python (deleted)"),
                "00500000-00501000 r-xp 00000000 08:01 12345 /tmp/evil.so",
            )
        )
        with mock.patch.object(Path, "read_text", return_value=synthetic):
            with self.assertRaisesRegex(RuntimeError, "outside admitted system roots"):
                runner.mapped_runtime_snapshot(
                    empty_bundle(), python_capture_evidence(), phase="synthetic"
                )


class SealedImportProbeTests(unittest.TestCase):
    def test_rejection_diagnostics_hash_logs_and_bound_binary_stdio_tails(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory_fd = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
            value = b"prefix:" + (b"x" * 5000) + b"\xff\x00tail"
            try:
                for name in ("probe.stdout.log", "probe.stderr.log"):
                    stream_fd = os.open(
                        name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o400,
                        dir_fd=directory_fd,
                    )
                    created = os.fstat(stream_fd)
                    os.write(stream_fd, value)
                    os.close(stream_fd)
                    observed = supervisor.capture_probe_log_diagnostic(
                        directory_fd,
                        name,
                        created,
                        include_tail=True,
                    )
                    self.assertTrue(observed["present"])
                    self.assertEqual(observed["size_bytes"], len(value))
                    self.assertEqual(observed["sha256"], sha256(value).hexdigest())
                    self.assertEqual(
                        observed["tail_bytes"], supervisor.PROBE_STDIO_TAIL_BYTES
                    )
                    self.assertTrue(observed["tail_truncated"])
                    self.assertEqual(
                        base64.b64decode(observed["tail_base64"]),
                        value[-supervisor.PROBE_STDIO_TAIL_BYTES :],
                    )
            finally:
                os.close(directory_fd)

    def test_report_presence_exposes_exact_size_hash_and_bound_identity(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory_fd = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
            report_fd = os.open(
                "sealed-import-probe-child.json",
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            created = os.fstat(report_fd)
            value = b'{"status":"synthetic"}'
            os.write(report_fd, value)
            try:
                observed = supervisor.probe_report_presence(
                    directory_fd, report_fd, created
                )
            finally:
                os.close(report_fd)
                os.close(directory_fd)
        self.assertTrue(observed["parent_created"])
        self.assertTrue(observed["retained_fd_present"])
        self.assertTrue(observed["named_entry_present"])
        self.assertTrue(observed["named_entry_matches_retained_fd"])
        self.assertEqual(observed["size_bytes"], len(value))
        self.assertEqual(observed["sha256"], sha256(value).hexdigest())

    def test_child_crash_classification_preserves_empty_report_and_stdio_facts(self) -> None:
        report = supervisor.probe_report_presence(None, None, None)
        report.update({"parent_created": True, "retained_fd_present": True, "size_bytes": 0})
        stdout = supervisor._absent_probe_log_diagnostic(include_tail=True)
        stderr = supervisor._absent_probe_log_diagnostic(include_tail=True)
        stderr.update(
            {
                "present": True,
                "size_bytes": 9,
                "sha256": sha256(b"traceback").hexdigest(),
                "tail_base64": base64.b64encode(b"traceback").decode("ascii"),
                "tail_bytes": 9,
            }
        )
        diagnostic = supervisor.build_probe_rejection_diagnostics(
            child_started=True,
            child_exit=1,
            stop_reason="probe_exception",
            cleanup={"errors": (), "original_pgid_asserted_empty": True},
            report=report,
            stdout=stdout,
            stderr=stderr,
            errors=("RuntimeError: probe report size rejected",),
        )
        self.assertEqual(diagnostic["primary_failure_classification"], "child_exit_nonzero")
        self.assertEqual(
            diagnostic["failure_classifications"],
            ["child_exit_nonzero", "report_empty", "child_stderr_nonempty", "probe_exception"],
        )
        self.assertNotIn("traceback", json.dumps(diagnostic))

    def test_success_omits_rejection_diagnostics_and_rejection_requires_them(self) -> None:
        accepted = supervisor.probe_result_payload(
            accepted=True,
            stop_reason="normal_exit",
            child_exit=0,
            final_elapsed_seconds=1.0,
            peak_whole_memory_kib=1,
            errors=(),
            evidence={"sha256": "a" * 64},
            rejection_diagnostics=None,
        )
        self.assertNotIn("rejection_diagnostics", accepted)
        with self.assertRaisesRegex(RuntimeError, "missing diagnostics"):
            supervisor.probe_result_payload(
                accepted=False,
                stop_reason="probe_exception",
                child_exit=1,
                final_elapsed_seconds=1.0,
                peak_whole_memory_kib=1,
                errors=("failure",),
                evidence=None,
                rejection_diagnostics=None,
            )

    def test_nonempty_stdio_remains_rejected(self) -> None:
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream):
                self.assertFalse(
                    supervisor.sealed_import_probe_accepted(
                        errors=(f"probe_child_{stream}_not_empty",),
                        stop_reason="normal_exit",
                        child_exit=0,
                        cleanup={
                            "errors": (),
                            "original_pgid_asserted_empty": True,
                        },
                        child_report={"status": "PASS"},
                        final_elapsed_seconds=1.0,
                        peak_whole_memory_kib=1,
                    )
                )

    def test_real_chain_reaches_probe_admission_without_opening_inputs(self) -> None:
        if os.environ.get("PLANORA_MUNI_V26_SKIP_HEAVY") == "1":
            self.skipTest("real sealed chain admission disabled by test contract")
        available = supervisor.host_sample()["mem_available_kib"]
        if available >= supervisor.LAUNCH_MEMAVAILABLE_FLOOR_KIB:
            self.skipTest("heavy probe admission is possible; lightweight suite must not start it")
        manifest_path = CHAIN_ROOT / "planora-muni-fspsx-frontier-v26-freeze-manifest.json"
        if not manifest_path.exists():
            self.skipTest("freeze manifest is built after final source hashes")
        payload = INLINE_TRUST.read_text()
        command = [
            str(PYTHON), "-I", "-S", "-B", "-c", payload,
            "--inline-trust-v1", str(BOOTSTRAP), sha256(BOOTSTRAP.read_bytes()).hexdigest(),
            sha256(payload.encode()).hexdigest(),
            "--sealed-import-probe",
            "--expected-launcher-sha256", sha256(LAUNCHER.read_bytes()).hexdigest(),
            "--expected-supervisor-sha256", sha256(SUPERVISOR.read_bytes()).hexdigest(),
            "--expected-manifest-sha256", sha256(manifest_path.read_bytes()).hexdigest(),
        ]
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC"},
            timeout=60,
            check=False,
        )
        self.assertEqual(completed.returncode, 2, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "NO_GO_RESOURCE_GATE")
        self.assertEqual(payload["chain_traversed"], ["bootstrap", "launcher", "supervisor"])
        self.assertFalse(payload["official_input_opened"])
        self.assertFalse(payload["solve_called"])

    def test_probe_path_has_no_input_capture_or_solver_reference(self) -> None:
        self.assertNotIn("instance", runner.PROBE_CAPTURE_LABELS)
        self.assertEqual(
            runner.PROBE_CAPTURE_LABELS,
            runner.EXPECTED_CAPTURE_LABELS - {"instance"},
        )
        supervisor_source = inspect.getsource(supervisor.run_sealed_import_probe)
        runner_source = inspect.getsource(runner.run_sealed_import_probe)
        for forbidden in ("INSTANCE", "PROGRESS"):
            self.assertNotIn(forbidden, supervisor_source)
        self.assertNotIn("solve_itc2019_native", runner_source)
        self.assertNotIn("parse_itc2019_xml", runner_source)
        for path in (BOOTSTRAP, LAUNCHER, SUPERVISOR, RUNNER):
            self.assertIn("--sealed-import-probe", path.read_text())

    def test_set_union_memory_does_not_double_count_supervisor(self) -> None:
        self.assertEqual(
            supervisor.set_union_memory_kib(100, 700, (11, 12), supervisor_pid=10),
            800,
        )
        self.assertEqual(
            supervisor.set_union_memory_kib(100, 700, (10, 12), supervisor_pid=10),
            700,
        )

    def test_cap_timeout_and_cleanup_errors_fail_closed(self) -> None:
        healthy = supervisor.RUNTIME_MEMAVAILABLE_FLOOR_KIB
        self.assertEqual(
            supervisor.sealed_import_probe_stop_reason(
                elapsed_seconds=180.0, group_memory_kib=1,
                whole_memory_kib=2, mem_available_kib=healthy,
            ),
            "probe_wall_deadline",
        )
        self.assertEqual(
            supervisor.sealed_import_probe_stop_reason(
                elapsed_seconds=1, group_memory_kib=1,
                whole_memory_kib=700_001, mem_available_kib=healthy,
            ),
            "whole_launch_memory_cap",
        )
        self.assertFalse(supervisor.sealed_import_probe_accepted(
            errors=(), stop_reason="normal_exit", child_exit=0,
            cleanup={"errors": ("pidfd_send:EPERM",)}, child_report={"status": "PASS"},
            final_elapsed_seconds=1.0, peak_whole_memory_kib=1,
        ))
        self.assertFalse(supervisor.sealed_import_probe_accepted(
            errors=(), stop_reason="probe_wall_deadline", child_exit=0,
            cleanup={"errors": ()}, child_report={"status": "PASS"},
            final_elapsed_seconds=1.0, peak_whole_memory_kib=1,
        ))

    def test_just_exited_child_cannot_bypass_cap_deadline_or_floor(self) -> None:
        cases = (
            ({"elapsed_seconds": 180.0, "group_memory_kib": 1, "whole_memory_kib": 2,
              "mem_available_kib": supervisor.RUNTIME_MEMAVAILABLE_FLOOR_KIB}, "probe_wall_deadline"),
            ({"elapsed_seconds": 1.0, "group_memory_kib": 1, "whole_memory_kib": 700_001,
              "mem_available_kib": supervisor.RUNTIME_MEMAVAILABLE_FLOOR_KIB}, "whole_launch_memory_cap"),
            ({"elapsed_seconds": 1.0, "group_memory_kib": 1, "whole_memory_kib": 2,
              "mem_available_kib": supervisor.RUNTIME_MEMAVAILABLE_FLOOR_KIB - 1},
             "host_pressure:memavailable_floor"),
        )
        for values, expected in cases:
            self.assertEqual(
                supervisor.sealed_import_probe_iteration_decision(
                    **values, received_signal=None, process_exited=True
                ),
                expected,
            )

    def test_unreaped_just_exited_child_has_identity_pinned_zero_memory(self) -> None:
        process = subprocess.Popen(
            [str(PYTHON), "-I", "-S", "-B", "-c", "import time;time.sleep(.1)"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        try:
            identity = supervisor.proc_stat_identity(process.pid)
            self.assertIsNotNone(identity)
            generation = supervisor.ProcessGroupGeneration(
                process.pid, process.pid, identity
            )
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                status = (Path("/proc") / str(process.pid) / "status").read_text()
                if "State:\tZ" in status:
                    break
                time.sleep(0.01)
            else:
                self.fail("child did not reach unreaped zombie state")
            supervisor_identity = supervisor.proc_stat_identity(os.getpid())
            self.assertIsNotNone(supervisor_identity)
            sample = supervisor.identity_pinned_process_memory_snapshot(
                generation,
                supervisor_pid=os.getpid(),
                supervisor_identity=supervisor_identity,
            )
            child_row = next(row for row in sample["rows"] if row["pid"] == process.pid)
            self.assertEqual(child_row["memory_kib"], 0)
        finally:
            process.wait(timeout=3)

    def test_reaped_zero_exit_leader_is_represented_once_after_valid_sample(self) -> None:
        leader = (10, 10, 1)
        own = (99, 99, 9)
        generation = supervisor.ProcessGroupGeneration(10, 10, leader)
        generation.sampled_members.add((10, leader))
        process = mock.Mock(pid=10)
        process.poll.return_value = 0
        with mock.patch.object(
            supervisor, "proc_stat_identity",
            side_effect=lambda pid: None if pid == 10 else own,
        ):
            proof = supervisor.successful_reaped_leader_zero_memory_proof(
                process, generation
            )
            with mock.patch.object(
                supervisor, "read_process_memory_status_once",
                return_value={"VmRSS": 7, "VmSwap": 1},
            ):
                sample = supervisor.identity_pinned_process_memory_snapshot(
                    generation,
                    supervisor_pid=99,
                    supervisor_identity=own,
                    reaped_zero_proof=proof,
                )
        leader_rows = [row for row in sample["rows"] if row["pid"] == 10]
        self.assertEqual(len(leader_rows), 1)
        self.assertEqual(leader_rows[0]["memory_kib"], 0)
        self.assertTrue(leader_rows[0]["reaped_gone_zero_memory"])
        self.assertEqual(sample["reaped_gone_zero_memory_pids"], (10,))

    def test_reaped_zero_proof_rejects_nonzero_live_reused_or_never_sampled(self) -> None:
        leader = (10, 10, 1)
        generation = supervisor.ProcessGroupGeneration(10, 10, leader)
        process = mock.Mock(pid=10)
        process.poll.return_value = 0
        with (
            mock.patch.object(supervisor, "proc_stat_identity", return_value=None),
            self.assertRaisesRegex(RuntimeError, "never identity-bound sampled"),
        ):
            supervisor.successful_reaped_leader_zero_memory_proof(
                process, generation
            )
        generation.sampled_members.add((10, leader))
        process.poll.return_value = 3
        with mock.patch.object(supervisor, "proc_stat_identity") as identity:
            self.assertIsNone(
                supervisor.successful_reaped_leader_zero_memory_proof(
                    process, generation
                )
            )
        identity.assert_not_called()
        process.poll.return_value = 0
        with (
            mock.patch.object(
                supervisor, "proc_stat_identity", return_value=(10, 10, 2)
            ),
            self.assertRaisesRegex(RuntimeError, "still live or was reused"),
        ):
            supervisor.successful_reaped_leader_zero_memory_proof(
                process, generation
            )

    def test_untrusted_reaped_zero_proofs_fail_closed(self) -> None:
        generation = supervisor.ProcessGroupGeneration(10, 10, (10, 10, 1))
        generation.sampled_members.add((10, (10, 10, 1)))
        proofs = (
            (11, (10, 10, 1), 0),
            (10, (10, 10, 2), 0),
            (10, (10, 10, 1), 1),
        )
        for proof in proofs:
            with self.subTest(proof=proof), self.assertRaisesRegex(
                RuntimeError, "not the admitted zero-exit leader"
            ):
                supervisor.identity_pinned_process_memory_snapshot(
                    generation,
                    supervisor_pid=99,
                    supervisor_identity=(99, 99, 1),
                    reaped_zero_proof=proof,
                )

    def test_live_status_missing_one_memory_field_fails_closed(self) -> None:
        status = "State:\tR (running)\nVmRSS:\t4 kB\n"
        with (
            mock.patch.object(Path, "open", mock.mock_open(read_data=status)),
            self.assertRaisesRegex(
                supervisor.ProcessStatusMemoryUnavailable,
                "memory fields missing",
            ),
        ):
            supervisor.read_process_memory_status_once(10)

    def test_reaped_proof_does_not_admit_pid_reuse(self) -> None:
        leader = (10, 10, 1)
        generation = supervisor.ProcessGroupGeneration(10, 10, leader)
        generation.sampled_members.add((10, leader))
        with (
            mock.patch.object(
                supervisor, "proc_stat_identity",
                side_effect=lambda pid: (10, 10, 2) if pid == 10 else (99, 99, 1),
            ),
            self.assertRaisesRegex(RuntimeError, "replaced before memory snapshot"),
        ):
            supervisor.identity_pinned_process_memory_snapshot(
                generation,
                supervisor_pid=99,
                supervisor_identity=(99, 99, 1),
                reaped_zero_proof=(10, leader, 0),
            )

    def test_numeric_pid_replacement_is_not_measured(self) -> None:
        generation = supervisor.ProcessGroupGeneration(10, 10, (10, 10, 1))

        def identity(pid: int):
            return (10, 10, 2) if pid == 10 else (99, 99, 1)

        with (
            mock.patch.object(supervisor, "proc_stat_identity", side_effect=identity),
            mock.patch.object(supervisor, "read_process_memory_status_once") as status,
            self.assertRaisesRegex(RuntimeError, "replaced before memory snapshot"),
        ):
            supervisor.identity_pinned_process_memory_snapshot(
                generation, supervisor_pid=99, supervisor_identity=(99, 99, 1)
            )
        status.assert_not_called()

    def test_unique_snapshot_reads_each_status_once_and_supervisor_once(self) -> None:
        generation = supervisor.ProcessGroupGeneration(10, 10, (10, 10, 1))
        generation.members[99] = (10, 10, 9)

        def identity(pid: int):
            return generation.members[pid]

        def status(pid: int):
            return {"VmRSS": pid, "VmSwap": 1}

        reader = mock.Mock(side_effect=status)
        with (
            mock.patch.object(supervisor, "proc_stat_identity", side_effect=identity),
            mock.patch.object(supervisor, "read_process_memory_status_once", reader),
        ):
            sample = supervisor.identity_pinned_process_memory_snapshot(
                generation,
                supervisor_pid=99,
                supervisor_identity=(10, 10, 9),
            )
        self.assertEqual(sample["pids"], (10, 99))
        self.assertEqual(reader.call_args_list, [mock.call(10), mock.call(99)])
        self.assertEqual(sample["whole_launch_set_union_memory_kib"], 111)
        self.assertEqual(sample["group_memory_kib"], 111)
        self.assertEqual(sample["supervisor_memory_kib"], 100)

    def test_identity_drift_during_single_status_read_fails_closed(self) -> None:
        generation = supervisor.ProcessGroupGeneration(10, 10, (10, 10, 1))
        counts = {10: 0, 99: 0}

        def identity(pid: int):
            counts[pid] += 1
            if pid == 10 and counts[pid] >= 3:
                return (10, 10, 2)
            return (10, 10, 1) if pid == 10 else (99, 99, 1)

        status = mock.Mock(return_value={"VmRSS": 4, "VmSwap": 1})
        with (
            mock.patch.object(supervisor, "proc_stat_identity", side_effect=identity),
            mock.patch.object(supervisor, "read_process_memory_status_once", status),
            self.assertRaisesRegex(RuntimeError, "drifted during status read"),
        ):
            supervisor.identity_pinned_process_memory_snapshot(
                generation, supervisor_pid=99, supervisor_identity=(99, 99, 1)
            )
        self.assertEqual(status.call_args_list, [mock.call(10)])

    def test_missing_status_after_identity_pin_fails_closed(self) -> None:
        generation = supervisor.ProcessGroupGeneration(10, 10, (10, 10, 1))

        def identity(pid: int):
            return (10, 10, 1) if pid == 10 else (99, 99, 1)

        with (
            mock.patch.object(supervisor, "proc_stat_identity", side_effect=identity),
            mock.patch.object(
                supervisor, "read_process_memory_status_once",
                side_effect=RuntimeError("process status missing"),
            ),
            self.assertRaisesRegex(RuntimeError, "process status missing"),
        ):
            supervisor.identity_pinned_process_memory_snapshot(
                generation, supervisor_pid=99, supervisor_identity=(99, 99, 1)
            )

    def test_memory_sampler_uses_admitted_registry_not_numeric_group_scan(self) -> None:
        source = inspect.getsource(supervisor.identity_pinned_process_memory_snapshot)
        self.assertNotIn("process_group_snapshot", source)
        self.assertNotIn("process_group_pids", source)
        self.assertNotIn("process_group_memory_kib", source)
        self.assertIn("generation.members", source)

    def test_late_replay_runs_every_stage_and_rejects(self) -> None:
        captures = {"one": {"fd": 3}, "two": {"fd": 4}}
        clock_values = iter((100.0, 181.0, 181.0, 181.0, 181.0, 181.0))
        sealed = mock.Mock()
        source = mock.Mock()
        runtime = mock.Mock()
        with (
            mock.patch.object(supervisor, "verify_sealed_capture", sealed),
            mock.patch.object(supervisor, "verify_source_contract", source),
            mock.patch.object(supervisor, "verify_runtime_bundle_end", runtime),
        ):
            errors = supervisor.replay_probe_closure_with_deadline(
                captures, {}, 180.0,
                external_rows=({"fd": 5}, {"fd": 6}),
                clock=lambda: next(clock_values),
            )
        self.assertEqual(sealed.call_count, 4)
        self.assertEqual(source.call_count, 4)
        runtime.assert_called_once_with({})
        self.assertTrue(any("probe_deadline_exceeded" in value for value in errors))

    def test_late_report_publication_is_unlinked_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            os.chmod(directory, 0o700)
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            observed = directory.stat()
            identity = {
                "device": observed.st_dev, "inode": observed.st_ino,
                "uid": observed.st_uid, "mode": 0o700,
            }
            clock_values = iter((100.0, 181.0))
            try:
                evidence, error = supervisor.publish_probe_monitor_with_deadline(
                    path=directory / "sealed-import-probe-report.json",
                    value=b'{}\n', run_directory=directory,
                    run_directory_fd=directory_fd, run_identity=identity,
                    absolute_deadline=180.0,
                    clock=lambda: next(clock_values),
                )
                self.assertIsNone(evidence)
                self.assertEqual(error, "probe_deadline_exceeded:after_report_publication")
                self.assertFalse((directory / "sealed-import-probe-report.json").exists())
            finally:
                os.close(directory_fd)

    def test_final_acceptance_requires_elapsed_and_peak_within_limits(self) -> None:
        common = {
            "errors": (), "stop_reason": "normal_exit", "child_exit": 0,
            "cleanup": {"errors": ()}, "child_report": {"status": "PASS"},
        }
        self.assertFalse(supervisor.sealed_import_probe_accepted(
            **common, final_elapsed_seconds=180.001, peak_whole_memory_kib=1
        ))
        self.assertFalse(supervisor.sealed_import_probe_accepted(
            **common, final_elapsed_seconds=1.0, peak_whole_memory_kib=700_001
        ))
        self.assertTrue(supervisor.sealed_import_probe_accepted(
            **common, final_elapsed_seconds=180.0, peak_whole_memory_kib=700_000
        ))

    def test_descriptor_report_transport_and_same_uid_swap_reject(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            report_fd = os.open(
                "sealed-import-probe-child.json",
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            created = os.fstat(report_fd)
            payload = {
                "schema": "planora.muni-fspsx.frontier-v26.sealed-import-probe-child.v1",
                "status": "PASS",
            }
            try:
                runner.write_sealed_import_probe_report(
                    report_fd,
                    (created.st_dev, created.st_ino, created.st_uid),
                    payload,
                )
                observed, evidence = supervisor.consume_probe_report(
                    directory_fd, report_fd, created
                )
                self.assertEqual(observed, payload)
                self.assertEqual(
                    evidence["transport"],
                    "parent_created_retained_fd_and_named_identity_replay",
                )
                os.close(report_fd)
                report_fd = os.open(
                    "sealed-import-probe-child.json",
                    os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
                created = os.fstat(report_fd)
                runner.write_sealed_import_probe_report(
                    report_fd,
                    (created.st_dev, created.st_ino, created.st_uid),
                    payload,
                )
                os.rename(
                    "sealed-import-probe-child.json", "original.json",
                    src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                )
                attacker = os.open(
                    "sealed-import-probe-child.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o400,
                    dir_fd=directory_fd,
                )
                os.write(attacker, b'{"status":"ATTACKER"}\n')
                os.close(attacker)
                with self.assertRaisesRegex(RuntimeError, "identity drift"):
                    supervisor.consume_probe_report(directory_fd, report_fd, created)
            finally:
                os.close(report_fd)
                os.close(directory_fd)


class ResourceAndCleanupTests(unittest.TestCase):
    def test_empty_group_never_signals_numeric_pgid(self) -> None:
        process = mock.Mock()
        process.pid = 424_242
        process.returncode = 0
        process.wait.return_value = 0
        generation = supervisor.ProcessGroupGeneration(
            process.pid, process.pid, (process.pid, process.pid, 1000)
        )
        with (
            mock.patch.object(supervisor, "proc_stat_identity", return_value=None),
            mock.patch.object(supervisor, "process_group_snapshot", return_value=()),
            mock.patch.object(supervisor.os, "killpg") as raw_killpg,
            mock.patch.object(supervisor.signal, "pidfd_send_signal") as pidfd_signal,
        ):
            result = supervisor.stop_process_group(
                process, generation, 99
            )
        raw_killpg.assert_not_called()
        pidfd_signal.assert_not_called()
        self.assertEqual(result["members_before"], ())
        self.assertTrue(result["group_observed_empty_before_any_later_signal"])
        self.assertFalse(result["numeric_pgid_signal_sent"])
        self.assertEqual(result["term_signal"]["signaled_pids"], ())
        self.assertEqual(result["kill_signal"]["signaled_pids"], ())

    def test_member_pid_reuse_between_snapshot_and_pidfd_replay_is_aggregated(self) -> None:
        pgid = 123_456
        admitted = (pgid, pgid, 1000)
        replaced = (pgid, pgid, 2000)
        with (
            mock.patch.object(supervisor.os, "pidfd_open", return_value=77),
            mock.patch.object(supervisor, "proc_stat_identity", return_value=replaced),
            mock.patch.object(supervisor.os, "close") as close_fd,
            mock.patch.object(supervisor.os, "killpg") as raw_killpg,
            mock.patch.object(supervisor.signal, "pidfd_send_signal") as pidfd_signal,
        ):
            result = supervisor.signal_process_group_snapshot(
                pgid, ((pgid, admitted),), signal.SIGTERM
            )
        close_fd.assert_called_once_with(77)
        raw_killpg.assert_not_called()
        pidfd_signal.assert_not_called()
        self.assertEqual(result["identity_mismatch_pids"], (pgid,))

    def test_reused_group_after_original_empty_and_reused_leader_exit_gets_zero_signals(self) -> None:
        process = mock.Mock()
        process.pid = 515_151
        process.returncode = 0
        process.wait.return_value = 0
        original = (process.pid, process.pid, 1000)
        generation = supervisor.ProcessGroupGeneration(
            process.pid, process.pid, original
        )
        # The numeric session/PGID was reused, its replacement leader has
        # already exited, and only that replacement generation's descendant
        # remains at the first cleanup enumeration.
        reused_descendant = (515_152, (process.pid, process.pid, 9000))
        with (
            mock.patch.object(supervisor, "proc_stat_identity", return_value=None),
            mock.patch.object(
                supervisor,
                "process_group_snapshot",
                return_value=(reused_descendant,),
            ),
            mock.patch.object(supervisor.os, "killpg") as raw_killpg,
            mock.patch.object(supervisor.os, "pidfd_open") as pidfd_open,
            mock.patch.object(supervisor.signal, "pidfd_send_signal") as pidfd_signal,
        ):
            result = supervisor.stop_process_group(process, generation, 99)
        raw_killpg.assert_not_called()
        pidfd_open.assert_not_called()
        pidfd_signal.assert_not_called()
        self.assertFalse(result["original_pgid_asserted_empty"])
        self.assertTrue(
            any("unregistered survivors" in value for value in result["errors"])
        )

    def test_emfile_for_first_member_does_not_block_later_admitted_member(self) -> None:
        pgid = 616_161
        first = (616_162, (pgid, pgid, 1000))
        second = (616_163, (pgid, pgid, 1001))

        def open_member(pid: int, _flags: int) -> int:
            if pid == first[0]:
                raise OSError(errno.EMFILE, "descriptor table full")
            return 88

        def replay(pid: int):
            return dict((first, second))[pid]

        with (
            mock.patch.object(supervisor.os, "pidfd_open", side_effect=open_member),
            mock.patch.object(supervisor, "proc_stat_identity", side_effect=replay),
            mock.patch.object(supervisor.os, "close") as close_fd,
            mock.patch.object(supervisor.signal, "pidfd_send_signal") as send,
        ):
            result = supervisor.signal_process_group_snapshot(
                pgid, (first, second), signal.SIGTERM
            )
        self.assertEqual(
            result["pidfd_open_failures"],
            ({"pid": first[0], "errno": errno.EMFILE},),
        )
        self.assertEqual(result["signaled_pids"], (second[0],))
        send.assert_called_once_with(88, signal.SIGTERM, None, 0)
        close_fd.assert_called_once_with(88)

    def test_persistent_wait_fault_does_not_skip_term_kill_or_throw(self) -> None:
        pgid = 717_171
        leader = (pgid, (pgid, pgid, 1000))
        first = (717_172, (pgid, pgid, 1001))
        later = (717_173, (pgid, pgid, 1002))
        identities = dict((leader, first, later))
        generation = supervisor.ProcessGroupGeneration(
            pgid, pgid, leader[1]
        )
        generation.members[first[0]] = first[1]
        generation.members[later[0]] = later[1]
        process = mock.Mock()
        process.pid = pgid
        process.returncode = None
        process.wait.side_effect = OSError(errno.EIO, "persistent wait fault")

        def send_member(
            descriptor: int, signum: int, _info: object, _flags: int
        ) -> None:
            if descriptor == 82:
                raise OSError(errno.EPERM, "first descendant signal denied")

        with (
            mock.patch.object(supervisor, "TERMINATION_GRACE_SECONDS", 0),
            mock.patch.object(
                supervisor,
                "proc_stat_identity",
                side_effect=lambda pid: identities.get(pid),
            ),
            mock.patch.object(
                supervisor,
                "process_group_snapshot",
                return_value=(leader, first, later),
            ),
            mock.patch.object(
                supervisor.os,
                "pidfd_open",
                side_effect=lambda pid, _flags: {
                    leader[0]: 81,
                    first[0]: 82,
                    later[0]: 83,
                }[pid],
            ),
            mock.patch.object(supervisor.os, "close"),
            mock.patch.object(
                supervisor.signal,
                "pidfd_send_signal",
                side_effect=send_member,
            ) as send,
        ):
            result = supervisor.stop_process_group(process, generation, 99)

        self.assertIn(
            mock.call(83, signal.SIGTERM, None, 0), send.call_args_list
        )
        self.assertIn(
            mock.call(83, signal.SIGKILL, None, 0), send.call_args_list
        )
        self.assertEqual(
            result["term_signal"]["pidfd_send_failures"],
            ({"pid": first[0], "errno": errno.EPERM},),
        )
        self.assertEqual(
            result["kill_signal"]["pidfd_send_failures"],
            ({"pid": first[0], "errno": errno.EPERM},),
        )
        self.assertTrue(
            any(value.startswith("initial_wait:OSError") for value in result["errors"])
        )
        self.assertTrue(
            any(value.startswith("final_wait:OSError") for value in result["errors"])
        )
        self.assertFalse(result["original_pgid_asserted_empty"])

    def test_unreaped_zombie_leader_is_reaped_then_descendants_drained(self) -> None:
        script = (
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-I','-S','-B','-c',"
            "'import time;time.sleep(30)']);"
            "print('ready',flush=True);time.sleep(0.2)"
        )
        process = subprocess.Popen(
            [str(PYTHON), "-I", "-S", "-B", "-c", script],
            stdout=subprocess.PIPE,
            start_new_session=True,
        )
        pidfd = os.pidfd_open(process.pid, 0) if hasattr(os, "pidfd_open") else None
        try:
            assert process.stdout is not None
            self.assertEqual(process.stdout.readline(), b"ready\n")
            _pgid, _identity, _pidfd, generation = (
                supervisor.admit_spawned_process_group(process, process.pid, pidfd)
            )
            supervisor.refresh_process_group_generation(generation)
            deadline = time.monotonic() + 3
            state = None
            while time.monotonic() < deadline:
                try:
                    raw = (Path("/proc") / str(process.pid) / "stat").read_text()
                except FileNotFoundError:
                    break
                state = raw[raw.rfind(")") + 2 :].split()[0]
                if state == "Z":
                    break
                time.sleep(0.01)
            self.assertEqual(state, "Z")
            self.assertIsNone(process.returncode)
            cleanup = supervisor.stop_process_group(
                process, generation, pidfd
            )
            self.assertTrue(
                cleanup["known_leader_reaped_before_group_interpretation"]
            )
            self.assertEqual(cleanup["final_survivors"], ())
            self.assertEqual(supervisor.process_group_pids(process.pid), ())
        finally:
            if pidfd is not None:
                os.close(pidfd)
            if process.stdout is not None:
                process.stdout.close()
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()

    def test_generic_report_same_uid_name_swap_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            directory = Path(raw)
            dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            report_fd = os.open(
                "report.json", os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o400,
                dir_fd=dirfd,
            )
            created = os.fstat(report_fd)
            os.write(report_fd, b'{"status":"COMPLETE_VALID"}\n')
            os.rename("report.json", "original.json", src_dir_fd=dirfd, dst_dir_fd=dirfd)
            attacker = os.open("report.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400, dir_fd=dirfd)
            os.write(attacker, b'{"status":"ATTACKER"}\n')
            os.close(attacker)
            try:
                with self.assertRaisesRegex(RuntimeError, "identity drift"):
                    runner.consume_exclusive_report_fd(
                        dirfd, "report.json", report_fd, created
                    )
                self.assertEqual(
                    os.stat("report.json", dir_fd=dirfd).st_size,
                    len(b'{"status":"ATTACKER"}\n'),
                )
            finally:
                os.close(report_fd)
                os.close(dirfd)

    def test_resource_semantics_and_mandatory_launch_floor(self) -> None:
        healthy = {"mem_available_kib": supervisor.RUNTIME_MEMAVAILABLE_FLOOR_KIB}
        self.assertIsNone(
            supervisor.resource_decision(
                elapsed_seconds=1,
                group_memory_kib=600_000,
                supervisor_memory_kib=100_000,
                sample={**healthy, "pswpin_pages": 10**12, "pswpout_pages": 10**12},
            )
        )
        self.assertEqual(supervisor.WALL_SECONDS, 630.0)
        self.assertEqual(supervisor.RUNNER_SECONDS, 600.0)
        self.assertEqual(supervisor.PROCESS_GROUP_MEMORY_CAP_KIB, 700_000)
        self.assertEqual(supervisor.WHOLE_LAUNCH_MEMORY_CAP_KIB, 700_000)
        self.assertEqual(
            supervisor.resource_decision(
                elapsed_seconds=1,
                group_memory_kib=600_000,
                supervisor_memory_kib=100_001,
                sample=healthy,
            ),
            "whole_launch_memory_cap",
        )
        self.assertEqual(supervisor.LAUNCH_MEMAVAILABLE_FLOOR_KIB, 1_900_000)
        self.assertEqual(supervisor.RUNTIME_MEMAVAILABLE_FLOOR_KIB, 650_000)

    def test_timeout_cleanup_reaches_grandchild(self) -> None:
        script = (
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-I','-S','-B','-c','import time;time.sleep(30)']);"
            "time.sleep(30)"
        )
        process = subprocess.Popen(
            [str(PYTHON), "-I", "-S", "-B", "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            _pgid, _identity, _pidfd, generation = (
                supervisor.admit_spawned_process_group(process, process.pid, None)
            )
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if len(supervisor.process_group_pids(process.pid)) >= 2:
                    supervisor.refresh_process_group_generation(generation)
                    break
                time.sleep(0.02)
            result = supervisor.stop_process_group(process, generation, None)
            self.assertEqual(result["final_survivors"], ())
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()

    def test_exited_leader_orphan_group_is_always_drained(self) -> None:
        script = (
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-I','-S','-B','-c',"
            "'import time;time.sleep(30)']);"
            "print('ready',flush=True);time.sleep(0.2)"
        )
        process = subprocess.Popen(
            [str(PYTHON), "-I", "-S", "-B", "-c", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdout is not None
        self.assertEqual(process.stdout.readline(), b"ready\n")
        _pgid, _identity, _pidfd, generation = (
            supervisor.admit_spawned_process_group(process, process.pid, None)
        )
        supervisor.refresh_process_group_generation(generation)
        process.wait(timeout=3)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if supervisor.process_group_pids(process.pid):
                break
            time.sleep(0.02)
        self.assertTrue(supervisor.process_group_pids(process.pid))
        result = supervisor.stop_process_group(process, generation, None)
        self.assertTrue(result["leader_exited_before_cleanup"])
        self.assertTrue(result["original_pgid_asserted_empty"])
        self.assertEqual(result["final_survivors"], ())
        process.stdout.close()
        assert process.stderr is not None
        process.stderr.close()

    def test_post_popen_admission_fault_always_drains_provisional_pgid(self) -> None:
        script = (
            "import subprocess,sys,time;"
            "subprocess.Popen([sys.executable,'-I','-S','-B','-c',"
            "'import time;time.sleep(30)']);"
            "time.sleep(0.3);raise SystemExit(0)"
        )
        process = subprocess.Popen(
            [str(PYTHON), "-I", "-S", "-B", "-c", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        provisional_pgid = process.pid

        def fail_after_anchored_admission(
            observed_process: subprocess.Popen[bytes],
            observed_pgid: int,
            generation: supervisor.ProcessGroupGeneration,
        ) -> None:
            self.assertIs(observed_process, process)
            self.assertEqual(observed_pgid, provisional_pgid)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if len(supervisor.process_group_pids(provisional_pgid)) >= 2:
                    supervisor.refresh_process_group_generation(generation)
                    break
                time.sleep(0.005)
            self.assertGreaterEqual(len(generation.members), 2)
            process.wait(timeout=3)
            raise RuntimeError("deterministic post-Popen admission fault")

        cleanup = None
        generation = None
        try:
            _pgid, _identity, _pidfd, generation = (
                supervisor.admit_spawned_process_group(
                    process, provisional_pgid, None
                )
            )
            with self.assertRaisesRegex(RuntimeError, "post-Popen"):
                fail_after_anchored_admission(
                    process, provisional_pgid, generation
                )
        finally:
            if generation is not None and supervisor.process_group_pids(provisional_pgid):
                cleanup = supervisor.stop_process_group(
                    process, generation, None
                )
        self.assertIsNotNone(cleanup)
        self.assertTrue(cleanup["leader_identity_available"])
        self.assertTrue(cleanup["original_pgid_asserted_empty"])
        self.assertEqual(supervisor.process_group_pids(provisional_pgid), ())

    def test_child_preexec_unblocks_inherited_stop_mask_and_cooperates(self) -> None:
        child = (
            "import json,signal,sys,time;"
            "stops={signal.SIGHUP,signal.SIGINT,signal.SIGTERM};"
            "masked=signal.pthread_sigmask(signal.SIG_BLOCK,[]);"
            "exec('def stop(signum,frame):\\n sys.exit(42)');"
            "[signal.signal(s,stop) for s in stops];"
            "print(json.dumps({'masked':sorted(int(x) for x in masked&stops)}),flush=True);"
            "time.sleep(30)"
        )
        old = signal.pthread_sigmask(signal.SIG_BLOCK, supervisor.STOP_SIGNALS)
        parent_pid = os.getpid()
        try:
            process = subprocess.Popen(
                [str(PYTHON), "-I", "-S", "-B", "-c", child],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                preexec_fn=lambda: supervisor.arm_parent_death_signal(parent_pid),
            )
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, old)
        assert process.stdout is not None
        line = process.stdout.readline()
        if not line:
            assert process.stderr is not None
            self.fail(process.stderr.read().decode("utf-8", "replace"))
        self.assertEqual(json.loads(line)["masked"], [])
        os.kill(process.pid, signal.SIGTERM)
        self.assertEqual(process.wait(timeout=5), 42)
        process.stdout.close()
        assert process.stderr is not None
        process.stderr.close()


class ArtifactSchemaTests(unittest.TestCase):
    def fairness(self) -> dict[str, object]:
        return {
            "certificate_sha256": runner.EXPECTED_HASHES[
                "fairness_certificate"
            ],
            "verdict": "NO_GO_UNPROVEN",
            "excluded_progress_sha256": supervisor.EXPECTED_PROGRESS_SHA256,
            "excluded_component_checkpoint_sha256": "b462c82cddaf78f43002cc4ce1f357a64e06876665f587d072bab6aa78e1aa80",
            "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
            "progress_runtime_accessed": False,
            "component_checkpoint_runtime_accessed": False,
        }

    def partial(self) -> dict[str, object]:
        return {
            "schema": "planora.muni-fspsx.frontier-v26.fresh-partial.v1",
            "status": "FRESH_SOLVE_NOT_YET_ADMISSIBLE",
            "admissible_as_solution": False,
            "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
            "competitor_schedule_or_result_used": False,
            "competitor_placement_or_hint_used": False,
            "lineage": {
                "instance_sha256": supervisor.EXPECTED_INSTANCE_SHA256,
                "runner_sha256": "a" * 64,
                "supervisor_sha256": "b" * 64,
                "planora_source_manifest_sha256": "c" * 64,
                "unsolved_classes": 1623,
                "unsolved_students": 1152,
            },
            "fairness_exclusion": self.fairness(),
            "runtime_lineage": {
                "python_binary_sha256": runner.EXPECTED_HASHES["python_binary"],
                "runtime_manifest_sha256": "d" * 64,
                "loaded_manifest_sha256": "e" * 64,
                "stdlib_manifest_sha256": "f" * 64,
                "residual_system_boundary": "observed_and_hashed_not_sealed",
            },
        }

    def test_partial_schema_is_exact_and_extra_field_fails(self) -> None:
        payload = self.partial()
        self.assertTrue(supervisor.validate_partial_payload(payload))
        payload["unreviewed"] = True
        self.assertFalse(supervisor.validate_partial_payload(payload))

    def test_controlled_unknown_schema_is_exact(self) -> None:
        payload = {
            "schema": "planora.muni-fspsx.frontier-v26.controlled-unknown.v1",
            "status": "CONTROLLED_UNKNOWN",
            "admissible_as_solution": False,
            "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
            "fairness_exclusion": self.fairness(),
            "competitor_schedule_or_result_used": False,
            "competitor_placement_or_hint_used": False,
            "partial": {"sha256": "a" * 64},
            "runtime_closure": {"phase": "controlled-unknown-pre-exit"},
            "reason": "synthetic",
        }
        self.assertTrue(supervisor.validate_controlled_stdout(payload))
        payload["solution"] = "forbidden"
        self.assertFalse(supervisor.validate_controlled_stdout(payload))

    def test_solution_xml_schema_and_cardinality_are_exact(self) -> None:
        root = ElementTree.Element(
            "solution", {"name": "synthetic", "technique": "planora-v10"}
        )
        for index in range(1623):
            klass = ElementTree.SubElement(
                root,
                "class",
                {
                    "id": str(index), "days": "1", "start": "0",
                    "weeks": "1", "room": "r",
                },
            )
            if index < 1152:
                ElementTree.SubElement(klass, "student", {"id": str(index)})
        value = ElementTree.tostring(root, encoding="utf-8")
        self.assertTrue(supervisor.validate_solution_document_bytes(value))
        root.attrib["technique"] = "attacker"
        self.assertFalse(
            supervisor.validate_solution_document_bytes(
                ElementTree.tostring(root, encoding="utf-8")
            )
        )

    def test_no_replace_collision_and_alias_tampering_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            path = Path(raw)
            os.chmod(path, 0o700)
            row = path.stat()
            identity = {
                "device": row.st_dev, "inode": row.st_ino,
                "uid": row.st_uid, "mode": 0o700,
            }
            target = path / "artifact"
            directory_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            self.addCleanup(os.close, directory_fd)
            runner.publish_no_replace(
                target, b"reviewed", run_directory=path,
                run_directory_fd=directory_fd, run_identity=identity
            )
            with self.assertRaises(FileExistsError):
                runner.publish_no_replace(
                    target, b"replacement", run_directory=path,
                    run_directory_fd=directory_fd, run_identity=identity
                )

            attacked = path / "attacked"
            stash = path / "retained-alias"
            original = runner.os.link

            def retain(source, destination, *args, **kwargs):
                original(source, destination, *args, **kwargs)
                if destination == attacked.name:
                    original(attacked, stash)

            with (
                mock.patch.object(runner.os, "link", side_effect=retain),
                self.assertRaisesRegex(RuntimeError, "differs"),
            ):
                runner.publish_no_replace(
                    attacked, b"reviewed", run_directory=path,
                    run_directory_fd=directory_fd, run_identity=identity
                )

    def test_bound_directory_rename_swap_and_diverted_open_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as raw:
            parent = Path(raw)
            bound = parent / "run"
            moved = parent / "moved"
            bound.mkdir(mode=0o700)
            directory_fd = os.open(bound, os.O_RDONLY | os.O_DIRECTORY)
            self.addCleanup(os.close, directory_fd)
            row = os.fstat(directory_fd)
            identity = {
                "device": row.st_dev,
                "inode": row.st_ino,
                "uid": row.st_uid,
                "mode": 0o700,
            }
            bound.rename(moved)
            bound.mkdir(mode=0o700)
            with self.assertRaisesRegex(RuntimeError, "bound FD|binding"):
                runner.publish_no_replace(
                    bound / "artifact", b"reviewed",
                    run_directory=bound,
                    run_directory_fd=directory_fd,
                    run_identity=identity,
                )
            self.assertFalse((bound / "artifact").exists())
            self.assertFalse((moved / "artifact").exists())

    def test_artifact_classification_rejects_report_or_output_tampering(self) -> None:
        partial = self.partial()
        controlled = {
            "schema": "planora.muni-fspsx.frontier-v26.controlled-unknown.v1",
            "status": "CONTROLLED_UNKNOWN",
            "admissible_as_solution": False,
            "solver_input_mode": "OFFICIAL_INPUT_ONLY_FRESH",
            "fairness_exclusion": self.fairness(),
            "competitor_schedule_or_result_used": False,
            "competitor_placement_or_hint_used": False,
            "partial": {"sha256": "a" * 64},
            "runtime_closure": {"phase": "controlled-unknown-pre-exit"},
            "reason": "synthetic",
        }
        accepted, partial_ok = supervisor.classify_artifacts(
            child_exit=3,
            stop_reason="normal_exit",
            received_signal=None,
            partial_payload=partial,
            partial_capture={"sha256": "a" * 64},
            report_payload=None,
            child_stdout_payload=controlled,
            output_bytes=None,
            output_capture=None,
            report_capture=None,
            errors=(),
        )
        self.assertEqual((accepted, partial_ok), (False, True))
        accepted, partial_ok = supervisor.classify_artifacts(
            child_exit=3,
            stop_reason="normal_exit",
            received_signal=None,
            partial_payload=partial,
            partial_capture={"sha256": "a" * 64},
            report_payload={"status": "forged"},
            child_stdout_payload=controlled,
            output_bytes=b"forged",
            output_capture={"sha256": "0" * 64},
            report_capture={"sha256": "1" * 64},
            errors=(),
        )
        self.assertEqual((accepted, partial_ok), (False, False))


def runtime_import_probe() -> None:
    captures: dict[str, dict[str, object]] = {}
    capture_fds: list[int] = []
    runtime_fds: list[int] = []
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="muni-v26-import-probe-") as raw:
        root_fd = os.open(raw, os.O_RDONLY | os.O_DIRECTORY)
        try:
            payloads: dict[str, bytes] = {}
            payloads["stdlib_manifest"] = STDLIB_MANIFEST.read_bytes()
            for label, path in supervisor.RUNTIME_RECORDS.items():
                descriptor, evidence = supervisor._stream_capture(
                    path, runner.EXPECTED_HASHES[label], label
                )
                captures[label] = evidence
                capture_fds.extend(
                    (descriptor, int(evidence["source_watch_fd"]))
                )
                payloads[label] = os.pread(
                    descriptor, os.fstat(descriptor).st_size, 0
                )
            with mock.patch.object(
                supervisor, "LAUNCH_MEMAVAILABLE_FLOOR_KIB", 0
            ):
                (
                    admitted_root,
                    manifest_fd,
                    files,
                    binding,
                    _summary,
                ) = supervisor.build_runtime_bundle(
                    runtime_root_fd=root_fd,
                    captures=captures,
                )
            runtime_fds.extend((admitted_root, manifest_fd, *files))
            with mock.patch.dict(
                os.environ,
                {
                    runner.RUNTIME_BUNDLE_ENV: json.dumps(
                        binding, sort_keys=True, separators=(",", ":")
                    )
                },
            ):
                admitted = runner.verify_runtime_bundle(payloads)
                runner.install_sealed_runtime(admitted)
                captured_stderr = io.StringIO()
                with contextlib.redirect_stderr(captured_stderr):
                    from ortools.sat.python import cp_model
                compile_warnings = runner.admit_sealed_runtime_compile_warnings(
                    admitted
                )

                audit_modules = {
                    name: module
                    for name, module in sys.modules.items()
                    if not isinstance(getattr(module, "__file__", None), str)
                    or getattr(module, "__file__").startswith(
                        ("<frozen ", "<sealed-runtime:", "/proc/self/fd/")
                    )
                    or any(
                        Path(getattr(module, "__file__")).resolve().is_relative_to(
                            root
                        )
                        for root in runner.STDLIB_ROOTS
                    )
                }
                with mock.patch.dict(sys.modules, audit_modules, clear=True):
                    loaded = runner.verify_loaded_runtime(payloads, admitted)
                replay = supervisor.verify_runtime_bundle_end(binding)
            print(
                json.dumps(
                    {
                        "status": "SEALED_RUNTIME_IMPORT_OK",
                        "loaded_file_count": loaded["loaded_file_count"],
                        "module_file": str(cp_model.__file__),
                        "compile_warnings": compile_warnings,
                        "captured_stderr": captured_stderr.getvalue(),
                        "replay_file_count": replay["file_count"],
                    },
                    sort_keys=True,
                )
            )
        finally:
            os.close(root_fd)
            for descriptor in runtime_fds + capture_fds:
                try:
                    os.close(descriptor)
                except OSError:
                    pass


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--runtime-import-probe":
        runtime_import_probe()
    elif os.name == "nt":
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        suite.addTests(loader.loadTestsFromTestCase(V26ProcObservationRegressionTests))
        suite.addTest(StaticContractTests("test_v26_final_core_parent_and_authorization_state"))
        suite.addTest(StaticContractTests("test_v26_preserves_v25_caps_and_mode_separation"))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
    else:
        unittest.main(verbosity=2)
