"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const helperPath = path.resolve(__dirname, "validate_itc2019_official_browser.cjs");
const {
  agrees,
  acquireValidationLock,
  assertCompleteSelection,
  assertManifestBinding,
  assertNoReusedOfficialEvidence,
  assertPersistedOfficialValidation,
  assertThirtyOfThirtyOfficialSuccess,
  captureOfficialValidationFromPage,
  createOfficialValidationEvidence,
  createOfficialResponseCapture,
  createSubmissionIntent,
  expectedRunIds,
  expectedRunSpecs,
  main,
  officialResult,
  resolvePersistedOfficialValidation,
  selectRecords,
  windowsPath,
} = require(helperPath);

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function fileHash(value) {
  return sha256(fs.readFileSync(value));
}

function makeRecord(overrides = {}) {
  return {
    run_id: "toy__planora__seed-17__rep-01",
    case: "toy",
    solver: "planora",
    output_path: "/tmp/solution.xml",
    output_sha256: "a".repeat(64),
    input_sha256: "b".repeat(64),
    seed: 17,
    effective_seed: 17,
    seed_control: "explicit",
    seed_pairing_group: 17,
    repetition: 1,
    unseeded_trial: null,
    independent_validation: {
      feasible: true,
      objective: {
        total: 10,
        time: 1,
        room: 2,
        distribution: 3,
        student: 4,
      },
    },
    ...overrides,
  };
}

function responseBytes(overrides = {}) {
  const obj = {
    instance: "toy",
    result: "OK",
    assignedVariables: { value: 12, total: 12 },
    totalCost: { value: 10 },
    timePenalty: { value: 1 },
    roomPenalty: { value: 2 },
    distributionPenalty: { value: 3 },
    studentConflicts: { value: 4 },
    logId: "validator-log-123",
    ...overrides,
  };
  return Buffer.from(
    `{\r\n  "status": "200",\r\n  "obj": ${JSON.stringify(obj)}\r\n}\r\n`,
  );
}

function makeEvidence(record = makeRecord(), raw = responseBytes()) {
  const intent = createSubmissionIntent({
    record,
    helperSha256: fileHash(helperPath),
    createdAt: "2026-08-26T12:34:55.000Z",
    attemptId: "11111111-1111-4111-8111-111111111111",
  });
  const request = {
    request_method: "POST",
    request_url: "https://www.itc2019.org/server/validator/validator-log-123",
    request_content_type: "multipart/form-data; boundary=test-boundary",
    request_body_sha256: "c".repeat(64),
    uploaded_file_sha256: record.output_sha256,
  };
  const responseCapture = createOfficialResponseCapture({
    rawResponse: raw,
    responseUrl: "https://www.itc2019.org/server/validator/validator-log-123",
    submittedOutputSha256: record.output_sha256,
    helperSha256: fileHash(helperPath),
    capturedAt: "2026-08-26T12:34:56.000Z",
    record,
    request,
    submissionIntent: intent,
    responseStatus: 200,
    responseContentType: "application/json;charset=UTF-8",
  });
  return createOfficialValidationEvidence({ record, responseCapture });
}

function mockedPlaywrightPage({
  outputBytes,
  requestOutputBytes = outputBytes,
  raw = responseBytes(),
  mismatch = false,
  afterSetInputFiles = () => undefined,
  onClick = () => undefined,
}) {
  const boundary = "planora-test-boundary";
  const body = Buffer.concat([
    Buffer.from(`--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="solution.xml"\r\nContent-Type: application/xml\r\n\r\n`),
    requestOutputBytes,
    Buffer.from(`\r\n--${boundary}--\r\n`),
  ]);
  const request = {
    method: () => "POST",
    url: () => "https://www.itc2019.org/server/validator/validator-log-123",
    headers: () => ({ "content-type": `multipart/form-data; boundary=${boundary}` }),
    postDataBuffer: () => body,
  };
  const responseRequest = mismatch ? { ...request } : request;
  const response = {
    request: () => responseRequest,
    url: () => request.url(),
    body: async () => raw,
    status: () => 200,
    headers: () => ({ "content-type": "application/json;charset=UTF-8" }),
  };
  const listeners = new Set();
  let predicate;
  let resolveResponse;
  return {
    locator: () => ({
      count: async () => 1,
      isVisible: async () => true,
      waitFor: async () => undefined,
      setInputFiles: async () => afterSetInputFiles(),
    }),
    on: (event, listener) => {
      if (event === "request") listeners.add(listener);
    },
    off: (event, listener) => {
      if (event === "request") listeners.delete(listener);
    },
    waitForResponse: (candidate) => {
      predicate = candidate;
      return new Promise((resolve) => {
        resolveResponse = resolve;
      });
    },
    getByRole: () => ({
      count: async () => 1,
      isVisible: async () => true,
      isEnabled: async () => true,
      click: async () => {
        onClick();
        for (const listener of listeners) listener(request);
        if (predicate(response)) resolveResponse(response);
      },
    }),
    url: () => "https://www.itc2019.org/validator",
  };
}

function safeSubmissionCallbacks(record) {
  return {
    submissionIntent: createSubmissionIntent({
      record,
      helperSha256: fileHash(helperPath),
      createdAt: "2026-08-26T12:34:55.000Z",
      attemptId: "11111111-1111-4111-8111-111111111111",
    }),
    beforeSubmit: async () => undefined,
    onResponseCaptured: async () => undefined,
  };
}

function completedRecord(record = makeRecord(), evidence = makeEvidence(record)) {
  const agreement = agrees(record, evidence);
  return {
    ...record,
    official_validator_status: agreement ? "agreement" : "disagreement",
    official_validator_agreement: agreement,
    official_validated_output_sha256: record.output_sha256,
    official_validation: evidence,
  };
}

function responseCapturedRecord(record = makeRecord()) {
  const intent = createSubmissionIntent({
    record,
    helperSha256: fileHash(helperPath),
    createdAt: "2026-08-26T12:34:55.000Z",
    attemptId: "11111111-1111-4111-8111-111111111111",
  });
  const requestUrl =
    "https://www.itc2019.org/server/validator/validator-log-123";
  const capture = createOfficialResponseCapture({
    rawResponse: responseBytes(),
    responseUrl: requestUrl,
    submittedOutputSha256: record.output_sha256,
    helperSha256: fileHash(helperPath),
    capturedAt: "2026-08-26T12:34:56.000Z",
    record,
    request: {
      request_method: "POST",
      request_url: requestUrl,
      request_content_type: "multipart/form-data; boundary=test-boundary",
      request_body_sha256: "c".repeat(64),
      uploaded_file_sha256: record.output_sha256,
    },
    submissionIntent: intent,
    responseStatus: 200,
    responseContentType: "application/json",
  });
  return {
    ...record,
    official_validator_status: "response_captured",
    official_validator_agreement: null,
    official_validated_output_sha256: record.output_sha256,
    official_submission_intent: intent,
    official_response_capture: capture,
  };
}

function expectedRunIdentity(
  caseId,
  solver,
  seed,
  repetition,
  seedIndex,
  repetitions,
) {
  if (solver === "lemos-maxsat") {
    const trial = seedIndex * repetitions + repetition;
    return {
      run_id: `${caseId}__${solver}__unseeded-trial-${String(trial).padStart(3, "0")}`,
      case: caseId,
      solver,
      seed: null,
      effective_seed: null,
      seed_control: "unsupported_upstream_clock_seed",
      seed_pairing_group: null,
      repetition,
      unseeded_trial: trial,
    };
  }
  return {
    run_id: `${caseId}__${solver}__seed-${seed}__rep-${String(repetition).padStart(2, "0")}`,
    case: caseId,
    solver,
    seed,
    effective_seed: seed,
    seed_control: "explicit",
    seed_pairing_group: seed,
    repetition,
    unseeded_trial: null,
  };
}

function manifestFixture({
  cases = ["toy"],
  solvers = ["planora"],
  seeds = [17],
  repetitions = 1,
} = {}) {
  const expectedRuns = [];
  for (const caseId of cases) {
    for (const solver of solvers) {
      for (const [seedIndex, seed] of seeds.entries()) {
        for (let repetition = 1; repetition <= repetitions; repetition += 1) {
          expectedRuns.push(
            expectedRunIdentity(
              caseId,
              solver,
              seed,
              repetition,
              seedIndex,
              repetitions,
            ),
          );
        }
      }
    }
  }
  return {
    cases,
    solvers,
    seeds,
    repetitions,
    expected_runs: expectedRuns,
  };
}

function controlledMatrixFixture(temporary, transform = (record) => record) {
  const manifest = manifestFixture();
  const runId = manifest.expected_runs[0].run_id;
  const runRoot = path.join(temporary, "runs", runId);
  fs.mkdirSync(runRoot, { recursive: true });
  const outputPath = path.join(runRoot, "solution.xml");
  const outputBytes = Buffer.from("<solution id=\"controlled\"/>\n");
  fs.writeFileSync(outputPath, outputBytes);
  const base = makeRecord({
    run_id: runId,
    output_path: outputPath,
    output_sha256: sha256(outputBytes),
  });
  const record = transform(base);
  const boundManifest = {
    ...manifest,
    inputs: { toy: base.input_sha256 },
    official_validator_helper_sha256: fileHash(helperPath),
  };
  const reportPath = path.join(temporary, "report.json");
  fs.writeFileSync(
    path.join(temporary, "manifest.json"),
    `${JSON.stringify(boundManifest, null, 2)}\n`,
  );
  fs.writeFileSync(
    reportPath,
    `${JSON.stringify(
      {
        manifest: boundManifest,
        records: [record],
        summary: [{ case: "toy", solver: "planora" }],
      },
      null,
      2,
    )}\n`,
  );
  const checkpointPath = path.join(runRoot, "result.json");
  fs.writeFileSync(
    checkpointPath,
    `${JSON.stringify(record, null, 2)}\n`,
  );
  return { reportPath, checkpointPath, outputBytes };
}

test("selects records and preserves manifest/output identity helpers", () => {
  const manifest = manifestFixture({
    solvers: ["planora", "lemos-maxsat"],
  });
  const expectedRuns = manifest.expected_runs;
  assert.deepEqual(
    expectedRunIds(manifest),
    expectedRuns.map((row) => row.run_id),
  );
  assert.equal(windowsPath("/mnt/d/matrix/report.json"), "D:/matrix/report.json");

  const records = [makeRecord()];
  assert.deepEqual(selectRecords(records, "all"), records);
  assert.deepEqual(selectRecords(records, "best"), records);

  const temporary = fs.mkdtempSync(
    path.join(os.tmpdir(), "planora-official-helper-"),
  );
  try {
    const boundManifest = {
      ...manifest,
      official_validator_helper_sha256: fileHash(helperPath),
    };
    const reportPath = path.join(temporary, "report.json");
    fs.writeFileSync(
      path.join(temporary, "manifest.json"),
      JSON.stringify(boundManifest),
    );
    fs.writeFileSync(
      reportPath,
      JSON.stringify({ manifest: boundManifest, records: [] }),
    );
    assert.deepEqual(
      assertManifestBinding(reportPath, { manifest: boundManifest }),
      boundManifest,
    );
    assert.throws(
      () =>
        assertManifestBinding(reportPath, {
          manifest: { ...boundManifest, expected_runs: [] },
        }),
      /does not match/,
    );
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test("rejects coercible local objective values before selecting an upload", () => {
  const record = makeRecord();
  record.independent_validation.objective.total = "10";
  assert.deepEqual(selectRecords([record], "all"), []);
});

test("binds official log identifiers to a strict default-port response URL", () => {
  const record = makeRecord();
  const request = {
    request_method: "POST",
    request_url: "https://www.itc2019.org/server/validator/other-log",
    request_content_type: "multipart/form-data; boundary=test-boundary",
    request_body_sha256: "c".repeat(64),
    uploaded_file_sha256: record.output_sha256,
  };
  const intent = createSubmissionIntent({
    record,
    helperSha256: fileHash(helperPath),
    createdAt: "2026-08-26T12:34:55.000Z",
    attemptId: "11111111-1111-4111-8111-111111111111",
  });
  const capture = createOfficialResponseCapture({
    rawResponse: responseBytes(),
    responseUrl: request.request_url,
    submittedOutputSha256: record.output_sha256,
    helperSha256: fileHash(helperPath),
    capturedAt: "2026-08-26T12:34:56.000Z",
    record,
    request,
    submissionIntent: intent,
    responseStatus: 200,
    responseContentType: "application/json",
  });
  assert.throws(
    () => createOfficialValidationEvidence({ record, responseCapture: capture }),
    /log identifier does not match its response URL/,
  );
  assert.throws(
    () =>
      createOfficialResponseCapture({
        rawResponse: responseBytes(),
        responseUrl: "https://www.itc2019.org:444/server/validator/validator-log-123",
        submittedOutputSha256: record.output_sha256,
        helperSha256: fileHash(helperPath),
        capturedAt: "2026-08-26T12:34:56.000Z",
        record,
        request: {
          ...request,
          request_url:
            "https://www.itc2019.org:444/server/validator/validator-log-123",
        },
        submissionIntent: intent,
        responseStatus: 200,
        responseContentType: "application/json",
      }),
    /outside the authenticated validator endpoint/,
  );
});

test("rejects coercible metadata while constructing durable official evidence", () => {
  const record = makeRecord();
  const helperSha256 = fileHash(helperPath);
  const createdAt = "2026-08-26T12:34:55.000Z";
  const capturedAt = "2026-08-26T12:34:56.000Z";
  const attemptId = "11111111-1111-4111-8111-111111111111";
  assert.throws(
    () =>
      createSubmissionIntent({
        record,
        helperSha256: [helperSha256],
        createdAt,
        attemptId,
      }),
    /lowercase SHA-256 digest/,
  );
  assert.throws(
    () =>
      createSubmissionIntent({
        record,
        helperSha256,
        createdAt,
        attemptId: [attemptId],
      }),
    /lowercase UUIDv4/,
  );
  assert.throws(
    () =>
      createSubmissionIntent({
        record,
        helperSha256,
        createdAt: [createdAt],
        attemptId,
      }),
    /canonical ISO-8601 value/,
  );
  for (const invalidTimestamp of [
    "0000-08-26T12:34:55.000Z",
    "+010000-08-26T12:34:55.000Z",
  ]) {
    assert.throws(
      () =>
        createSubmissionIntent({
          record,
          helperSha256,
          createdAt: invalidTimestamp,
          attemptId,
        }),
      /canonical ISO-8601 value/,
    );
  }

  const submissionIntent = createSubmissionIntent({
    record,
    helperSha256,
    createdAt,
    attemptId,
  });
  const requestUrl =
    "https://www.itc2019.org/server/validator/validator-log-123";
  const request = {
    request_method: "POST",
    request_url: requestUrl,
    request_content_type: "multipart/form-data; boundary=test-boundary",
    request_body_sha256: "c".repeat(64),
    uploaded_file_sha256: record.output_sha256,
  };
  const base = {
    rawResponse: responseBytes(),
    responseUrl: requestUrl,
    submittedOutputSha256: record.output_sha256,
    helperSha256,
    capturedAt,
    record,
    request,
    submissionIntent,
    responseStatus: 200,
    responseContentType: "application/json",
  };
  assert.throws(
    () =>
      createOfficialResponseCapture({
        ...base,
        responseUrl:
          "https://www.itc2019.org:443/server/validator/validator-log-123",
      }),
    /outside the authenticated validator endpoint/,
  );
  assert.throws(
    () => createOfficialResponseCapture({ ...base, responseUrl: [requestUrl] }),
    /Official validator URL is invalid/,
  );
  assert.throws(
    () =>
      createOfficialResponseCapture({
        ...base,
        responseUrl:
          "https:\\\\www.itc2019.org\\server\\validator\\validator-log-123",
      }),
    /outside the authenticated validator endpoint/,
  );
  assert.throws(
    () =>
      createOfficialResponseCapture({
        ...base,
        request: {
          ...request,
          request_content_type: [request.request_content_type],
        },
      }),
    /multipart file upload/,
  );
  assert.throws(
    () =>
      createOfficialResponseCapture({
        ...base,
        responseContentType: ["application/json"],
      }),
    /Content-Type is missing/,
  );
  assert.throws(
    () => createOfficialResponseCapture({ ...base, capturedAt: [capturedAt] }),
    /canonical ISO-8601 value/,
  );
});

test("parses agreement and disagreement from the exact official response", () => {
  const record = makeRecord();
  const official = officialResult(responseBytes());
  assert.equal(agrees(record, official), true);

  const disagreement = officialResult(
    responseBytes({ totalCost: { value: 11 } }),
  );
  assert.equal(agrees(record, disagreement), false);
});

test("requires the exact string 200 official response status", () => {
  const baseline = responseBytes().toString("utf8");
  for (const status of [200, ["200"], { value: "200" }, "", null]) {
    const raw = Buffer.from(
      baseline.replace('"status": "200"', `"status": ${JSON.stringify(status)}`),
    );
    assert.throws(() => officialResult(raw), /Unexpected official response/);
  }
  assert.throws(
    () => officialResult(Buffer.from(baseline.replace(/\s*"status": "200",\r\n/u, ""))),
    /Unexpected official response/,
  );
});

test("rejects coercible and malformed official numeric fields", () => {
  const fields = [
    [
      "assigned",
      (value) => ({ assignedVariables: { value, total: 12 } }),
    ],
    [
      "variables",
      (value) => ({ assignedVariables: { value: 12, total: value } }),
    ],
    ["total", (value) => ({ totalCost: { value } })],
    ["time", (value) => ({ timePenalty: { value } })],
    ["room", (value) => ({ roomPenalty: { value } })],
    ["distribution", (value) => ({ distributionPenalty: { value } })],
    ["student", (value) => ({ studentConflicts: { value } })],
  ];
  for (const [field, override] of fields) {
    for (const value of [null, false, "", "10"]) {
      assert.throws(
        () => officialResult(responseBytes(override(value))),
        new RegExp(`invalid ${field} value`),
      );
    }
  }
});

test("accepts integral JSON float lexemes as safe integer values", () => {
  const raw = Buffer.from(
    responseBytes().toString("utf8").replace('"value":12', '"value":12.0'),
  );

  const parsed = officialResult(raw);

  assert.equal(parsed.assigned, 12);
});

test("rejects non-string official identifiers without coercion", () => {
  for (const override of [
    { instance: 123 },
    { result: 456 },
    { logId: 789 },
  ]) {
    assert.throws(
      () => officialResult(responseBytes(override)),
      /invalid (instance|result|log identifier) value/,
    );
  }
});

test("rejects duplicate official response object keys", () => {
  const raw = Buffer.from(
    responseBytes()
      .toString("utf8")
      .replace('"status": "200",', '"status": "500",\r\n  "status": "200",'),
  );

  assert.throws(() => officialResult(raw), /duplicate key: status/);
});

test("rejects official response bytes that are not strict UTF-8", () => {
  const raw = Buffer.from(responseBytes());
  raw[raw.indexOf(Buffer.from("toy"))] = 0xff;

  assert.throws(() => officialResult(raw), /not strict UTF-8 JSON/);
});

test("rejects a UTF-8 BOM before the official JSON payload", () => {
  const raw = Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), responseBytes()]);

  assert.throws(() => officialResult(raw), /not valid JSON/);
});

test("preserves and hashes the exact response bytes with all provenance bindings", () => {
  const record = makeRecord();
  const raw = responseBytes();
  const evidence = makeEvidence(record, raw);

  assert.deepEqual(Buffer.from(evidence.response_body_base64, "base64"), raw);
  assert.equal(evidence.response_sha256, sha256(raw));
  assert.match(evidence.evidence_binding_sha256, /^[0-9a-f]{64}$/);
  assert.equal(evidence.submitted_output_sha256, record.output_sha256);
  assert.equal(evidence.run_id, record.run_id);
  assert.equal(evidence.case, record.case);
  assert.equal(evidence.input_sha256, record.input_sha256);
  assert.equal(evidence.solver, record.solver);
  assert.equal(evidence.seed, record.seed);
  assert.equal(evidence.repetition, record.repetition);
  assert.equal(evidence.request_method, "POST");
  assert.equal(evidence.request_url, evidence.response_url);
  assert.equal(
    evidence.correlation_method,
    "playwright_response_request_identity_and_multipart_bytes",
  );
  assert.equal(
    evidence.external_source_authenticity,
    "endpoint_and_existing_cdp_session_observed_not_independently_attested",
  );
  assert.equal(evidence.helper_sha256, fileHash(helperPath));
  assert.equal(evidence.captured_at, "2026-08-26T12:34:56.000Z");
  assert.equal(
    evidence.response_url,
    "https://www.itc2019.org/server/validator/validator-log-123",
  );
  assert.equal(evidence.log_id, "validator-log-123");
});

test("captures the exact mocked Playwright request and preserves raw response bytes", async () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "planora-upload-"));
  try {
    const outputPath = path.join(temporary, "solution.xml");
    const outputBytes = Buffer.from("<solution id=\"current\"/>\r\n");
    fs.writeFileSync(outputPath, outputBytes);
    const record = makeRecord({
      output_path: outputPath,
      output_sha256: sha256(outputBytes),
    });
    const raw = responseBytes();
    const events = [];
    let persistedCapture;
    const intent = createSubmissionIntent({
      record,
      helperSha256: fileHash(helperPath),
      createdAt: "2026-08-26T12:34:55.000Z",
      attemptId: "11111111-1111-4111-8111-111111111111",
    });
    const evidence = await captureOfficialValidationFromPage({
      page: mockedPlaywrightPage({
        outputBytes,
        raw,
        onClick: () => events.push("click"),
      }),
      outputPath,
      record,
      submittedOutputSha256: record.output_sha256,
      helperSha256: fileHash(helperPath),
      submissionIntent: intent,
      beforeSubmit: async () => events.push("intent"),
      onResponseCaptured: async (capture) => {
        events.push("capture");
        persistedCapture = capture;
      },
      capturedAt: () => "2026-08-26T12:34:56.000Z",
    });
    assert.deepEqual(events, ["intent", "click", "capture"]);
    assert.deepEqual(Buffer.from(evidence.response_body_base64, "base64"), raw);
    assert.equal(evidence.response_sha256, sha256(raw));
    assert.equal(evidence.uploaded_file_sha256, sha256(outputBytes));
    assert.equal(evidence.response_status, 200);
    assert.equal(evidence.response_content_type, "application/json;charset=UTF-8");
    assert.equal(
      persistedCapture.response_capture_binding_sha256,
      evidence.response_capture_binding_sha256,
    );
    assert.match(evidence.request_body_sha256, /^[0-9a-f]{64}$/);
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test("never clicks unless a durable submission-intent callback succeeds", async () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "planora-no-click-"));
  try {
    const outputPath = path.join(temporary, "solution.xml");
    const outputBytes = Buffer.from("<solution/>\n");
    fs.writeFileSync(outputPath, outputBytes);
    const record = makeRecord({ output_path: outputPath, output_sha256: sha256(outputBytes) });
    const intent = createSubmissionIntent({
      record,
      helperSha256: fileHash(helperPath),
      createdAt: "2026-08-26T12:34:55.000Z",
      attemptId: "11111111-1111-4111-8111-111111111111",
    });
    let clicks = 0;
    await assert.rejects(
      captureOfficialValidationFromPage({
        page: mockedPlaywrightPage({ outputBytes, onClick: () => (clicks += 1) }),
        outputPath,
        record,
        submittedOutputSha256: record.output_sha256,
        helperSha256: fileHash(helperPath),
        submissionIntent: intent,
        beforeSubmit: async () => {
          throw new Error("durable write failed");
        },
        onResponseCaptured: async () => undefined,
      }),
      /durable write failed/,
    );
    assert.equal(clicks, 0);
    await assert.rejects(
      captureOfficialValidationFromPage({
        page: mockedPlaywrightPage({ outputBytes, onClick: () => (clicks += 1) }),
        outputPath,
        record,
        submittedOutputSha256: record.output_sha256,
        helperSha256: fileHash(helperPath),
        submissionIntent: intent,
        onResponseCaptured: async () => undefined,
      }),
      /beforeSubmit callback is required/,
    );
    assert.equal(clicks, 0);
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test("rejects a response attached to a different Playwright request object", async () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "planora-mismatch-"));
  try {
    const outputPath = path.join(temporary, "solution.xml");
    const outputBytes = Buffer.from("<solution/>\n");
    fs.writeFileSync(outputPath, outputBytes);
    const record = makeRecord({ output_path: outputPath, output_sha256: sha256(outputBytes) });
    await assert.rejects(
      captureOfficialValidationFromPage({
        page: mockedPlaywrightPage({ outputBytes, mismatch: true }),
        outputPath,
        record,
        ...safeSubmissionCallbacks(record),
        submittedOutputSha256: record.output_sha256,
        helperSha256: fileHash(helperPath),
      }),
      /did not match exactly one current Playwright request object/,
    );
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test("rejects output mutation immediately after Playwright selects the file", async () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "planora-mutated-upload-"));
  try {
    const outputPath = path.join(temporary, "solution.xml");
    const outputBytes = Buffer.from("<solution id=\"original\"/>\n");
    fs.writeFileSync(outputPath, outputBytes);
    const record = makeRecord({
      output_path: outputPath,
      output_sha256: sha256(outputBytes),
    });
    await assert.rejects(
      captureOfficialValidationFromPage({
        page: mockedPlaywrightPage({
          outputBytes,
          afterSetInputFiles: () =>
            fs.writeFileSync(outputPath, "<solution id=\"mutated\"/>\n"),
        }),
        outputPath,
        record,
        ...safeSubmissionCallbacks(record),
        submittedOutputSha256: record.output_sha256,
        helperSha256: fileHash(helperPath),
      }),
      /Output bytes changed after file selection/,
    );
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test("rejects a validator request carrying bytes from a different upload", async () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "planora-wrong-upload-"));
  try {
    const outputPath = path.join(temporary, "solution.xml");
    const outputBytes = Buffer.from("<solution id=\"current\"/>\n");
    fs.writeFileSync(outputPath, outputBytes);
    const record = makeRecord({
      output_path: outputPath,
      output_sha256: sha256(outputBytes),
    });
    await assert.rejects(
      captureOfficialValidationFromPage({
        page: mockedPlaywrightPage({
          outputBytes,
          requestOutputBytes: Buffer.from("<solution id=\"stale\"/>\n"),
        }),
        outputPath,
        record,
        ...safeSubmissionCallbacks(record),
        submittedOutputSha256: record.output_sha256,
        helperSha256: fileHash(helperPath),
      }),
      /request is not uniquely bound to the current upload bytes/,
    );
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test("rejects reused request or response evidence across distinct runs", () => {
  const first = completedRecord();
  const secondRecord = makeRecord({
    run_id: "toy__planora__seed-23__rep-01",
    seed: 23,
  });
  const replayed = completedRecord(secondRecord, makeEvidence(secondRecord));
  assert.throws(
    () => assertNoReusedOfficialEvidence([first, replayed]),
    /Reused official (log_id|response_sha256|request_body_sha256)/,
  );

  const identityReplay = completedRecord(secondRecord, first.official_validation);
  assert.throws(
    () =>
      assertPersistedOfficialValidation(
        identityReplay,
        structuredClone(identityReplay),
        fileHash(helperPath),
      ),
    /run binding mismatch \(run_id\)/,
  );
});

test("rejects persisted v1 official evidence downgrade", () => {
  const downgraded = completedRecord();
  downgraded.official_validation.evidence_version = 1;

  assert.throws(
    () =>
      assertPersistedOfficialValidation(
        downgraded,
        structuredClone(downgraded),
        fileHash(helperPath),
      ),
    /Unsupported official evidence version/,
  );
});

test("rejects tampered persisted official evidence", () => {
  const record = completedRecord();
  const checkpoint = structuredClone(record);
  assert.equal(
    assertPersistedOfficialValidation(record, checkpoint, fileHash(helperPath)),
    true,
  );

  const tamperedRaw = structuredClone(record);
  const bytes = Buffer.from(tamperedRaw.official_validation.response_body_base64, "base64");
  bytes[bytes.length - 2] ^= 1;
  tamperedRaw.official_validation.response_body_base64 = bytes.toString("base64");
  assert.throws(
    () =>
      assertPersistedOfficialValidation(
        tamperedRaw,
        structuredClone(tamperedRaw),
        fileHash(helperPath),
      ),
    /response hash mismatch/,
  );

  const tamperedParsed = structuredClone(record);
  tamperedParsed.official_validation.total = 999;
  assert.throws(
    () =>
      assertPersistedOfficialValidation(
        tamperedParsed,
        structuredClone(tamperedParsed),
        fileHash(helperPath),
      ),
    /parsed response mismatch/,
  );

  const tamperedBinding = structuredClone(record);
  tamperedBinding.official_validation.captured_at = "2026-08-26T12:34:57.000Z";
  assert.throws(
    () =>
      assertPersistedOfficialValidation(
        tamperedBinding,
        structuredClone(tamperedBinding),
        fileHash(helperPath),
      ),
    /evidence binding mismatch/,
  );
});

test("rejects disagreement and interrupted or incomplete resume state", () => {
  const pending = {
    ...makeRecord(),
    official_validator_status: "pending_upload",
    official_validator_agreement: null,
  };
  assert.equal(
    assertPersistedOfficialValidation(
      pending,
      structuredClone(pending),
      fileHash(helperPath),
    ),
    false,
  );

  const base = makeRecord();
  const disagreement = completedRecord(
    base,
    makeEvidence(base, responseBytes({ totalCost: { value: 11 } })),
  );
  assert.throws(
    () =>
      assertPersistedOfficialValidation(
        disagreement,
        structuredClone(disagreement),
        fileHash(helperPath),
      ),
    /official validator disagreement/,
  );

  const complete = completedRecord();
  assert.throws(
    () =>
      assertPersistedOfficialValidation(
        makeRecord(),
        structuredClone(complete),
        fileHash(helperPath),
      ),
    /interrupted official-validation resume/,
  );

  const incomplete = {
    ...makeRecord(),
    official_validator_status: "agreement",
  };
  assert.throws(
    () =>
      assertPersistedOfficialValidation(
        incomplete,
        structuredClone(incomplete),
        fileHash(helperPath),
      ),
    /incomplete official-validation state/,
  );
});

test("requires the complete selected run set before validation", () => {
  const planora = makeRecord();
  const maxsat = makeRecord({
    run_id: "toy__lemos-maxsat__unseeded-trial-001",
    solver: "lemos-maxsat",
  });
  const manifest = manifestFixture({
    solvers: ["planora", "lemos-maxsat"],
  });

  assert.doesNotThrow(() =>
    assertCompleteSelection([planora, maxsat], manifest, "all"),
  );
  assert.throws(
    () => assertCompleteSelection([planora], manifest, "all"),
    /required official-validator selection is incomplete/,
  );
  assert.doesNotThrow(() =>
    assertCompleteSelection([planora, maxsat], manifest, "best"),
  );
  assert.throws(
    () => assertCompleteSelection([planora], manifest, "best"),
    /required official-validator selection is incomplete/,
  );
});

test("derives MaxSAT unseeded trials with runner-compatible identities", () => {
  const manifest = manifestFixture({
    solvers: ["planora", "lemos-maxsat"],
    seeds: [17, 23],
    repetitions: 2,
  });
  const maxsat = expectedRunSpecs(manifest).filter(
    (row) => row.solver === "lemos-maxsat",
  );

  assert.deepEqual(
    maxsat.map((row) => row.run_id),
    [1, 2, 3, 4].map(
      (trial) =>
        `toy__lemos-maxsat__unseeded-trial-${String(trial).padStart(3, "0")}`,
    ),
  );
  assert.deepEqual(
    maxsat.map((row) => row.repetition),
    [1, 2, 1, 2],
  );
  assert.deepEqual(
    maxsat.map((row) => row.unseeded_trial),
    [1, 2, 3, 4],
  );
  assert.ok(
    maxsat.every(
      (row) =>
        row.seed === null &&
        row.effective_seed === null &&
        row.seed_pairing_group === null &&
        row.seed_control === "unsupported_upstream_clock_seed",
    ),
  );
});

test("rejects shrunken, duplicate, and identity-mismatched expected runs", () => {
  const manifest = manifestFixture({ seeds: [17, 23] });
  assert.throws(
    () =>
      expectedRunIds({
        ...manifest,
        expected_runs: manifest.expected_runs.slice(0, 1),
      }),
    /does not match derived run identities/,
  );

  const duplicated = structuredClone(manifest);
  duplicated.expected_runs[1] = structuredClone(duplicated.expected_runs[0]);
  assert.throws(
    () => expectedRunIds(duplicated),
    /duplicate run identity/,
  );

  const mismatched = structuredClone(manifest);
  mismatched.expected_runs[0].effective_seed = 999;
  assert.throws(
    () => expectedRunIds(mismatched),
    /run identity mismatch \(effective_seed\)/,
  );
});

test("rejects empty and duplicate manifest dimensions", () => {
  for (const field of ["cases", "solvers", "seeds"]) {
    const empty = manifestFixture();
    empty[field] = [];
    empty.expected_runs = [];
    assert.throws(
      () => expectedRunIds(empty),
      new RegExp(`Manifest ${field} must be a non-empty array`),
    );

    const duplicate = manifestFixture();
    duplicate[field] = [duplicate[field][0], duplicate[field][0]];
    assert.throws(
      () => expectedRunIds(duplicate),
      new RegExp(`Manifest ${field} contains duplicates`),
    );
  }
});

test("submission intent makes an interrupted resume fail closed without resubmission", () => {
  const record = makeRecord();
  const intent = createSubmissionIntent({
    record,
    helperSha256: fileHash(helperPath),
    createdAt: "2026-08-26T12:34:55.000Z",
    attemptId: "11111111-1111-4111-8111-111111111111",
  });
  const interrupted = {
    ...record,
    official_validator_status: "submission_intent_committed",
    official_validator_agreement: null,
    official_validated_output_sha256: record.output_sha256,
    official_submission_intent: intent,
  };
  assert.throws(
    () =>
      resolvePersistedOfficialValidation(
        interrupted,
        structuredClone(interrupted),
        fileHash(helperPath),
      ),
    /ambiguous submission intent.*must not be resubmitted/i,
  );
});

test("a durably captured response can finish offline without another submission", () => {
  const record = makeRecord();
  const intent = createSubmissionIntent({
    record,
    helperSha256: fileHash(helperPath),
    createdAt: "2026-08-26T12:34:55.000Z",
    attemptId: "11111111-1111-4111-8111-111111111111",
  });
  const request = {
    request_method: "POST",
    request_url: "https://www.itc2019.org/server/validator/validator-log-123",
    request_content_type: "multipart/form-data; boundary=test-boundary",
    request_body_sha256: "c".repeat(64),
    uploaded_file_sha256: record.output_sha256,
  };
  const capture = createOfficialResponseCapture({
    rawResponse: responseBytes(),
    responseUrl: request.request_url,
    submittedOutputSha256: record.output_sha256,
    helperSha256: fileHash(helperPath),
    capturedAt: "2026-08-26T12:34:56.000Z",
    record,
    request,
    submissionIntent: intent,
    responseStatus: 200,
    responseContentType: "application/json",
  });
  const captured = {
    ...record,
    official_validator_status: "response_captured",
    official_validator_agreement: null,
    official_validated_output_sha256: record.output_sha256,
    official_submission_intent: intent,
    official_response_capture: capture,
  };
  const resolved = resolvePersistedOfficialValidation(
    captured,
    structuredClone(captured),
    fileHash(helperPath),
  );
  assert.equal(resolved.state, "response_captured");
  const evidence = createOfficialValidationEvidence({
    record,
    responseCapture: resolved.responseCapture,
  });
  assert.equal(agrees(record, evidence), true);
});

test("rejects torn or tampered durable intermediate states", () => {
  const captured = responseCapturedRecord();
  const intentOnly = structuredClone(captured);
  intentOnly.official_validator_status = "submission_intent_committed";
  delete intentOnly.official_response_capture;
  assert.throws(
    () =>
      resolvePersistedOfficialValidation(
        captured,
        intentOnly,
        fileHash(helperPath),
      ),
    /interrupted official-validation resume/,
  );

  const tampered = structuredClone(captured);
  tampered.official_response_capture.captured_at =
    "2026-08-26T12:34:57.000Z";
  assert.throws(
    () =>
      resolvePersistedOfficialValidation(
        tampered,
        structuredClone(tampered),
        fileHash(helperPath),
      ),
    /response capture binding mismatch/,
  );
});

test("main finalizes a captured response offline before any CDP connection", async () => {
  const temporary = fs.mkdtempSync(
    path.join(os.tmpdir(), "planora-official-offline-resume-"),
  );
  try {
    const { reportPath, checkpointPath } = controlledMatrixFixture(
      temporary,
      (record) => responseCapturedRecord(record),
    );
    let connectionAttempts = 0;
    const result = await main(
      ["node", helperPath, "--report", reportPath, "--scope", "all"],
      {
        connectOverCDP: async () => {
          connectionAttempts += 1;
          throw new Error("CDP must not be reached during offline resume");
        },
      },
    );
    assert.equal(connectionAttempts, 0);
    assert.equal(result.all_agree, true);
    const report = JSON.parse(fs.readFileSync(reportPath, "utf8"));
    const checkpoint = JSON.parse(fs.readFileSync(checkpointPath, "utf8"));
    assert.equal(report.records[0].official_validator_status, "agreement");
    assert.equal(report.records[0].official_validation.evidence_version, 3);
    assert.deepEqual(report.records[0], checkpoint);
    assert.equal(
      fs.existsSync(path.join(temporary, ".official-validation.lock")),
      false,
    );
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test("main rejects an intent-only resume before any CDP connection", async () => {
  const temporary = fs.mkdtempSync(
    path.join(os.tmpdir(), "planora-official-intent-resume-"),
  );
  try {
    const { reportPath } = controlledMatrixFixture(temporary, (record) => {
      const intent = createSubmissionIntent({
        record,
        helperSha256: fileHash(helperPath),
        createdAt: "2026-08-26T12:34:55.000Z",
        attemptId: "11111111-1111-4111-8111-111111111111",
      });
      return {
        ...record,
        official_validator_status: "submission_intent_committed",
        official_validator_agreement: null,
        official_validated_output_sha256: record.output_sha256,
        official_submission_intent: intent,
      };
    });
    let connectionAttempts = 0;
    await assert.rejects(
      main(
        ["node", helperPath, "--report", reportPath, "--scope", "all"],
        {
          connectOverCDP: async () => {
            connectionAttempts += 1;
            throw new Error("CDP must not be reached for an ambiguous intent");
          },
        },
      ),
      /ambiguous submission intent.*must not be resubmitted/i,
    );
    assert.equal(connectionAttempts, 0);
    assert.equal(
      fs.existsSync(path.join(temporary, ".official-validation.lock")),
      false,
    );
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test("main durably publishes intent and capture around one mocked submission", async () => {
  const temporary = fs.mkdtempSync(
    path.join(os.tmpdir(), "planora-official-mocked-main-"),
  );
  try {
    const { reportPath, checkpointPath, outputBytes } =
      controlledMatrixFixture(temporary);
    const events = [];
    const page = mockedPlaywrightPage({
      outputBytes,
      onClick: () => events.push("click"),
    });
    let connectionAttempts = 0;
    let closes = 0;
    const result = await main(
      ["node", helperPath, "--report", reportPath, "--scope", "all"],
      {
        connectOverCDP: async () => {
          connectionAttempts += 1;
          return {
            contexts: () => [
              {
                pages: () => [page],
                newPage: async () => page,
              },
            ],
            close: async () => {
              closes += 1;
            },
          };
        },
      },
    );
    assert.equal(connectionAttempts, 1);
    assert.equal(closes, 1);
    assert.deepEqual(events, ["click"]);
    assert.equal(result.all_agree, true);
    const report = JSON.parse(fs.readFileSync(reportPath, "utf8"));
    const checkpoint = JSON.parse(fs.readFileSync(checkpointPath, "utf8"));
    assert.equal(report.records[0].official_validator_status, "agreement");
    assert.equal(report.records[0].official_validation.evidence_version, 3);
    assert.deepEqual(report.records[0], checkpoint);
    assert.equal(
      fs.existsSync(path.join(temporary, ".official-validation.lock")),
      false,
    );
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test("30-of-30 proof requires thirty unique independently reparsed success receipts", () => {
  const cases = Array.from({ length: 30 }, (_, index) => `case-${String(index + 1).padStart(2, "0")}`);
  const records = cases.map((caseId, index) => {
    const record = makeRecord({
      run_id: `${caseId}__planora__seed-17__rep-01`,
      case: caseId,
      output_sha256: sha256(Buffer.from(`solution-${caseId}`)),
      input_sha256: sha256(Buffer.from(`input-${caseId}`)),
    });
    const raw = responseBytes({
      instance: caseId,
      logId: `validator-log-${String(index + 1).padStart(2, "0")}`,
    });
    const intent = createSubmissionIntent({
      record,
      helperSha256: fileHash(helperPath),
      createdAt: "2026-08-26T12:34:55.000Z",
      attemptId: `11111111-1111-4111-8111-${String(index + 1).padStart(12, "0")}`,
    });
    const url = `https://www.itc2019.org/server/validator/validator-log-${String(index + 1).padStart(2, "0")}`;
    const capture = createOfficialResponseCapture({
      rawResponse: raw,
      responseUrl: url,
      submittedOutputSha256: record.output_sha256,
      helperSha256: fileHash(helperPath),
      capturedAt: `2026-08-26T12:34:${String(index + 10).padStart(2, "0")}.000Z`,
      record,
      request: {
        request_method: "POST",
        request_url: url,
        request_content_type: "multipart/form-data; boundary=test-boundary",
        request_body_sha256: sha256(Buffer.from(`request-${caseId}`)),
        uploaded_file_sha256: record.output_sha256,
      },
      submissionIntent: intent,
      responseStatus: 200,
      responseContentType: "application/json",
    });
    return completedRecord(
      record,
      createOfficialValidationEvidence({ record, responseCapture: capture }),
    );
  });
  const manifest = manifestFixture({ cases });
  const proof = assertThirtyOfThirtyOfficialSuccess(
    records,
    manifest,
    "planora",
    fileHash(helperPath),
  );
  assert.equal(proof.receipt_count, 30);
  assert.equal(proof.status, "VERIFIED_30_OF_30");
  assert.match(proof.proof_sha256, /^[0-9a-f]{64}$/);
  const permuted = assertThirtyOfThirtyOfficialSuccess(
    [...records].reverse(),
    manifest,
    "planora",
    fileHash(helperPath),
  );
  assert.equal(permuted.proof_sha256, proof.proof_sha256);
  assert.deepEqual(permuted.receipts, proof.receipts);
  assert.throws(
    () =>
      assertThirtyOfThirtyOfficialSuccess(
        records.slice(0, 29),
        manifest,
        "planora",
        fileHash(helperPath),
      ),
    /exactly 30 independently parsed official success receipts/,
  );
  assert.throws(
    () =>
      assertThirtyOfThirtyOfficialSuccess(
        [...records, records[0]],
        manifest,
        "planora",
        fileHash(helperPath),
      ),
    /exactly 30 independently parsed official success receipts/,
  );
  const tampered = structuredClone(records);
  tampered[0].official_validation.total += 1;
  assert.throws(
    () =>
      assertThirtyOfThirtyOfficialSuccess(
        tampered,
        manifest,
        "planora",
        fileHash(helperPath),
      ),
    /(evidence binding|parsed response) mismatch/,
  );
  const downgraded = structuredClone(records);
  downgraded[0].official_validation.evidence_version = 2;
  assert.throws(
    () =>
      assertThirtyOfThirtyOfficialSuccess(
        downgraded,
        manifest,
        "planora",
        fileHash(helperPath),
      ),
    /Unsupported official evidence version/,
  );
});

test("exclusive validation lock prevents concurrent submitters", () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "planora-official-lock-"));
  try {
    const first = acquireValidationLock(
      temporary,
      path.join(temporary, "report.json"),
      fileHash(helperPath),
    );
    assert.throws(
      () =>
        acquireValidationLock(
          temporary,
          path.join(temporary, "report.json"),
          fileHash(helperPath),
        ),
      /validation lock already exists/,
    );
    first.release();
    const second = acquireValidationLock(
      temporary,
      path.join(temporary, "report.json"),
      fileHash(helperPath),
    );
    second.release();
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test("validation lock release refuses a replaced named lock", () => {
  const temporary = fs.mkdtempSync(
    path.join(os.tmpdir(), "planora-official-lock-replaced-"),
  );
  try {
    const lock = acquireValidationLock(
      temporary,
      path.join(temporary, "report.json"),
      fileHash(helperPath),
    );
    const displaced = path.join(temporary, "displaced-lock.json");
    fs.renameSync(lock.lockPath, displaced);
    const foreign = Buffer.from("foreign-lock-must-survive\n");
    fs.writeFileSync(lock.lockPath, foreign);
    assert.throws(
      () => lock.release(),
      /validation lock identity changed before release/i,
    );
    assert.deepEqual(fs.readFileSync(lock.lockPath), foreign);
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test("validation lock never auto-recovers a malformed retained lock", () => {
  const temporary = fs.mkdtempSync(
    path.join(os.tmpdir(), "planora-official-lock-retained-"),
  );
  try {
    const lockPath = path.join(temporary, ".official-validation.lock");
    const retained = Buffer.from("malformed-retained-lock\n");
    fs.writeFileSync(lockPath, retained);
    assert.throws(
      () =>
        acquireValidationLock(
          temporary,
          path.join(temporary, "report.json"),
          fileHash(helperPath),
        ),
      /validation lock already exists/i,
    );
    assert.deepEqual(fs.readFileSync(lockPath), retained);
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});
