package com.planora.mobile.domain

interface PlanoraGateway {
  suspend fun hasSession(): Boolean
  suspend fun loadAuthConfig(): GatewayResult<AuthConfig>
  suspend fun login(email: String, password: String): GatewayResult<Principal>
  suspend fun register(email: String, password: String, displayName: String): GatewayResult<RegistrationResult>
  suspend fun verifyEmail(email: String, code: String): GatewayResult<Principal>
  suspend fun forgotPassword(email: String): GatewayResult<String?>
  suspend fun resetPassword(email: String, code: String, newPassword: String): GatewayResult<Principal>
  suspend fun restoreSession(): GatewayResult<Principal>
  suspend fun logout()
  suspend fun loadAccount(): GatewayResult<AccountSnapshot>
  suspend fun joinInvite(code: String): GatewayResult<Principal>
  suspend fun switchOrganization(tenantId: String): GatewayResult<Principal>
  suspend fun changePassword(currentPassword: String, newPassword: String): GatewayResult<Unit>
  suspend fun revokeOtherSessions(): GatewayResult<List<AuthSession>>
  suspend fun loadCatalog(): GatewayResult<UiCatalog>
  suspend fun listProjects(): GatewayResult<List<ProjectSummary>>
  suspend fun openProject(name: String, tenantId: String): GatewayResult<ScheduleWorkspace>
  suspend fun createScenario(scenarioId: String): GatewayResult<ScheduleWorkspace>
  suspend fun importCsv(
    filename: String,
    content: String,
    fieldMap: Map<String, String> = emptyMap(),
  ): GatewayResult<ScheduleWorkspace>
  suspend fun startSolve(
    workspace: ScheduleWorkspace,
    modeId: String,
    settings: SolverSettings = SolverSettings(),
    useAdvancedOverrides: Boolean = false,
  ): GatewayResult<ScheduleWorkspace>
  suspend fun validate(workspace: ScheduleWorkspace): GatewayResult<ScheduleWorkspace>
  suspend fun startImprove(
    workspace: ScheduleWorkspace,
    modeId: String,
    settings: SolverSettings = SolverSettings(),
    useAdvancedOverrides: Boolean = false,
  ): GatewayResult<JobStatus>
  suspend fun pollJob(jobId: String, workspace: ScheduleWorkspace): GatewayResult<Pair<JobStatus, ScheduleWorkspace?>>
  suspend fun cancelJob(jobId: String): GatewayResult<JobStatus>
  suspend fun exportCsv(workspace: ScheduleWorkspace): GatewayResult<ExportedSchedule>
  suspend fun saveProject(name: String, workspace: ScheduleWorkspace): GatewayResult<ProjectSummary>
  suspend fun renameProject(project: ProjectSummary, newName: String): GatewayResult<ProjectSummary>
  suspend fun deleteProject(project: ProjectSummary): GatewayResult<Unit>
  suspend fun loadMoveTargets(workspace: ScheduleWorkspace, event: ScheduleEvent, week: Int): GatewayResult<List<MoveTarget>>
  suspend fun moveEvent(workspace: ScheduleWorkspace, event: ScheduleEvent, target: MoveTarget): GatewayResult<ScheduleWorkspace>
  suspend fun loadParity(): GatewayResult<DataRow>
  suspend fun loadAccess(): GatewayResult<AccessSnapshot>
  suspend fun applyAccessChange(change: Map<String, Any?>): GatewayResult<AccessSnapshot>
  suspend fun loadAdmin(filters: Map<String, String> = emptyMap()): GatewayResult<AdminSnapshot>
  suspend fun sendTestEmail(email: String): GatewayResult<Unit>
  suspend fun exportAdminCsv(kind: String, filters: Map<String, String> = emptyMap()): GatewayResult<ExportedSchedule>
  suspend fun updateBaseUrl(value: String): GatewayResult<String>
  fun canEditBaseUrl(): Boolean
  fun currentBaseUrl(): String
}
