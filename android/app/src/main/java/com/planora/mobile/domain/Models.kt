package com.planora.mobile.domain

data class Principal(
  val userId: String,
  val displayName: String,
  val role: String,
  val tenantId: String,
  val permissions: Set<String>,
  val isGlobalAdmin: Boolean = false,
  val groups: List<String> = emptyList(),
) {
  val canRunSolver: Boolean get() = "solver:run" in permissions
  val canWriteSchedule: Boolean get() = "schedule:write" in permissions || canRunSolver
  val canWriteProjects: Boolean get() = "projects:write" in permissions
}

data class CatalogItem(
  val id: String,
  val label: String,
  val description: String,
  val recommended: Boolean = false,
)

data class TutorialStep(
  val id: String,
  val title: String,
  val body: String,
)

data class UiCatalog(
  val contractVersion: String,
  val scenarios: List<CatalogItem>,
  val modes: List<CatalogItem>,
  val tutorial: List<TutorialStep>,
  val backendId: String,
)

data class ProjectSummary(
  val name: String,
  val tenantId: String,
  val updatedAt: Long?,
  val createdBy: String = "",
  val storage: String = "",
)

data class AuthConfig(
  val registrationEnabled: Boolean = true,
  val emailVerificationRequired: Boolean = true,
  val smtpConfigured: Boolean = false,
)

data class RegistrationResult(
  val signedInPrincipal: Principal? = null,
  val verificationRequired: Boolean = true,
  val developmentCode: String? = null,
)

data class OrganizationMembership(
  val tenantId: String,
  val displayName: String,
  val role: String,
  val enabled: Boolean,
  val active: Boolean,
  val groupCount: Int,
)

data class AuthSession(
  val sessionId: String,
  val current: Boolean,
  val active: Boolean,
  val lastSeenAt: Long,
)

data class AccountSnapshot(
  val organizations: List<OrganizationMembership> = emptyList(),
  val sessions: List<AuthSession> = emptyList(),
)

data class MoveTarget(
  val week: Int,
  val day: String,
  val slot: Int,
  val roomId: Int?,
  val staffId: Int?,
  val allowed: Boolean,
  val explanation: String = "",
)

data class SolverSettings(
  val roomMode: String = "greedy",
  val profile: String = "balanced",
  val timeLimitSeconds: Int = 60,
  val workers: Int = 4,
  val useObjective: Boolean = true,
  val forceRepeatWeeklyPattern: Boolean = false,
  val improveIterations: Int = 2_000,
  val improveSeconds: Int = 30,
  val progressEvery: Int = 100,
)

data class DataRow(val values: Map<String, String>) {
  operator fun get(key: String): String = values[key].orEmpty()
}

data class AccessSnapshot(
  val users: List<DataRow> = emptyList(),
  val groups: List<DataRow> = emptyList(),
  val memberships: List<DataRow> = emptyList(),
  val roleBindings: List<DataRow> = emptyList(),
  val inviteCodes: List<DataRow> = emptyList(),
  val accountTenants: List<DataRow> = emptyList(),
  val newInviteCode: String = "",
)

data class AdminSnapshot(
  val system: DataRow = DataRow(emptyMap()),
  val status: DataRow = DataRow(emptyMap()),
  val analytics: DataRow = DataRow(emptyMap()),
  val auditEvents: List<DataRow> = emptyList(),
)

data class AcademicResource(
  val id: String,
  val label: String,
  val secondary: String = "",
)

data class ScheduleEvent(
  val activityId: Int,
  val title: String,
  val code: String,
  val kind: String,
  val week: Int,
  val day: String,
  val slot: Int,
  val duration: Int,
  val room: String,
  val staff: String,
  val groups: List<String>,
)

enum class ValidationState {
  NOT_VALIDATED,
  VALID,
  INVALID,
}

data class ScheduleWorkspace(
  val projectName: String,
  val days: List<String>,
  val weeks: List<Int>,
  val slotsPerDay: Int,
  val events: List<ScheduleEvent>,
  val programs: List<AcademicResource>,
  val groups: List<AcademicResource>,
  val courses: List<AcademicResource>,
  val staff: List<AcademicResource>,
  val rooms: List<AcademicResource>,
  val hardConflicts: List<String> = emptyList(),
  val softPenalty: Int? = null,
  val sessionId: String? = null,
  val validationState: ValidationState = ValidationState.NOT_VALIDATED,
)

data class ExportedSchedule(
  val filename: String,
  val content: String,
)

data class JobStatus(
  val id: String,
  val status: String,
  val message: String,
  val progress: Float?,
)

sealed interface GatewayResult<out T> {
  data class Success<T>(val value: T) : GatewayResult<T>
  data class Failure(
    val message: String,
    val retryable: Boolean = false,
    val requiresSignIn: Boolean = false,
    val sessionStateUnknown: Boolean = false,
  ) : GatewayResult<Nothing>
}
