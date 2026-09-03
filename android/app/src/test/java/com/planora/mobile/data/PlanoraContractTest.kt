package com.planora.mobile.data

import com.google.gson.Gson
import com.planora.mobile.domain.Principal
import com.planora.mobile.domain.ProjectSummary
import com.planora.mobile.domain.ValidationState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class PlanoraContractTest {
  @Test
  fun acceptsTheCurrentlyHostedLegacyCapabilitiesShape() {
    val payload = """
      {
        "actions": ["load_preset", "solve", "improve"],
        "shared_backend": "python-services"
      }
    """.trimIndent()

    val parsed = Gson().fromJson(payload, CapabilitiesDto::class.java)

    assertEquals("python-services", parsed.resolvedBackendId())
    assertEquals(
      listOf("small_demo", "ss23_uni_like", "import"),
      parsed.compatibleUiContract()?.scenarios?.map { it.id },
    )
  }

  @Test
  fun keepsScheduleAndProjectWritePermissionsIndependent() {
    val scheduleEditor = Principal("scheduler", "Scheduler", "staff", "eastbridge", setOf("schedule:write", "solver:run"))
    val projectEditor = Principal("librarian", "Librarian", "staff", "eastbridge", setOf("projects:write"))

    assertTrue(scheduleEditor.canWriteSchedule)
    assertFalse(scheduleEditor.canWriteProjects)
    assertFalse(projectEditor.canWriteSchedule)
    assertTrue(projectEditor.canWriteProjects)
  }

  @Test
  fun rejectsInsecureRemoteHttpButAllowsEmulatorHost() {
    assertEquals("https://example.edu/planora", BaseUrlNormalizer.normalize("example.edu/planora", ""))
    assertEquals("http://10.0.2.2:8787", BaseUrlNormalizer.normalize("http://10.0.2.2:8787", ""))
    assertEquals("https://fallback.edu", BaseUrlNormalizer.normalize("http://example.edu", "https://fallback.edu"))
  }

  @Test
  fun parsesTheStableUiCatalogWithoutEngineControls() {
    val payload = """
      {
        "actions": ["solve", "improve"],
        "shared_backend": {"backend_id": "planora-solver-service-v1"},
        "ui_contract": {
          "contract_version": "planora.ui.v1",
          "scenarios": [
            {"id": "demo", "label": "Demo", "description": "Small example", "source": "generated"},
            {"id": "spring_2023", "label": "Spring 2023", "description": "University profile", "source": "generated"},
            {"id": "import", "label": "Import", "description": "Your CSV", "source": "import"}
          ],
          "run_modes": [
            {"id": "fast", "label": "Fast", "recommended": false},
            {"id": "balanced", "label": "Balanced", "recommended": true},
            {"id": "quality", "label": "Maximum quality", "recommended": false}
          ],
          "tutorial": [
            {"id": "bring-in", "title": "Bring in your timetable", "body": "Open an example or import your data."}
          ]
        }
      }
    """.trimIndent()

    val parsed = Gson().fromJson(payload, CapabilitiesDto::class.java)

    assertEquals("planora-solver-service-v1", parsed.resolvedBackendId())
    assertEquals("planora.ui.v1", parsed.uiContract?.version)
    assertEquals(listOf("demo", "spring_2023", "import"), parsed.uiContract?.scenarios?.map { it.id })
    assertEquals(listOf("fast", "balanced", "quality"), parsed.uiContract?.modes?.map { it.id })
    assertEquals("balanced", parsed.uiContract?.modes?.single { it.recommended }?.id)
    assertEquals("Bring in your timetable", parsed.uiContract?.tutorial?.single()?.title)
    assertTrue(parsed.uiContract?.modes.orEmpty().none { it.id.contains("worker") || it.id.contains("room") })
  }

  @Test
  fun mapsApiWorkspaceIntoReadableScheduleEvents() {
    val instance = InstanceDto(
      days = listOf("MON", "TUE"),
      weeks = listOf(1),
      slotsPerDay = 6,
      courses = mapOf("7" to NamedDto(7, "Algorithms", "CS201")),
      staff = mapOf("3" to NamedDto(3, "Dr. Smith")),
      rooms = mapOf("2" to NamedDto(2, "R1.201", capacity = 80, roomType = "LECTURE")),
      groups = mapOf("5" to NamedDto(5, "Engineering Year 2")),
      activities = mapOf("11" to ActivityDto(11, 7, 1, "LEC", 1, listOf(5), professorId = 3)),
    )
    val schedule = mapOf(
      "11" to ScheduleRowDto(
        roomId = 2,
        staffId = 3,
        week = 1,
        day = "MON",
        slot = 1,
        groupIds = listOf(5),
        courseId = 7,
        kind = "LEC",
      ),
    )

    val workspace = WorkspaceMapper.map("Faculty review", "session-1", instance, schedule)

    assertEquals("Algorithms", workspace.events.single().title)
    assertEquals("CS201", workspace.events.single().code)
    assertEquals("R1.201", workspace.events.single().room)
    assertEquals("Dr. Smith", workspace.events.single().staff)
    assertEquals(listOf("Engineering Year 2"), workspace.events.single().groups)
  }

  @Test
  fun preservesTheCompleteEngineInstanceAcrossTheAndroidSessionBoundary() {
    val payload = """
      {
        "session_id": "session-1",
        "instance": {
          "days": ["MON"],
          "weeks": [1],
          "slots_per_day": 5,
          "programs": {"1": {"id": 1, "name": "Engineering"}},
          "groups": {"2": {"id": 2, "name": "Year 1", "program_id": 1}},
          "courses": {"3": {"id": 3, "name": "Algorithms", "program_id": 1}},
          "staff": {},
          "rooms": {},
          "activities": {"4": {"id": 4, "course_id": 3, "week": 1, "kind": "LEC", "duration": 1}},
          "hard_constraints": {"max_consecutive_slots": 3},
          "distribution_constraints": [{"type": "SameTime", "activity_ids": [4]}]
        },
        "schedule": {}
      }
    """.trimIndent()

    val parsed = Gson().fromJson(payload, WorkspaceDto::class.java)
    val encoded = Gson().toJson(SessionCreateRequest(parsed.instance, parsed.schedule))

    assertTrue(encoded.contains("\"program_id\":1"))
    assertTrue(encoded.contains("\"hard_constraints\""))
    assertTrue(encoded.contains("\"distribution_constraints\""))
  }

  @Test
  fun canonicalizesApiOriginsIndependentlyFromApiPaths() {
    assertEquals("https://example.edu", ApiOrigin.fromBaseUrl("https://EXAMPLE.edu:443/api"))
    assertEquals("http://localhost", ApiOrigin.fromBaseUrl("http://localhost:80/v1"))
    assertEquals("https://example.edu:8443", ApiOrigin.fromBaseUrl("https://example.edu:8443/api"))
    assertFalse(ApiOrigin.fromBaseUrl("https://one.example/api") == ApiOrigin.fromBaseUrl("https://two.example/api"))
  }

  @Test
  fun releaseApiPolicyIgnoresAStoredDebugEndpoint() {
    assertEquals(
      "https://planora.elfeel.me/api",
      effectiveApiBaseUrl(
        canEdit = false,
        stored = "http://10.0.2.2:8787",
        fallback = "https://planora.elfeel.me/api",
      ),
    )
    assertEquals(
      "http://10.0.2.2:8787",
      effectiveApiBaseUrl(
        canEdit = true,
        stored = "http://10.0.2.2:8787",
        fallback = "https://planora.elfeel.me/api",
      ),
    )
  }

  @Test
  fun encryptedTokenEnvelopeCanOnlyBeReadForItsBoundOrigin() {
    val encoded = OriginBoundTokenCodec.encode("https://planora.example", "bearer-value")

    assertEquals("bearer-value", OriginBoundTokenCodec.tokenFor(encoded, "https://planora.example"))
    assertEquals("", OriginBoundTokenCodec.tokenFor(encoded, "https://other.example"))
    assertNull(OriginBoundTokenCodec.decode("legacy-unbound-token".toByteArray()))
  }

  @Test
  fun classifiesJwtExpiryAndRefreshWindowWithoutUsingWallClockTime() {
    assertEquals(JwtLifetime.EXPIRED, JwtSessionPolicy.classify(jwt(exp = 1_000), 1_000))
    assertEquals(JwtLifetime.REFRESH, JwtSessionPolicy.classify(jwt(exp = 1_600), 1_000))
    assertEquals(JwtLifetime.VALID, JwtSessionPolicy.classify(jwt(exp = 3_000), 1_000))
    assertEquals(JwtLifetime.UNKNOWN, JwtSessionPolicy.classify("opaque-session", 1_000))
  }

  @Test
  fun parsesImportScoreAndValidationErrorsAsInvalidWorkspaceEvidence() {
    val payload = """
      {
        "instance": {"days":["MON"],"weeks":[1],"slots_per_day":4},
        "schedule": {},
        "meta": {"validation_errors":["Activity 4 has no room"]},
        "score": {"soft_penalty":17,"hard_conflicts":["Group overlap"]}
      }
    """.trimIndent()
    val imported = Gson().fromJson(payload, WorkspaceDto::class.java)

    val workspace = WorkspaceMapper.map(
      "Import",
      "session-1",
      imported.instance,
      imported.schedule,
      imported.score,
      imported.meta.validationErrorsOrNull(),
    )

    assertEquals(listOf("Group overlap", "Activity 4 has no room"), workspace.hardConflicts)
    assertEquals(17, workspace.softPenalty)
    assertEquals(ValidationState.INVALID, workspace.validationState)
  }

  @Test
  fun parsesTypedImproveScoreAndDoesNotClearKnownConflictsWhenScoreIsMissing() {
    val instance = InstanceDto(days = listOf("MON"), weeks = listOf(1), slotsPerDay = 4)
    val base = WorkspaceMapper.map(
      "Review",
      "session-1",
      instance,
      emptyMap(),
      ScoreResultDto(softPenalty = 20, hardConflicts = listOf("Existing conflict")),
    )
    val row = ScheduleRowDto(week = 1, day = "MON", slot = 1)
    val withoutScore = SolverResultDto(schedule = mapOf("1" to row))

    val preserved = WorkspaceMapper.withImproveResult(base, withoutScore)

    assertEquals(listOf("Existing conflict"), preserved.hardConflicts)
    assertEquals(20, preserved.softPenalty)
    assertEquals(ValidationState.INVALID, preserved.validationState)

    val parsed = Gson().fromJson(
      """{"schedule":{"1":{"week":1,"day":"MON","slot":1}},"global_after":{"soft_penalty":5,"hard_conflicts":[]}}""",
      SolverResultDto::class.java,
    )
    val improved = WorkspaceMapper.withImproveResult(base, parsed)

    assertEquals(5, improved.softPenalty)
    assertTrue(improved.hardConflicts.isEmpty())
    assertEquals(ValidationState.VALID, improved.validationState)
  }

  @Test
  fun acceptsOnlyFeasibleNonemptySolveResults() {
    val row = ScheduleRowDto(week = 1, day = "MON", slot = 1)

    assertFalse(SolverResultDto(rawStatus = 1, schedule = mapOf("1" to row)).hasFeasibleSchedule())
    assertFalse(SolverResultDto(rawStatus = 2, schedule = emptyMap()).hasFeasibleSchedule())
    assertTrue(SolverResultDto(rawStatus = 2, schedule = mapOf("1" to row)).hasFeasibleSchedule())
    assertTrue(SolverResultDto(rawStatus = 4, schedule = mapOf("1" to row)).hasFeasibleSchedule())
  }

  @Test
  fun usesCanonicalSavedProjectNameAndSessionOnlySavePayload() {
    val response = Gson().fromJson(
      """{"saved":{"name":"Faculty_Review","storage":"sqlite"}}""",
      ProjectSaveResponseDto::class.java,
    )
    val request = Gson().toJson(ProjectSaveRequest("Faculty Review", "session-7"))

    assertEquals("Faculty_Review", response.saved.name)
    assertTrue(request.contains("\"session_id\":\"session-7\""))
    assertFalse(request.contains("instance"))
    assertFalse(request.contains("schedule"))
  }

  @Test
  fun globalAdminProjectRowsStayInsideTheActiveUniversityOnAndroid() {
    val projects = listOf(
      ProjectSummary("Engineering", "eastbridge", null),
      ProjectSummary("Medicine", "north-campus", null),
    )

    assertEquals(
      listOf("Engineering"),
      ProjectTenantPolicy.visibleToActiveTenant("eastbridge", projects).map { it.name },
    )
    assertTrue(
      runCatching {
        ProjectTenantPolicy.requireOpenAllowed("eastbridge", "north-campus")
      }.isFailure,
    )
    ProjectTenantPolicy.requireOpenAllowed("eastbridge", "eastbridge")
  }

  private fun jwt(exp: Long): String {
    val payload = Base64.getUrlEncoder().withoutPadding()
      .encodeToString("{\"exp\":$exp}".toByteArray())
    return "header.$payload.signature"
  }
}
