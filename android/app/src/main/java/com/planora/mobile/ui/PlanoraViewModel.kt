package com.planora.mobile.ui

import android.content.Context
import androidx.core.content.edit
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.planora.mobile.domain.CatalogItem
import com.planora.mobile.domain.AccessSnapshot
import com.planora.mobile.domain.AccountSnapshot
import com.planora.mobile.domain.AdminSnapshot
import com.planora.mobile.domain.AuthConfig
import com.planora.mobile.domain.DataRow
import com.planora.mobile.domain.ExportedSchedule
import com.planora.mobile.domain.GatewayResult
import com.planora.mobile.domain.JobStatus
import com.planora.mobile.domain.MoveTarget
import com.planora.mobile.domain.PlanoraGateway
import com.planora.mobile.domain.Principal
import com.planora.mobile.domain.ProjectSummary
import com.planora.mobile.domain.ScheduleEvent
import com.planora.mobile.domain.ScheduleWorkspace
import com.planora.mobile.domain.SolverSettings
import com.planora.mobile.domain.UiCatalog
import com.planora.mobile.ui.theme.ThemeMode
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.delay
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class Destination(val label: String) {
  HOME("Home"),
  DATA("Data"),
  SCHEDULE("Schedule"),
  REVIEW("Review"),
  PROJECTS("Projects"),
  INSIGHTS("Insights"),
  ADVANCED("Advanced"),
  ACCOUNT("Account"),
  PLATFORM("Platform"),
  ACCESS("Access"),
  ADMIN("Admin"),
  TOOLS("Tools"),
  SETTINGS("Settings"),
  TUTORIAL("Guide"),
}

enum class AuthStage { LOGIN, REGISTER, VERIFY, FORGOT, RESET }

data class PlanoraUiState(
  val initializing: Boolean = true,
  val authenticated: Boolean = false,
  val authConfig: AuthConfig = AuthConfig(),
  val authStage: AuthStage = AuthStage.LOGIN,
  val principal: Principal? = null,
  val catalog: UiCatalog? = null,
  val projects: List<ProjectSummary> = emptyList(),
  val projectsLoadError: String? = null,
  val account: AccountSnapshot = AccountSnapshot(),
  val parity: DataRow? = null,
  val access: AccessSnapshot? = null,
  val admin: AdminSnapshot? = null,
  val workspace: ScheduleWorkspace? = null,
  val destination: Destination = Destination.HOME,
  val selectedWeek: Int = 1,
  val selectedDay: String = "MON",
  val selectedEvent: ScheduleEvent? = null,
  val heldEvent: ScheduleEvent? = null,
  val moveTargets: List<MoveTarget> = emptyList(),
  val selectedModeId: String = "fast",
  val solverSettings: SolverSettings = SolverSettings(),
  val advancedOverridesEnabled: Boolean = false,
  val busy: Boolean = false,
  val runningJob: JobStatus? = null,
  val tutorialPage: Int = 0,
  val tutorialReturn: Destination = Destination.HOME,
  val message: String? = null,
  val isError: Boolean = false,
  val apiBaseUrl: String = "",
  val canEditBaseUrl: Boolean = false,
  val themeMode: ThemeMode = ThemeMode.SYSTEM,
  val pendingExport: ExportedSchedule? = null,
  val canRetrySession: Boolean = false,
)

class PlanoraViewModel(
  private val gateway: PlanoraGateway,
  context: Context,
) : ViewModel() {
  private val onboardingStore = context.applicationContext
    .getSharedPreferences("planora_onboarding", Context.MODE_PRIVATE)
  private val appearanceStore = context.applicationContext
    .getSharedPreferences("planora_appearance", Context.MODE_PRIVATE)
  private var pollingJob: Job? = null
  private var activeActionJob: Job? = null
  private var restoreJob: Job? = null
  private var cancelRequestJob: Job? = null
  private var logoutJob: Job? = null
  private var sessionGeneration = 0L
  private val _uiState = MutableStateFlow(
    PlanoraUiState(
      apiBaseUrl = gateway.currentBaseUrl(),
      canEditBaseUrl = gateway.canEditBaseUrl(),
      themeMode = ThemeMode.fromStorage(appearanceStore.getString("theme_mode", null)),
    ),
  )
  val uiState: StateFlow<PlanoraUiState> = _uiState.asStateFlow()

  init {
    restore()
  }

  fun login(email: String, password: String) = launchBusy { generation ->
    logoutJob?.join()
    if (!isCurrent(generation)) return@launchBusy
    when (val result = gateway.login(email, password)) {
      is GatewayResult.Success -> {
        if (!isCurrent(generation)) return@launchBusy
        _uiState.update { it.copy(authenticated = true, principal = result.value) }
        bootstrap(
          showTutorial = !onboardingStore.getBoolean("seen", false),
          generation = generation,
        )
      }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun chooseAuthStage(stage: AuthStage) {
    _uiState.update { it.copy(authStage = stage, message = null, isError = false) }
  }

  fun register(email: String, password: String, displayName: String) = launchBusy { generation ->
    when (val result = gateway.register(email, password, displayName)) {
      is GatewayResult.Success -> {
        if (!isCurrent(generation)) return@launchBusy
        val principal = result.value.signedInPrincipal
        if (principal != null) {
          _uiState.update { it.copy(authenticated = true, principal = principal, authStage = AuthStage.LOGIN) }
          bootstrap(showTutorial = !onboardingStore.getBoolean("seen", false), generation = generation)
        } else {
          val suffix = result.value.developmentCode?.let { " Development code: $it" }.orEmpty()
          _uiState.update {
            it.copy(
              authStage = AuthStage.VERIFY,
              message = "Account created. Check your email for the confirmation code.$suffix",
              isError = false,
            )
          }
        }
      }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun verifyEmail(email: String, code: String) = launchBusy { generation ->
    when (val result = gateway.verifyEmail(email, code)) {
      is GatewayResult.Success -> if (isCurrent(generation)) {
        _uiState.update { it.copy(authenticated = true, principal = result.value, authStage = AuthStage.LOGIN) }
        bootstrap(showTutorial = !onboardingStore.getBoolean("seen", false), generation = generation)
        showMessage("Email confirmed. Welcome to Planora.")
      }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun forgotPassword(email: String) = launchBusy { generation ->
    when (val result = gateway.forgotPassword(email)) {
      is GatewayResult.Success -> if (isCurrent(generation)) {
        val suffix = result.value?.let { " Development code: $it" }.orEmpty()
        _uiState.update {
          it.copy(
            authStage = AuthStage.RESET,
            message = "If that account exists, Planora sent a reset email.$suffix",
            isError = false,
          )
        }
      }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun resetPassword(email: String, code: String, newPassword: String) = launchBusy { generation ->
    when (val result = gateway.resetPassword(email, code, newPassword)) {
      is GatewayResult.Success -> if (isCurrent(generation)) {
        _uiState.update { it.copy(authenticated = true, principal = result.value, authStage = AuthStage.LOGIN) }
        bootstrap(showTutorial = !onboardingStore.getBoolean("seen", false), generation = generation)
        showMessage("Password reset. You are signed in.")
      }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun logout() {
    invalidateSession()
    _uiState.value = signedOutState()
    launchLogout()
  }

  fun retrySession() {
    _uiState.update { it.copy(initializing = true, message = null, canRetrySession = false) }
    restore()
  }

  /** Captures the signed-in account epoch for account-bound Android picker work. */
  fun captureAuthenticatedGeneration(): Long? =
    sessionGeneration.takeIf { _uiState.value.authenticated }

  fun isAuthenticatedGeneration(generation: Long): Boolean =
    isCurrent(generation) && _uiState.value.authenticated

  fun chooseTheme(mode: ThemeMode) {
    appearanceStore.edit { putString("theme_mode", mode.storageValue) }
    _uiState.update { it.copy(themeMode = mode) }
  }

  fun navigate(destination: Destination) {
    _uiState.update { it.copy(destination = destination, selectedEvent = null, message = null) }
    when (destination) {
      Destination.ACCOUNT -> refreshAccount()
      Destination.PLATFORM -> refreshParity()
      Destination.ACCESS -> refreshAccess()
      Destination.ADMIN -> refreshAdmin()
      else -> Unit
    }
  }

  fun openTutorial(returnTo: Destination = _uiState.value.destination) {
    _uiState.update { it.copy(destination = Destination.TUTORIAL, tutorialPage = 0, tutorialReturn = returnTo) }
  }

  fun tutorialNext() {
    val lastPage = (_uiState.value.catalog?.tutorial?.lastIndex ?: 4).coerceAtLeast(0)
    _uiState.update { it.copy(tutorialPage = (it.tutorialPage + 1).coerceAtMost(lastPage)) }
  }

  fun tutorialPrevious() {
    _uiState.update { it.copy(tutorialPage = (it.tutorialPage - 1).coerceAtLeast(0)) }
  }

  fun finishTutorial() {
    onboardingStore.edit { putBoolean("seen", true) }
    _uiState.update { it.copy(destination = it.tutorialReturn, tutorialPage = 0) }
  }

  fun chooseWeek(week: Int) {
    _uiState.update { it.copy(selectedWeek = week, selectedEvent = null) }
  }

  fun chooseDay(day: String) {
    _uiState.update { it.copy(selectedDay = day, selectedEvent = null) }
  }

  fun selectEvent(event: ScheduleEvent?) {
    _uiState.update { it.copy(selectedEvent = event) }
  }

  fun chooseMode(modeId: String) {
    _uiState.update { it.copy(selectedModeId = modeId, advancedOverridesEnabled = false) }
  }

  fun updateSolverSettings(settings: SolverSettings) {
    _uiState.update { it.copy(solverSettings = settings, advancedOverridesEnabled = true) }
  }

  fun useModeDefaults() {
    _uiState.update { it.copy(advancedOverridesEnabled = false) }
  }

  fun openProject(project: ProjectSummary) = launchBusy { generation ->
    if (!canReplaceWorkspace()) return@launchBusy
    when (val result = gateway.openProject(project.name, project.tenantId)) {
      is GatewayResult.Success -> if (isCurrent(generation)) openWorkspace(result.value)
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun refreshProjects() = launchBusy { generation ->
    when (val result = gateway.listProjects()) {
      is GatewayResult.Success -> if (isCurrent(generation)) {
        _uiState.update { it.copy(projects = result.value, projectsLoadError = null) }
      }
      is GatewayResult.Failure -> {
        if (!isCurrent(generation)) return@launchBusy
        if (result.requiresSignIn) {
          showFailure(result)
        } else {
          _uiState.update { it.copy(projectsLoadError = result.message) }
          showMessage("Saved projects could not be refreshed: ${result.message}", true)
        }
      }
    }
  }

  fun createScenario(item: CatalogItem) {
    if (!canReplaceWorkspace()) return
    if (item.id == "import") {
      if (_uiState.value.principal?.canWriteSchedule != true) {
        showMessage("Your role can view schedules but cannot import timetable data.", true)
        return
      }
      _uiState.update { it.copy(message = "Choose a CSV file to continue.", isError = false) }
      return
    }
    launchBusy { generation ->
      when (val result = gateway.createScenario(item.id)) {
        is GatewayResult.Success -> if (isCurrent(generation)) openWorkspace(result.value)
        is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
      }
    }
  }

  fun importCsv(
    filename: String,
    content: String,
    expectedGeneration: Long,
    fieldMap: Map<String, String> = emptyMap(),
  ) {
    if (!isAuthenticatedGeneration(expectedGeneration)) return
    if (_uiState.value.principal?.canWriteSchedule != true) {
      showMessage("Your role can view schedules but cannot import timetable data.", true)
      return
    }
    launchBusy(expectedGeneration) { generation ->
    if (!canReplaceWorkspace()) return@launchBusy
    when (val result = gateway.importCsv(filename, content, fieldMap)) {
        is GatewayResult.Success -> if (isCurrent(generation)) openWorkspace(result.value)
        is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
      }
    }
  }

  fun solve() {
    val workspace = _uiState.value.workspace ?: return
    val principal = _uiState.value.principal
    if (principal?.canRunSolver != true) {
      showMessage("Your role can view schedules but cannot run the scheduler.", true)
      return
    }
    if (!canReplaceWorkspace()) return
    val modeId = _uiState.value.selectedModeId
    val settings = _uiState.value.solverSettings
    val useAdvancedOverrides = _uiState.value.advancedOverridesEnabled
    launchBusy { generation ->
      when (val result = gateway.startSolve(workspace, modeId, settings, useAdvancedOverrides)) {
        is GatewayResult.Success -> {
          if (!isCurrent(generation)) return@launchBusy
          openWorkspace(result.value)
          showMessage("Draft schedule ready.")
        }
        is GatewayResult.Failure -> {
          if (!isCurrent(generation)) return@launchBusy
          if (result.sessionStateUnknown) quarantineWorkspace(result.message) else showFailure(result)
        }
      }
    }
  }

  fun improve() {
    if (_uiState.value.busy) return
    val workspace = _uiState.value.workspace ?: return
    if (_uiState.value.principal?.canRunSolver != true) {
      showMessage("Your role can review this schedule but cannot improve it.", true)
      return
    }
    if (_uiState.value.runningJob != null) {
      showMessage("An improvement is already running. Cancel it before starting another.", true)
      return
    }
    val sessionId = workspace.sessionId
    if (sessionId.isNullOrBlank()) {
      showMessage("Open or create a schedule first.", true)
      return
    }
    val modeId = _uiState.value.selectedModeId
    val settings = _uiState.value.solverSettings
    val useAdvancedOverrides = _uiState.value.advancedOverridesEnabled
    launchBusy { generation ->
      when (val result = gateway.startImprove(workspace, modeId, settings, useAdvancedOverrides)) {
        is GatewayResult.Success -> {
          if (!isCurrent(generation)) return@launchBusy
          _uiState.update { it.copy(runningJob = result.value) }
          poll(result.value.id, sessionId, workspace, generation)
        }
        is GatewayResult.Failure -> {
          if (!isCurrent(generation)) return@launchBusy
          if (result.sessionStateUnknown) quarantineWorkspace(result.message) else showFailure(result)
        }
      }
    }
  }

  fun cancelImprove() {
    val job = _uiState.value.runningJob ?: return
    if (job.status == TRACKING_ERROR_STATUS) {
      pollingJob?.cancel()
      _uiState.update {
        it.copy(
          runningJob = null,
          workspace = null,
          selectedEvent = null,
          destination = Destination.HOME,
          message = "Stopped tracking the server job. Reopen a saved project or start a fresh schedule.",
          isError = false,
        )
      }
      return
    }
    val generation = sessionGeneration
    cancelRequestJob?.cancel()
    val requestJob = viewModelScope.launch(start = CoroutineStart.LAZY) {
      val ownJob = currentCoroutineContext()[Job]
      when (val result = gateway.cancelJob(job.id)) {
        is GatewayResult.Success -> {
          if (!isCurrent(generation)) return@launch
          var responseApplied = false
          _uiState.update { state ->
            if (state.runningJob?.id == job.id) {
              responseApplied = true
              state.copy(runningJob = result.value)
            } else state
          }
          if (responseApplied) showMessage("Cancelling the improvement…")
        }
        is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
      }
      if (cancelRequestJob === ownJob) cancelRequestJob = null
    }
    cancelRequestJob = requestJob
    requestJob.start()
  }

  fun validate() {
    val workspace = _uiState.value.workspace ?: return
    launchBusy { generation ->
      when (val result = gateway.validate(workspace)) {
        is GatewayResult.Success -> {
          if (!isCurrent(generation)) return@launchBusy
          _uiState.update { it.copy(workspace = result.value, selectedEvent = null) }
          val conflicts = result.value.hardConflicts.size
          showMessage(
            if (conflicts == 0) "Validation passed. This timetable is ready to save or share."
            else "$conflicts hard conflict${if (conflicts == 1) "" else "s"} still need attention.",
            conflicts > 0,
          )
        }
        is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
      }
    }
  }

  fun saveProject(name: String) {
    val workspace = _uiState.value.workspace ?: return
    if (_uiState.value.principal?.canWriteProjects != true) {
      showMessage("Your role can open projects but cannot save them.", true)
      return
    }
    launchBusy { generation ->
      when (val result = gateway.saveProject(name, workspace)) {
        is GatewayResult.Success -> {
          if (!isCurrent(generation)) return@launchBusy
          _uiState.update { state ->
            state.copy(
              workspace = state.workspace?.copy(projectName = result.value.name),
              projects = (state.projects.filterNot {
                it.name == result.value.name && it.tenantId == result.value.tenantId
              } + result.value).sortedBy { it.name },
            )
          }
          showMessage("Saved ${result.value.name}.")
        }
        is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
      }
    }
  }

  fun renameProject(project: ProjectSummary, newName: String) = launchBusy { generation ->
    if (_uiState.value.principal?.canWriteProjects != true) {
      showMessage("Your role can open projects but cannot rename them.", true)
      return@launchBusy
    }
    when (val result = gateway.renameProject(project, newName)) {
      is GatewayResult.Success -> if (isCurrent(generation)) {
        _uiState.update { state ->
          state.copy(
            projects = (state.projects.filterNot {
              it.name == project.name && it.tenantId == project.tenantId
            } + result.value).sortedBy { it.name },
          )
        }
        showMessage("Renamed project to ${result.value.name}.")
      }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun deleteProject(project: ProjectSummary) = launchBusy { generation ->
    if (_uiState.value.principal?.canWriteProjects != true) {
      showMessage("Your role can open projects but cannot delete them.", true)
      return@launchBusy
    }
    when (val result = gateway.deleteProject(project)) {
      is GatewayResult.Success -> if (isCurrent(generation)) {
        _uiState.update { state ->
          state.copy(projects = state.projects.filterNot {
            it.name == project.name && it.tenantId == project.tenantId
          })
        }
        showMessage("Deleted ${project.name}.")
      }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun previewMoves(event: ScheduleEvent) {
    val workspace = _uiState.value.workspace ?: return
    if (_uiState.value.principal?.canWriteSchedule != true) {
      showMessage("Your role can review this class but cannot move it.", true)
      return
    }
    launchBusy { generation ->
      when (val result = gateway.loadMoveTargets(workspace, event, _uiState.value.selectedWeek)) {
        is GatewayResult.Success -> if (isCurrent(generation)) {
          _uiState.update { it.copy(heldEvent = event, moveTargets = result.value) }
          if (result.value.none { it.allowed }) showMessage("No safe move targets are available.", true)
        }
        is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
      }
    }
  }

  fun moveEvent(target: MoveTarget) {
    val workspace = _uiState.value.workspace ?: return
    val event = _uiState.value.heldEvent ?: return
    launchBusy { generation ->
      when (val result = gateway.moveEvent(workspace, event, target)) {
        is GatewayResult.Success -> if (isCurrent(generation)) {
          _uiState.update {
            it.copy(
              workspace = result.value,
              selectedEvent = result.value.events.firstOrNull { row ->
                row.activityId == event.activityId && row.week == target.week
              },
              heldEvent = null,
              moveTargets = emptyList(),
            )
          }
          showMessage("Moved ${event.title} to ${target.day}, slot ${target.slot + 1}.")
        }
        is GatewayResult.Failure -> if (isCurrent(generation)) {
          if (result.sessionStateUnknown) quarantineWorkspace(result.message) else showFailure(result)
        }
      }
    }
  }

  fun releaseMove() {
    _uiState.update { it.copy(heldEvent = null, moveTargets = emptyList()) }
  }

  fun refreshAccount() = launchBusy { generation ->
    when (val result = gateway.loadAccount()) {
      is GatewayResult.Success -> if (isCurrent(generation)) _uiState.update { it.copy(account = result.value) }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun joinInvite(code: String) = launchBusy { generation ->
    when (val result = gateway.joinInvite(code)) {
      is GatewayResult.Success -> if (isCurrent(generation)) {
        _uiState.update { it.copy(principal = result.value) }
        bootstrap(showTutorial = false, generation = generation)
        showMessage("Group joined. Your permissions are up to date.")
      }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun switchOrganization(tenantId: String) = launchBusy { generation ->
    when (val result = gateway.switchOrganization(tenantId)) {
      is GatewayResult.Success -> if (isCurrent(generation)) {
        _uiState.update {
          it.copy(
            principal = result.value,
            workspace = null,
            selectedEvent = null,
            heldEvent = null,
            moveTargets = emptyList(),
          )
        }
        bootstrap(showTutorial = false, generation = generation)
        showMessage("Switched to ${result.value.tenantId}.")
      }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun changePassword(currentPassword: String, newPassword: String) = launchBusy { generation ->
    when (val result = gateway.changePassword(currentPassword, newPassword)) {
      is GatewayResult.Success -> if (isCurrent(generation)) {
        showMessage("Password changed. Other sessions were revoked.")
        when (val account = gateway.loadAccount()) {
          is GatewayResult.Success -> if (isCurrent(generation)) _uiState.update { it.copy(account = account.value) }
          is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(account)
        }
      }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun revokeOtherSessions() = launchBusy { generation ->
    when (val result = gateway.revokeOtherSessions()) {
      is GatewayResult.Success -> if (isCurrent(generation)) {
        _uiState.update { it.copy(account = it.account.copy(sessions = result.value)) }
        showMessage("Other sessions revoked.")
      }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun refreshParity() = launchBusy { generation ->
    when (val result = gateway.loadParity()) {
      is GatewayResult.Success -> if (isCurrent(generation)) _uiState.update { it.copy(parity = result.value) }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun refreshAccess() = launchBusy { generation ->
    when (val result = gateway.loadAccess()) {
      is GatewayResult.Success -> if (isCurrent(generation)) _uiState.update { it.copy(access = result.value) }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun applyAccessChange(change: Map<String, Any?>) = launchBusy { generation ->
    when (val result = gateway.applyAccessChange(change)) {
      is GatewayResult.Success -> if (isCurrent(generation)) {
        _uiState.update { it.copy(access = result.value) }
        showMessage("Access settings updated.")
      }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun refreshAdmin(filters: Map<String, String> = emptyMap()) = launchBusy { generation ->
    when (val result = gateway.loadAdmin(filters)) {
      is GatewayResult.Success -> if (isCurrent(generation)) _uiState.update { it.copy(admin = result.value) }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun sendTestEmail(email: String) = launchBusy { generation ->
    when (val result = gateway.sendTestEmail(email)) {
      is GatewayResult.Success -> if (isCurrent(generation)) showMessage("Test email sent.")
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun exportAdminCsv(kind: String, filters: Map<String, String>) = launchBusy { generation ->
    when (val result = gateway.exportAdminCsv(kind, filters)) {
      is GatewayResult.Success -> if (isCurrent(generation)) _uiState.update { it.copy(pendingExport = result.value) }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun exportCsv() {
    val workspace = _uiState.value.workspace ?: return
    launchBusy { generation ->
      when (val result = gateway.exportCsv(workspace)) {
        is GatewayResult.Success -> if (isCurrent(generation)) {
          _uiState.update { it.copy(pendingExport = result.value) }
        }
        is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
      }
    }
  }

  fun exportHandled(saved: Boolean, expectedGeneration: Long) {
    if (!isAuthenticatedGeneration(expectedGeneration)) return
    val filename = _uiState.value.pendingExport?.filename
    _uiState.update { it.copy(pendingExport = null) }
    if (saved && !filename.isNullOrBlank()) showMessage("Exported $filename.")
  }

  fun reportError(message: String, expectedGeneration: Long? = null) {
    if (expectedGeneration == null || isAuthenticatedGeneration(expectedGeneration)) {
      showMessage(message, true)
    }
  }

  fun updateBaseUrl(value: String) = launchBusy { generation ->
    when (val result = gateway.updateBaseUrl(value)) {
      is GatewayResult.Success -> {
        if (!isCurrent(generation)) return@launchBusy
        val changed = result.value != _uiState.value.apiBaseUrl
        if (changed) {
          invalidateSession(cancelActiveAction = false)
          _uiState.value = signedOutState().copy(
            apiBaseUrl = result.value,
            message = "Server address saved. Sign in again to reconnect.",
          )
        } else {
          _uiState.update { it.copy(apiBaseUrl = result.value) }
          showMessage("Server address is already up to date.")
        }
      }
      is GatewayResult.Failure -> if (isCurrent(generation)) showFailure(result)
    }
  }

  fun clearMessage() {
    _uiState.update { it.copy(message = null) }
  }

  private fun restore() {
    restoreJob?.cancel()
    val generation = sessionGeneration
    val job = viewModelScope.launch(start = CoroutineStart.LAZY) {
      val ownJob = currentCoroutineContext()[Job]
      val hasSession = gateway.hasSession()
      if (!hasSession && isCurrent(generation)) {
        _uiState.update { it.copy(initializing = false) }
      }
      when (val config = gateway.loadAuthConfig()) {
        is GatewayResult.Success -> if (isCurrent(generation)) {
          _uiState.update { it.copy(authConfig = config.value) }
        }
        is GatewayResult.Failure -> if (isCurrent(generation)) {
          _uiState.update { it.copy(message = config.message, isError = true) }
        }
      }
      if (!hasSession) {
        return@launch
      }
      if (!isCurrent(generation)) return@launch
      when (val result = gateway.restoreSession()) {
        is GatewayResult.Success -> {
          if (!isCurrent(generation)) return@launch
          _uiState.update { it.copy(authenticated = true, principal = result.value) }
          bootstrap(
            showTutorial = !onboardingStore.getBoolean("seen", false),
            generation = generation,
          )
        }
        is GatewayResult.Failure -> {
          if (!isCurrent(generation)) return@launch
          if (result.requiresSignIn) {
            showFailure(result)
          } else {
            _uiState.value = signedOutState().copy(
              message = result.message,
              isError = true,
              canRetrySession = true,
            )
          }
        }
      }
      if (restoreJob === ownJob) restoreJob = null
    }
    restoreJob = job
    job.start()
  }

  private suspend fun bootstrap(showTutorial: Boolean, generation: Long) {
    if (!isCurrent(generation)) return
    val (catalog, projects, account) = coroutineScope {
      val catalogRequest = async { gateway.loadCatalog() }
      val projectsRequest = async { gateway.listProjects() }
      val accountRequest = async { gateway.loadAccount() }
      Triple(catalogRequest.await(), projectsRequest.await(), accountRequest.await())
    }
    if (!isCurrent(generation)) return
    if (catalog is GatewayResult.Failure) {
      if (catalog.requiresSignIn) {
        showFailure(catalog)
      } else {
        _uiState.update { it.copy(initializing = false, message = catalog.message, isError = true) }
      }
      return
    }
    if (projects is GatewayResult.Failure && projects.requiresSignIn) {
      showFailure(projects)
      return
    }
    val projectsFailure = projects as? GatewayResult.Failure
    _uiState.update {
      it.copy(
        initializing = false,
        catalog = (catalog as GatewayResult.Success).value,
        projects = (projects as? GatewayResult.Success)?.value.orEmpty(),
        projectsLoadError = projectsFailure?.message,
        account = (account as? GatewayResult.Success)?.value ?: it.account,
        destination = if (showTutorial) Destination.TUTORIAL else Destination.HOME,
        tutorialReturn = Destination.HOME,
        selectedModeId = (catalog.value.modes.firstOrNull { mode -> mode.recommended }
          ?: catalog.value.modes.first()).id,
        message = projectsFailure?.let { failure ->
          "Workspace opened, but saved projects could not be loaded: ${failure.message}"
        },
        isError = projectsFailure != null,
      )
    }
  }

  private fun openWorkspace(workspace: ScheduleWorkspace) {
    _uiState.update {
      it.copy(
        workspace = workspace,
        destination = Destination.SCHEDULE,
        selectedWeek = workspace.weeks.firstOrNull() ?: 1,
        selectedDay = workspace.days.firstOrNull() ?: "MON",
        selectedEvent = null,
      )
    }
  }

  private fun poll(
    jobId: String,
    sessionId: String,
    originalWorkspace: ScheduleWorkspace,
    generation: Long,
  ) {
    pollingJob?.cancel()
    pollingJob = viewModelScope.launch {
      var delayMillis = 650L
      while (isCurrent(generation)) {
        when (val result = gateway.pollJob(jobId, originalWorkspace)) {
          is GatewayResult.Success -> {
            if (!isCurrent(generation)) return@launch
            val (job, updated) = result.value
            var responseApplied = false
            _uiState.update {
              if (it.runningJob?.id != jobId) return@update it
              responseApplied = true
              val sameSession = it.workspace?.sessionId == sessionId
              it.copy(
                runningJob = if (job.status in setOf("complete", "failed", "cancelled")) null else job,
                workspace = if (sameSession) updated ?: it.workspace else it.workspace,
                selectedEvent = if (sameSession && updated != null) null else it.selectedEvent,
              )
            }
            if (job.status in setOf("complete", "failed", "cancelled")) {
              if (!responseApplied) return@launch
              val stillOpen = _uiState.value.workspace?.sessionId == sessionId
              showMessage(
                if (job.status == "complete" && !stillOpen) {
                  "Improvement completed for the previous schedule; its result was not applied here."
                } else if (job.status == "cancelled" && updated != null) {
                  "Improvement cancelled. The latest server schedule is shown."
                } else job.message,
                job.status == "failed",
              )
              return@launch
            }
          }
          is GatewayResult.Failure -> {
            if (!isCurrent(generation)) return@launch
            if (result.retryable) {
              _uiState.update { state ->
                state.copy(
                  runningJob = state.runningJob?.copy(
                    message = "Connection interrupted. Retrying the server job…",
                  ),
                )
              }
            } else {
              if (result.requiresSignIn) {
                showFailure(result)
              } else {
                _uiState.update { state ->
                  if (state.runningJob?.id == jobId) {
                    state.copy(
                      runningJob = state.runningJob.copy(
                        status = TRACKING_ERROR_STATUS,
                        message = "${result.message} Stop tracking to close this schedule safely.",
                        progress = null,
                      ),
                    )
                  } else state
                }
              }
              return@launch
            }
          }
        }
        delay(delayMillis)
        delayMillis = (delayMillis * 3 / 2).coerceAtMost(10_000L)
      }
    }
  }

  private fun launchBusy(
    expectedGeneration: Long = sessionGeneration,
    block: suspend (generation: Long) -> Unit,
  ) {
    if (!isCurrent(expectedGeneration)) return
    while (true) {
      if (!isCurrent(expectedGeneration)) return
      val current = _uiState.value
      if (current.busy) return
      if (_uiState.compareAndSet(current, current.copy(busy = true, message = null))) break
    }
    val job = viewModelScope.launch(start = CoroutineStart.LAZY) {
      val ownJob = currentCoroutineContext()[Job]
      try {
        if (isCurrent(expectedGeneration)) block(expectedGeneration)
      } finally {
        if (isCurrent(expectedGeneration)) {
          _uiState.update { it.copy(busy = false) }
        }
        if (activeActionJob === ownJob) activeActionJob = null
      }
    }
    activeActionJob = job
    job.start()
  }

  private fun showFailure(result: GatewayResult.Failure) {
    if (result.requiresSignIn) {
      invalidateSession()
      _uiState.value = signedOutState().copy(message = result.message, isError = true)
      launchLogout()
    } else {
      showMessage(result.message, true)
    }
  }

  private fun showMessage(message: String, error: Boolean = false) {
    _uiState.update { it.copy(message = message, isError = error) }
  }

  private fun quarantineWorkspace(message: String) {
    pollingJob?.cancel()
    pollingJob = null
    _uiState.update {
      it.copy(
        workspace = null,
        runningJob = null,
        selectedEvent = null,
        destination = Destination.HOME,
        message = "$message The temporary schedule was closed so an unknown server result cannot be saved or exported.",
        isError = true,
      )
    }
  }

  private fun invalidateSession(cancelActiveAction: Boolean = true) {
    sessionGeneration += 1
    pollingJob?.cancel()
    pollingJob = null
    restoreJob?.cancel()
    restoreJob = null
    cancelRequestJob?.cancel()
    cancelRequestJob = null
    if (cancelActiveAction) {
      activeActionJob?.cancel()
      activeActionJob = null
    }
  }

  private fun launchLogout() {
    val job = viewModelScope.launch(start = CoroutineStart.LAZY) {
      val ownJob = currentCoroutineContext()[Job]
      gateway.logout()
      if (logoutJob === ownJob) logoutJob = null
    }
    logoutJob = job
    job.start()
  }

  private fun isCurrent(generation: Long): Boolean = generation == sessionGeneration

  private fun canReplaceWorkspace(): Boolean {
    if (_uiState.value.runningJob == null) return true
    showMessage("Cancel the running improvement before opening or rebuilding another schedule.", true)
    return false
  }

  private fun signedOutState() = PlanoraUiState(
    initializing = false,
    authConfig = _uiState.value.authConfig,
    authStage = _uiState.value.authStage,
    apiBaseUrl = gateway.currentBaseUrl(),
    canEditBaseUrl = gateway.canEditBaseUrl(),
    themeMode = _uiState.value.themeMode,
  )

  companion object {
    private const val TRACKING_ERROR_STATUS = "tracking_error"

    fun factory(gateway: PlanoraGateway, context: Context): ViewModelProvider.Factory =
      object : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T {
          return PlanoraViewModel(gateway, context) as T
        }
      }
  }
}
