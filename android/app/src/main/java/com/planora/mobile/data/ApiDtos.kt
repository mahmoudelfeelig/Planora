package com.planora.mobile.data

import com.google.gson.JsonObject
import com.google.gson.annotations.SerializedName

data class LoginRequest(val email: String, val password: String)

data class RegisterRequest(
  val email: String,
  val password: String,
  @SerializedName("display_name") val displayName: String,
)

data class AuthConfigDto(
  @SerializedName("registration_enabled") val registrationEnabled: Boolean = true,
  @SerializedName("email_verification_required") val emailVerificationRequired: Boolean = true,
  @SerializedName("smtp_configured") val smtpConfigured: Boolean = false,
)

data class RegistrationResponseDto(
  val token: String? = null,
  val principal: PrincipalDto? = null,
  @SerializedName("email_verification_required") val verificationRequired: Boolean = true,
  @SerializedName("verification_code") val verificationCode: String? = null,
)

data class VerifyEmailRequest(
  val email: String,
  val code: String,
  val token: String = code,
)

data class ForgotPasswordRequest(val email: String)

data class ForgotPasswordResponseDto(
  @SerializedName("reset_code") val resetCode: String? = null,
)

data class ResetPasswordRequest(
  val email: String,
  val code: String,
  val token: String = code,
  @SerializedName("new_password") val newPassword: String,
)

data class LoginResponseDto(
  val token: String,
  val principal: PrincipalDto,
)

data class PrincipalDto(
  @SerializedName("user_id") val userId: String,
  @SerializedName("display_name") val displayName: String? = null,
  val role: String,
  @SerializedName("tenant_id") val tenantId: String,
  val permissions: List<String> = emptyList(),
  @SerializedName("is_global_admin") val isGlobalAdmin: Boolean = false,
  val groups: List<String> = emptyList(),
)

data class OrganizationMembershipDto(
  @SerializedName("tenant_id") val tenantId: String,
  @SerializedName("display_name") val displayName: String? = null,
  val role: String,
  val enabled: Boolean = true,
  val active: Boolean = false,
  @SerializedName("group_count") val groupCount: Int = 0,
)

data class OrganizationsDto(val organizations: List<OrganizationMembershipDto> = emptyList())

data class SessionsDto(val sessions: List<JsonObject> = emptyList())

data class AuthenticatedAccountDto(
  val token: String,
  val principal: PrincipalDto,
  val organizations: List<OrganizationMembershipDto> = emptyList(),
)

data class CatalogEntryDto(
  val id: String,
  val label: String,
  val description: String = "",
  val recommended: Boolean = false,
)

data class TutorialStepDto(
  val id: String,
  val title: String,
  val body: String = "",
)

data class UiContractDto(
  @SerializedName("contract_version") val version: String,
  val scenarios: List<CatalogEntryDto> = emptyList(),
  @SerializedName("run_modes") val modes: List<CatalogEntryDto> = emptyList(),
  val tutorial: List<TutorialStepDto> = emptyList(),
)

data class BackendContractDto(
  @SerializedName("backend_id") val backendId: String = "unknown",
)

data class CapabilitiesDto(
  val actions: List<String> = emptyList(),
  @SerializedName("shared_backend") val sharedBackend: BackendContractDto? = null,
  @SerializedName("ui_contract") val uiContract: UiContractDto? = null,
)

data class ProjectsDto(val projects: List<ProjectSummaryDto> = emptyList())

data class ProjectSummaryDto(
  val name: String,
  @SerializedName("tenant_id") val tenantId: String? = null,
  @SerializedName("updated_at") val updatedAt: Double? = null,
  @SerializedName("created_by") val createdBy: String? = null,
  val storage: String? = null,
)

data class NamedDto(
  val id: Int,
  val name: String,
  val code: String? = null,
  val capacity: Int? = null,
  @SerializedName("room_type") val roomType: String? = null,
)

data class ActivityDto(
  val id: Int,
  @SerializedName("course_id") val courseId: Int,
  val week: Int,
  val kind: String,
  val duration: Int,
  @SerializedName("group_ids") val groupIds: List<Int> = emptyList(),
  @SerializedName("prof_id") val professorId: Int? = null,
  @SerializedName("ta_id") val taId: Int? = null,
)

data class InstanceDto(
  val days: List<String> = emptyList(),
  val weeks: List<Int> = emptyList(),
  @SerializedName("slots_per_day") val slotsPerDay: Int = 0,
  val programs: Map<String, NamedDto> = emptyMap(),
  val groups: Map<String, NamedDto> = emptyMap(),
  val courses: Map<String, NamedDto> = emptyMap(),
  val staff: Map<String, NamedDto> = emptyMap(),
  val rooms: Map<String, NamedDto> = emptyMap(),
  val activities: Map<String, ActivityDto> = emptyMap(),
)

data class ScheduleRowDto(
  @SerializedName("room_id") val roomId: Int? = null,
  @SerializedName("staff_id") val staffId: Int? = null,
  val week: Int = 1,
  val day: String = "MON",
  val slot: Int = 0,
  val duration: Int = 1,
  @SerializedName("group_ids") val groupIds: List<Int> = emptyList(),
  @SerializedName("course_id") val courseId: Int? = null,
  val kind: String? = null,
)

data class WorkspaceDto(
  @SerializedName("session_id") val sessionId: String? = null,
  val name: String? = null,
  val instance: JsonObject,
  val schedule: Map<String, ScheduleRowDto> = emptyMap(),
  val meta: JsonObject? = null,
  val score: ScoreResultDto? = null,
)

data class SessionCreateRequest(
  val instance: JsonObject,
  val schedule: Map<String, ScheduleRowDto> = emptyMap(),
  val meta: Map<String, String> = mapOf("source" to "android"),
)

data class PresetDto(
  val mode: String,
  val instance: JsonObject,
)

data class SolveOverridesDto(
  @SerializedName("room_mode") val roomMode: String,
  @SerializedName("objective_profile") val objectiveProfile: String,
  @SerializedName("time_limit_seconds") val timeLimitSeconds: Int,
  val workers: Int,
  @SerializedName("use_objective") val useObjective: Boolean,
)

data class ImproveOverridesDto(
  val iterations: Int,
  @SerializedName("max_seconds") val maxSeconds: Int,
  @SerializedName("progress_every") val progressEvery: Int,
)

data class AdvancedOverridesDto(
  val solve: SolveOverridesDto? = null,
  val improve: ImproveOverridesDto? = null,
)

data class HardConstraintsDto(
  @SerializedName("force_repeat_weekly_pattern") val forceRepeatWeeklyPattern: Boolean,
)

data class SolveRequestDto(
  @SerializedName("run_mode") val runMode: String,
  @SerializedName("advanced_overrides") val advancedOverrides: AdvancedOverridesDto? = null,
  @SerializedName("hard_constraints") val hardConstraints: HardConstraintsDto? = null,
)

data class ImportCsvRequestDto(
  val filename: String,
  val content: String,
  @SerializedName("field_map") val fieldMap: Map<String, String> = emptyMap(),
  @SerializedName("lock_imported") val lockImported: Boolean = false,
)

data class ImproveRequestDto(
  @SerializedName("session_id") val sessionId: String,
  @SerializedName("run_mode") val runMode: String,
  @SerializedName("advanced_overrides") val advancedOverrides: AdvancedOverridesDto? = null,
)

data class MoveTargetsRequestDto(
  @SerializedName("activity_id") val activityId: Int,
  val week: Int,
  val limit: Int = 60,
)

data class MoveTargetDto(
  val week: Int = 1,
  val day: String = "MON",
  val slot: Int = 0,
  @SerializedName("room_id") val roomId: Int? = null,
  @SerializedName("staff_id") val staffId: Int? = null,
  val ok: Boolean = false,
  val reason: String? = null,
)

data class MoveTargetsResultDto(val targets: List<MoveTargetDto> = emptyList())
data class MoveTargetsActionDto(val result: MoveTargetsResultDto)

data class MoveRequestDto(
  @SerializedName("activity_id") val activityId: Int,
  val week: Int,
  val day: String,
  val slot: Int,
  @SerializedName("room_id") val roomId: Int?,
  @SerializedName("staff_id") val staffId: Int?,
  @SerializedName("enforce_hard_conflict_free") val enforceHardConflictFree: Boolean = true,
)

data class MoveResultDto(
  val schedule: Map<String, ScheduleRowDto> = emptyMap(),
  val score: ScoreResultDto? = null,
)

data class MoveActionDto(val result: MoveResultDto)

data class SolverResultDto(
  val status: Int? = null,
  @SerializedName("raw_status") val rawStatus: Int? = null,
  val schedule: Map<String, ScheduleRowDto> = emptyMap(),
  @SerializedName("hard_conflicts") val hardConflicts: List<String>? = null,
  val meta: JsonObject? = null,
  @SerializedName("global_after") val globalAfter: ScoreResultDto? = null,
  val after: ScoreResultDto? = null,
)

data class SessionActionDto(val result: SolverResultDto)

data class ScoreResultDto(
  @SerializedName("soft_penalty") val softPenalty: Int? = null,
  @SerializedName("hard_conflicts") val hardConflicts: List<String>? = null,
)

data class ScoreActionDto(val result: ScoreResultDto)

data class JobDto(
  @SerializedName("job_id") val jobId: String,
  val status: String,
  val progress: JsonObject? = null,
  val result: SolverResultDto? = null,
  val error: String? = null,
)

data class ProjectSaveRequest(
  val name: String,
  @SerializedName("session_id") val sessionId: String,
)

data class SavedProjectDto(
  val name: String,
  val storage: String? = null,
)

data class ProjectSaveResponseDto(
  val saved: SavedProjectDto,
)

data class ExportCsvRequestDto(
  val filename: String = "planora-schedule.csv",
)

data class ExportResultDto(
  val filename: String,
  val content: String,
  @SerializedName("content_type") val contentType: String? = null,
)

data class ExportActionDto(val result: ExportResultDto)

internal fun SolverResultDto.hasFeasibleSchedule(): Boolean =
  rawStatus in setOf(2, 4) && schedule.isNotEmpty()

internal fun SolverResultDto.scoreAfter(): ScoreResultDto? = globalAfter ?: after
