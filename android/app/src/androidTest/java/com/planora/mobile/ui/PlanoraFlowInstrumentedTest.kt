package com.planora.mobile.ui

import android.content.Context
import android.content.pm.ActivityInfo
import android.content.res.Configuration
import android.graphics.Bitmap
import android.os.ParcelFileDescriptor
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isRoot
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.unit.dp
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.planora.mobile.domain.AcademicResource
import com.planora.mobile.domain.AccessSnapshot
import com.planora.mobile.domain.AccountSnapshot
import com.planora.mobile.domain.AdminSnapshot
import com.planora.mobile.domain.AuthConfig
import com.planora.mobile.domain.AuthSession
import com.planora.mobile.domain.CatalogItem
import com.planora.mobile.domain.DataRow
import com.planora.mobile.domain.ExportedSchedule
import com.planora.mobile.domain.GatewayResult
import com.planora.mobile.domain.JobStatus
import com.planora.mobile.domain.MoveTarget
import com.planora.mobile.domain.PlanoraGateway
import com.planora.mobile.domain.Principal
import com.planora.mobile.domain.ProjectSummary
import com.planora.mobile.domain.RegistrationResult
import com.planora.mobile.domain.ScheduleEvent
import com.planora.mobile.domain.ScheduleWorkspace
import com.planora.mobile.domain.SolverSettings
import com.planora.mobile.domain.TutorialStep
import com.planora.mobile.domain.UiCatalog
import com.planora.mobile.TestActivity
import com.planora.mobile.ui.theme.PlanoraTheme
import com.planora.mobile.ui.theme.ThemeMode
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.delay
import java.io.File
import kotlin.concurrent.thread
import kotlin.coroutines.resume
import kotlin.coroutines.suspendCoroutine
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

class PlanoraFlowInstrumentedTest {
  @get:Rule
  val composeRule = createAndroidComposeRule<TestActivity>()

  private val context: Context = ApplicationProvider.getApplicationContext()

  @Before
  fun resetTutorial() {
    composeRule.activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
    composeRule.waitUntil(5_000) {
      composeRule.activity.resources.configuration.orientation == Configuration.ORIENTATION_PORTRAIT
    }
    context.getSharedPreferences("planora_onboarding", Context.MODE_PRIVATE).edit().clear().commit()
    context.getSharedPreferences("planora_appearance", Context.MODE_PRIVATE).edit().clear().commit()
  }

  @After
  fun restoreDisplaySize() {
    composeRule.activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
  }

  @Test
  fun firstRunGuideIsReplayableAndUsesPlainLanguage() {
    val viewModel = PlanoraViewModel(FakeGateway(), context)
    composeRule.setContent { PlanoraTheme { PlanoraRoot(viewModel) } }

    composeRule.waitUntil(5_000) { composeRule.onAllNodes(hasText("Bring in your timetable")).fetchSemanticsNodes().isNotEmpty() }
    composeRule.onNodeWithText("Bring in your timetable").assertIsDisplayed()
    capture("planora-guide.png")
    repeat(4) { composeRule.onNodeWithText("Next").performClick() }
    composeRule.onNodeWithText("Validate and publish").assertIsDisplayed()
    composeRule.onNodeWithText("Open Planora").performClick()
    composeRule.onNodeWithText("Build a schedule people can understand.").assertIsDisplayed()
  }

  @Test
  fun demoMovesFromHomeToReadableSchedule() {
    context.getSharedPreferences("planora_onboarding", Context.MODE_PRIVATE).edit().putBoolean("seen", true).commit()
    val viewModel = PlanoraViewModel(FakeGateway(), context)
    viewModel.chooseTheme(ThemeMode.LIGHT)
    composeRule.setContent { PlanoraTheme { PlanoraRoot(viewModel) } }

    composeRule.waitUntil(5_000) { composeRule.onAllNodes(hasText("Small demo")).fetchSemanticsNodes().isNotEmpty() }
    capture("planora-home.png")
    composeRule.onNodeWithText("Small demo").performClick()
    composeRule.waitUntil(5_000) { composeRule.onAllNodes(hasText("Algorithms")).fetchSemanticsNodes().isNotEmpty() }
    composeRule.onNodeWithText("Algorithms").assertIsDisplayed().performClick()
    composeRule.waitUntil(5_000) { composeRule.onAllNodes(hasText("R1.201")).fetchSemanticsNodes().isNotEmpty() }
    composeRule.onNodeWithText("Suggested next steps").performScrollTo().assertIsDisplayed()
    val repairAction = composeRule
      .onNode(
        hasClickAction() and
          (hasText("Run quality pass") or hasText("Repair timetable")),
      )
      .performScrollTo()
    capture("planora-schedule-portrait.png")
    repairAction.assertIsDisplayed()
  }

  @Test
  fun productionLoginExplainsSecureHostedAccess() {
    composeRule.setContent {
      PlanoraTheme(themeMode = ThemeMode.LIGHT) {
        LoginScreen(
          baseUrl = "https://planora.elfeel.me/api",
          canEditBaseUrl = false,
          busy = false,
          message = null,
          onLogin = { _, _ -> },
          onBaseUrlSave = {},
          onOpenTutorial = {},
        )
      }
    }

    composeRule.onNodeWithText("Sign in").assertIsDisplayed()
    composeRule.onNodeWithText("Open workspace").assertIsDisplayed()
    capture("planora-login.png")
  }

  @Test
  fun registrationIsVisibleAndOpensTheNativeAccountFlow() {
    composeRule.setContent {
      var stage by remember { mutableStateOf(AuthStage.LOGIN) }
      PlanoraTheme(themeMode = ThemeMode.LIGHT) {
        LoginScreen(
          baseUrl = "https://planora.elfeel.me/api",
          authConfig = AuthConfig(registrationEnabled = true),
          authStage = stage,
          canEditBaseUrl = false,
          busy = false,
          message = null,
          onLogin = { _, _ -> },
          onAuthStage = { stage = it },
          onBaseUrlSave = {},
          onOpenTutorial = {},
        )
      }
    }

    composeRule.onNodeWithText("Register").performScrollTo().assertIsDisplayed().performClick()
    composeRule.onAllNodes(hasText("Create account"))[0].assertIsDisplayed()
    composeRule.onNodeWithText("Display name").assertIsDisplayed()
    capture("planora-register.png")
  }

  @Test
  fun toolsExposeTheWebWorkspaceFeatures() {
    context.getSharedPreferences("planora_onboarding", Context.MODE_PRIVATE).edit()
      .putBoolean("seen", true).commit()
    val viewModel = PlanoraViewModel(FakeGateway(), context)
    composeRule.setContent { PlanoraTheme(themeMode = ThemeMode.LIGHT) { PlanoraRoot(viewModel) } }

    composeRule.waitUntil(5_000) { composeRule.onAllNodes(hasText("Small demo")).fetchSemanticsNodes().isNotEmpty() }
    composeRule.onNodeWithTag("nav-tools").performClick()
    composeRule.onNodeWithText("Data and scenarios").assertIsDisplayed()
    composeRule.onNodeWithText("Advanced solver").assertIsDisplayed()
    composeRule.onNodeWithText("Fairness and utilization").assertIsDisplayed()
    composeRule.onNodeWithText("Account and organizations").assertIsDisplayed()
    composeRule.onNodeWithText("Platform parity").assertIsDisplayed()
    capture("planora-tools.png")
    composeRule.onNodeWithText("Data and scenarios").performClick()
    composeRule.onNodeWithText("CSV column mapping").performScrollTo().assertIsDisplayed()
    capture("planora-data.png")
  }

  @Test
  fun aClassCanBeMovedThroughServerApprovedTargets() {
    context.getSharedPreferences("planora_onboarding", Context.MODE_PRIVATE).edit()
      .putBoolean("seen", true).commit()
    val viewModel = PlanoraViewModel(FakeGateway(), context)
    composeRule.setContent { PlanoraTheme(themeMode = ThemeMode.LIGHT) { PlanoraRoot(viewModel) } }

    composeRule.waitUntil(5_000) { composeRule.onAllNodes(hasText("Small demo")).fetchSemanticsNodes().isNotEmpty() }
    composeRule.onNodeWithText("Small demo").performClick()
    composeRule.waitUntil(5_000) { composeRule.onAllNodes(hasText("Algorithms")).fetchSemanticsNodes().isNotEmpty() }
    composeRule.onNodeWithText("Algorithms").performClick()
    composeRule.onNodeWithText("Find safe moves").performScrollTo().performClick()
    composeRule.waitUntil(5_000) { composeRule.onAllNodes(hasText("Move Algorithms")).fetchSemanticsNodes().isNotEmpty() }
    composeRule.onNodeWithText("Move", useUnmergedTree = true).performClick()
    composeRule.waitUntil(5_000) { viewModel.uiState.value.selectedEvent?.day == "TUE" }
    assertTrue(viewModel.uiState.value.selectedEvent?.slot == 3)
  }

  @Test
  fun coreDestinationsStayReadable() {
    context.getSharedPreferences("planora_onboarding", Context.MODE_PRIVATE).edit()
      .putBoolean("seen", true).commit()
    val viewModel = PlanoraViewModel(FakeGateway(), context)
    viewModel.chooseTheme(ThemeMode.LIGHT)
    composeRule.setContent { PlanoraTheme { PlanoraRoot(viewModel) } }

    composeRule.waitUntil(5_000) {
      composeRule.onAllNodes(hasText("Small demo")).fetchSemanticsNodes().isNotEmpty()
    }
    composeRule.onNodeWithText("Small demo").performClick()
    composeRule.waitUntil(5_000) {
      composeRule.onAllNodes(hasText("Algorithms")).fetchSemanticsNodes().isNotEmpty()
    }

    composeRule.onNodeWithTag("nav-review").performClick()
    composeRule.onNodeWithText("Review the draft").assertIsDisplayed()
    capture("planora-review.png")

    composeRule.onNodeWithTag("nav-projects").performClick()
    composeRule.waitUntil(5_000) {
      composeRule.onAllNodes(hasText("Faculty review")).fetchSemanticsNodes().isNotEmpty()
    }
    capture("planora-projects.png")

    composeRule.onNodeWithContentDescription("Settings").performClick()
    composeRule.onNodeWithText("Account").assertIsDisplayed()
    capture("planora-settings.png")
  }

  @Test
  fun expandedWorkspaceShowsDataTimetableAndInspector() {
    composeRule.activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
    composeRule.waitUntil(15_000) {
      composeRule.activity.resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE
    }
    var reviewOpened = false
    val state = PlanoraUiState(
      initializing = false,
      authenticated = true,
      principal = FakeGateway.principal,
      catalog = FakeGateway.catalog,
      workspace = FakeGateway.workspace,
      destination = Destination.SCHEDULE,
      selectedWeek = 1,
      selectedDay = "MON",
      selectedEvent = FakeGateway.workspace.events.first(),
    )
    composeRule.setContent {
      PlanoraTheme(themeMode = ThemeMode.LIGHT) {
        ScheduleScreen(
          state = state,
          expanded = true,
          onWeek = {},
          onDay = {},
          onEvent = {},
          onMode = {},
          onSolve = {},
          onValidate = {},
          onImprove = {},
          onCancelImprove = {},
          onOpenReview = { reviewOpened = true },
          onSave = {},
          onExport = {},
        )
      }
    }

    composeRule.onNodeWithText("Academic data").assertIsDisplayed()
    composeRule.waitUntil(5_000) { composeRule.onAllNodes(hasText("Algorithms"), useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty() }
    capture("planora-schedule-expanded.png")
    composeRule.onNodeWithText("Validation").performScrollTo().assertIsDisplayed()
    composeRule.onNodeWithText("Suggested next steps").performScrollTo().assertIsDisplayed()
    composeRule.onNodeWithText("Engineering review").assertIsDisplayed()
    composeRule.onNodeWithText("Open full review").performScrollTo().performClick()
    assertTrue(reviewOpened)
  }

  @Test
  fun loginRemainsScrollableInPhoneLandscapeWithConnectionDetailsOpen() {
    composeRule.activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
    composeRule.waitUntil(15_000) {
      composeRule.activity.resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE
    }
    composeRule.setContent {
      PlanoraTheme {
        LoginScreen(
          baseUrl = "http://10.0.2.2:8787",
          busy = false,
          message = null,
          onLogin = { _, _ -> },
          onBaseUrlSave = {},
          onOpenTutorial = {},
        )
      }
    }

    composeRule.onNodeWithText("Connection").performScrollTo().performClick()
    composeRule.onNodeWithText("Save server address").performScrollTo().assertIsDisplayed()
    composeRule.onNodeWithText(
      "Your password is sent only to your Planora server and is never stored on this device.",
    ).performScrollTo().assertIsDisplayed()
  }

  @Test
  fun darkScheduleUsesThePlanoraPalette() {
    context.getSharedPreferences("planora_onboarding", Context.MODE_PRIVATE).edit()
      .putBoolean("seen", true).commit()
    val viewModel = PlanoraViewModel(FakeGateway(), context)
    viewModel.chooseTheme(ThemeMode.DARK)
    composeRule.setContent { PlanoraRoot(viewModel) }

    composeRule.waitUntil(5_000) {
      composeRule.onAllNodes(hasText("Small demo")).fetchSemanticsNodes().isNotEmpty()
    }
    composeRule.onNodeWithText("Small demo").performClick()
    composeRule.waitUntil(5_000) {
      composeRule.onAllNodes(hasText("Algorithms")).fetchSemanticsNodes().isNotEmpty()
    }
    capture("planora-schedule-dark.png")
  }

  @Test
  fun compactLandscapeKeepsTheAgendaVisible() {
    composeRule.activity.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
    composeRule.waitUntil(15_000) {
      composeRule.activity.resources.configuration.orientation == Configuration.ORIENTATION_LANDSCAPE
    }
    val state = PlanoraUiState(
      initializing = false,
      authenticated = true,
      principal = FakeGateway.principal,
      catalog = FakeGateway.catalog,
      workspace = FakeGateway.workspace,
      destination = Destination.SCHEDULE,
      selectedWeek = 1,
      selectedDay = "MON",
    )
    composeRule.setContent {
      PlanoraTheme(themeMode = ThemeMode.LIGHT) {
        Box(Modifier.fillMaxWidth().height(400.dp)) {
          ScheduleScreen(
            state = state,
            expanded = false,
            onWeek = {},
            onDay = {},
            onEvent = {},
            onMode = {},
            onSolve = {},
            onValidate = {},
            onImprove = {},
            onCancelImprove = {},
            onOpenReview = {},
            onSave = {},
            onExport = {},
          )
        }
      }
    }

    composeRule.onNodeWithText("Week").assertIsDisplayed()
    composeRule.onNodeWithText("Day").assertIsDisplayed()
    composeRule.onNodeWithText("Algorithms").assertIsDisplayed()
    composeRule.onNodeWithContentDescription("More schedule actions").assertIsDisplayed()
    capture("planora-schedule-landscape.png")
    composeRule.onNodeWithContentDescription("More schedule actions").performClick()
    composeRule.onNodeWithText("Save project").assertIsDisplayed()
    composeRule.onNodeWithText("Export CSV").assertIsDisplayed()
    composeRule.onNodeWithText("Rebuild schedule").assertIsDisplayed()
  }

  @Test
  fun readOnlyRoleSeesImportAsUnavailable() {
    context.getSharedPreferences("planora_onboarding", Context.MODE_PRIVATE).edit()
      .putBoolean("seen", true).commit()
    val viewModel = PlanoraViewModel(ReadOnlyGateway(), context)
    composeRule.setContent { PlanoraTheme { PlanoraRoot(viewModel) } }

    composeRule.waitUntil(5_000) {
      composeRule.onAllNodes(hasText("Import CSV")).fetchSemanticsNodes().isNotEmpty()
    }
    composeRule.onNodeWithTag("scenario-import").assertIsDisplayed().assertIsNotEnabled()
    composeRule.onNodeWithText("Requires schedule editing permission.").assertIsDisplayed()
  }

  @Test
  fun staleAccountWorkCannotAffectTheNextLogin() {
    context.getSharedPreferences("planora_onboarding", Context.MODE_PRIVATE).edit()
      .putBoolean("seen", true).commit()
    val gateway = CrossAccountGateway()
    val viewModel = PlanoraViewModel(gateway, context)
    composeRule.setContent { PlanoraTheme { PlanoraRoot(viewModel) } }

    composeRule.waitUntil(5_000) { viewModel.uiState.value.authenticated }
    val stalePickerGeneration = requireNotNull(viewModel.captureAuthenticatedGeneration())
    viewModel.createScenario(FakeGateway.catalog.scenarios.first())
    composeRule.waitUntil(5_000) { gateway.scenarioStarted.get() == 1 }

    viewModel.logout()
    composeRule.waitUntil(5_000) { !viewModel.uiState.value.authenticated }
    viewModel.login("user-b@eastbridge.edu", "test-password")
    composeRule.waitUntil(5_000) { gateway.loginStarted.get() == 1 }
    composeRule.waitUntil(5_000) { gateway.scenarioFinished.get() == 1 }

    assertTrue(viewModel.uiState.value.busy)
    composeRule.waitUntil(5_000) {
      viewModel.uiState.value.principal?.userId == "user-b@eastbridge.edu" &&
        !viewModel.uiState.value.busy
    }
    viewModel.importCsv("user-a.csv", "activity_id,title\n1,Private\n", stalePickerGeneration)
    composeRule.waitForIdle()

    assertTrue(viewModel.uiState.value.workspace == null)
    assertTrue(gateway.importCalls.get() == 0)
  }

  @Test
  fun transientRestoreFailureKeepsTheSavedSessionRetryable() {
    val gateway = FlakyRestoreGateway()
    val viewModel = PlanoraViewModel(gateway, context)
    composeRule.setContent { PlanoraRoot(viewModel) }

    composeRule.waitUntil(5_000) { viewModel.uiState.value.canRetrySession }
    assertTrue(!viewModel.uiState.value.authenticated)
    assertTrue(gateway.logoutCalls.get() == 0)
    composeRule.onNodeWithText("Retry saved session").performScrollTo().performClick()
    composeRule.waitUntil(5_000) { viewModel.uiState.value.authenticated }
    assertTrue(gateway.logoutCalls.get() == 0)
  }

  @Test
  fun rapidImproveRequestsStartOnlyOneServerJob() {
    context.getSharedPreferences("planora_onboarding", Context.MODE_PRIVATE).edit()
      .putBoolean("seen", true).commit()
    val gateway = DelayedImproveGateway()
    val viewModel = PlanoraViewModel(gateway, context)
    composeRule.setContent { PlanoraRoot(viewModel) }

    composeRule.waitUntil(5_000) { viewModel.uiState.value.authenticated }
    viewModel.createScenario(FakeGateway.catalog.scenarios.first())
    composeRule.waitUntil(5_000) { viewModel.uiState.value.workspace != null }
    viewModel.improve()
    viewModel.improve()
    composeRule.waitUntil(5_000) { !viewModel.uiState.value.busy }

    assertTrue(gateway.improveCalls.get() == 1)
  }

  private fun capture(name: String) {
    val output = File(context.getExternalFilesDir(null), "visual/$name")
    output.parentFile?.mkdirs()
    output.outputStream().use { stream ->
      composeRule.onAllNodes(isRoot())[0].captureToImage().asAndroidBitmap()
        .compress(Bitmap.CompressFormat.PNG, 100, stream)
    }
    shell("cp ${output.absolutePath} /sdcard/Download/$name")
  }

  private fun shell(command: String) {
    ParcelFileDescriptor.AutoCloseInputStream(
      InstrumentationRegistry.getInstrumentation().uiAutomation.executeShellCommand(command),
    ).use { it.readBytes() }
  }
}

private open class FakeGateway : PlanoraGateway {
  override suspend fun hasSession() = true
  override suspend fun loadAuthConfig() = GatewayResult.Success(AuthConfig())
  override suspend fun login(email: String, password: String): GatewayResult<Principal> =
    GatewayResult.Success(principal)
  override suspend fun register(email: String, password: String, displayName: String) =
    GatewayResult.Success(RegistrationResult(developmentCode = "123456"))
  override suspend fun verifyEmail(email: String, code: String) = GatewayResult.Success(principal.copy(userId = email))
  override suspend fun forgotPassword(email: String) = GatewayResult.Success("123456")
  override suspend fun resetPassword(email: String, code: String, newPassword: String) = GatewayResult.Success(principal.copy(userId = email))
  override suspend fun restoreSession(): GatewayResult<Principal> = GatewayResult.Success(principal)
  override suspend fun logout() = Unit
  override suspend fun loadAccount() = GatewayResult.Success(AccountSnapshot(sessions = listOf(AuthSession("current", true, true, 1))))
  override suspend fun joinInvite(code: String) = GatewayResult.Success(principal)
  override suspend fun switchOrganization(tenantId: String) = GatewayResult.Success(principal.copy(tenantId = tenantId))
  override suspend fun changePassword(currentPassword: String, newPassword: String) = GatewayResult.Success(Unit)
  override suspend fun revokeOtherSessions() = GatewayResult.Success(listOf(AuthSession("current", true, true, 1)))
  override suspend fun loadCatalog() = GatewayResult.Success(catalog)
  override suspend fun listProjects() = GatewayResult.Success(listOf(ProjectSummary("Faculty review", "eastbridge", null)))
  override suspend fun openProject(name: String, tenantId: String) = GatewayResult.Success(workspace.copy(projectName = name))
  override suspend fun createScenario(scenarioId: String): GatewayResult<ScheduleWorkspace> =
    GatewayResult.Success(workspace)
  override suspend fun importCsv(
    filename: String,
    content: String,
    fieldMap: Map<String, String>,
  ): GatewayResult<ScheduleWorkspace> = GatewayResult.Success(workspace.copy(projectName = filename))
  override suspend fun startSolve(workspace: ScheduleWorkspace, modeId: String, settings: SolverSettings, useAdvancedOverrides: Boolean) = GatewayResult.Success(workspace)
  override suspend fun validate(workspace: ScheduleWorkspace) = GatewayResult.Success(workspace)
  override suspend fun startImprove(
    workspace: ScheduleWorkspace,
    modeId: String,
    settings: SolverSettings,
    useAdvancedOverrides: Boolean,
  ): GatewayResult<JobStatus> = GatewayResult.Success(JobStatus("job-1", "queued", "Waiting", null))
  override suspend fun pollJob(jobId: String, workspace: ScheduleWorkspace) = GatewayResult.Success(JobStatus(jobId, "complete", "Improvement complete", 1f) to workspace)
  override suspend fun cancelJob(jobId: String) = GatewayResult.Success(JobStatus(jobId, "cancelled", "Improvement cancelled", null))
  override suspend fun exportCsv(workspace: ScheduleWorkspace) = GatewayResult.Success(ExportedSchedule("planora-schedule.csv", "activity_id,title\n1,Algorithms\n"))
  override suspend fun saveProject(name: String, workspace: ScheduleWorkspace) = GatewayResult.Success(ProjectSummary(name, "eastbridge", null))
  override suspend fun renameProject(project: ProjectSummary, newName: String) = GatewayResult.Success(project.copy(name = newName))
  override suspend fun deleteProject(project: ProjectSummary) = GatewayResult.Success(Unit)
  override suspend fun loadMoveTargets(workspace: ScheduleWorkspace, event: ScheduleEvent, week: Int) = GatewayResult.Success(
    listOf(MoveTarget(week, "TUE", 3, 3, 4, true, "No hard conflicts")),
  )
  override suspend fun moveEvent(workspace: ScheduleWorkspace, event: ScheduleEvent, target: MoveTarget) = GatewayResult.Success(
    workspace.copy(events = workspace.events.map { if (it.activityId == event.activityId && it.week == event.week) it.copy(week = target.week, day = target.day, slot = target.slot) else it }),
  )
  override suspend fun loadParity() = GatewayResult.Success(DataRow(mapOf("android" to "supported")))
  override suspend fun loadAccess() = GatewayResult.Success(AccessSnapshot())
  override suspend fun applyAccessChange(change: Map<String, Any?>) = GatewayResult.Success(AccessSnapshot())
  override suspend fun loadAdmin(filters: Map<String, String>) = GatewayResult.Success(AdminSnapshot())
  override suspend fun sendTestEmail(email: String) = GatewayResult.Success(Unit)
  override suspend fun exportAdminCsv(kind: String, filters: Map<String, String>) = GatewayResult.Success(ExportedSchedule("$kind.csv", ""))
  override suspend fun updateBaseUrl(value: String) = GatewayResult.Success(value)
  override fun canEditBaseUrl() = true
  override fun currentBaseUrl() = "http://10.0.2.2:8787"

  companion object {
    val principal = Principal("admin@eastbridge.edu", "A. Elfeel", "uni_admin", "Eastbridge University", setOf("schedule:read", "schedule:write", "solver:run"))
    val catalog = UiCatalog(
      "planora.ui.v1",
      listOf(
        CatalogItem("demo", "Small demo", "A quick example to explore."),
        CatalogItem("spring_2023", "Spring 2023", "A full university-shaped profile."),
        CatalogItem("import", "Import CSV", "Use an export from your current system."),
      ),
      listOf(
        CatalogItem("fast", "Fast", "Quick draft"),
        CatalogItem("balanced", "Balanced", "Recommended", recommended = true),
        CatalogItem("quality", "Quality", "Longest search"),
      ),
      listOf(
        TutorialStep("bring-in", "Bring in your timetable", "Open an example or import your data."),
        TutorialStep("check-essentials", "Check the essentials", "Confirm rooms, people, courses, and groups."),
        TutorialStep("build-draft", "Build a draft", "Choose the outcome you want."),
        TutorialStep("review-repair", "Review and repair", "Open an issue and apply a suggestion."),
        TutorialStep("validate-publish", "Validate and publish", "Resolve hard conflicts before sharing."),
      ),
      "planora-solver-service-v1",
    )
    val workspace = ScheduleWorkspace(
      projectName = "Engineering review",
      days = listOf("MON", "TUE", "WED", "THU", "FRI"),
      weeks = listOf(1, 2),
      slotsPerDay = 7,
      events = listOf(
        ScheduleEvent(1, "Algorithms", "CS201", "Lecture", 1, "MON", 1, 1, "R1.201", "Dr. Smith", listOf("Engineering Year 2")),
        ScheduleEvent(2, "Data Structures", "CS204", "Tutorial", 1, "TUE", 2, 1, "R2.301", "Dr. Lee", listOf("Engineering Year 2")),
      ),
      programs = listOf(AcademicResource("1", "Computer Science")),
      groups = listOf(AcademicResource("5", "Engineering Year 2")),
      courses = listOf(AcademicResource("7", "Algorithms", "CS201"), AcademicResource("8", "Data Structures", "CS204")),
      staff = listOf(AcademicResource("3", "Dr. Smith"), AcademicResource("4", "Dr. Lee")),
      rooms = listOf(AcademicResource("2", "R1.201", "80 seats"), AcademicResource("3", "R2.301", "40 seats")),
      sessionId = "session-1",
    )
  }
}

private class ReadOnlyGateway : FakeGateway() {
  private val readOnlyPrincipal = principal.copy(
    userId = "student@eastbridge.edu",
    displayName = "Student Viewer",
    role = "student",
    permissions = setOf("schedule:read"),
  )

  override suspend fun restoreSession(): GatewayResult<Principal> =
    GatewayResult.Success(readOnlyPrincipal)
}

private class CrossAccountGateway : FakeGateway() {
  val scenarioStarted = AtomicInteger()
  val scenarioFinished = AtomicInteger()
  val loginStarted = AtomicInteger()
  val importCalls = AtomicInteger()

  override suspend fun createScenario(scenarioId: String): GatewayResult<ScheduleWorkspace> =
    suspendCoroutine { continuation ->
      scenarioStarted.incrementAndGet()
      thread(name = "stale-planora-scenario") {
        Thread.sleep(300)
        scenarioFinished.incrementAndGet()
        continuation.resume(
          GatewayResult.Success(workspace.copy(projectName = "User A private workspace")),
        )
      }
    }

  override suspend fun login(email: String, password: String): GatewayResult<Principal> {
    loginStarted.incrementAndGet()
    delay(800)
    return GatewayResult.Success(
      principal.copy(userId = email, displayName = "User B"),
    )
  }

  override suspend fun importCsv(
    filename: String,
    content: String,
    fieldMap: Map<String, String>,
  ): GatewayResult<ScheduleWorkspace> {
    importCalls.incrementAndGet()
    return GatewayResult.Success(workspace.copy(projectName = filename))
  }
}

private class FlakyRestoreGateway : FakeGateway() {
  private val restoreCalls = AtomicInteger()
  val logoutCalls = AtomicInteger()

  override suspend fun restoreSession(): GatewayResult<Principal> =
    if (restoreCalls.getAndIncrement() == 0) {
      GatewayResult.Failure("Planora could not reach the server.", retryable = true)
    } else {
      GatewayResult.Success(principal)
    }

  override suspend fun logout() {
    logoutCalls.incrementAndGet()
  }
}

private class DelayedImproveGateway : FakeGateway() {
  val improveCalls = AtomicInteger()

  override suspend fun startImprove(
    workspace: ScheduleWorkspace,
    modeId: String,
    settings: SolverSettings,
    useAdvancedOverrides: Boolean,
  ): GatewayResult<JobStatus> {
    improveCalls.incrementAndGet()
    delay(300)
    return GatewayResult.Success(JobStatus("job-delayed", "queued", "Waiting", null))
  }
}
