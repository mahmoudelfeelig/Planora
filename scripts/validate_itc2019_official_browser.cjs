"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { TextDecoder } = require("node:util");
const { chromium } = require("../web/node_modules/playwright");

const EXTERNAL_SOURCE_AUTHENTICITY =
  "endpoint_and_existing_cdp_session_observed_not_independently_attested";

function parseArgs(argv) {
  const result = { cdp: "http://127.0.0.1:9223", scope: "all" };
  for (let index = 2; index < argv.length; index += 1) {
    const key = argv[index];
    if (key === "--report" || key === "--cdp" || key === "--scope") {
      result[key.slice(2)] = argv[++index];
    } else {
      throw new Error(`Unknown argument: ${key}`);
    }
  }
  if (!result.report) throw new Error("--report is required");
  if (!new Set(["all", "best"]).has(result.scope)) {
    throw new Error("--scope must be all or best");
  }
  return result;
}

function windowsPath(value) {
  const match = String(value).match(/^\/mnt\/([a-zA-Z])\/(.*)$/);
  return match ? `${match[1].toUpperCase()}:/${match[2]}` : String(value);
}

function expectedComponents(record) {
  const objective = record.independent_validation?.objective;
  if (!objective) return null;
  const components = {};
  for (const field of ["total", "time", "room", "distribution", "student"]) {
    const value = objective[field];
    if (!Number.isSafeInteger(value) || value < 0) return null;
    components[field] = value;
  }
  return components;
}

function selectRecords(records, scope) {
  const valid = records.filter(
    (row) =>
      row.output_path &&
      row.independent_validation?.feasible === true &&
      expectedComponents(row),
  );
  if (scope === "all") return valid;
  const best = new Map();
  for (const row of valid) {
    const key = `${row.case}\u0000${row.solver}`;
    const current = best.get(key);
    if (
      !current ||
      expectedComponents(row).total < expectedComponents(current).total
    ) {
      best.set(key, row);
    }
  }
  return [...best.values()];
}

const RUN_IDENTITY_FIELDS = [
  "run_id",
  "case",
  "solver",
  "seed",
  "effective_seed",
  "seed_control",
  "seed_pairing_group",
  "repetition",
  "unseeded_trial",
];

function manifestDimension(manifest, field, predicate, description) {
  const values = manifest?.[field];
  if (!Array.isArray(values) || values.length === 0) {
    throw new Error(`Manifest ${field} must be a non-empty array`);
  }
  if (!values.every(predicate)) {
    throw new Error(`Manifest ${field} must contain only ${description}`);
  }
  if (new Set(values).size !== values.length) {
    throw new Error(`Manifest ${field} contains duplicates`);
  }
  return values;
}

function deriveExpectedRunSpecs(manifest) {
  if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
    throw new Error("Manifest must be an object");
  }
  const cases = manifestDimension(
    manifest,
    "cases",
    (value) => typeof value === "string" && value.length > 0,
    "non-empty strings",
  );
  const solvers = manifestDimension(
    manifest,
    "solvers",
    (value) => typeof value === "string" && value.length > 0,
    "non-empty strings",
  );
  const seeds = manifestDimension(
    manifest,
    "seeds",
    (value) => Number.isSafeInteger(value),
    "safe integers",
  );
  const repetitions = manifest.repetitions;
  if (!Number.isSafeInteger(repetitions) || repetitions <= 0) {
    throw new Error("Manifest repetitions must be a positive safe integer");
  }

  const expected = [];
  for (const caseId of cases) {
    for (const solver of solvers) {
      for (const [seedIndex, seed] of seeds.entries()) {
        for (let repetition = 1; repetition <= repetitions; repetition += 1) {
          if (solver === "lemos-maxsat") {
            const trial = seedIndex * repetitions + repetition;
            expected.push({
              run_id: `${caseId}__${solver}__unseeded-trial-${String(trial).padStart(3, "0")}`,
              case: caseId,
              solver,
              seed: null,
              effective_seed: null,
              seed_control: "unsupported_upstream_clock_seed",
              seed_pairing_group: null,
              repetition,
              unseeded_trial: trial,
            });
          } else {
            expected.push({
              run_id: `${caseId}__${solver}__seed-${seed}__rep-${String(repetition).padStart(2, "0")}`,
              case: caseId,
              solver,
              seed,
              effective_seed: seed,
              seed_control: "explicit",
              seed_pairing_group: seed,
              repetition,
              unseeded_trial: null,
            });
          }
        }
      }
    }
  }
  return expected;
}

function expectedRunSpecs(manifest) {
  const derived = deriveExpectedRunSpecs(manifest);
  if (!Array.isArray(manifest.expected_runs)) {
    throw new Error("Manifest expected_runs must be an array");
  }
  if (manifest.expected_runs.length !== derived.length) {
    throw new Error("Manifest expected_runs does not match derived run identities");
  }

  const derivedById = new Map(derived.map((row) => [row.run_id, row]));
  const seen = new Set();
  for (const row of manifest.expected_runs) {
    if (!row || typeof row !== "object" || Array.isArray(row)) {
      throw new Error("Manifest expected_runs contains a non-object entry");
    }
    if (typeof row.run_id !== "string" || row.run_id.length === 0) {
      throw new Error("Manifest expected_runs contains an empty run identity");
    }
    if (seen.has(row.run_id)) {
      throw new Error(`Manifest expected_runs contains duplicate run identity: ${row.run_id}`);
    }
    seen.add(row.run_id);
    const expected = derivedById.get(row.run_id);
    if (!expected) {
      throw new Error(`Unexpected manifest run identity: ${row.run_id}`);
    }
    for (const field of RUN_IDENTITY_FIELDS) {
      if (row[field] !== expected[field]) {
        throw new Error(`Manifest run identity mismatch (${field}): ${row.run_id}`);
      }
    }
  }
  return derived;
}

function expectedRunIds(manifest) {
  return expectedRunSpecs(manifest).map((row) => row.run_id);
}

function sha256File(value) {
  const digest = crypto.createHash("sha256");
  digest.update(fs.readFileSync(value));
  return digest.digest("hex");
}

function sha256Bytes(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function assertSha256(value, label) {
  if (typeof value !== "string" || !/^[0-9a-f]{64}$/.test(value)) {
    throw new Error(`${label} is not a lowercase SHA-256 digest`);
  }
}

function validatorEndpoint(value) {
  if (typeof value !== "string") {
    throw new Error("Official validator URL is invalid");
  }
  let parsedUrl;
  try {
    parsedUrl = new URL(value);
  } catch {
    throw new Error("Official validator URL is invalid");
  }
  if (
    !/^https:\/\/(?:www\.)?itc2019\.org\/server\/validator\/[A-Za-z0-9._~-]+$/iu.test(
      value,
    ) ||
    parsedUrl.protocol !== "https:" ||
    !new Set(["itc2019.org", "www.itc2019.org"]).has(parsedUrl.hostname) ||
    parsedUrl.port !== "" ||
    parsedUrl.username !== "" ||
    parsedUrl.password !== "" ||
    parsedUrl.search !== "" ||
    parsedUrl.hash !== "" ||
    !/^\/server\/validator\/[A-Za-z0-9._~-]+$/.test(parsedUrl.pathname)
  ) {
    throw new Error("Official validator URL is outside the authenticated validator endpoint");
  }
  return parsedUrl;
}

function officialRunBinding(record) {
  for (const field of ["run_id", "case", "solver", "seed_control"]) {
    if (typeof record?.[field] !== "string" || record[field].length === 0) {
      throw new Error(`Official evidence has an invalid ${field} binding`);
    }
  }
  assertSha256(record.input_sha256, "Run input hash");
  for (const field of ["seed", "effective_seed", "seed_pairing_group"]) {
    if (record[field] !== null && !Number.isSafeInteger(record[field])) {
      throw new Error(`Official evidence has an invalid ${field} binding`);
    }
  }
  if (!Number.isSafeInteger(record.repetition) || record.repetition <= 0) {
    throw new Error("Official evidence has an invalid repetition binding");
  }
  if (record.unseeded_trial !== null && !Number.isSafeInteger(record.unseeded_trial)) {
    throw new Error("Official evidence has an invalid unseeded_trial binding");
  }
  return Object.fromEntries([
    ...RUN_IDENTITY_FIELDS.map((field) => [field, record[field]]),
    ["input_sha256", record.input_sha256],
  ]);
}

function canonicalTimestamp(value, label) {
  if (typeof value !== "string") {
    throw new Error(`${label} is not a canonical ISO-8601 value`);
  }
  const timestamp = value;
  if (
    !/^(?!0000)\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/u.test(timestamp) ||
    Number.isNaN(Date.parse(timestamp)) ||
    new Date(timestamp).toISOString() !== timestamp
  ) {
    throw new Error(`${label} is not a canonical ISO-8601 value`);
  }
  return timestamp;
}

function submissionIntentBindingSha256(intent) {
  const binding = { ...intent };
  delete binding.submission_intent_binding_sha256;
  return sha256Bytes(Buffer.from(JSON.stringify(canonicalJson(binding)), "utf8"));
}

function createSubmissionIntent({
  record,
  helperSha256,
  createdAt,
  attemptId = crypto.randomUUID(),
}) {
  assertSha256(record.output_sha256, "Submission output hash");
  assertSha256(helperSha256, "Helper hash");
  if (
    typeof attemptId !== "string" ||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(attemptId)
  ) {
    throw new Error("Submission attempt ID is not a lowercase UUIDv4");
  }
  const intent = {
    schema: "planora.itc2019.official-submission-intent.v1",
    ...officialRunBinding(record),
    output_sha256: record.output_sha256,
    helper_sha256: helperSha256,
    attempt_id: attemptId,
    created_at: canonicalTimestamp(createdAt, "Submission intent timestamp"),
  };
  return {
    ...intent,
    submission_intent_binding_sha256: submissionIntentBindingSha256(intent),
  };
}

function assertSubmissionIntentIntegrity(intent, record, helperSha256) {
  if (!intent || typeof intent !== "object" || Array.isArray(intent)) {
    throw new Error(`Submission intent is missing for ${record.run_id}`);
  }
  const rebuilt = createSubmissionIntent({
    record,
    helperSha256,
    createdAt: intent.created_at,
    attemptId: intent.attempt_id,
  });
  if (
    JSON.stringify(canonicalJson(rebuilt)) !==
    JSON.stringify(canonicalJson(intent))
  ) {
    throw new Error(`Submission intent binding mismatch for ${record.run_id}`);
  }
  return intent;
}

function countBufferOccurrences(haystack, needle) {
  if (needle.length === 0) return 0;
  let count = 0;
  let offset = 0;
  while ((offset = haystack.indexOf(needle, offset)) !== -1) {
    count += 1;
    offset += needle.length;
  }
  return count;
}

function requestEvidence(request, uploadedBytes, uploadedSha256) {
  if (!request || request.method() !== "POST") {
    throw new Error("Official response is not bound to a validator POST request");
  }
  const requestUrl = validatorEndpoint(request.url()).toString();
  const headers = request.headers();
  const contentType = String(headers?.["content-type"] || "");
  if (!/^multipart\/form-data\s*;/i.test(contentType)) {
    throw new Error("Official validator request is not a multipart file upload");
  }
  const body = request.postDataBuffer();
  if (!Buffer.isBuffer(body) || body.length === 0) {
    throw new Error("Official validator request body is unavailable");
  }
  if (sha256Bytes(uploadedBytes) !== uploadedSha256) {
    throw new Error("Selected output bytes drifted before validator submission");
  }
  if (countBufferOccurrences(body, uploadedBytes) !== 1) {
    throw new Error("Validator request is not uniquely bound to the current upload bytes");
  }
  return {
    request_method: "POST",
    request_url: requestUrl,
    request_content_type: contentType,
    request_body_sha256: sha256Bytes(body),
    uploaded_file_sha256: uploadedSha256,
  };
}

function assertNoDuplicateJsonObjectKeys(text) {
  let index = 0;

  function skipWhitespace() {
    while (/\s/u.test(text[index] || "")) index += 1;
  }

  function scanString() {
    const start = index;
    index += 1;
    while (index < text.length) {
      const character = text[index];
      index += 1;
      if (character === '"') {
        return JSON.parse(text.slice(start, index));
      }
      if (character === "\\") index += 1;
    }
    throw new Error("Unterminated JSON string");
  }

  function scanValue() {
    skipWhitespace();
    const character = text[index];
    if (character === "{") {
      index += 1;
      const keys = new Set();
      skipWhitespace();
      if (text[index] === "}") {
        index += 1;
        return;
      }
      while (index < text.length) {
        skipWhitespace();
        const key = scanString();
        if (keys.has(key)) {
          throw new Error(`Official response contains duplicate key: ${key}`);
        }
        keys.add(key);
        skipWhitespace();
        index += 1;
        scanValue();
        skipWhitespace();
        if (text[index] === "}") {
          index += 1;
          return;
        }
        index += 1;
      }
      throw new Error("Unterminated JSON object");
    }
    if (character === "[") {
      index += 1;
      skipWhitespace();
      if (text[index] === "]") {
        index += 1;
        return;
      }
      while (index < text.length) {
        scanValue();
        skipWhitespace();
        if (text[index] === "]") {
          index += 1;
          return;
        }
        index += 1;
      }
      throw new Error("Unterminated JSON array");
    }
    if (character === '"') {
      scanString();
      return;
    }
    while (index < text.length && !/[\s,\]}]/u.test(text[index])) index += 1;
  }

  scanValue();
}

function officialResult(rawResponse) {
  if (
    !Buffer.isBuffer(rawResponse) &&
    !(rawResponse instanceof Uint8Array) &&
    typeof rawResponse !== "string"
  ) {
    throw new Error("The official response must be supplied as exact bytes or text");
  }
  const bytes = Buffer.isBuffer(rawResponse)
    ? rawResponse
    : Buffer.from(rawResponse);
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
  } catch {
    throw new Error("The official response payload is not strict UTF-8 JSON");
  }
  let response;
  try {
    response = JSON.parse(text);
    assertNoDuplicateJsonObjectKeys(text);
  } catch (error) {
    if (String(error?.message || "").includes("duplicate key:")) throw error;
    throw new Error("The official response payload is not valid JSON");
  }
  const obj = response?.obj;
  if (!obj || response.status !== "200") {
    throw new Error(`Unexpected official response: ${JSON.stringify(response)}`);
  }
  const numericFields = {
    assigned: obj.assignedVariables?.value,
    variables: obj.assignedVariables?.total,
    total: obj.totalCost?.value,
    time: obj.timePenalty?.value,
    room: obj.roomPenalty?.value,
    distribution: obj.distributionPenalty?.value,
    student: obj.studentConflicts?.value,
  };
  for (const [field, value] of Object.entries(numericFields)) {
    if (
      typeof value !== "number" ||
      !Number.isSafeInteger(value) ||
      value < 0
    ) {
      throw new Error(`Official response has an invalid ${field} value`);
    }
  }
  const textFields = {
    instance: obj.instance,
    result: obj.result,
    "log identifier": obj.logId,
  };
  for (const [field, value] of Object.entries(textFields)) {
    if (typeof value !== "string" || value.length === 0) {
      throw new Error(`Official response has an invalid ${field} value`);
    }
  }
  return {
    instance: obj.instance,
    result: obj.result,
    ...numericFields,
    log_id: obj.logId,
  };
}

function evidenceBindingSha256(evidence) {
  const binding = {
    evidence_version: evidence.evidence_version,
    ...Object.fromEntries(
      [...RUN_IDENTITY_FIELDS, "input_sha256"].map((field) => [
        field,
        evidence[field],
      ]),
    ),
    response_sha256: evidence.response_sha256,
    response_capture_binding_sha256: evidence.response_capture_binding_sha256,
    submission_intent_binding_sha256:
      evidence.submission_intent_binding_sha256,
    submitted_output_sha256: evidence.submitted_output_sha256,
    helper_sha256: evidence.helper_sha256,
    attempt_id: evidence.attempt_id,
    captured_at: evidence.captured_at,
    response_url: evidence.response_url,
    response_status: evidence.response_status,
    response_content_type: evidence.response_content_type,
    log_id: evidence.log_id,
    request_method: evidence.request_method,
    request_url: evidence.request_url,
    request_content_type: evidence.request_content_type,
    request_body_sha256: evidence.request_body_sha256,
    uploaded_file_sha256: evidence.uploaded_file_sha256,
    correlation_method: evidence.correlation_method,
    external_source_authenticity: evidence.external_source_authenticity,
  };
  return sha256Bytes(Buffer.from(JSON.stringify(canonicalJson(binding)), "utf8"));
}

function responseCaptureBindingSha256(capture) {
  const binding = { ...capture };
  delete binding.response_body_base64;
  delete binding.response_capture_binding_sha256;
  return sha256Bytes(Buffer.from(JSON.stringify(canonicalJson(binding)), "utf8"));
}

function createOfficialResponseCapture({
  rawResponse,
  responseUrl,
  submittedOutputSha256,
  helperSha256,
  capturedAt,
  record,
  request,
  submissionIntent,
  responseStatus,
  responseContentType,
}) {
  const bytes = Buffer.isBuffer(rawResponse)
    ? rawResponse
    : Buffer.from(rawResponse);
  assertSha256(submittedOutputSha256, "Submitted output hash");
  assertSha256(helperSha256, "Helper hash");
  const intent = assertSubmissionIntentIntegrity(
    submissionIntent,
    record,
    helperSha256,
  );
  if (intent.output_sha256 !== submittedOutputSha256) {
    throw new Error("Official response does not match its submission intent output");
  }

  const parsedUrl = validatorEndpoint(responseUrl);
  const runBinding = officialRunBinding(record);
  if (!request || request.request_url !== parsedUrl.toString()) {
    throw new Error("Official response URL does not match its exact validator request");
  }
  if (
    request.uploaded_file_sha256 !== submittedOutputSha256 ||
    request.request_method !== "POST"
  ) {
    throw new Error("Official response request does not match the current upload");
  }
  if (
    typeof request.request_content_type !== "string" ||
    !/^multipart\/form-data\s*;/i.test(request.request_content_type)
  ) {
    throw new Error("Official response request is not bound to a multipart file upload");
  }
  assertSha256(request.request_body_sha256, "Validator request body hash");
  assertSha256(request.uploaded_file_sha256, "Uploaded file hash");
  if (!Number.isSafeInteger(responseStatus) || responseStatus < 100 || responseStatus > 599) {
    throw new Error("Official response HTTP status is invalid");
  }
  if (typeof responseContentType !== "string" || !responseContentType.trim()) {
    throw new Error("Official response Content-Type is missing");
  }
  const contentType = responseContentType.trim();

  const capture = {
    schema: "planora.itc2019.official-response-capture.v1",
    ...runBinding,
    ...request,
    attempt_id: intent.attempt_id,
    submission_intent_created_at: intent.created_at,
    submission_intent_binding_sha256:
      intent.submission_intent_binding_sha256,
    response_body_base64: bytes.toString("base64"),
    response_sha256: sha256Bytes(bytes),
    submitted_output_sha256: submittedOutputSha256,
    helper_sha256: helperSha256,
    captured_at: canonicalTimestamp(capturedAt, "Official response timestamp"),
    response_url: parsedUrl.toString(),
    response_status: responseStatus,
    response_content_type: contentType,
    correlation_method: "playwright_response_request_identity_and_multipart_bytes",
    external_source_authenticity: EXTERNAL_SOURCE_AUTHENTICITY,
  };
  return {
    ...capture,
    response_capture_binding_sha256: responseCaptureBindingSha256(capture),
  };
}

function assertResponseCaptureIntegrity(capture, record, helperSha256) {
  if (!capture || typeof capture !== "object" || Array.isArray(capture)) {
    throw new Error(`Official response capture is missing for ${record.run_id}`);
  }
  if (typeof capture.response_body_base64 !== "string") {
    throw new Error(`Official response bytes are missing for ${record.run_id}`);
  }
  const rawResponse = Buffer.from(capture.response_body_base64, "base64");
  if (rawResponse.toString("base64") !== capture.response_body_base64) {
    throw new Error(`Official response bytes are not canonical for ${record.run_id}`);
  }
  if (sha256Bytes(rawResponse) !== capture.response_sha256) {
    throw new Error(`Official response hash mismatch for ${record.run_id}`);
  }
  if (
    responseCaptureBindingSha256(capture) !==
    capture.response_capture_binding_sha256
  ) {
    throw new Error(`Official response capture binding mismatch for ${record.run_id}`);
  }
  if (
    capture.helper_sha256 !== helperSha256 ||
    capture.submitted_output_sha256 !== record.output_sha256 ||
    capture.uploaded_file_sha256 !== record.output_sha256
  ) {
    throw new Error(`Official response capture output/helper mismatch for ${record.run_id}`);
  }
  const runBinding = officialRunBinding(record);
  for (const [field, expected] of Object.entries(runBinding)) {
    if (capture[field] !== expected) {
      throw new Error(`Official response capture run binding mismatch (${field}) for ${record.run_id}`);
    }
  }
  const rebuiltIntent = createSubmissionIntent({
    record,
    helperSha256,
    createdAt: capture.submission_intent_created_at,
    attemptId: capture.attempt_id,
  });
  if (
    rebuiltIntent.submission_intent_binding_sha256 !==
    capture.submission_intent_binding_sha256
  ) {
    throw new Error(`Official response capture intent mismatch for ${record.run_id}`);
  }
  validatorEndpoint(capture.response_url);
  if (
    capture.schema !== "planora.itc2019.official-response-capture.v1" ||
    capture.request_method !== "POST" ||
    capture.request_url !== capture.response_url ||
    typeof capture.request_content_type !== "string" ||
    !/^multipart\/form-data\s*;/i.test(capture.request_content_type) ||
    !Number.isSafeInteger(capture.response_status) ||
    capture.response_status < 100 ||
    capture.response_status > 599 ||
    typeof capture.response_content_type !== "string" ||
    capture.response_content_type.trim() === ""
  ) {
    throw new Error(`Official response capture request/response mismatch for ${record.run_id}`);
  }
  canonicalTimestamp(capture.captured_at, "Official response timestamp");
  assertSha256(capture.request_body_sha256, "Validator request body hash");
  assertSha256(capture.response_sha256, "Official response hash");
  return { capture, rawResponse };
}

function createOfficialValidationEvidence({ record, responseCapture }) {
  const { capture, rawResponse } = assertResponseCaptureIntegrity(
    responseCapture,
    record,
    responseCapture?.helper_sha256,
  );
  if (capture.response_status !== 200) {
    throw new Error(`Unexpected official HTTP response status: ${capture.response_status}`);
  }
  const official = officialResult(rawResponse);
  const parsedUrl = validatorEndpoint(capture.response_url);
  if (parsedUrl.pathname !== `/server/validator/${official.log_id}`) {
    throw new Error("Official log identifier does not match its response URL");
  }
  const evidence = {
    ...capture,
    ...official,
    evidence_version: 3,
  };
  delete evidence.schema;
  return {
    ...evidence,
    evidence_binding_sha256: evidenceBindingSha256(evidence),
  };
}

async function captureOfficialValidationFromPage({
  page,
  outputPath,
  record,
  submittedOutputSha256,
  helperSha256,
  submissionIntent,
  beforeSubmit,
  onResponseCaptured,
  capturedAt = () => new Date().toISOString(),
}) {
  if (typeof beforeSubmit !== "function") {
    throw new Error("A durable beforeSubmit callback is required");
  }
  if (typeof onResponseCaptured !== "function") {
    throw new Error("A durable onResponseCaptured callback is required");
  }
  assertSubmissionIntentIntegrity(submissionIntent, record, helperSha256);
  const fileInput = page.locator("input[type=file]");
  const validateButton = page.getByRole("button", {
    name: "Validate",
    exact: true,
  });
  if (
    (await fileInput.count()) !== 1 ||
    (await validateButton.count()) !== 1 ||
    !(await fileInput.isVisible()) ||
    !(await validateButton.isVisible()) ||
    !(await validateButton.isEnabled())
  ) {
    throw new Error("Official validator controls are missing, ambiguous, hidden, or disabled");
  }
  const beforeSelection = fs.readFileSync(outputPath);
  if (sha256Bytes(beforeSelection) !== submittedOutputSha256) {
    throw new Error(`Output hash drift before upload for ${record.run_id}`);
  }
  await fileInput.setInputFiles(outputPath);
  const uploadedBytes = fs.readFileSync(outputPath);
  if (
    !uploadedBytes.equals(beforeSelection) ||
    sha256Bytes(uploadedBytes) !== submittedOutputSha256
  ) {
    throw new Error(`Output bytes changed after file selection for ${record.run_id}`);
  }

  const observedRequests = [];
  const onRequest = (candidate) => {
    try {
      if (
        candidate.method() === "POST" &&
        validatorEndpoint(candidate.url())
      ) {
        observedRequests.push(candidate);
      }
    } catch {
      // Ignore unrelated requests; the awaited response must still match exactly.
    }
  };
  page.on("request", onRequest);
  try {
    const responsePromise = page.waitForResponse(
      (response) => {
        try {
          return (
            response.request().method() === "POST" &&
            Boolean(validatorEndpoint(response.url()))
          );
        } catch {
          return false;
        }
      },
      { timeout: 30000 },
    );
    await beforeSubmit();
    await validateButton.click();
    const response = await responsePromise;
    const exactRequest = response.request();
    if (
      observedRequests.length !== 1 ||
      observedRequests[0] !== exactRequest
    ) {
      throw new Error("Official response did not match exactly one current Playwright request object");
    }
    const request = requestEvidence(
      exactRequest,
      uploadedBytes,
      submittedOutputSha256,
    );
    if (response.url() !== request.request_url) {
      throw new Error("Official response URL does not match its exact Playwright request");
    }
    const rawResponse = Buffer.from(await response.body());
    const responseCapture = createOfficialResponseCapture({
      rawResponse,
      responseUrl: response.url(),
      submittedOutputSha256,
      helperSha256,
      capturedAt: capturedAt(),
      record,
      request,
      submissionIntent,
      responseStatus: response.status(),
      responseContentType: response.headers()["content-type"],
    });
    await onResponseCaptured(responseCapture);
    return createOfficialValidationEvidence({ record, responseCapture });
  } finally {
    page.off("request", onRequest);
  }
}

function assertNoReusedOfficialEvidence(records) {
  const fields = [
    "log_id",
    "attempt_id",
    "response_sha256",
    "request_body_sha256",
    "submission_intent_binding_sha256",
    "response_capture_binding_sha256",
    "evidence_binding_sha256",
  ];
  const seen = new Map(fields.map((field) => [field, new Map()]));
  for (const record of records) {
    const evidence = record?.official_validation;
    if (!evidence || typeof evidence !== "object") continue;
    for (const field of fields) {
      const value = evidence[field];
      if (typeof value !== "string" || value.length === 0) {
        throw new Error(`Official evidence is missing ${field} for ${record.run_id}`);
      }
      const priorRun = seen.get(field).get(value);
      if (priorRun && priorRun !== record.run_id) {
        throw new Error(
          `Reused official ${field} across ${priorRun} and ${record.run_id}`,
        );
      }
      seen.get(field).set(value, record.run_id);
    }
  }
}

function agrees(record, official) {
  const expected = expectedComponents(record);
  return Boolean(
    expected &&
      official.instance === record.case &&
      official.result === "OK" &&
      official.assigned === official.variables &&
      official.total === expected.total &&
      official.time === expected.time &&
      official.room === expected.room &&
      official.distribution === expected.distribution &&
      official.student === expected.student,
  );
}

function assertCompleteSelection(selected, manifest, scope) {
  const expectedSpecs = expectedRunSpecs(manifest);
  const expectedIds = expectedSpecs.map((row) => row.run_id);
  const selectedIds = selected.map((row) => String(row.run_id));
  const uniqueSelectedIds = new Set(selectedIds);
  let complete = uniqueSelectedIds.size === selectedIds.length;

  if (scope === "all") {
    const expectedSet = new Set(expectedIds);
    complete =
      complete &&
      expectedSet.size === expectedIds.length &&
      selectedIds.length === expectedIds.length &&
      selectedIds.every((runId) => expectedSet.has(runId));
  } else {
    const requiredKeys = [
      ...new Set(
        expectedSpecs.map((row) => `${row.case}\u0000${row.solver}`),
      ),
    ];
    const requiredSet = new Set(requiredKeys);
    const selectedKeys = selected.map((row) => `${row.case}\u0000${row.solver}`);
    complete =
      complete &&
      requiredKeys.length > 0 &&
      requiredSet.size === requiredKeys.length &&
      new Set(selectedKeys).size === selectedKeys.length &&
      selectedKeys.length === requiredKeys.length &&
      selectedKeys.every((key) => requiredSet.has(key));
  }

  if (!complete) {
    throw new Error("The required official-validator selection is incomplete or duplicated");
  }
  return selected.length;
}

function officialValidationState(record) {
  const status = record.official_validator_status;
  const agreement = record.official_validator_agreement;
  const outputHash = record.official_validated_output_sha256;
  const evidence = record.official_validation;
  const intent = record.official_submission_intent;
  const responseCapture = record.official_response_capture;
  const empty = (value) => value === undefined || value === null;
  const object = (value) =>
    value && typeof value === "object" && !Array.isArray(value);
  if (
    (status === undefined || status === null || status === "pending_upload") &&
    empty(agreement) &&
    empty(outputHash) &&
    empty(evidence) &&
    empty(intent) &&
    empty(responseCapture)
  ) {
    return "absent";
  }
  if (
    new Set(["agreement", "disagreement"]).has(status) &&
    typeof agreement === "boolean" &&
    typeof outputHash === "string" &&
    object(evidence) &&
    empty(intent) &&
    empty(responseCapture)
  ) {
    return "complete";
  }
  if (
    status === "submission_intent_committed" &&
    agreement === null &&
    typeof outputHash === "string" &&
    empty(evidence) &&
    object(intent) &&
    empty(responseCapture)
  ) {
    return "submission_intent_committed";
  }
  if (
    status === "response_captured" &&
    agreement === null &&
    typeof outputHash === "string" &&
    empty(evidence) &&
    object(intent) &&
    object(responseCapture)
  ) {
    return "response_captured";
  }
  return "incomplete";
}

function assertEvidenceIntegrity(record, helperHash) {
  const evidence = record.official_validation;
  if (evidence.evidence_version !== 3) {
    throw new Error(`Unsupported official evidence version for ${record.run_id}`);
  }
  if (typeof evidence.response_body_base64 !== "string") {
    throw new Error(`Official response bytes are missing for ${record.run_id}`);
  }
  const rawResponse = Buffer.from(evidence.response_body_base64, "base64");
  if (rawResponse.toString("base64") !== evidence.response_body_base64) {
    throw new Error(`Official response bytes are not canonical for ${record.run_id}`);
  }
  if (sha256Bytes(rawResponse) !== evidence.response_sha256) {
    throw new Error(`Official response hash mismatch for ${record.run_id}`);
  }
  if (evidenceBindingSha256(evidence) !== evidence.evidence_binding_sha256) {
    throw new Error(`Official evidence binding mismatch for ${record.run_id}`);
  }
  if (
    evidence.submitted_output_sha256 !== record.output_sha256 ||
    record.official_validated_output_sha256 !== record.output_sha256
  ) {
    throw new Error(`Official evidence output binding mismatch for ${record.run_id}`);
  }
  if (evidence.helper_sha256 !== helperHash) {
    throw new Error(`Official evidence helper binding mismatch for ${record.run_id}`);
  }
  const runBinding = officialRunBinding(record);
  for (const [field, expected] of Object.entries(runBinding)) {
    if (evidence[field] !== expected) {
      throw new Error(`Official evidence run binding mismatch (${field}) for ${record.run_id}`);
    }
  }
  if (
    evidence.request_method !== "POST" ||
    evidence.request_url !== evidence.response_url ||
    evidence.uploaded_file_sha256 !== record.output_sha256 ||
    evidence.correlation_method !==
      "playwright_response_request_identity_and_multipart_bytes" ||
    evidence.external_source_authenticity !== EXTERNAL_SOURCE_AUTHENTICITY
  ) {
    throw new Error(`Official evidence request binding mismatch for ${record.run_id}`);
  }
  assertSha256(evidence.response_sha256, "Official response hash");
  assertSha256(evidence.evidence_binding_sha256, "Official evidence binding hash");
  assertSha256(evidence.submitted_output_sha256, "Submitted output hash");
  assertSha256(evidence.helper_sha256, "Helper hash");
  assertSha256(evidence.input_sha256, "Run input hash");
  assertSha256(evidence.request_body_sha256, "Validator request body hash");
  assertSha256(evidence.uploaded_file_sha256, "Uploaded file hash");
  assertSha256(
    evidence.response_capture_binding_sha256,
    "Official response capture binding hash",
  );
  assertSha256(
    evidence.submission_intent_binding_sha256,
    "Submission intent binding hash",
  );

  const reparsed = officialResult(rawResponse);
  for (const field of [
    "instance",
    "result",
    "assigned",
    "variables",
    "total",
    "time",
    "room",
    "distribution",
    "student",
    "log_id",
  ]) {
    if (evidence[field] !== reparsed[field]) {
      throw new Error(`Official parsed response mismatch (${field}) for ${record.run_id}`);
    }
  }

  const responseCapture = {
    schema: "planora.itc2019.official-response-capture.v1",
    ...officialRunBinding(record),
    attempt_id: evidence.attempt_id,
    submission_intent_created_at: evidence.submission_intent_created_at,
    submission_intent_binding_sha256:
      evidence.submission_intent_binding_sha256,
    response_body_base64: evidence.response_body_base64,
    response_sha256: evidence.response_sha256,
    submitted_output_sha256: evidence.submitted_output_sha256,
    helper_sha256: evidence.helper_sha256,
    captured_at: evidence.captured_at,
    response_url: evidence.response_url,
    response_status: evidence.response_status,
    response_content_type: evidence.response_content_type,
    correlation_method: evidence.correlation_method,
    external_source_authenticity: evidence.external_source_authenticity,
    request_method: evidence.request_method,
    request_url: evidence.request_url,
    request_content_type: evidence.request_content_type,
    request_body_sha256: evidence.request_body_sha256,
    uploaded_file_sha256: evidence.uploaded_file_sha256,
    response_capture_binding_sha256:
      evidence.response_capture_binding_sha256,
  };
  const rebuilt = createOfficialValidationEvidence({
    record,
    responseCapture,
  });
  if (
    JSON.stringify(canonicalJson(rebuilt)) !==
    JSON.stringify(canonicalJson(evidence))
  ) {
    throw new Error(`Official evidence contains unbound fields for ${record.run_id}`);
  }

  const agreement = agrees(record, reparsed);
  if (
    record.official_validator_agreement !== agreement ||
    record.official_validator_status !==
      (agreement ? "agreement" : "disagreement")
  ) {
    throw new Error(`Official agreement state mismatch for ${record.run_id}`);
  }
  return agreement;
}

const PERSISTED_OFFICIAL_FIELDS = [
  "official_validator_status",
  "official_validator_agreement",
  "official_validated_output_sha256",
  "official_validation",
  "official_submission_intent",
  "official_response_capture",
];

function canonicalEqual(first, second) {
  return (
    JSON.stringify(canonicalJson(first)) === JSON.stringify(canonicalJson(second))
  );
}

function assertMatchingPersistedOfficialFields(record, checkpoint) {
  for (const field of PERSISTED_OFFICIAL_FIELDS) {
    if (!canonicalEqual(record[field], checkpoint[field])) {
      throw new Error(`Persisted official validation mismatch for ${record.run_id}`);
    }
  }
}

function resolvePersistedOfficialValidation(record, checkpoint, helperHash) {
  const reportState = officialValidationState(record);
  const checkpointState = officialValidationState(checkpoint);
  if (reportState === "incomplete" || checkpointState === "incomplete") {
    throw new Error(`Detected incomplete official-validation state for ${record.run_id}`);
  }
  if (reportState !== checkpointState) {
    throw new Error(`Detected interrupted official-validation resume for ${record.run_id}`);
  }
  assertMatchingPersistedOfficialFields(record, checkpoint);
  if (reportState === "absent") return { state: "absent" };

  if (
    record.official_validated_output_sha256 !== record.output_sha256 ||
    checkpoint.official_validated_output_sha256 !== checkpoint.output_sha256
  ) {
    throw new Error(`Persisted official output binding mismatch for ${record.run_id}`);
  }

  if (reportState === "submission_intent_committed") {
    assertSubmissionIntentIntegrity(
      record.official_submission_intent,
      record,
      helperHash,
    );
    assertSubmissionIntentIntegrity(
      checkpoint.official_submission_intent,
      checkpoint,
      helperHash,
    );
    throw new Error(
      `Ambiguous submission intent for ${record.run_id}; it must not be resubmitted`,
    );
  }

  if (reportState === "response_captured") {
    const intent = assertSubmissionIntentIntegrity(
      record.official_submission_intent,
      record,
      helperHash,
    );
    assertSubmissionIntentIntegrity(
      checkpoint.official_submission_intent,
      checkpoint,
      helperHash,
    );
    const { capture } = assertResponseCaptureIntegrity(
      record.official_response_capture,
      record,
      helperHash,
    );
    assertResponseCaptureIntegrity(
      checkpoint.official_response_capture,
      checkpoint,
      helperHash,
    );
    if (
      capture.submission_intent_binding_sha256 !==
      intent.submission_intent_binding_sha256
    ) {
      throw new Error(`Official response capture intent mismatch for ${record.run_id}`);
    }
    return {
      state: "response_captured",
      submissionIntent: intent,
      responseCapture: capture,
    };
  }

  const agreement = assertEvidenceIntegrity(record, helperHash);
  assertEvidenceIntegrity(checkpoint, helperHash);
  return { state: "complete", agreement };
}

function assertPersistedOfficialValidation(record, checkpoint, helperHash) {
  const resolved = resolvePersistedOfficialValidation(
    record,
    checkpoint,
    helperHash,
  );
  if (resolved.state === "absent") return false;
  if (resolved.state !== "complete") {
    throw new Error(
      `Detected incomplete official-validation state for ${record.run_id}`,
    );
  }
  const agreement = resolved.agreement;
  if (!agreement) {
    throw new Error(`Persisted official validator disagreement for ${record.run_id}`);
  }
  return true;
}

function assertThirtyOfThirtyOfficialSuccess(
  records,
  manifest,
  solver,
  helperHash,
) {
  assertSha256(helperHash, "Helper hash");
  if (typeof solver !== "string" || solver.length === 0) {
    throw new Error("Official success proof solver is invalid");
  }
  const expected = expectedRunSpecs(manifest).filter(
    (row) => row.solver === solver,
  );
  if (
    !Array.isArray(records) ||
    records.length !== 30 ||
    expected.length !== 30 ||
    new Set(expected.map((row) => row.case)).size !== 30
  ) {
    throw new Error(
      "Official success proof requires exactly 30 independently parsed official success receipts",
    );
  }

  const expectedById = new Map(expected.map((row) => [row.run_id, row]));
  const seenRunIds = new Set();
  const seenCases = new Set();
  const seenOutputs = new Set();
  const seenEvidence = new Set();
  const receipts = [];
  for (const record of records) {
    const expectedRecord = expectedById.get(String(record?.run_id));
    if (!expectedRecord || record.solver !== solver) {
      throw new Error(`Official success proof has an unexpected run: ${record?.run_id}`);
    }
    for (const field of RUN_IDENTITY_FIELDS) {
      if (record[field] !== expectedRecord[field]) {
        throw new Error(
          `Official success proof run identity mismatch (${field}): ${record.run_id}`,
        );
      }
    }
    if (
      manifest.inputs &&
      record.input_sha256 !== manifest.inputs[record.case]
    ) {
      throw new Error(`Official success proof input hash mismatch: ${record.run_id}`);
    }
    assertSha256(record.input_sha256, "Run input hash");
    assertSha256(record.output_sha256, "Run output hash");
    const evidence = record.official_validation;
    if (!evidence || typeof evidence !== "object" || Array.isArray(evidence)) {
      throw new Error(`Official success receipt is missing for ${record.run_id}`);
    }
    assertSha256(
      evidence.evidence_binding_sha256,
      "Official evidence binding hash",
    );
    if (
      record.official_validator_status !== "agreement" ||
      record.official_validator_agreement !== true ||
      record.official_validated_output_sha256 !== record.output_sha256 ||
      assertEvidenceIntegrity(record, helperHash) !== true
    ) {
      throw new Error(`Official success receipt is not an agreement: ${record.run_id}`);
    }
    if (
      seenRunIds.has(record.run_id) ||
      seenCases.has(record.case) ||
      seenOutputs.has(record.output_sha256) ||
      seenEvidence.has(evidence.evidence_binding_sha256)
    ) {
      throw new Error(`Official success proof contains a reused identity: ${record.run_id}`);
    }
    seenRunIds.add(record.run_id);
    seenCases.add(record.case);
    seenOutputs.add(record.output_sha256);
    seenEvidence.add(evidence.evidence_binding_sha256);
    receipts.push({
      ...Object.fromEntries(
        RUN_IDENTITY_FIELDS.map((field) => [field, record[field]]),
      ),
      input_sha256: record.input_sha256,
      output_sha256: record.output_sha256,
      evidence_binding_sha256: evidence.evidence_binding_sha256,
      response_capture_binding_sha256:
        evidence.response_capture_binding_sha256,
      submission_intent_binding_sha256:
        evidence.submission_intent_binding_sha256,
      response_sha256: evidence.response_sha256,
      request_body_sha256: evidence.request_body_sha256,
      log_id: evidence.log_id,
      attempt_id: evidence.attempt_id,
      captured_at: evidence.captured_at,
      response_url: evidence.response_url,
      official_result: Object.fromEntries(
        [
          "instance",
          "result",
          "assigned",
          "variables",
          "total",
          "time",
          "room",
          "distribution",
          "student",
        ].map((field) => [field, evidence[field]]),
      ),
    });
  }
  assertNoReusedOfficialEvidence(records);
  if (
    seenRunIds.size !== 30 ||
    seenCases.size !== 30 ||
    seenOutputs.size !== 30 ||
    seenEvidence.size !== 30
  ) {
    throw new Error(
      "Official success proof requires exactly 30 independently parsed official success receipts",
    );
  }
  receipts.sort((first, second) =>
    first.run_id < second.run_id ? -1 : first.run_id > second.run_id ? 1 : 0,
  );
  const proof = {
    schema: "planora.itc2019.official-success-proof.v1",
    status: "VERIFIED_30_OF_30",
    solver,
    receipt_count: receipts.length,
    manifest_binding_sha256: sha256Bytes(
      Buffer.from(JSON.stringify(canonicalJson(manifest)), "utf8"),
    ),
    helper_sha256: helperHash,
    receipts,
  };
  return {
    ...proof,
    proof_sha256: sha256Bytes(
      Buffer.from(JSON.stringify(canonicalJson(proof)), "utf8"),
    ),
  };
}

function durableJsonBytes(value) {
  return Buffer.from(`${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function fsyncDirectory(directory) {
  let directoryFd;
  try {
    directoryFd = fs.openSync(directory, "r");
    fs.fsyncSync(directoryFd);
  } catch (error) {
    if (
      process.platform === "win32" &&
      new Set(["EACCES", "EBADF", "EINVAL", "EPERM"]).has(error?.code)
    ) {
      return;
    }
    throw error;
  } finally {
    if (directoryFd !== undefined) fs.closeSync(directoryFd);
  }
}

function writeDurableJson(targetPath, value) {
  const directory = path.dirname(targetPath);
  const temporary = path.join(
    directory,
    `.${path.basename(targetPath)}.${process.pid}.${crypto.randomUUID()}.tmp`,
  );
  let temporaryFd;
  try {
    temporaryFd = fs.openSync(temporary, "wx", 0o600);
    fs.writeFileSync(temporaryFd, durableJsonBytes(value));
    fs.fsyncSync(temporaryFd);
    fs.closeSync(temporaryFd);
    temporaryFd = undefined;
    fs.renameSync(temporary, targetPath);
    const targetFd = fs.openSync(targetPath, "r+");
    try {
      fs.fsyncSync(targetFd);
    } finally {
      fs.closeSync(targetFd);
    }
    fsyncDirectory(directory);
  } catch (error) {
    if (temporaryFd !== undefined) {
      try {
        fs.closeSync(temporaryFd);
      } catch {
        // Preserve the original durable-publication failure.
      }
    }
    try {
      fs.unlinkSync(temporary);
    } catch (cleanupError) {
      if (cleanupError?.code !== "ENOENT") {
        error.message = `${error.message}; temporary cleanup failed: ${cleanupError.message}`;
      }
    }
    throw error;
  }
}

function writeReport(reportPath, report) {
  writeDurableJson(reportPath, report);
}

function sameFileIdentity(first, second) {
  return (
    first.dev === second.dev &&
    first.ino === second.ino &&
    first.birthtimeMs === second.birthtimeMs
  );
}

function acquireValidationLock(matrixRoot, reportPath, helperHash) {
  assertSha256(helperHash, "Helper hash");
  const canonicalRoot = fs.realpathSync(matrixRoot);
  const canonicalReportPath = fs.existsSync(reportPath)
    ? fs.realpathSync(reportPath)
    : path.resolve(reportPath);
  const lockPath = path.join(canonicalRoot, ".official-validation.lock");
  const token = crypto.randomUUID();
  const owner = {
    schema: "planora.itc2019.official-validation-lock.v1",
    token,
    pid: process.pid,
    hostname: os.hostname(),
    report_path: canonicalReportPath,
    helper_sha256: helperHash,
    acquired_at: new Date().toISOString(),
  };
  const ownerBytes = durableJsonBytes(owner);
  let fd;
  try {
    fd = fs.openSync(lockPath, "wx", 0o600);
  } catch (error) {
    if (error?.code === "EEXIST") {
      throw new Error(`Official validation lock already exists: ${lockPath}`);
    }
    throw error;
  }

  try {
    fs.writeFileSync(fd, ownerBytes);
    fs.fsyncSync(fd);
    fsyncDirectory(canonicalRoot);
  } catch (error) {
    fs.closeSync(fd);
    throw error;
  }

  let closed = false;
  return {
    lockPath,
    owner: structuredClone(owner),
    release() {
      if (closed) throw new Error("Official validation lock is already released");
      let namedFd;
      try {
        const retainedStat = fs.fstatSync(fd);
        namedFd = fs.openSync(lockPath, "r");
        const namedStat = fs.fstatSync(namedFd);
        if (!sameFileIdentity(retainedStat, namedStat)) {
          throw new Error("Official validation lock identity changed before release");
        }
        const namedBytes = fs.readFileSync(namedFd);
        if (!namedBytes.equals(ownerBytes)) {
          throw new Error("Official validation lock bytes changed before release");
        }
        let namedOwner;
        try {
          namedOwner = JSON.parse(namedBytes.toString("utf8"));
        } catch {
          throw new Error("Official validation lock owner metadata is malformed");
        }
        if (namedOwner.token !== token) {
          throw new Error("Official validation lock token changed before release");
        }
        const pathStat = fs.statSync(lockPath);
        const finalRetainedStat = fs.fstatSync(fd);
        if (
          !sameFileIdentity(retainedStat, pathStat) ||
          !sameFileIdentity(retainedStat, finalRetainedStat)
        ) {
          throw new Error("Official validation lock identity changed before unlink");
        }
        fs.unlinkSync(lockPath);
        fsyncDirectory(canonicalRoot);
      } finally {
        if (namedFd !== undefined) fs.closeSync(namedFd);
        fs.closeSync(fd);
        closed = true;
      }
    },
  };
}

function canonicalJson(value) {
  if (Array.isArray(value)) return value.map(canonicalJson);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonicalJson(value[key])]),
    );
  }
  return value;
}

function assertManifestBinding(reportPath, report) {
  const manifestPath = path.join(path.dirname(reportPath), "manifest.json");
  if (!fs.existsSync(manifestPath)) {
    throw new Error("The controlled matrix manifest.json is missing");
  }
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  if (
    JSON.stringify(canonicalJson(manifest)) !==
    JSON.stringify(canonicalJson(report.manifest || {}))
  ) {
    throw new Error("The report manifest does not match manifest.json");
  }
  const helperHash = sha256File(__filename);
  assertNoReusedOfficialEvidence(report.records || []);
  if (helperHash !== manifest.official_validator_helper_sha256) {
    throw new Error("The official validator helper hash does not match the matrix manifest");
  }
  return manifest;
}

function validationContext(matrixRoot, row) {
  const outputPath = windowsPath(row.output_path);
  if (!fs.existsSync(outputPath)) {
    throw new Error(`Output is unavailable to the browser: ${outputPath}`);
  }
  const canonicalOutput = fs.realpathSync(outputPath);
  const canonicalRuns = `${fs.realpathSync(path.join(matrixRoot, "runs"))}${path.sep}`;
  const expectedOutput = fs.realpathSync(
    path.join(matrixRoot, "runs", String(row.run_id), "solution.xml"),
  );
  if (
    !canonicalOutput.startsWith(canonicalRuns) ||
    canonicalOutput !== expectedOutput ||
    path.extname(canonicalOutput).toLowerCase() !== ".xml"
  ) {
    throw new Error(`Output is outside the controlled XML matrix: ${row.run_id}`);
  }
  const currentOutputSha256 = sha256File(outputPath);
  if (currentOutputSha256 !== row.output_sha256) {
    throw new Error(`Output hash drift for ${row.run_id}`);
  }
  const checkpointPath = path.join(
    matrixRoot,
    "runs",
    String(row.run_id),
    "result.json",
  );
  if (!fs.existsSync(checkpointPath)) {
    throw new Error(`Checkpoint is missing for ${row.run_id}`);
  }
  const checkpoint = JSON.parse(fs.readFileSync(checkpointPath, "utf8"));
  if (
    checkpoint.run_id !== row.run_id ||
    checkpoint.output_sha256 !== row.output_sha256 ||
    windowsPath(checkpoint.output_path) !== outputPath
  ) {
    throw new Error(`Checkpoint binding mismatch for ${row.run_id}`);
  }
  for (const field of [...RUN_IDENTITY_FIELDS, "input_sha256"]) {
    if (checkpoint[field] !== row[field]) {
      throw new Error(
        `Checkpoint run identity mismatch (${field}) for ${row.run_id}`,
      );
    }
  }
  return {
    row,
    outputPath,
    currentOutputSha256,
    checkpointPath,
    checkpoint,
  };
}

function setSubmissionIntentState(row, submissionIntent) {
  row.official_validator_status = "submission_intent_committed";
  row.official_validator_agreement = null;
  row.official_validated_output_sha256 = row.output_sha256;
  delete row.official_validation;
  row.official_submission_intent = submissionIntent;
  delete row.official_response_capture;
}

function setResponseCapturedState(row, submissionIntent, responseCapture) {
  row.official_validator_status = "response_captured";
  row.official_validator_agreement = null;
  row.official_validated_output_sha256 = row.output_sha256;
  delete row.official_validation;
  row.official_submission_intent = submissionIntent;
  row.official_response_capture = responseCapture;
}

function setCompleteOfficialState(row, evidence) {
  const agreement = agrees(row, evidence);
  row.official_validator_status = agreement ? "agreement" : "disagreement";
  row.official_validator_agreement = agreement;
  row.official_validated_output_sha256 = row.output_sha256;
  row.official_validation = evidence;
  delete row.official_submission_intent;
  delete row.official_response_capture;
  return agreement;
}

function updateOfficialValidationMetadata({
  report,
  selected,
  scope,
  expectedSelections,
  manifest,
  helperHash,
}) {
  const completedRuns = selected.filter(
    (item) =>
      new Set(["agreement", "disagreement"]).has(
        item.official_validator_status,
      ) && item.official_validated_output_sha256 === item.output_sha256,
  ).length;
  const agreementRuns = selected.filter(
    (item) => item.official_validator_agreement === true,
  ).length;
  report.official_validation = {
    validator: "itc2019.org authenticated web validator",
    scope,
    selected_runs: selected.length,
    completed_runs: completedRuns,
    agreement_runs: agreementRuns,
    complete: completedRuns === selected.length,
    all_agree:
      completedRuns === selected.length && agreementRuns === selected.length,
    selection_complete: true,
    expected_selections: expectedSelections,
    evidence_version: 3,
  };
  for (const summary of report.summary || []) {
    const rows = (report.records || []).filter(
      (row) => row.case === summary.case && row.solver === summary.solver,
    );
    summary.official_validator_agreement_complete =
      rows.length > 0 &&
      rows.every((row) => row.official_validator_agreement === true);
  }

  const expectedPlanora = expectedRunSpecs(manifest).filter(
    (row) => row.solver === "planora",
  );
  if (
    report.official_validation.complete &&
    report.official_validation.all_agree &&
    expectedPlanora.length === 30
  ) {
    report.official_validation_proof = assertThirtyOfThirtyOfficialSuccess(
      (report.records || []).filter((row) => row.solver === "planora"),
      manifest,
      "planora",
      helperHash,
    );
  } else {
    delete report.official_validation_proof;
  }
}

function publishOfficialState({
  context,
  reportPath,
  report,
  selected,
  scope,
  expectedSelections,
  manifest,
  helperHash,
}) {
  updateOfficialValidationMetadata({
    report,
    selected,
    scope,
    expectedSelections,
    manifest,
    helperHash,
  });
  writeDurableJson(context.checkpointPath, context.row);
  writeReport(reportPath, report);
  context.checkpoint = structuredClone(context.row);
}

async function main(argv = process.argv, browserType = chromium) {
  const args = parseArgs(argv);
  const reportPath = path.resolve(windowsPath(args.report));
  const matrixRoot = path.dirname(reportPath);
  const helperHash = sha256File(__filename);
  const validationLock = acquireValidationLock(
    matrixRoot,
    reportPath,
    helperHash,
  );
  try {
    const report = JSON.parse(fs.readFileSync(reportPath, "utf8"));
    const manifest = assertManifestBinding(reportPath, report);
    const expectedRuns = expectedRunSpecs(manifest);
    const expectedIds = expectedRuns.map((row) => row.run_id);
    const actualIds = (report.records || []).map((row) => String(row.run_id));
    const expectedSet = new Set(expectedIds);
    const actualSet = new Set(actualIds);
    if (
      expectedSet.size !== expectedIds.length ||
      actualSet.size !== actualIds.length ||
      expectedIds.length !== actualIds.length ||
      expectedIds.some((runId) => !actualSet.has(runId)) ||
      actualIds.some((runId) => !expectedSet.has(runId))
    ) {
      throw new Error("The benchmark report is partial or has duplicate run records");
    }
    const expectedById = new Map(expectedRuns.map((row) => [row.run_id, row]));
    for (const row of report.records || []) {
      const expected = expectedById.get(String(row.run_id));
      if (!expected) throw new Error(`Unexpected run identity: ${row.run_id}`);
      for (const field of RUN_IDENTITY_FIELDS) {
        if (row[field] !== expected[field]) {
          throw new Error(`Run identity mismatch (${field}): ${row.run_id}`);
        }
      }
      if (row.input_sha256 !== manifest.inputs?.[row.case]) {
        throw new Error(`Run input hash mismatch: ${row.run_id}`);
      }
    }
    const selected = selectRecords(report.records || [], args.scope);
    if (!selected.length) throw new Error("No valid output records to validate");
    const expectedSelections = assertCompleteSelection(
      selected,
      manifest,
      args.scope,
    );

    const contexts = selected.map((row) => validationContext(matrixRoot, row));
    const resolved = contexts.map((context) => ({
      context,
      state: resolvePersistedOfficialValidation(
        context.row,
        context.checkpoint,
        helperHash,
      ),
    }));
    for (const item of resolved) {
      if (item.state.state === "complete" && !item.state.agreement) {
        throw new Error(
          `Persisted official validator disagreement for ${item.context.row.run_id}`,
        );
      }
    }

    for (const item of resolved) {
      if (item.state.state !== "response_captured") continue;
      const evidence = createOfficialValidationEvidence({
        record: item.context.row,
        responseCapture: item.state.responseCapture,
      });
      const agreement = setCompleteOfficialState(item.context.row, evidence);
      assertEvidenceIntegrity(item.context.row, helperHash);
      assertNoReusedOfficialEvidence(report.records || []);
      publishOfficialState({
        context: item.context,
        reportPath,
        report,
        selected,
        scope: args.scope,
        expectedSelections,
        manifest,
        helperHash,
      });
      if (!agreement) {
        throw new Error(
          `Official validator disagreement for ${item.context.row.run_id}`,
        );
      }
    }

    const pending = resolved.filter((item) => item.state.state === "absent");
    if (pending.length === 0) {
      updateOfficialValidationMetadata({
        report,
        selected,
        scope: args.scope,
        expectedSelections,
        manifest,
        helperHash,
      });
      writeReport(reportPath, report);
      return report.official_validation;
    }
    if (sha256File(__filename) !== helperHash) {
      throw new Error("Official validator helper changed after lock acquisition");
    }

    const browser = await browserType.connectOverCDP(args.cdp);
    try {
      const context = browser.contexts()[0];
      if (!context) throw new Error("No authenticated browser context is available");
      let page = context.pages().find((item) => item.url().includes("itc2019.org"));
      if (!page) page = await context.newPage();
      if (!page.url().startsWith("https://www.itc2019.org/validator")) {
        await page.goto("https://www.itc2019.org/validator", {
          waitUntil: "domcontentloaded",
        });
      }
      try {
        await page.locator("input[type=file]").waitFor({
          state: "attached",
          timeout: 15000,
        });
      } catch {
        throw new Error("The ITC-2019 browser session is not logged in");
      }

      for (const item of pending) {
        const current = item.context;
        if (
          sha256File(__filename) !== helperHash ||
          sha256File(current.outputPath) !== current.currentOutputSha256
        ) {
          throw new Error(`Locked input drift before submission: ${current.row.run_id}`);
        }
        const submissionIntent = createSubmissionIntent({
          record: current.row,
          helperSha256: helperHash,
          createdAt: new Date().toISOString(),
        });
        const official = await captureOfficialValidationFromPage({
          page,
          outputPath: current.outputPath,
          record: current.row,
          submittedOutputSha256: current.currentOutputSha256,
          helperSha256: helperHash,
          submissionIntent,
          beforeSubmit: async () => {
            setSubmissionIntentState(current.row, submissionIntent);
            publishOfficialState({
              context: current,
              reportPath,
              report,
              selected,
              scope: args.scope,
              expectedSelections,
              manifest,
              helperHash,
            });
          },
          onResponseCaptured: async (responseCapture) => {
            setResponseCapturedState(
              current.row,
              submissionIntent,
              responseCapture,
            );
            publishOfficialState({
              context: current,
              reportPath,
              report,
              selected,
              scope: args.scope,
              expectedSelections,
              manifest,
              helperHash,
            });
          },
          capturedAt: () => new Date().toISOString(),
        });
        const agreement = setCompleteOfficialState(current.row, official);
        assertEvidenceIntegrity(current.row, helperHash);
        assertNoReusedOfficialEvidence(report.records || []);
        publishOfficialState({
          context: current,
          reportPath,
          report,
          selected,
          scope: args.scope,
          expectedSelections,
          manifest,
          helperHash,
        });
        console.log(
          JSON.stringify({
            run: current.row.run_id,
            agreement,
            official_total: official.total,
            log_id: official.log_id,
          }),
        );
        if (!agreement) {
          throw new Error(`Official validator disagreement for ${current.row.run_id}`);
        }
      }
    } finally {
      await browser.close();
    }

    updateOfficialValidationMetadata({
      report,
      selected,
      scope: args.scope,
      expectedSelections,
      manifest,
      helperHash,
    });
    if (!report.official_validation.all_agree) {
      throw new Error("Official validation did not complete with unanimous agreement");
    }
    writeReport(reportPath, report);
    return report.official_validation;
  } finally {
    validationLock.release();
  }
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error.message || error);
    process.exitCode = 1;
  });
}

module.exports = {
  agrees,
  acquireValidationLock,
  assertCompleteSelection,
  assertManifestBinding,
  assertNoReusedOfficialEvidence,
  assertPersistedOfficialValidation,
  assertThirtyOfThirtyOfficialSuccess,
  captureOfficialValidationFromPage,
  createOfficialResponseCapture,
  createSubmissionIntent,
  createOfficialValidationEvidence,
  expectedRunIds,
  expectedRunSpecs,
  main,
  officialResult,
  resolvePersistedOfficialValidation,
  selectRecords,
  windowsPath,
};
