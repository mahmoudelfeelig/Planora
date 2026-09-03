package com.planora.mobile.data

import com.google.gson.JsonObject
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.QueryMap
import okhttp3.ResponseBody

interface PlanoraApi {
  @GET("auth/config")
  suspend fun authConfig(): AuthConfigDto

  @POST("auth/login")
  suspend fun login(@Body request: LoginRequest): LoginResponseDto

  @POST("auth/register")
  suspend fun register(@Body request: RegisterRequest): RegistrationResponseDto

  @POST("auth/verify")
  suspend fun verifyEmail(@Body request: VerifyEmailRequest): LoginResponseDto

  @POST("auth/forgot-password")
  suspend fun forgotPassword(@Body request: ForgotPasswordRequest): ForgotPasswordResponseDto

  @POST("auth/reset-password")
  suspend fun resetPassword(@Body request: ResetPasswordRequest): LoginResponseDto

  @POST("auth/refresh")
  suspend fun refresh(@Body request: Map<String, String> = emptyMap()): LoginResponseDto

  @POST("auth/logout")
  suspend fun logout(@Body request: Map<String, String> = emptyMap()): Map<String, Any>

  @GET("auth/whoami")
  suspend fun whoAmI(): PrincipalDto

  @GET("access/my-organizations")
  suspend fun organizations(): OrganizationsDto

  @GET("auth/sessions")
  suspend fun sessions(): SessionsDto

  @POST("auth/sessions")
  suspend fun revokeOtherSessions(@Body request: Map<String, String> = emptyMap()): SessionsDto

  @POST("auth/change-password")
  suspend fun changePassword(@Body request: Map<String, String>): JsonObject

  @POST("access/join-invite")
  suspend fun joinInvite(@Body request: Map<String, String>): AuthenticatedAccountDto

  @POST("access/switch-organization")
  suspend fun switchOrganization(@Body request: Map<String, String>): AuthenticatedAccountDto

  @GET("capabilities")
  suspend fun capabilities(): CapabilitiesDto

  @GET("projects")
  suspend fun projects(): ProjectsDto

  @GET("projects/{name}")
  suspend fun project(
    @Path("name") name: String,
    @Query("tenant_id") tenantId: String,
  ): WorkspaceDto

  @DELETE("projects/{name}")
  suspend fun deleteProject(
    @Path("name") name: String,
    @Query("tenant_id") tenantId: String,
  ): JsonObject

  @GET("preset/{scenario}")
  suspend fun preset(@Path("scenario") scenario: String): PresetDto

  @POST("sessions")
  suspend fun createSession(@Body request: SessionCreateRequest): WorkspaceDto

  @POST("import/csv")
  suspend fun importCsv(@Body request: ImportCsvRequestDto): WorkspaceDto

  @GET("sessions/{id}")
  suspend fun session(@Path("id") id: String): WorkspaceDto

  @POST("sessions/{id}/solve")
  suspend fun solve(
    @Path("id") id: String,
    @Body request: SolveRequestDto,
  ): SessionActionDto

  @POST("sessions/{id}/score")
  suspend fun score(
    @Path("id") id: String,
    @Body request: Map<String, String> = emptyMap(),
  ): ScoreActionDto

  @POST("sessions/{id}/move-deltas")
  suspend fun moveTargets(
    @Path("id") id: String,
    @Body request: MoveTargetsRequestDto,
  ): MoveTargetsActionDto

  @POST("sessions/{id}/move")
  suspend fun move(
    @Path("id") id: String,
    @Body request: MoveRequestDto,
  ): MoveActionDto

  @POST("jobs/improve")
  suspend fun improve(@Body request: ImproveRequestDto): JobDto

  @GET("jobs/{id}")
  suspend fun job(@Path("id") id: String): JobDto

  @POST("jobs/{id}/cancel")
  suspend fun cancelJob(
    @Path("id") id: String,
    @Body request: Map<String, String> = emptyMap(),
  ): JobDto

  @POST("sessions/{id}/export-csv")
  suspend fun exportCsv(
    @Path("id") id: String,
    @Body request: ExportCsvRequestDto = ExportCsvRequestDto(),
  ): ExportActionDto

  @POST("projects")
  suspend fun saveProject(@Body request: ProjectSaveRequest): ProjectSaveResponseDto

  @GET("parity")
  suspend fun parity(): JsonObject

  @GET("access")
  suspend fun access(): JsonObject

  @POST("access")
  suspend fun applyAccess(@Body request: Map<String, @JvmSuppressWildcards Any?>): JsonObject

  @GET("system")
  suspend fun system(): JsonObject

  @GET("system/status")
  suspend fun systemStatus(): JsonObject

  @GET("audit")
  suspend fun audit(@QueryMap filters: Map<String, String>): JsonObject

  @GET("analytics/summary")
  suspend fun analytics(@QueryMap filters: Map<String, String>): JsonObject

  @POST("system/email-test")
  suspend fun sendTestEmail(@Body request: Map<String, String>): JsonObject

  @GET("audit.csv")
  suspend fun auditCsv(@QueryMap filters: Map<String, String>): ResponseBody

  @GET("analytics/export.csv")
  suspend fun analyticsCsv(@QueryMap filters: Map<String, String>): ResponseBody
}
