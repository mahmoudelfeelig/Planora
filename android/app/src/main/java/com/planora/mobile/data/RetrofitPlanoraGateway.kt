package com.planora.mobile.data

import com.google.gson.GsonBuilder
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import com.planora.mobile.BuildConfig
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
import com.planora.mobile.domain.OrganizationMembership
import com.planora.mobile.domain.PlanoraGateway
import com.planora.mobile.domain.Principal
import com.planora.mobile.domain.ProjectSummary
import com.planora.mobile.domain.RegistrationResult
import com.planora.mobile.domain.ScheduleEvent
import com.planora.mobile.domain.ScheduleWorkspace
import com.planora.mobile.domain.SolverSettings
import com.planora.mobile.domain.UiCatalog
import com.planora.mobile.domain.TutorialStep
import com.planora.mobile.domain.ValidationState
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.HttpException
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.io.IOException
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

class RetrofitPlanoraGateway(
  private val settingsStore: ApiSettingsStore,
  private val tokenStore: EncryptedTokenStore,
  private val epochSeconds: () -> Long = { System.currentTimeMillis() / 1000L },
) : PlanoraGateway {
  @Volatile private var cachedClient: CachedClient? = null
  @Volatile private var currentPrincipal: PrincipalSnapshot? = null
  private val refreshMutex = Mutex()
  private val refreshAttemptMutex = Mutex()
  private val credentialGeneration = AtomicLong(0L)

  override suspend fun hasSession(): Boolean = refreshMutex.withLock {
    val target = currentTarget()
    val token = tokenStore.load(target.origin)
    if (token.isBlank()) return@withLock false
    if (JwtSessionPolicy.classify(token, epochSeconds()) == JwtLifetime.EXPIRED) {
      clearSession()
      return@withLock false
    }
    true
  }

  override suspend fun loadAuthConfig(): GatewayResult<AuthConfig> = request {
    val response = service(currentTarget().baseUrl, token = "").authConfig()
    AuthConfig(
      registrationEnabled = response.registrationEnabled,
      emailVerificationRequired = response.emailVerificationRequired,
      smtpConfigured = response.smtpConfigured,
    )
  }

  override suspend fun login(email: String, password: String): GatewayResult<Principal> =
    request(loginAttempt = true) {
      require(email.isNotBlank()) { "Enter your university email." }
      require(password.isNotBlank()) { "Enter your password." }
      val attempt = beginAuthenticationAttempt()
      val response = service(attempt.target.baseUrl, token = "")
        .login(LoginRequest(email.trim(), password))
      acceptAuthentication(attempt, response.token, response.principal)
    }

  override suspend fun register(
    email: String,
    password: String,
    displayName: String,
  ): GatewayResult<RegistrationResult> = request(loginAttempt = true) {
    require(email.isNotBlank()) { "Enter your university email." }
    require(password.length >= 10) { "Password must be at least 10 characters." }
    require(displayName.isNotBlank()) { "Enter your name." }
    val attempt = beginAuthenticationAttempt()
    val response = service(attempt.target.baseUrl, token = "")
      .register(RegisterRequest(email.trim(), password, displayName.trim()))
    currentCoroutineContext().ensureActive()
    val principal = if (!response.token.isNullOrBlank() && response.principal != null) {
      acceptAuthentication(attempt, response.token, response.principal)
    } else null
    RegistrationResult(
      signedInPrincipal = principal,
      verificationRequired = response.verificationRequired && principal == null,
      developmentCode = response.verificationCode,
    )
  }

  override suspend fun verifyEmail(email: String, code: String): GatewayResult<Principal> = request {
    require(email.isNotBlank()) { "Enter the email used to register." }
    require(code.isNotBlank()) { "Enter the six-digit confirmation code." }
    val attempt = beginAuthenticationAttempt()
    val response = service(attempt.target.baseUrl, token = "")
      .verifyEmail(VerifyEmailRequest(email.trim(), code.trim()))
    acceptAuthentication(attempt, response.token, response.principal)
  }

  override suspend fun forgotPassword(email: String): GatewayResult<String?> = request {
    require(email.isNotBlank()) { "Enter your account email." }
    service(currentTarget().baseUrl, token = "")
      .forgotPassword(ForgotPasswordRequest(email.trim())).resetCode
  }

  override suspend fun resetPassword(
    email: String,
    code: String,
    newPassword: String,
  ): GatewayResult<Principal> = request {
    require(email.isNotBlank()) { "Enter your account email." }
    require(code.isNotBlank()) { "Enter the reset code." }
    require(newPassword.length >= 10) { "Password must be at least 10 characters." }
    val attempt = beginAuthenticationAttempt()
    val response = service(attempt.target.baseUrl, token = "")
      .resetPassword(ResetPasswordRequest(email.trim(), code.trim(), newPassword = newPassword))
    acceptAuthentication(attempt, response.token, response.principal)
  }

  override suspend fun restoreSession(): GatewayResult<Principal> = authenticatedRequest { client ->
    val principal = client.api.whoAmI().toDomain()
    currentCoroutineContext().ensureActive()
    refreshMutex.withLock {
      if (credentialGeneration.get() == client.generation) {
        currentPrincipal = PrincipalSnapshot(client.generation, principal)
      }
    }
    principal
  }

  override suspend fun logout() {
    val authenticatedApi = refreshMutex.withLock {
      val target = currentTarget()
      val token = tokenStore.load(target.origin)
      val api = token.takeIf { it.isNotBlank() }?.let {
        buildApi("${target.baseUrl.trimEnd('/')}/", it, readTimeoutSeconds = 10)
      }
      clearSession()
      api
    }
    try {
      authenticatedApi?.logout()
    } catch (error: CancellationException) {
      throw error
    } catch (_: Exception) {
      // Local credentials are already cleared; remote revocation is best effort.
    }
  }

  override suspend fun loadAccount(): GatewayResult<AccountSnapshot> = authenticatedRequest { client ->
    val organizations = client.api.organizations().organizations.map { it.toDomain() }
    val sessions = client.api.sessions().sessions.map { it.toAuthSession() }
    AccountSnapshot(organizations = organizations, sessions = sessions)
  }

  override suspend fun joinInvite(code: String): GatewayResult<Principal> = authenticatedRequest { client ->
    require(code.trim().length >= 8) { "Enter a valid invite code." }
    val response = client.api.joinInvite(mapOf("invite_code" to code.trim()))
    acceptRotatedAuthentication(client, response.token, response.principal)
  }

  override suspend fun switchOrganization(tenantId: String): GatewayResult<Principal> = authenticatedRequest { client ->
    require(tenantId.isNotBlank()) { "Choose an organization." }
    val response = client.api.switchOrganization(mapOf("tenant_id" to tenantId))
    acceptRotatedAuthentication(client, response.token, response.principal)
  }

  override suspend fun changePassword(
    currentPassword: String,
    newPassword: String,
  ): GatewayResult<Unit> = authenticatedRequest { client ->
    require(currentPassword.isNotBlank()) { "Enter your current password." }
    require(newPassword.length >= 10) { "New password must be at least 10 characters." }
    client.api.changePassword(
      mapOf("current_password" to currentPassword, "new_password" to newPassword),
    )
    Unit
  }

  override suspend fun revokeOtherSessions(): GatewayResult<List<AuthSession>> = authenticatedRequest { client ->
    client.api.revokeOtherSessions().sessions.map { it.toAuthSession() }
  }

  override suspend fun loadCatalog(): GatewayResult<UiCatalog> = authenticatedRequest { client ->
    val capabilities = client.api.capabilities()
    val contract = capabilities.uiContract
      ?: error("This Planora server does not publish the ${BuildConfig.UI_CONTRACT_VERSION} UI contract yet.")
    require(contract.version == BuildConfig.UI_CONTRACT_VERSION) {
      "This app requires ${BuildConfig.UI_CONTRACT_VERSION}; the server reports ${contract.version}."
    }
    require(contract.scenarios.isNotEmpty() && contract.modes.isNotEmpty()) {
      "The server returned an empty scheduling catalog."
    }
    UiCatalog(
      contractVersion = contract.version,
      scenarios = contract.scenarios.map {
        CatalogItem(
          it.id,
          it.label,
          if (it.id == "import") "Choose a timetable CSV from this device." else it.description,
          it.recommended,
        )
      },
      modes = contract.modes.map { CatalogItem(it.id, it.label, it.description, it.recommended) },
      tutorial = contract.tutorial.map { TutorialStep(it.id, it.title, it.body) },
      backendId = capabilities.sharedBackend?.backendId.orEmpty(),
    )
  }

  override suspend fun listProjects(): GatewayResult<List<ProjectSummary>> = authenticatedRequest { client ->
    val activeTenant = client.requirePrincipal().tenantId
    ProjectTenantPolicy.visibleToActiveTenant(
      activeTenant,
      client.api.projects().projects.map { it.toDomain() },
    )
  }

  override suspend fun openProject(name: String, tenantId: String): GatewayResult<ScheduleWorkspace> = authenticatedRequest { client ->
    ProjectTenantPolicy.requireOpenAllowed(client.requirePrincipal().tenantId, tenantId)
    val api = client.api
    val project = api.project(name, tenantId)
    val session = api.createSession(
      SessionCreateRequest(project.instance, project.schedule, mapOf("source" to "android-project")),
    )
    WorkspaceMapper.map(
      projectName = name,
      sessionId = session.sessionId,
      instance = session.instance,
      schedule = session.schedule,
    )
  }

  override suspend fun createScenario(scenarioId: String): GatewayResult<ScheduleWorkspace> = authenticatedRequest { client ->
    require(scenarioId != "import") { "Choose a CSV file to import." }
    val api = client.api
    val preset = api.preset(scenarioId)
    val session = api.createSession(SessionCreateRequest(preset.instance))
    WorkspaceMapper.map(
      projectName = preset.mode,
      sessionId = session.sessionId,
      instance = session.instance,
      schedule = session.schedule,
    )
  }

  override suspend fun importCsv(
    filename: String,
    content: String,
    fieldMap: Map<String, String>,
  ): GatewayResult<ScheduleWorkspace> = authenticatedRequest { client ->
    require(content.isNotBlank()) { "The selected file is empty." }
    val api = client.api
    val imported = api.importCsv(ImportCsvRequestDto(filename, content, fieldMap = fieldMap))
    val session = api.createSession(
      SessionCreateRequest(imported.instance, imported.schedule, mapOf("source" to "android-import")),
    )
    WorkspaceMapper.map(
      projectName = filename.substringBeforeLast('.').ifBlank { "Imported schedule" },
      sessionId = session.sessionId,
      instance = session.instance,
      schedule = session.schedule,
      score = imported.score,
      validationErrors = imported.meta.validationErrorsOrNull(),
    )
  }

  override suspend fun startSolve(
    workspace: ScheduleWorkspace,
    modeId: String,
    settings: SolverSettings,
    useAdvancedOverrides: Boolean,
  ): GatewayResult<ScheduleWorkspace> = authenticatedRequest(sessionMayChange = true) { client ->
    val sessionId = workspace.sessionId ?: error("Open or create a schedule first.")
    val overrides = settings.takeIf { useAdvancedOverrides }?.let {
      AdvancedOverridesDto(
        solve = SolveOverridesDto(
          roomMode = it.roomMode,
          objectiveProfile = it.profile,
          timeLimitSeconds = it.timeLimitSeconds.coerceIn(1, 3_600),
          workers = it.workers.coerceIn(1, 64),
          useObjective = it.useObjective,
        ),
      )
    }
    val constraints = settings.takeIf { useAdvancedOverrides }?.let {
      HardConstraintsDto(it.forceRepeatWeeklyPattern)
    }
    val result = client.api.solve(
      sessionId,
      SolveRequestDto(modeId, advancedOverrides = overrides, hardConstraints = constraints),
    ).result
    require(result.hasFeasibleSchedule()) {
      "The scheduler did not produce a feasible timetable. Your previous timetable is unchanged."
    }
    WorkspaceMapper.withSolveResult(workspace, result)
  }

  override suspend fun validate(workspace: ScheduleWorkspace): GatewayResult<ScheduleWorkspace> = authenticatedRequest { client ->
    val sessionId = workspace.sessionId ?: error("Open or create a schedule first.")
    val score = client.api.score(sessionId).result
    val conflicts = score.hardConflicts.orEmpty().distinct()
    workspace.copy(
      hardConflicts = conflicts,
      softPenalty = score.softPenalty,
      validationState = conflicts.validationState(),
    )
  }

  override suspend fun startImprove(
    workspace: ScheduleWorkspace,
    modeId: String,
    settings: SolverSettings,
    useAdvancedOverrides: Boolean,
  ): GatewayResult<JobStatus> = authenticatedRequest(sessionMayChange = true) { client ->
    val sessionId = workspace.sessionId ?: error("Open or create a schedule first.")
    val overrides = settings.takeIf { useAdvancedOverrides }?.let {
      AdvancedOverridesDto(
        improve = ImproveOverridesDto(
          iterations = it.improveIterations.coerceIn(1, 200_000),
          maxSeconds = it.improveSeconds.coerceIn(1, 3_600),
          progressEvery = it.progressEvery.coerceIn(1, 10_000),
        ),
      )
    }
    client.api.improve(ImproveRequestDto(sessionId, modeId, overrides)).toDomain()
  }

  override suspend fun pollJob(
    jobId: String,
    workspace: ScheduleWorkspace,
  ): GatewayResult<Pair<JobStatus, ScheduleWorkspace?>> = authenticatedRequest { client ->
    delay(350)
    val api = client.api
    val job = api.job(jobId)
    val sessionId = workspace.sessionId
    val updated = if (job.status in TERMINAL_JOB_STATUSES && !sessionId.isNullOrBlank()) {
      val session = api.session(sessionId)
      WorkspaceMapper.map(
        projectName = workspace.projectName,
        sessionId = session.sessionId ?: sessionId,
        instance = session.instance,
        schedule = session.schedule,
        score = session.score,
        validationErrors = session.meta.validationErrorsOrNull(),
      )
    } else null
    job.toDomain() to updated
  }

  override suspend fun cancelJob(jobId: String): GatewayResult<JobStatus> = authenticatedRequest { client ->
    client.api.cancelJob(jobId).toDomain()
  }

  override suspend fun exportCsv(workspace: ScheduleWorkspace): GatewayResult<ExportedSchedule> = authenticatedRequest { client ->
    val sessionId = workspace.sessionId ?: error("Open or create a schedule first.")
    val exported = client.api.exportCsv(sessionId).result
    val filename = exported.filename.substringAfterLast('/').substringAfterLast('\\')
      .ifBlank { "planora-schedule.csv" }
    require(exported.content.isNotEmpty()) { "Planora returned an empty CSV export." }
    ExportedSchedule(filename = filename, content = exported.content)
  }

  override suspend fun saveProject(
    name: String,
    workspace: ScheduleWorkspace,
  ): GatewayResult<ProjectSummary> = authenticatedRequest { client ->
    require(name.trim().isNotEmpty()) { "Enter a project name." }
    val sessionId = workspace.sessionId ?: error("Open or create a schedule first.")
    val response = client.api.saveProject(ProjectSaveRequest(name.trim(), sessionId))
    val canonicalName = response.saved.name.trim()
    require(canonicalName.isNotEmpty()) { "Planora saved the project without returning its name." }
    val tenantId = client.requirePrincipal().tenantId
    ProjectSummary(canonicalName, tenantId, System.currentTimeMillis())
  }

  override suspend fun renameProject(
    project: ProjectSummary,
    newName: String,
  ): GatewayResult<ProjectSummary> = authenticatedRequest(sessionMayChange = true) { client ->
    val canonicalName = newName.trim()
    require(canonicalName.isNotEmpty()) { "Enter a new project name." }
    require(canonicalName != project.name) { "Choose a different project name." }
    ProjectTenantPolicy.requireOpenAllowed(client.requirePrincipal().tenantId, project.tenantId)
    val api = client.api
    val stored = api.project(project.name, project.tenantId)
    val session = api.createSession(
      SessionCreateRequest(stored.instance, stored.schedule, mapOf("source" to "android-project-rename")),
    )
    val sessionId = session.sessionId ?: error("Planora could not prepare this project for renaming.")
    val saved = api.saveProject(ProjectSaveRequest(canonicalName, sessionId)).saved
    api.deleteProject(project.name, project.tenantId)
    ProjectSummary(
      name = saved.name,
      tenantId = project.tenantId,
      updatedAt = System.currentTimeMillis(),
      createdBy = project.createdBy,
      storage = saved.storage.orEmpty(),
    )
  }

  override suspend fun deleteProject(project: ProjectSummary): GatewayResult<Unit> = authenticatedRequest { client ->
    ProjectTenantPolicy.requireOpenAllowed(client.requirePrincipal().tenantId, project.tenantId)
    client.api.deleteProject(project.name, project.tenantId)
    Unit
  }

  override suspend fun loadMoveTargets(
    workspace: ScheduleWorkspace,
    event: ScheduleEvent,
    week: Int,
  ): GatewayResult<List<MoveTarget>> = authenticatedRequest { client ->
    val sessionId = workspace.sessionId ?: error("Open or create a schedule first.")
    client.api.moveTargets(sessionId, MoveTargetsRequestDto(event.activityId, week)).result.targets.map {
      MoveTarget(
        week = it.week,
        day = it.day,
        slot = it.slot,
        roomId = it.roomId,
        staffId = it.staffId,
        allowed = it.ok,
        explanation = it.reason.orEmpty(),
      )
    }
  }

  override suspend fun moveEvent(
    workspace: ScheduleWorkspace,
    event: ScheduleEvent,
    target: MoveTarget,
  ): GatewayResult<ScheduleWorkspace> = authenticatedRequest(sessionMayChange = true) { client ->
    require(target.allowed) { "Choose an available move target." }
    val sessionId = workspace.sessionId ?: error("Open or create a schedule first.")
    val result = client.api.move(
      sessionId,
      MoveRequestDto(
        activityId = event.activityId,
        week = target.week,
        day = target.day,
        slot = target.slot,
        roomId = target.roomId,
        staffId = target.staffId,
      ),
    ).result
    require(result.schedule.isNotEmpty()) { "Planora moved the class without returning the updated timetable." }
    val room = target.roomId?.let { id -> workspace.rooms.firstOrNull { it.id == id.toString() }?.label }
    val staff = target.staffId?.let { id -> workspace.staff.firstOrNull { it.id == id.toString() }?.label }
    workspace.copy(
      events = workspace.events.map { current ->
        if (current.activityId == event.activityId && current.week == event.week) {
          current.copy(
            week = target.week,
            day = target.day,
            slot = target.slot,
            room = room ?: current.room,
            staff = staff ?: current.staff,
          )
        } else current
      },
      softPenalty = result.score?.softPenalty ?: workspace.softPenalty,
      hardConflicts = result.score?.hardConflicts ?: workspace.hardConflicts,
      validationState = ValidationState.NOT_VALIDATED,
    )
  }

  override suspend fun loadParity(): GatewayResult<DataRow> = authenticatedRequest { client ->
    client.api.parity().toDataRow()
  }

  override suspend fun loadAccess(): GatewayResult<AccessSnapshot> = authenticatedRequest { client ->
    client.api.access().toAccessSnapshot()
  }

  override suspend fun applyAccessChange(change: Map<String, Any?>): GatewayResult<AccessSnapshot> =
    authenticatedRequest { client -> client.api.applyAccess(change).toAccessSnapshot() }

  override suspend fun loadAdmin(filters: Map<String, String>): GatewayResult<AdminSnapshot> =
    authenticatedRequest { client ->
      val system = client.api.system()
      val status = client.api.systemStatus()
      val analytics = client.api.analytics(filters)
      val audit = client.api.audit(filters)
      AdminSnapshot(
        system = system.toDataRow(),
        status = status.toDataRow(),
        analytics = analytics.toDataRow(),
        auditEvents = audit.arrayRows("events"),
      )
    }

  override suspend fun sendTestEmail(email: String): GatewayResult<Unit> = authenticatedRequest { client ->
    require(email.contains('@')) { "Enter a valid destination email." }
    client.api.sendTestEmail(mapOf("email" to email.trim()))
    Unit
  }

  override suspend fun exportAdminCsv(
    kind: String,
    filters: Map<String, String>,
  ): GatewayResult<ExportedSchedule> = authenticatedRequest { client ->
    val response = when (kind) {
      "analytics" -> client.api.analyticsCsv(filters)
      "audit" -> client.api.auditCsv(filters)
      else -> error("Unknown admin export.")
    }
    val content = response.string()
    require(content.isNotEmpty()) { "Planora returned an empty admin export." }
    ExportedSchedule(
      filename = if (kind == "analytics") "planora-analytics.csv" else "planora-audit.csv",
      content = content,
    )
  }

  override suspend fun updateBaseUrl(value: String): GatewayResult<String> = request {
    refreshMutex.withLock {
      require(canEditBaseUrl()) { "This production build uses the hosted Planora server and cannot change it." }
      val previousOrigin = currentTarget().origin
      val normalized = settingsStore.setBaseUrl(value)
      val nextOrigin = ApiOrigin.fromBaseUrl(normalized)
        ?: error("Enter a valid Planora server address.")
      if (previousOrigin != nextOrigin) clearSession() else invalidateClient()
      normalized
    }
  }

  override fun canEditBaseUrl(): Boolean = BuildConfig.CAN_EDIT_API_BASE_URL

  override fun currentBaseUrl(): String = settingsStore.baseUrl()

  private suspend fun beginAuthenticationAttempt(): LoginAttempt = refreshMutex.withLock {
    val target = currentTarget()
    clearSession()
    LoginAttempt(target, credentialGeneration.get())
  }

  private suspend fun acceptAuthentication(
    attempt: LoginAttempt,
    token: String,
    principalDto: PrincipalDto,
  ): Principal {
    currentCoroutineContext().ensureActive()
    require(token.isNotBlank()) { "Planora authenticated without returning a session token." }
    return refreshMutex.withLock {
      require(
        credentialGeneration.get() == attempt.generation &&
          currentTarget().origin == attempt.target.origin,
      ) { "Authentication was cancelled because the active session changed." }
      tokenStore.save(attempt.target.origin, token)
      val generation = credentialGeneration.incrementAndGet()
      invalidateClient()
      principalDto.toDomain().also { principal ->
        currentPrincipal = PrincipalSnapshot(generation, principal)
      }
    }
  }

  private suspend fun acceptRotatedAuthentication(
    client: AuthenticatedClient,
    token: String,
    principalDto: PrincipalDto,
  ): Principal {
    currentCoroutineContext().ensureActive()
    require(token.isNotBlank()) { "Planora changed the account context without returning a session token." }
    return refreshMutex.withLock {
      require(credentialGeneration.get() == client.generation) {
        "The active session changed while the organization was updating. Please try again."
      }
      val target = currentTarget()
      tokenStore.save(target.origin, token)
      val generation = credentialGeneration.incrementAndGet()
      invalidateClient()
      principalDto.toDomain().also { principal ->
        currentPrincipal = PrincipalSnapshot(generation, principal)
      }
    }
  }

  private suspend fun authenticatedClient(forceRefresh: Boolean = false): AuthenticatedClient {
    val snapshot = credentialSnapshot(forceRefresh)
    if (!snapshot.refreshRequired) return snapshot.toClient()

    return refreshAttemptMutex.withLock {
      val current = credentialSnapshot(forceRefresh)
      if (current.generation != snapshot.generation || current.token != snapshot.token) {
        throw SignInRequiredException("Your session changed while the request was waiting. Please try again.")
      }
      if (!current.refreshRequired) return@withLock current.toClient()

      val refreshed = service(current.target.baseUrl, current.token).refresh()
      currentCoroutineContext().ensureActive()
      require(refreshed.token.isNotBlank()) { "Planora refreshed the session without returning a token." }
      refreshMutex.withLock {
        val unchanged = credentialGeneration.get() == current.generation &&
          currentTarget().origin == current.target.origin &&
          tokenStore.load(current.target.origin) == current.token
        if (!unchanged) {
          throw SignInRequiredException("Your session changed while it was refreshing. Please try again.")
        }
      tokenStore.save(current.target.origin, refreshed.token)
      val generation = credentialGeneration.incrementAndGet()
      val principal = refreshed.principal.toDomain()
      currentPrincipal = PrincipalSnapshot(generation, principal)
      invalidateClient()
      AuthenticatedClient(
        api = service(current.target.baseUrl, refreshed.token),
        generation = generation,
        principal = principal,
      )
      }
    }
  }

  private suspend fun credentialSnapshot(forceRefresh: Boolean): CredentialSnapshot =
    refreshMutex.withLock {
      val target = currentTarget()
      val token = tokenStore.load(target.origin)
      if (token.isBlank()) throw SignInRequiredException("Please sign in to continue.")
      val lifetime = JwtSessionPolicy.classify(token, epochSeconds())
      if (lifetime == JwtLifetime.EXPIRED) {
        throw SignInRequiredException("Your saved session has expired. Please sign in again.")
      }
      CredentialSnapshot(
        target = target,
        token = token,
        generation = credentialGeneration.get(),
        refreshRequired = forceRefresh || lifetime == JwtLifetime.REFRESH,
      )
    }

  private fun CredentialSnapshot.toClient() = AuthenticatedClient(
    api = service(target.baseUrl, token),
    generation = generation,
    principal = currentPrincipal?.takeIf { it.generation == generation }?.principal,
  )

  private fun AuthenticatedClient.requirePrincipal(): Principal =
    requireNotNull(principal) { "Planora could not verify the active university. Please sign in again." }

  private fun service(baseUrl: String, token: String): PlanoraApi {
    val retrofitBaseUrl = "${baseUrl.trimEnd('/')}/"
    val cacheKey = "$retrofitBaseUrl|$token"
    cachedClient?.takeIf { it.key == cacheKey }?.let { return it.api }
    return synchronized(this) {
      cachedClient?.takeIf { it.key == cacheKey }?.api ?: buildApi(retrofitBaseUrl, token).also {
        cachedClient = CachedClient(cacheKey, it)
      }
    }
  }

  private fun buildApi(
    baseUrl: String,
    token: String,
    readTimeoutSeconds: Long = 180,
  ): PlanoraApi {
    val client = OkHttpClient.Builder()
      .connectTimeout(20, TimeUnit.SECONDS)
      .readTimeout(readTimeoutSeconds, TimeUnit.SECONDS)
      .writeTimeout(60, TimeUnit.SECONDS)
      .addInterceptor { chain ->
        val request = chain.request().newBuilder()
          .header("Accept", "application/json")
          .apply { if (token.isNotBlank()) header("Authorization", "Bearer $token") }
          .build()
        chain.proceed(request)
      }
      .apply {
        if (BuildConfig.DEBUG) {
          addInterceptor(
            HttpLoggingInterceptor().apply {
              level = HttpLoggingInterceptor.Level.BASIC
              redactHeader("Authorization")
            },
          )
        }
      }
      .build()
    return Retrofit.Builder()
      .baseUrl(baseUrl)
      .client(client)
      .addConverterFactory(GsonConverterFactory.create(GsonBuilder().create()))
      .build()
      .create(PlanoraApi::class.java)
  }

  private fun currentTarget(): ApiTarget {
    val baseUrl = settingsStore.baseUrl()
    val origin = ApiOrigin.fromBaseUrl(baseUrl)
      ?: error("The configured Planora server address is invalid.")
    return ApiTarget(baseUrl, origin)
  }

  private fun clearSession() {
    tokenStore.clear()
    currentPrincipal = null
    credentialGeneration.incrementAndGet()
    invalidateClient()
  }

  private suspend fun clearSessionIfCurrent(requestGeneration: Long): Boolean =
    refreshMutex.withLock {
      if (credentialGeneration.get() != requestGeneration) return@withLock false
      clearSession()
      true
    }

  private fun invalidateClient() {
    cachedClient = null
  }

  private suspend fun <T> authenticatedRequest(
    sessionMayChange: Boolean = false,
    block: suspend (AuthenticatedClient) -> T,
  ): GatewayResult<T> {
    var requestCredentialGeneration = credentialGeneration.get()
    return request(
      authenticated = true,
      sessionMayChange = sessionMayChange,
      credentialGenerationAtFailure = { requestCredentialGeneration },
    ) {
      val client = authenticatedClient()
      requestCredentialGeneration = client.generation
      block(client)
    }
  }

  private suspend fun <T> request(
    authenticated: Boolean = false,
    loginAttempt: Boolean = false,
    sessionMayChange: Boolean = false,
    credentialGenerationAtFailure: (() -> Long)? = null,
    block: suspend () -> T,
  ): GatewayResult<T> {
    val initialCredentialGeneration = credentialGeneration.get()
    fun failedCredentialGeneration(): Long =
      credentialGenerationAtFailure?.invoke() ?: initialCredentialGeneration
    return try {
      val value = block()
      currentCoroutineContext().ensureActive()
      GatewayResult.Success(value)
    } catch (error: CancellationException) {
      throw error
    } catch (error: SignInRequiredException) {
      currentCoroutineContext().ensureActive()
      val rejectedCurrentCredential = clearSessionIfCurrent(failedCredentialGeneration())
      GatewayResult.Failure(
        message = if (rejectedCurrentCredential) {
          error.message.orEmpty().ifBlank { "Please sign in to continue." }
        } else {
          "Your session changed while the request was running. Please try again."
        },
        retryable = !rejectedCurrentCredential,
        requiresSignIn = rejectedCurrentCredential,
      )
    } catch (error: HttpException) {
      val serverMessage = safeServerMessage(error)
      val credentialRejected = authenticated && (
        error.code() == 401 || (error.code() == 403 && isRevokedSessionMessage(serverMessage))
      )
      currentCoroutineContext().ensureActive()
      val requiresSignIn = credentialRejected && clearSessionIfCurrent(failedCredentialGeneration())
      val staleCredentialResponse = credentialRejected && !requiresSignIn
      val message = when {
        loginAttempt && error.code() in setOf(401, 403) ->
          serverMessage.ifBlank { "Email or password is incorrect." }
        staleCredentialResponse -> "Your session changed while the request was running. Please try again."
        requiresSignIn -> "Your sign-in is no longer valid. Please sign in again."
        error.code() == 401 -> "Please sign in to continue."
        error.code() == 403 -> "Your account does not have permission for that action."
        error.code() == 409 -> "The schedule changed elsewhere. Refresh and try again."
        error.code() == 429 -> "The scheduler is busy. Please try again shortly."
        else -> serverMessage.ifBlank { "Planora returned ${error.code()}. Please try again." }
      }
      GatewayResult.Failure(
        message = message,
        retryable = staleCredentialResponse || error.code() >= 500 || error.code() == 429,
        requiresSignIn = requiresSignIn,
        sessionStateUnknown = sessionMayChange && error.code() >= 500,
      )
    } catch (_: IOException) {
      currentCoroutineContext().ensureActive()
      GatewayResult.Failure(
        "Planora could not reach the server. Check your connection and server address.",
        retryable = true,
        sessionStateUnknown = sessionMayChange,
      )
    } catch (error: Exception) {
      currentCoroutineContext().ensureActive()
      GatewayResult.Failure(error.message ?: "Planora could not complete that action.")
    }
  }

  private data class CachedClient(val key: String, val api: PlanoraApi)
  private data class AuthenticatedClient(
    val api: PlanoraApi,
    val generation: Long,
    val principal: Principal?,
  )
  private data class CredentialSnapshot(
    val target: ApiTarget,
    val token: String,
    val generation: Long,
    val refreshRequired: Boolean,
  )
  private data class LoginAttempt(val target: ApiTarget, val generation: Long)
  private data class PrincipalSnapshot(val generation: Long, val principal: Principal)
  private data class ApiTarget(val baseUrl: String, val origin: String)
  private class SignInRequiredException(message: String) : IllegalStateException(message)

  private companion object {
    val TERMINAL_JOB_STATUSES = setOf("complete", "failed", "cancelled")
  }
}

internal object WorkspaceMapper {
  private val gson = GsonBuilder().create()

  fun map(
    projectName: String,
    sessionId: String?,
    instance: JsonObject,
    schedule: Map<String, ScheduleRowDto>,
    score: ScoreResultDto? = null,
    validationErrors: List<String>? = null,
  ): ScheduleWorkspace {
    val displayInstance = gson.fromJson(instance, InstanceDto::class.java)
    val conflicts = (score?.hardConflicts.orEmpty() + validationErrors.orEmpty()).distinct()
    val hasValidationEvidence = score != null || validationErrors != null
    return ScheduleWorkspace(
      projectName = projectName.replace('_', ' ').replaceFirstChar { it.uppercase() },
      days = displayInstance.days.ifEmpty { listOf("MON", "TUE", "WED", "THU", "FRI") },
      weeks = displayInstance.weeks.ifEmpty { listOf(1) },
      slotsPerDay = displayInstance.slotsPerDay.coerceAtLeast(1),
      events = schedule.mapNotNull { (id, row) -> event(id, row, displayInstance) }
        .sortedWith(compareBy<ScheduleEvent> { it.week }.thenBy { it.day }.thenBy { it.slot }),
      programs = displayInstance.programs.values.resources(),
      groups = displayInstance.groups.values.resources(),
      courses = displayInstance.courses.values.resources(),
      staff = displayInstance.staff.values.resources(),
      rooms = displayInstance.rooms.values.resources { value ->
        listOfNotNull(value.roomType, value.capacity?.let { "$it seats" }).joinToString(" · ")
      },
      hardConflicts = conflicts,
      softPenalty = score?.softPenalty,
      sessionId = sessionId,
      validationState = if (hasValidationEvidence) conflicts.validationState() else ValidationState.NOT_VALIDATED,
    )
  }

  fun map(
    projectName: String,
    sessionId: String?,
    instance: InstanceDto,
    schedule: Map<String, ScheduleRowDto>,
    score: ScoreResultDto? = null,
    validationErrors: List<String>? = null,
  ): ScheduleWorkspace = map(
    projectName,
    sessionId,
    gson.toJsonTree(instance).asJsonObject,
    schedule,
    score,
    validationErrors,
  )

  fun withSolveResult(workspace: ScheduleWorkspace, result: SolverResultDto): ScheduleWorkspace {
    require(result.hasFeasibleSchedule()) { "The solve result is not a feasible timetable." }
    val resultConflicts = result.hardConflicts
    return workspace.copy(
      events = mappedEvents(workspace, result.schedule),
      hardConflicts = resultConflicts?.distinct() ?: workspace.hardConflicts,
      softPenalty = null,
      validationState = resultConflicts?.distinct()?.validationState() ?: ValidationState.NOT_VALIDATED,
    )
  }

  fun withImproveResult(workspace: ScheduleWorkspace, result: SolverResultDto): ScheduleWorkspace {
    require(result.schedule.isNotEmpty()) {
      "The improvement completed without returning a timetable. Your previous timetable is unchanged."
    }
    val score = result.scoreAfter()
    val conflicts = score?.hardConflicts.orEmpty().distinct()
    return workspace.copy(
      events = mappedEvents(workspace, result.schedule),
      hardConflicts = if (score != null) conflicts else workspace.hardConflicts,
      softPenalty = if (score != null) score.softPenalty else workspace.softPenalty,
      validationState = if (score != null) conflicts.validationState() else workspace.validationState,
    )
  }

  private fun mappedEvents(
    workspace: ScheduleWorkspace,
    schedule: Map<String, ScheduleRowDto>,
  ): List<ScheduleEvent> {
    val courseById = workspace.courses.associateBy { it.id.toIntOrNull() }
    val staffById = workspace.staff.associateBy { it.id.toIntOrNull() }
    val roomById = workspace.rooms.associateBy { it.id.toIntOrNull() }
    val groupById = workspace.groups.associateBy { it.id.toIntOrNull() }
    return schedule.mapNotNull { (activityId, row) ->
      val id = activityId.toIntOrNull() ?: return@mapNotNull null
      val course = courseById[row.courseId]
      ScheduleEvent(
        activityId = id,
        title = course?.label ?: "Activity $id",
        code = course?.secondary.orEmpty().ifBlank { "A$id" },
        kind = row.kind ?: "Class",
        week = row.week,
        day = row.day,
        slot = row.slot,
        duration = row.duration.coerceAtLeast(1),
        room = roomById[row.roomId]?.label ?: "Room pending",
        staff = staffById[row.staffId]?.label ?: "Staff pending",
        groups = row.groupIds.map { groupById[it]?.label ?: "Group $it" },
      )
    }.sortedWith(compareBy<ScheduleEvent> { it.week }.thenBy { it.day }.thenBy { it.slot })
  }

  private fun event(id: String, row: ScheduleRowDto, instance: InstanceDto): ScheduleEvent? {
    val activityId = id.toIntOrNull() ?: return null
    val activity = instance.activities[id]
    val courseId = row.courseId ?: activity?.courseId
    val course = instance.courses[courseId?.toString()]
    val staffId = row.staffId ?: activity?.taId ?: activity?.professorId
    return ScheduleEvent(
      activityId = activityId,
      title = course?.name ?: "Activity $activityId",
      code = course?.code ?: "A$activityId",
      kind = row.kind ?: activity?.kind ?: "Class",
      week = row.week,
      day = row.day,
      slot = row.slot,
      duration = row.duration.coerceAtLeast(1),
      room = instance.rooms[row.roomId?.toString()]?.name ?: "Room pending",
      staff = instance.staff[staffId?.toString()]?.name ?: "Staff pending",
      groups = row.groupIds.map { instance.groups[it.toString()]?.name ?: "Group $it" },
    )
  }

  private fun Collection<NamedDto>.resources(
    secondary: (NamedDto) -> String = { it.code.orEmpty() },
  ): List<AcademicResource> = map {
    AcademicResource(it.id.toString(), it.name, secondary(it))
  }.sortedBy { it.label }
}

internal fun JsonObject?.validationErrorsOrNull(): List<String>? {
  val element = this?.get("validation_errors") ?: return null
  if (!element.isJsonArray) return null
  val errors = mutableListOf<String>()
  for (item in element.asJsonArray) {
    if (!item.isJsonPrimitive || !item.asJsonPrimitive.isString) return null
    item.asString.trim().takeIf { it.isNotEmpty() }?.let(errors::add)
  }
  return errors.distinct()
}

private fun List<String>.validationState(): ValidationState =
  if (isEmpty()) ValidationState.VALID else ValidationState.INVALID

private fun PrincipalDto.toDomain() = Principal(
  userId = userId,
  displayName = displayName?.takeIf { it.isNotBlank() } ?: userId.substringBefore('@'),
  role = role,
  tenantId = tenantId,
  permissions = permissions.orEmpty().toSet(),
  isGlobalAdmin = isGlobalAdmin,
  groups = groups.orEmpty(),
)

private fun OrganizationMembershipDto.toDomain() = OrganizationMembership(
  tenantId = tenantId,
  displayName = displayName?.ifBlank { tenantId } ?: tenantId,
  role = role,
  enabled = enabled,
  active = active,
  groupCount = groupCount,
)

private fun JsonObject.toAuthSession() = AuthSession(
  sessionId = stringValue("session_id"),
  current = booleanValue("current"),
  active = booleanValue("active"),
  lastSeenAt = longValue("last_seen_at"),
)

private fun ProjectSummaryDto.toDomain() = ProjectSummary(
  name = name,
  tenantId = tenantId.orEmpty(),
  updatedAt = updatedAt?.times(1000)?.toLong(),
  createdBy = createdBy.orEmpty(),
  storage = storage.orEmpty(),
)

private fun JsonObject.toAccessSnapshot() = AccessSnapshot(
  users = arrayRows("users"),
  groups = arrayRows("groups"),
  memberships = arrayRows("memberships"),
  roleBindings = arrayRows("role_bindings"),
  inviteCodes = arrayRows("invite_codes"),
  accountTenants = arrayRows("account_tenants"),
  newInviteCode = stringValue("new_invite_code"),
)

private fun JsonObject.arrayRows(key: String): List<DataRow> {
  val value = get(key) ?: return emptyList()
  if (!value.isJsonArray) return emptyList()
  return value.asJsonArray.mapNotNull { element ->
    element.takeIf { it.isJsonObject }?.asJsonObject?.toDataRow()
  }
}

private fun JsonObject.toDataRow(): DataRow = DataRow(
  entrySet().associate { (key, value) -> key to value.toDisplayString() },
)

private fun com.google.gson.JsonElement.toDisplayString(): String = when {
  isJsonNull -> ""
  isJsonPrimitive -> asJsonPrimitive.let { value ->
    when {
      value.isBoolean -> value.asBoolean.toString()
      value.isNumber -> value.asNumber.toString()
      else -> value.asString
    }
  }
  isJsonArray -> asJsonArray.joinToString(", ") { it.toDisplayString() }.take(320)
  else -> toString().take(320)
}

private fun JsonObject.stringValue(key: String): String =
  get(key)?.takeIf { it.isJsonPrimitive }?.asString.orEmpty()

private fun JsonObject.booleanValue(key: String): Boolean =
  get(key)?.takeIf { it.isJsonPrimitive }?.asBoolean ?: false

private fun JsonObject.longValue(key: String): Long =
  get(key)?.takeIf { it.isJsonPrimitive }?.asDouble?.toLong() ?: 0L

private fun JobDto.toDomain(): JobStatus {
  val iteration = progress?.get("iteration")?.asFloat
  val iterations = progress?.get("iterations")?.asFloat
  val ratio = if (iteration != null && iterations != null && iterations > 0f) iteration / iterations else null
  val message = when (status) {
    "queued" -> "Waiting for an available scheduler"
    "running" -> "Improving the timetable"
    "complete" -> "Improvement complete"
    "failed" -> error ?: "Improvement failed"
    "cancelled" -> "Improvement cancelled"
    else -> status.replace('_', ' ')
  }
  return JobStatus(jobId, status, message, ratio)
}

private fun safeServerMessage(error: HttpException): String {
  val raw = runCatching {
    error.response()?.errorBody()?.string()?.let { body ->
      val parsed = JsonParser.parseString(body)
      parsed.takeIf { it.isJsonObject }
        ?.asJsonObject
        ?.get("error")
        ?.takeIf { it.isJsonPrimitive && it.asJsonPrimitive.isString }
        ?.asString
    }
  }.getOrNull().orEmpty()
  val cleaned = raw.replace(Regex("[\\p{Cc}&&[^\\r\\n\\t]]"), " ")
    .replace(Regex("\\s+"), " ")
    .trim()
    .take(240)
  return if (SENSITIVE_VALUE_PATTERN.containsMatchIn(cleaned)) "" else cleaned
}

internal fun isRevokedSessionMessage(message: String): Boolean {
  val normalized = message.lowercase()
  return "session" in normalized && (
    "expired" in normalized || "revoked" in normalized || "not active" in normalized
  )
}

private val SENSITIVE_VALUE_PATTERN =
  Regex("(?i)\\b(?:password|token|secret|authorization)\\s*[:=]\\s*[^\\s,;]+")
