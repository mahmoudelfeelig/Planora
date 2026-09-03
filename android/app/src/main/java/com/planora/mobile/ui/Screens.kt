package com.planora.mobile.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material.icons.automirrored.rounded.ArrowForward
import androidx.compose.material.icons.automirrored.rounded.MenuBook
import androidx.compose.material.icons.rounded.AutoAwesome
import androidx.compose.material.icons.rounded.CalendarMonth
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.CloudDone
import androidx.compose.material.icons.rounded.Cancel
import androidx.compose.material.icons.rounded.DarkMode
import androidx.compose.material.icons.rounded.EventAvailable
import androidx.compose.material.icons.rounded.FileDownload
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.Groups
import androidx.compose.material.icons.rounded.ImportExport
import androidx.compose.material.icons.rounded.Lightbulb
import androidx.compose.material.icons.rounded.LightMode
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.MoreVert
import androidx.compose.material.icons.rounded.People
import androidx.compose.material.icons.rounded.Publish
import androidx.compose.material.icons.rounded.Room
import androidx.compose.material.icons.rounded.Save
import androidx.compose.material.icons.rounded.School
import androidx.compose.material.icons.rounded.SettingsBrightness
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import com.planora.mobile.BuildConfig
import com.planora.mobile.R
import com.planora.mobile.domain.AcademicResource
import com.planora.mobile.domain.CatalogItem
import com.planora.mobile.domain.JobStatus
import com.planora.mobile.domain.ProjectSummary
import com.planora.mobile.domain.ScheduleEvent
import com.planora.mobile.domain.ScheduleWorkspace
import com.planora.mobile.domain.TutorialStep
import com.planora.mobile.domain.ValidationState
import com.planora.mobile.ui.theme.ThemeMode
import com.planora.mobile.ui.theme.planoraColors

@Composable
internal fun LoginScreen(
  baseUrl: String,
  authConfig: com.planora.mobile.domain.AuthConfig = com.planora.mobile.domain.AuthConfig(),
  authStage: AuthStage = AuthStage.LOGIN,
  busy: Boolean,
  message: String?,
  messageIsError: Boolean = false,
  canEditBaseUrl: Boolean = true,
  canRetrySession: Boolean = false,
  onLogin: (String, String) -> Unit,
  onRegister: (String, String, String) -> Unit = { _, _, _ -> },
  onVerify: (String, String) -> Unit = { _, _ -> },
  onForgotPassword: (String) -> Unit = {},
  onResetPassword: (String, String, String) -> Unit = { _, _, _ -> },
  onAuthStage: (AuthStage) -> Unit = {},
  onRetrySession: () -> Unit = {},
  onBaseUrlSave: (String) -> Unit,
  onOpenTutorial: () -> Unit,
) {
  val uriHandler = LocalUriHandler.current
  var email by remember { mutableStateOf("") }
  var password by remember { mutableStateOf("") }
  var newPassword by remember { mutableStateOf("") }
  var displayName by remember { mutableStateOf("") }
  var code by remember { mutableStateOf("") }
  var server by remember(baseUrl) { mutableStateOf(baseUrl) }
  var showServer by remember { mutableStateOf(false) }

  LazyColumn(
    modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).safeDrawingPadding(),
    contentPadding = PaddingValues(20.dp),
    horizontalAlignment = Alignment.CenterHorizontally,
    verticalArrangement = Arrangement.Center,
  ) {
    item {
      Column(
      modifier = Modifier.widthIn(max = 500.dp).fillMaxWidth(),
      verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
      Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
      ) {
        Image(
          painter = painterResource(R.drawable.planora_elephant),
          contentDescription = null,
          modifier = Modifier.size(56.dp),
        )
        Column {
          Text("Planora", style = MaterialTheme.typography.titleLarge)
          Text(
            "Academic scheduling",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
          )
        }
      }
      Text(
        "Timetabling built for academia.",
        style = MaterialTheme.typography.headlineLarge,
        color = MaterialTheme.colorScheme.onBackground,
        modifier = Modifier.semantics { heading() },
      )
      Text(
        "Open your university workspace to build, review, and save schedules.",
        style = MaterialTheme.typography.bodyLarge,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
      )
      Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        shape = MaterialTheme.shapes.large,
      ) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
          Text(
            when (authStage) {
              AuthStage.LOGIN -> "Sign in"
              AuthStage.REGISTER -> "Create account"
              AuthStage.VERIFY -> "Confirm email"
              AuthStage.FORGOT -> "Reset password"
              AuthStage.RESET -> "Choose new password"
            },
            style = MaterialTheme.typography.titleLarge,
          )
          Text(
            when (authStage) {
              AuthStage.LOGIN -> "Use the same Planora account as the web and desktop apps."
              AuthStage.REGISTER -> "Create your account, then confirm the code sent to your email."
              AuthStage.VERIFY -> "Enter the six-digit confirmation code from your Planora email."
              AuthStage.FORGOT -> "We will send a secure reset link and one-time code."
              AuthStage.RESET -> "Enter the reset code and choose a new password."
            },
            color = MaterialTheme.colorScheme.onSurfaceVariant,
          )
          OutlinedTextField(
            value = email,
            onValueChange = { email = it },
            label = { Text("University email") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
          )
          if (authStage == AuthStage.REGISTER) {
            OutlinedTextField(
              value = displayName,
              onValueChange = { displayName = it },
              label = { Text("Display name") },
              singleLine = true,
              modifier = Modifier.fillMaxWidth(),
            )
          }
          if (authStage in setOf(AuthStage.LOGIN, AuthStage.REGISTER)) {
            OutlinedTextField(
              value = password,
              onValueChange = { password = it },
              label = { Text(if (authStage == AuthStage.REGISTER) "Password · at least 10 characters" else "Password") },
              visualTransformation = PasswordVisualTransformation(),
              keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Password,
                autoCorrectEnabled = false,
              ),
              singleLine = true,
              modifier = Modifier.fillMaxWidth(),
            )
          }
          if (authStage in setOf(AuthStage.VERIFY, AuthStage.RESET)) {
            OutlinedTextField(
              value = code,
              onValueChange = { code = it.filter(Char::isDigit).take(6) },
              label = { Text(if (authStage == AuthStage.VERIFY) "Confirmation code" else "Reset code") },
              keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
              singleLine = true,
              modifier = Modifier.fillMaxWidth(),
            )
          }
          if (authStage == AuthStage.RESET) {
            OutlinedTextField(
              value = newPassword,
              onValueChange = { newPassword = it },
              label = { Text("New password · at least 10 characters") },
              visualTransformation = PasswordVisualTransformation(),
              keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false),
              singleLine = true,
              modifier = Modifier.fillMaxWidth(),
            )
          }
          Button(
            onClick = {
              when (authStage) {
                AuthStage.LOGIN -> onLogin(email, password)
                AuthStage.REGISTER -> onRegister(email, password, displayName)
                AuthStage.VERIFY -> onVerify(email, code)
                AuthStage.FORGOT -> onForgotPassword(email)
                AuthStage.RESET -> onResetPassword(email, code, newPassword)
              }
            },
            enabled = !busy && when (authStage) {
              AuthStage.LOGIN -> email.isNotBlank() && password.isNotBlank()
              AuthStage.REGISTER -> email.isNotBlank() && displayName.isNotBlank() && password.length >= 10
              AuthStage.VERIFY -> email.isNotBlank() && code.length == 6
              AuthStage.FORGOT -> email.isNotBlank()
              AuthStage.RESET -> email.isNotBlank() && code.length == 6 && newPassword.length >= 10
            },
            modifier = Modifier.fillMaxWidth().height(52.dp),
          ) {
            Text(
              if (busy) "Working…" else when (authStage) {
                AuthStage.LOGIN -> "Open workspace"
                AuthStage.REGISTER -> "Create account"
                AuthStage.VERIFY -> "Confirm email"
                AuthStage.FORGOT -> "Send reset email"
                AuthStage.RESET -> "Reset password"
              },
            )
          }
          when (authStage) {
            AuthStage.LOGIN -> {
              if (authConfig.registrationEnabled) {
                OutlinedButton(
                  onClick = { onAuthStage(AuthStage.REGISTER) },
                  enabled = !busy,
                  modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                ) { Text("Register") }
              }
              TextButton(onClick = { onAuthStage(AuthStage.FORGOT) }, modifier = Modifier.align(Alignment.CenterHorizontally)) {
                Text("Forgot password?")
              }
            }
            AuthStage.REGISTER -> TextButton(
              onClick = { onAuthStage(AuthStage.LOGIN) },
              modifier = Modifier.align(Alignment.CenterHorizontally),
            ) { Text("Already registered? Sign in") }
            AuthStage.VERIFY -> TextButton(
              onClick = { onAuthStage(AuthStage.LOGIN) },
              modifier = Modifier.align(Alignment.CenterHorizontally),
            ) { Text("Confirmed already? Sign in") }
            AuthStage.FORGOT, AuthStage.RESET -> TextButton(
              onClick = { onAuthStage(AuthStage.LOGIN) },
              modifier = Modifier.align(Alignment.CenterHorizontally),
            ) { Text("Back to sign in") }
          }
          TextButton(onClick = onOpenTutorial, modifier = Modifier.align(Alignment.CenterHorizontally)) {
            Icon(Icons.Rounded.Lightbulb, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("See how Planora works")
          }
          if (BuildConfig.APP_WEB_URL.isNotBlank()) {
            TextButton(
              onClick = { uriHandler.openUri(BuildConfig.APP_WEB_URL) },
              modifier = Modifier.align(Alignment.CenterHorizontally),
            ) {
              Text("Need help signing in?")
            }
          }
          HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
          TextButton(onClick = { showServer = !showServer }) {
            Icon(Icons.Rounded.CloudDone, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text(if (showServer) "Hide connection" else "Connection")
          }
          if (showServer) {
            if (canEditBaseUrl) {
              OutlinedTextField(
                value = server,
                onValueChange = { server = it },
                label = { Text("Planora server") },
                supportingText = { Text("HTTPS is required except for local development.") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
              )
              OutlinedButton(onClick = { onBaseUrlSave(server) }, modifier = Modifier.fillMaxWidth()) {
                Text("Save server address")
              }
            } else {
              ConnectedEndpoint(baseUrl)
            }
          }
          if (!message.isNullOrBlank()) {
            Text(
              message,
              color = if (messageIsError) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary,
              style = MaterialTheme.typography.bodyMedium,
            )
            if (canRetrySession) {
              OutlinedButton(onClick = onRetrySession, enabled = !busy, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Rounded.CloudDone, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("Retry saved session")
              }
            }
          }
        }
      }
      Text(
        "Your password is sent only to your Planora server and is never stored on this device.",
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodyMedium,
        textAlign = TextAlign.Center,
        modifier = Modifier.fillMaxWidth(),
      )
    }
    }
  }
}

@Composable
internal fun HomeScreen(
  state: PlanoraUiState,
  onScenario: (CatalogItem) -> Unit,
  onMode: (String) -> Unit,
  onOpenProject: (ProjectSummary) -> Unit,
  onOpenTutorial: () -> Unit,
  onOpenSchedule: () -> Unit,
) {
  LazyColumn(
    modifier = Modifier.fillMaxSize(),
    contentPadding = PaddingValues(16.dp),
    verticalArrangement = Arrangement.spacedBy(24.dp),
  ) {
    item {
      Surface(
        color = MaterialTheme.colorScheme.surface,
        shape = MaterialTheme.shapes.large,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
      ) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
          Text("Academic blueprint", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelLarge)
          Text(
            if (state.workspace == null) "Build a schedule people can understand."
            else "Continue ${state.workspace.projectName}",
            style = MaterialTheme.typography.headlineLarge,
            modifier = Modifier.semantics { heading() },
          )
          Text(
            if (state.workspace == null) {
              "Start from the Spring 2023 university profile, a small demo, or your own file. Planora keeps the technical solver choices out of your way."
            } else {
              workspaceSummary(state.workspace)
            },
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyLarge,
          )
          Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Button(onClick = if (state.workspace == null) onOpenTutorial else onOpenSchedule) {
              Text(if (state.workspace == null) "Learn the process" else "Open schedule")
            }
            if (state.workspace != null) {
              OutlinedButton(onClick = onOpenTutorial) { Text("View guide") }
            }
          }
        }
      }
    }

    item { SectionTitle("Start a new schedule", "Choose the source; the server supplies the supported options.") }
    item {
      Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        state.catalog?.scenarios.orEmpty().forEach { item ->
          val enabled = item.id != "import" || state.principal?.canWriteSchedule == true
          ScenarioCard(
            item = item,
            enabled = enabled,
            disabledReason = if (enabled) null else "Requires schedule editing permission.",
            onClick = { onScenario(item) },
          )
        }
      }
    }
    item {
      val recommended = state.catalog?.modes?.firstOrNull { it.recommended }?.label ?: "Balanced"
      SectionTitle("Planning mode", "$recommended is the server-recommended everyday choice.")
    }
    item { ModePicker(state.catalog?.modes.orEmpty(), state.selectedModeId, onSelect = onMode) }

    if (state.projects.isNotEmpty()) {
      item { SectionTitle("Recent projects", "Continue without rebuilding the source data.") }
      items(state.projects.take(3), key = { "${it.tenantId}:${it.name}" }) { project ->
        ProjectRow(
          project = project,
          canWrite = false,
          onOpen = onOpenProject,
          onRename = {},
          onDelete = {},
        )
      }
    }
  }
}

@Composable
private fun ScenarioCard(
  item: CatalogItem,
  enabled: Boolean = true,
  disabledReason: String? = null,
  onClick: () -> Unit,
) {
  val icon = when (item.id) {
    "demo" -> Icons.Rounded.EventAvailable
    "spring_2023" -> Icons.Rounded.School
    else -> Icons.Rounded.ImportExport
  }
  Card(
    modifier = Modifier.fillMaxWidth().testTag("scenario-${item.id}")
      .alpha(if (enabled) 1f else 0.62f)
      .clickable(enabled = enabled, role = Role.Button, onClick = onClick),
    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    shape = MaterialTheme.shapes.medium,
  ) {
    Row(
      Modifier.padding(16.dp),
      verticalAlignment = Alignment.CenterVertically,
      horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
      Surface(color = MaterialTheme.colorScheme.primaryContainer, shape = MaterialTheme.shapes.medium) {
        Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(12.dp).size(26.dp))
      }
      Column(Modifier.weight(1f)) {
        Text(item.label, style = MaterialTheme.typography.titleMedium)
        Text(item.description, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
        disabledReason?.let {
          Text(
            it,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
          )
        }
      }
      Icon(
        imageVector = if (enabled) Icons.AutoMirrored.Rounded.ArrowForward else Icons.Rounded.Lock,
        contentDescription = if (enabled) null else "Unavailable for this role",
        tint = MaterialTheme.colorScheme.onSurfaceVariant,
      )
    }
  }
}

@Composable
internal fun ScheduleScreen(
  state: PlanoraUiState,
  expanded: Boolean,
  onWeek: (Int) -> Unit,
  onDay: (String) -> Unit,
  onEvent: (ScheduleEvent?) -> Unit,
  onMode: (String) -> Unit,
  onSolve: () -> Unit,
  onValidate: () -> Unit,
  onImprove: () -> Unit,
  onCancelImprove: () -> Unit,
  onOpenReview: () -> Unit,
  onSave: (String) -> Unit,
  onExport: () -> Unit,
  onPreviewMoves: (ScheduleEvent) -> Unit = {},
) {
  val workspace = state.workspace
  if (workspace == null) {
    EmptySchedule()
    return
  }
  var saveDialog by remember { mutableStateOf(false) }
  var saveName by remember(workspace.projectName) { mutableStateOf(workspace.projectName) }

  if (saveDialog) {
    AlertDialog(
      onDismissRequest = { saveDialog = false },
      title = { Text("Save timetable") },
      text = {
        OutlinedTextField(
          value = saveName,
          onValueChange = { saveName = it },
          label = { Text("Project name") },
          singleLine = true,
        )
      },
      confirmButton = {
        TextButton(onClick = { onSave(saveName); saveDialog = false }, enabled = saveName.isNotBlank()) {
          Text("Save version")
        }
      },
      dismissButton = { TextButton(onClick = { saveDialog = false }) { Text("Cancel") } },
    )
  }

  if (expanded) {
    Row(Modifier.fillMaxSize()) {
      AcademicTree(workspace, Modifier.width(180.dp).fillMaxHeight())
      Column(Modifier.weight(1f).fillMaxHeight()) {
        ScheduleToolbar(state, onMode, onSolve, onValidate, onImprove, onCancelImprove, { saveDialog = true }, onExport)
        WeekPicker(workspace.weeks, state.selectedWeek, onWeek)
        ExpandedTimetable(workspace, state.selectedWeek, state.selectedEvent, onEvent, Modifier.weight(1f))
      }
      EventInspector(
        event = state.selectedEvent,
        conflicts = workspace.hardConflicts,
        validationState = workspace.validationState,
        onImprove = onImprove,
        onOpenReview = onOpenReview,
        canImprove = state.principal?.canRunSolver == true && state.runningJob == null,
        onCancelImprove = onCancelImprove,
        runningJob = state.runningJob,
        onPreviewMoves = onPreviewMoves,
        modifier = Modifier.width(280.dp).fillMaxHeight().background(MaterialTheme.colorScheme.surfaceContainerLow).padding(18.dp),
      )
    }
  } else {
    BoxWithConstraints(Modifier.fillMaxSize()) {
      val compactHeight = maxHeight < 520.dp
      Column(Modifier.fillMaxSize()) {
        ScheduleToolbar(
          state,
          onMode,
          onSolve,
          onValidate,
          onImprove,
          onCancelImprove,
          { saveDialog = true },
          onExport,
          compact = compactHeight,
        )
        if (compactHeight) {
          CompactPeriodPicker(
            weeks = workspace.weeks,
            selectedWeek = state.selectedWeek,
            days = workspace.days,
            selectedDay = state.selectedDay,
            onWeek = onWeek,
            onDay = onDay,
          )
        } else {
          WeekPicker(workspace.weeks, state.selectedWeek, onWeek)
          DayPicker(workspace.days, state.selectedDay, onDay)
        }
        PhoneAgenda(
          workspace = workspace,
          week = state.selectedWeek,
          day = state.selectedDay,
          selected = state.selectedEvent,
          onEvent = onEvent,
          modifier = Modifier.weight(1f),
        )
      }
    }
  }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ScheduleToolbar(
  state: PlanoraUiState,
  onMode: (String) -> Unit,
  onSolve: () -> Unit,
  onValidate: () -> Unit,
  onImprove: () -> Unit,
  onCancelImprove: () -> Unit,
  onSave: () -> Unit,
  onExport: () -> Unit,
  compact: Boolean = false,
) {
  val workspace = state.workspace ?: return
  val improvementRunning = state.runningJob != null
  val actionsEnabled = !state.busy && !improvementRunning
  var compactActionsExpanded by remember { mutableStateOf(false) }
  if (compact) {
    Row(
      Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface)
        .horizontalScroll(rememberScrollState()).padding(horizontal = 10.dp, vertical = 6.dp),
      horizontalArrangement = Arrangement.spacedBy(8.dp),
      verticalAlignment = Alignment.CenterVertically,
    ) {
      Column(Modifier.widthIn(min = 150.dp, max = 220.dp)) {
        Text(
          workspace.projectName,
          style = MaterialTheme.typography.titleMedium,
          maxLines = 1,
          overflow = TextOverflow.Ellipsis,
        )
        Text(
          workspaceSummary(workspace),
          color = MaterialTheme.colorScheme.onSurfaceVariant,
          style = MaterialTheme.typography.bodySmall,
          maxLines = 1,
        )
      }
      DraftStatus(workspace.validationState, workspace.hardConflicts.size)
      state.catalog?.modes.orEmpty().forEach { mode ->
        FilterChip(
          selected = mode.id == state.selectedModeId,
          onClick = { onMode(mode.id) },
          enabled = actionsEnabled,
          label = { Text(mode.label) },
        )
      }
      if (improvementRunning) {
        Text(state.runningJob?.message.orEmpty(), style = MaterialTheme.typography.bodySmall)
        OutlinedButton(onClick = onCancelImprove, modifier = Modifier.heightIn(min = 44.dp)) {
          Icon(Icons.Rounded.Cancel, contentDescription = null)
          Spacer(Modifier.width(6.dp))
          Text(if (state.runningJob?.status == "tracking_error") "Stop tracking" else "Cancel")
        }
      } else if (workspace.events.isEmpty()) {
        Button(onClick = onSolve, enabled = actionsEnabled && state.principal?.canRunSolver == true) {
          Text("Build draft")
        }
      } else {
        OutlinedButton(onClick = onValidate, enabled = actionsEnabled) { Text("Validate") }
        OutlinedButton(onClick = onImprove, enabled = actionsEnabled && state.principal?.canRunSolver == true) {
          Text("Improve")
        }
        Box {
          IconButton(
            onClick = { compactActionsExpanded = true },
            enabled = actionsEnabled,
          ) {
            Icon(Icons.Rounded.MoreVert, contentDescription = "More schedule actions")
          }
          DropdownMenu(
            expanded = compactActionsExpanded,
            onDismissRequest = { compactActionsExpanded = false },
          ) {
            DropdownMenuItem(
              text = { Text("Save project") },
              leadingIcon = { Icon(Icons.Rounded.Save, contentDescription = null) },
              enabled = state.principal?.canWriteSchedule == true,
              onClick = {
                compactActionsExpanded = false
                onSave()
              },
            )
            DropdownMenuItem(
              text = { Text("Export CSV") },
              leadingIcon = { Icon(Icons.Rounded.FileDownload, contentDescription = null) },
              onClick = {
                compactActionsExpanded = false
                onExport()
              },
            )
            DropdownMenuItem(
              text = { Text("Rebuild schedule") },
              leadingIcon = { Icon(Icons.Rounded.AutoAwesome, contentDescription = null) },
              enabled = state.principal?.canRunSolver == true,
              onClick = {
                compactActionsExpanded = false
                onSolve()
              },
            )
          }
        }
      }
    }
    return
  }
  Column(
    Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface).padding(horizontal = 16.dp, vertical = 12.dp),
    verticalArrangement = Arrangement.spacedBy(12.dp),
  ) {
    Row(
      Modifier.fillMaxWidth(),
      horizontalArrangement = Arrangement.spacedBy(12.dp),
      verticalAlignment = Alignment.CenterVertically,
    ) {
      Column(Modifier.weight(1f)) {
        Text(workspace.projectName, style = MaterialTheme.typography.titleLarge)
        Text(
          workspaceSummary(workspace),
          color = MaterialTheme.colorScheme.onSurfaceVariant,
          style = MaterialTheme.typography.bodyMedium,
        )
      }
      DraftStatus(workspace.validationState, workspace.hardConflicts.size)
    }

    FlowRow(
      modifier = Modifier.fillMaxWidth(),
      horizontalArrangement = Arrangement.spacedBy(8.dp),
      verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
      if (workspace.events.isEmpty()) {
        Button(
          onClick = onSolve,
          enabled = actionsEnabled && state.principal?.canRunSolver == true,
          modifier = Modifier.defaultMinSize(minHeight = 48.dp),
        ) {
          Icon(Icons.Rounded.AutoAwesome, contentDescription = null)
          Spacer(Modifier.width(7.dp))
          Text("Build draft")
        }
      } else {
        OutlinedButton(
          onClick = onValidate,
          enabled = actionsEnabled,
          modifier = Modifier.defaultMinSize(minHeight = 48.dp),
        ) {
          Icon(Icons.Rounded.CheckCircle, contentDescription = null)
          Spacer(Modifier.width(6.dp))
          Text("Validate")
        }
        OutlinedButton(
          onClick = onImprove,
          enabled = actionsEnabled && state.principal?.canRunSolver == true,
          modifier = Modifier.defaultMinSize(minHeight = 48.dp),
        ) {
          Text("Improve")
        }
        OutlinedButton(
          onClick = onSave,
          enabled = actionsEnabled && state.principal?.canWriteSchedule == true,
          modifier = Modifier.defaultMinSize(minHeight = 48.dp),
        ) {
          Icon(Icons.Rounded.Save, contentDescription = null)
          Spacer(Modifier.width(6.dp))
          Text("Save")
        }
        OutlinedButton(
          onClick = onExport,
          enabled = actionsEnabled,
          modifier = Modifier.defaultMinSize(minHeight = 48.dp),
        ) {
          Icon(Icons.Rounded.FileDownload, contentDescription = null)
          Spacer(Modifier.width(6.dp))
          Text("Export")
        }
      }
    }

    ModePicker(state.catalog?.modes.orEmpty(), state.selectedModeId, actionsEnabled, onMode)
    if (workspace.events.isNotEmpty() && !improvementRunning) {
      TextButton(
        onClick = onSolve,
        enabled = actionsEnabled && state.principal?.canRunSolver == true,
      ) {
        Text("Rebuild with the selected mode")
      }
    }
    state.runningJob?.let { job -> JobProgressPanel(job, onCancelImprove) }
  }
}

@Composable
private fun ModePicker(modes: List<CatalogItem>, selected: String, enabled: Boolean = true, onSelect: (String) -> Unit) {
  Row(
    Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
    horizontalArrangement = Arrangement.spacedBy(8.dp),
  ) {
    modes.forEach { mode ->
      FilterChip(
        selected = mode.id == selected,
        onClick = { onSelect(mode.id) },
        enabled = enabled,
        label = { Text(mode.label) },
        leadingIcon = if (mode.id == selected) {
          { Icon(Icons.Rounded.Check, contentDescription = null, modifier = Modifier.size(18.dp)) }
        } else null,
      )
    }
  }
}

@Composable
private fun CompactPeriodPicker(
  weeks: List<Int>,
  selectedWeek: Int,
  days: List<String>,
  selectedDay: String,
  onWeek: (Int) -> Unit,
  onDay: (String) -> Unit,
) {
  Row(
    Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface)
      .horizontalScroll(rememberScrollState()).padding(horizontal = 10.dp, vertical = 4.dp),
    horizontalArrangement = Arrangement.spacedBy(6.dp),
    verticalAlignment = Alignment.CenterVertically,
  ) {
    Text("Week", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    weeks.forEach { week ->
      FilterChip(selected = week == selectedWeek, onClick = { onWeek(week) }, label = { Text(week.toString()) })
    }
    Text("Day", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    days.forEach { day ->
      FilterChip(selected = day == selectedDay, onClick = { onDay(day) }, label = { Text(dayLabel(day).take(3)) })
    }
  }
}

@Composable
private fun WeekPicker(weeks: List<Int>, selected: Int, onSelect: (Int) -> Unit) {
  Row(
    Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface).horizontalScroll(rememberScrollState())
      .padding(horizontal = 12.dp, vertical = 8.dp),
    horizontalArrangement = Arrangement.spacedBy(8.dp),
  ) {
    weeks.forEach { week ->
      FilterChip(selected = week == selected, onClick = { onSelect(week) }, label = { Text("Week $week") })
    }
  }
}

@Composable
private fun DayPicker(days: List<String>, selected: String, onSelect: (String) -> Unit) {
  Row(
    Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainerLow)
      .horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 8.dp),
    horizontalArrangement = Arrangement.spacedBy(8.dp),
  ) {
    days.forEach { day ->
      FilterChip(selected = day == selected, onClick = { onSelect(day) }, label = { Text(dayLabel(day)) })
    }
  }
}

@Composable
private fun ExpandedTimetable(
  workspace: ScheduleWorkspace,
  week: Int,
  selected: ScheduleEvent?,
  onEvent: (ScheduleEvent) -> Unit,
  modifier: Modifier = Modifier,
) {
  val visible = remember(workspace.events, week) { workspace.events.filter { it.week == week }.groupBy { it.day } }
  val horizontalScroll = rememberScrollState()
  val verticalScroll = rememberScrollState()
  val slotHeight = 76.dp
  BoxWithConstraints(modifier.background(MaterialTheme.colorScheme.background)) {
    val contentWidth = maxOf(maxWidth, 62.dp + (116.dp * workspace.days.size))
    Column(Modifier.fillMaxSize()) {
      Box(Modifier.fillMaxWidth().horizontalScroll(horizontalScroll)) {
        Row(Modifier.width(contentWidth).background(MaterialTheme.colorScheme.surfaceContainerHigh)) {
          Box(
            Modifier.width(62.dp).height(40.dp).border(0.5.dp, MaterialTheme.colorScheme.outlineVariant),
            contentAlignment = Alignment.Center,
          ) {
            Text("Slot", style = MaterialTheme.typography.labelMedium)
          }
          workspace.days.forEach { day ->
            Box(
              Modifier.weight(1f).height(40.dp).border(0.5.dp, MaterialTheme.colorScheme.outlineVariant),
              contentAlignment = Alignment.Center,
            ) {
              Text(dayLabel(day), style = MaterialTheme.typography.titleSmall)
            }
          }
        }
      }
      Box(
        Modifier.weight(1f).fillMaxWidth().horizontalScroll(horizontalScroll).verticalScroll(verticalScroll),
      ) {
        Row(Modifier.width(contentWidth).height(slotHeight * workspace.slotsPerDay)) {
          Column(Modifier.width(62.dp).fillMaxHeight()) {
            repeat(workspace.slotsPerDay) { slot ->
              Box(
                Modifier.fillMaxWidth().height(slotHeight)
                  .background(MaterialTheme.colorScheme.surfaceContainerHigh)
                  .border(0.5.dp, MaterialTheme.colorScheme.outlineVariant),
                contentAlignment = Alignment.TopCenter,
              ) {
                Text(
                  slotNumberLabel(slot),
                  modifier = Modifier.padding(top = 10.dp),
                  color = MaterialTheme.colorScheme.onSurfaceVariant,
                  style = MaterialTheme.typography.labelMedium,
                )
              }
            }
          }
          workspace.days.forEach { day ->
            Box(Modifier.weight(1f).fillMaxHeight().background(MaterialTheme.colorScheme.surface)) {
              Column(Modifier.fillMaxSize()) {
                repeat(workspace.slotsPerDay) {
                  Box(
                    Modifier.fillMaxWidth().height(slotHeight)
                      .border(0.5.dp, MaterialTheme.colorScheme.outlineVariant),
                  )
                }
              }
              visible[day].orEmpty().groupBy { it.slot }.forEach { (slot, events) ->
                val safeSlot = slot.coerceIn(0, (workspace.slotsPerDay - 1).coerceAtLeast(0))
                val span = events.maxOfOrNull { it.duration.coerceAtLeast(1) }?.coerceAtMost(workspace.slotsPerDay - safeSlot) ?: 1
                Row(
                  Modifier.fillMaxWidth().height(slotHeight * span).offset(y = slotHeight * safeSlot)
                    .padding(5.dp).zIndex(1f),
                  horizontalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                  events.forEach { event ->
                    val eventSpan = event.duration.coerceAtLeast(1).coerceAtMost(workspace.slotsPerDay - safeSlot)
                    EventCard(
                      event = event,
                      selected = event.activityId == selected?.activityId,
                      onClick = onEvent,
                      compact = true,
                      modifier = Modifier.weight(1f).height(slotHeight * eventSpan),
                    )
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}

@Composable
private fun PhoneAgenda(
  workspace: ScheduleWorkspace,
  week: Int,
  day: String,
  selected: ScheduleEvent?,
  onEvent: (ScheduleEvent) -> Unit,
  modifier: Modifier = Modifier,
) {
  val visible = remember(workspace.events, week, day) {
    workspace.events.filter { it.week == week && it.day == day }.groupBy { it.slot }
  }
  val coveredSlots = remember(visible, workspace.slotsPerDay) {
    visible.values.flatten().flatMap { event ->
      val start = (event.slot + 1).coerceAtMost(workspace.slotsPerDay)
      val end = (event.slot + event.duration.coerceAtLeast(1)).coerceAtMost(workspace.slotsPerDay)
      (start until end).toList()
    }.toSet()
  }
  LazyColumn(
    modifier.background(MaterialTheme.colorScheme.background),
    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
  ) {
    items(workspace.slotsPerDay) { slot ->
      val events = visible[slot].orEmpty()
      if (events.isEmpty() && slot in coveredSlots) return@items
      Row(
        Modifier.fillMaxWidth().heightIn(min = 68.dp).padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
      ) {
        Text(
          slotNumberLabel(slot),
          modifier = Modifier.width(52.dp).padding(top = 10.dp),
          color = MaterialTheme.colorScheme.onSurfaceVariant,
          style = MaterialTheme.typography.labelMedium,
        )
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
          if (events.isEmpty()) {
            Surface(
              color = MaterialTheme.colorScheme.surfaceContainerLow,
              shape = MaterialTheme.shapes.small,
              border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
              modifier = Modifier.fillMaxWidth().height(56.dp),
            ) {}
          } else {
            events.forEach { event ->
              EventCard(
                event = event,
                selected = event.activityId == selected?.activityId,
                onClick = onEvent,
                modifier = Modifier.heightIn(min = 64.dp * event.duration.coerceAtLeast(1)),
              )
            }
          }
        }
      }
    }
  }
}

@Composable
private fun EventCard(
  event: ScheduleEvent,
  selected: Boolean,
  onClick: (ScheduleEvent) -> Unit,
  compact: Boolean = false,
  modifier: Modifier = Modifier,
) {
  val colors = MaterialTheme.planoraColors.courseTones
  val toneIndex = event.activityId.toString().sumOf { it.code } % colors.size
  val tone = colors[toneIndex]
  val eventDescription = buildString {
    append(event.title)
    append(", ${event.code}, ${event.kind}, ${dayLabel(event.day)}, ${slotRangeLabel(event.slot, event.duration)}")
    append(", ${durationLabel(event.duration)}")
    append(", room ${event.room}, ${event.staff}")
  }
  Surface(
    modifier = modifier.fillMaxWidth()
      .clickable(role = Role.Button, onClickLabel = "Open class details") { onClick(event) }
      .semantics(mergeDescendants = true) {
        contentDescription = eventDescription
        this.selected = selected
        stateDescription = if (selected) "Selected" else "Not selected"
      },
    color = tone.container,
    contentColor = tone.content,
    shape = MaterialTheme.shapes.small,
    border = BorderStroke(
      if (selected) 2.dp else 1.dp,
      if (selected) MaterialTheme.planoraColors.focus else tone.outline,
    ),
  ) {
    Box {
      Box(
        Modifier.align(Alignment.CenterStart).fillMaxHeight().width(3.dp).background(tone.accent),
      )
      Column(
        Modifier.padding(start = if (compact) 9.dp else 12.dp, top = if (compact) 5.dp else 8.dp, end = 8.dp, bottom = if (compact) 5.dp else 8.dp),
        verticalArrangement = Arrangement.spacedBy(2.dp),
      ) {
        Text(
          event.title,
          style = if (compact) {
            MaterialTheme.typography.labelMedium.copy(fontSize = 11.sp, lineHeight = 13.sp)
          } else {
            MaterialTheme.typography.titleSmall
          },
          maxLines = if (compact) 2 else 1,
          overflow = TextOverflow.Ellipsis,
          color = tone.content,
        )
        Text(
          "${event.kind} · ${slotRangeLabel(event.slot, event.duration)} · ${durationLabel(event.duration)}",
          style = MaterialTheme.typography.bodySmall,
          color = tone.content,
          maxLines = 1,
          overflow = TextOverflow.Ellipsis,
        )
        Text("${event.code} · ${event.room}", style = MaterialTheme.typography.bodySmall, color = tone.content, maxLines = 1)
      }
    }
  }
}

@Composable
private fun AcademicTree(workspace: ScheduleWorkspace, modifier: Modifier = Modifier) {
  Column(modifier.background(MaterialTheme.colorScheme.surfaceContainerLow).verticalScroll(rememberScrollState()).padding(14.dp)) {
    Text("Academic data", style = MaterialTheme.typography.titleMedium)
    Text("What this draft is built from", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
    Spacer(Modifier.height(14.dp))
    ResourceGroup("Programs", Icons.Rounded.School, workspace.programs)
    ResourceGroup("Groups", Icons.Rounded.Groups, workspace.groups)
    ResourceGroup("Courses", Icons.AutoMirrored.Rounded.MenuBook, workspace.courses)
    ResourceGroup("Staff", Icons.Rounded.People, workspace.staff)
    ResourceGroup("Rooms", Icons.Rounded.Room, workspace.rooms)
  }
}

@Composable
private fun ResourceGroup(title: String, icon: ImageVector, values: List<AcademicResource>) {
  var expanded by remember { mutableStateOf(title in setOf("Programs", "Courses")) }
  Column(Modifier.fillMaxWidth()) {
    Row(
      Modifier.fillMaxWidth().clickable { expanded = !expanded }.padding(vertical = 10.dp),
      verticalAlignment = Alignment.CenterVertically,
      horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
      Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(19.dp))
      Text(title, style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
      Text(values.size.toString(), color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    if (expanded) {
      values.take(12).forEach { value ->
        Column(Modifier.padding(start = 27.dp, bottom = 8.dp)) {
          Text(value.label, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
          if (value.secondary.isNotBlank()) {
            Text(value.secondary, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
          }
        }
      }
      if (values.size > 12) {
        Text("+ ${values.size - 12} more", color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(start = 27.dp, bottom = 8.dp))
      }
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
  }
}

@Composable
internal fun EventInspector(
  event: ScheduleEvent?,
  conflicts: List<String>,
  validationState: ValidationState?,
  onImprove: () -> Unit,
  onCancelImprove: () -> Unit = {},
  onOpenReview: () -> Unit,
  canImprove: Boolean,
  runningJob: JobStatus? = null,
  onPreviewMoves: (ScheduleEvent) -> Unit = {},
  modifier: Modifier = Modifier,
) {
  val resolvedValidation = validationState ?: ValidationState.NOT_VALIDATED
  Column(modifier.verticalScroll(rememberScrollState())) {
    MotionAwareContent(targetState = event, label = "selected class details") { selectedEvent ->
      if (selectedEvent == null) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
          Image(
            painter = painterResource(R.drawable.planora_elephant),
            contentDescription = null,
            modifier = Modifier.size(width = 64.dp, height = 48.dp),
          )
          Text("Select a class", style = MaterialTheme.typography.titleLarge)
          Text(
            "Details, validation, and practical next steps will appear here.",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
          )
        }
      } else {
        EventInspectorContent(
          selectedEvent,
          conflicts,
          resolvedValidation,
          onImprove,
          onCancelImprove,
          onOpenReview,
          canImprove,
          runningJob,
          onPreviewMoves,
        )
      }
    }
  }
}

@Composable
private fun EventInspectorContent(
  event: ScheduleEvent,
  conflicts: List<String>,
  validationState: ValidationState,
  onImprove: () -> Unit,
  onCancelImprove: () -> Unit,
  onOpenReview: () -> Unit,
  canImprove: Boolean,
  runningJob: JobStatus?,
  onPreviewMoves: (ScheduleEvent) -> Unit,
) {
  val related = conflicts.filter { conflictMentionsActivity(it, event.activityId) }.take(3)
  Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
      Text(event.title, style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() })
      Text("${event.code} · ${event.kind}", color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    DetailLine("Placement", "${dayLabel(event.day)} · ${slotRangeLabel(event.slot, event.duration)}")
    DetailLine("Duration", durationLabel(event.duration))
    DetailLine("Room", event.room)
    DetailLine("Staff", event.staff)
    DetailLine("Groups", event.groups.joinToString().ifBlank { "No group assigned" })
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    Text("Validation", style = MaterialTheme.typography.titleMedium)
    when (validationState) {
      ValidationState.NOT_VALIDATED -> {
        Surface(color = MaterialTheme.colorScheme.primaryContainer, shape = MaterialTheme.shapes.medium) {
          Row(
            Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
          ) {
            Icon(Icons.Rounded.Lock, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            Text(
              "Not validated yet. Validate the timetable before treating this placement as conflict-free.",
              color = MaterialTheme.colorScheme.onPrimaryContainer,
              style = MaterialTheme.typography.bodyMedium,
            )
          }
        }
      }
      ValidationState.VALID -> Surface(
        color = MaterialTheme.planoraColors.successContainer,
        shape = MaterialTheme.shapes.medium,
      ) {
        Row(
          Modifier.padding(12.dp),
          verticalAlignment = Alignment.CenterVertically,
          horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
          Icon(Icons.Rounded.CheckCircle, contentDescription = null, tint = MaterialTheme.planoraColors.success)
          Text(
            "Validated. No hard conflict is attached to this class.",
            color = MaterialTheme.planoraColors.success,
            style = MaterialTheme.typography.bodyMedium,
          )
        }
      }
      ValidationState.INVALID -> if (related.isEmpty()) {
        Surface(color = MaterialTheme.planoraColors.warningContainer, shape = MaterialTheme.shapes.medium) {
          Text(
            "This class has no reported conflict, but the timetable is invalid elsewhere.",
            color = MaterialTheme.planoraColors.warning,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.padding(12.dp),
          )
        }
      } else {
        related.forEach { conflict ->
          Surface(color = MaterialTheme.planoraColors.dangerContainer, shape = MaterialTheme.shapes.medium) {
            Text(
              plainConflict(conflict),
              color = MaterialTheme.planoraColors.danger,
              style = MaterialTheme.typography.bodyMedium,
              modifier = Modifier.padding(12.dp),
            )
          }
        }
      }
    }
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    OutlinedButton(
      onClick = { onPreviewMoves(event) },
      modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
    ) {
      Icon(Icons.Rounded.CalendarMonth, contentDescription = null)
      Spacer(Modifier.width(8.dp))
      Text("Find safe moves")
    }
    Text("Suggested next steps", style = MaterialTheme.typography.titleMedium)
    SuggestionCard(
      rank = 1,
      title = when {
        validationState == ValidationState.NOT_VALIDATED -> "Validate before comparing alternatives"
        related.isEmpty() -> "Compare feasible alternatives"
        else -> "Repair the conflicting placement"
      },
      body = when {
        validationState == ValidationState.NOT_VALIDATED -> "Validation establishes whether this placement is feasible before a quality pass is interpreted."
        related.isEmpty() -> "Run a quality pass to compare this class with other valid placements while preserving hard constraints."
        else -> "Run the bounded improvement pass for this draft, then validate again to confirm the conflict is gone."
      },
      highlighted = true,
    )
    SuggestionCard(
      rank = 2,
      title = "Review linked resources",
      body = "Confirm ${event.room}, ${event.staff}, and ${event.groups.joinToString().ifBlank { "the assigned groups" }} before saving this version.",
    )
    if (runningJob != null) {
      JobProgressPanel(runningJob, onCancelImprove)
    } else {
      Button(onClick = onImprove, enabled = canImprove, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) {
        Icon(Icons.Rounded.AutoAwesome, contentDescription = null)
        Spacer(Modifier.width(8.dp))
        Text(if (related.isEmpty()) "Run quality pass" else "Repair timetable")
      }
    }
    OutlinedButton(onClick = onOpenReview, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) {
      Text("Open full review")
    }
    if (!canImprove && runningJob == null) {
      Text(
        "Your role can review this draft but cannot run improvements.",
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
      )
    }
  }
}

@Composable
private fun SuggestionCard(rank: Int, title: String, body: String, highlighted: Boolean = false) {
  Surface(
    color = if (highlighted) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceContainerLow,
    shape = MaterialTheme.shapes.medium,
    border = BorderStroke(1.dp, if (highlighted) MaterialTheme.colorScheme.primary.copy(alpha = 0.55f) else MaterialTheme.colorScheme.outlineVariant),
  ) {
    Row(Modifier.padding(12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
      Surface(color = MaterialTheme.colorScheme.primary, shape = RoundedCornerShape(20.dp)) {
        Text(
          rank.toString(),
          color = MaterialTheme.colorScheme.onPrimary,
          style = MaterialTheme.typography.labelMedium,
          modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
        )
      }
      Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Text(title, style = MaterialTheme.typography.titleSmall)
        Text(body, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
      }
    }
  }
}

@Composable
private fun DraftStatus(validationState: ValidationState, conflictCount: Int) {
  val colors = MaterialTheme.planoraColors
  val container = when (validationState) {
    ValidationState.NOT_VALIDATED -> MaterialTheme.colorScheme.primaryContainer
    ValidationState.VALID -> colors.successContainer
    ValidationState.INVALID -> colors.dangerContainer
  }
  val content = when (validationState) {
    ValidationState.NOT_VALIDATED -> MaterialTheme.colorScheme.onPrimaryContainer
    ValidationState.VALID -> colors.success
    ValidationState.INVALID -> colors.danger
  }
  val label = when (validationState) {
    ValidationState.NOT_VALIDATED -> "Not validated"
    ValidationState.VALID -> "Validated"
    ValidationState.INVALID -> "$conflictCount conflict${if (conflictCount == 1) "" else "s"}"
  }
  Surface(
    color = container,
    shape = RoundedCornerShape(20.dp),
  ) {
    Row(
      Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
      horizontalArrangement = Arrangement.spacedBy(6.dp),
      verticalAlignment = Alignment.CenterVertically,
    ) {
      Icon(
        if (validationState == ValidationState.VALID) Icons.Rounded.CheckCircle else Icons.Rounded.Lock,
        contentDescription = null,
        tint = content,
        modifier = Modifier.size(16.dp),
      )
      Text(
        label,
        color = content,
        style = MaterialTheme.typography.labelMedium,
      )
    }
  }
}

@Composable
private fun DetailLine(label: String, value: String) {
  Column {
    Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.labelMedium)
    Text(value, style = MaterialTheme.typography.bodyLarge)
  }
}

@Composable
internal fun ReviewScreen(
  state: PlanoraUiState,
  onImprove: () -> Unit,
  onCancelImprove: () -> Unit,
  onValidate: () -> Unit,
  onNavigate: (Destination) -> Unit,
) {
  val workspace = state.workspace
  if (workspace == null) {
    EmptySchedule()
    return
  }
  LazyColumn(
    Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background),
    contentPadding = PaddingValues(16.dp),
    verticalArrangement = Arrangement.spacedBy(16.dp),
  ) {
    item {
      SectionTitle("Review the draft", "Validate feasibility first, then improve everyday quality.")
    }
    item {
      Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        MetricCard("Activities", workspace.events.size.toString(), Icons.Rounded.CalendarMonth, Modifier.weight(1f))
        MetricCard(
          "Hard conflicts",
          if (workspace.validationState == ValidationState.NOT_VALIDATED) "Not checked" else workspace.hardConflicts.size.toString(),
          Icons.Rounded.Lock,
          Modifier.weight(1f),
        )
      }
    }
    item {
      ValidationReviewCard(workspace)
    }
    if (workspace.validationState != ValidationState.VALID) {
      item {
        OutlinedButton(
          onClick = onValidate,
          enabled = !state.busy && state.runningJob == null,
          modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
        ) {
          Icon(Icons.Rounded.CheckCircle, contentDescription = null)
          Spacer(Modifier.width(8.dp))
          Text(if (workspace.validationState == ValidationState.NOT_VALIDATED) "Validate timetable" else "Validate again")
        }
      }
    }
    item {
      if (state.runningJob != null) {
        JobProgressPanel(state.runningJob, onCancelImprove)
      } else {
        Button(
          onClick = onImprove,
          enabled = !state.busy && state.principal?.canRunSolver == true,
          modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
        ) {
          Icon(Icons.Rounded.AutoAwesome, contentDescription = null)
          Spacer(Modifier.width(8.dp))
          Text(if (workspace.validationState == ValidationState.INVALID) "Repair and improve" else "Improve this schedule")
        }
      }
    }
    item {
      OutlinedButton(onClick = { onNavigate(Destination.SCHEDULE) }, modifier = Modifier.fillMaxWidth()) {
        Text("Return to timetable")
      }
    }
  }
}

@Composable
private fun ValidationReviewCard(workspace: ScheduleWorkspace) {
  val colors = MaterialTheme.planoraColors
  val containerColor = when (workspace.validationState) {
    ValidationState.NOT_VALIDATED -> MaterialTheme.colorScheme.primaryContainer
    ValidationState.VALID -> colors.successContainer
    ValidationState.INVALID -> colors.dangerContainer
  }
  val contentColor = when (workspace.validationState) {
    ValidationState.NOT_VALIDATED -> MaterialTheme.colorScheme.onPrimaryContainer
    ValidationState.VALID -> colors.success
    ValidationState.INVALID -> colors.danger
  }
  val summary = when (workspace.validationState) {
    ValidationState.NOT_VALIDATED -> "This draft has not been validated. An empty conflict list is not yet proof of feasibility."
    ValidationState.VALID -> "Validated. No hard conflicts were reported, so this draft is ready for a quality pass."
    ValidationState.INVALID -> "Validation found ${workspace.hardConflicts.size} hard conflict${if (workspace.hardConflicts.size == 1) "" else "s"}."
  }
  Card(
    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    shape = MaterialTheme.shapes.large,
  ) {
    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
      Text("Validation", style = MaterialTheme.typography.titleLarge)
      Surface(color = containerColor, contentColor = contentColor, shape = MaterialTheme.shapes.medium) {
        Text(summary, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(12.dp))
      }
      if (workspace.validationState == ValidationState.INVALID) {
        workspace.hardConflicts.take(8).forEach { conflict ->
          Text("• ${plainConflict(conflict)}", color = contentColor, style = MaterialTheme.typography.bodyMedium)
        }
        if (workspace.hardConflicts.size > 8) {
          Text(
            "+ ${workspace.hardConflicts.size - 8} more",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
          )
        }
      }
    }
  }
}

@Composable
private fun MetricCard(label: String, value: String, icon: ImageVector, modifier: Modifier = Modifier) {
  Card(
    modifier,
    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    shape = MaterialTheme.shapes.medium,
  ) {
    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
      Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
      Text(value, style = MaterialTheme.typography.headlineSmall)
      Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
  }
}

@Composable
internal fun ProjectsScreen(
  projects: List<ProjectSummary>,
  loadError: String? = null,
  canWrite: Boolean = false,
  canSave: Boolean = false,
  onRetry: () -> Unit = {},
  onSave: (String) -> Unit = {},
  onOpen: (ProjectSummary) -> Unit,
  onRename: (ProjectSummary, String) -> Unit = { _, _ -> },
  onDelete: (ProjectSummary) -> Unit = {},
) {
  var editing by remember { mutableStateOf<ProjectSummary?>(null) }
  var deleting by remember { mutableStateOf<ProjectSummary?>(null) }
  var newName by remember { mutableStateOf("") }
  var saveName by remember { mutableStateOf("") }
  editing?.let { project ->
    AlertDialog(
      onDismissRequest = { editing = null },
      title = { Text("Rename project") },
      text = { OutlinedTextField(newName, { newName = it }, label = { Text("Project name") }, singleLine = true) },
      confirmButton = { TextButton(onClick = { onRename(project, newName.trim()); editing = null }, enabled = newName.isNotBlank()) { Text("Rename") } },
      dismissButton = { TextButton(onClick = { editing = null }) { Text("Cancel") } },
    )
  }
  deleting?.let { project ->
    AlertDialog(
      onDismissRequest = { deleting = null },
      title = { Text("Delete ${project.name}?") },
      text = { Text("This removes the saved project. The timetable currently open on this device is not discarded.") },
      confirmButton = { TextButton(onClick = { onDelete(project); deleting = null }) { Text("Delete") } },
      dismissButton = { TextButton(onClick = { deleting = null }) { Text("Cancel") } },
    )
  }
  LazyColumn(
    Modifier.fillMaxSize(),
    contentPadding = PaddingValues(22.dp),
    verticalArrangement = Arrangement.spacedBy(12.dp),
  ) {
    item { SectionTitle("Projects", "Save the current workspace or reopen a tenant-scoped timetable snapshot.") }
    if (canWrite) {
      item {
        Card(
          colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
          border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
          shape = MaterialTheme.shapes.large,
        ) {
          Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Save current workspace", style = MaterialTheme.typography.titleLarge)
            OutlinedTextField(saveName, { saveName = it }, label = { Text("Project name") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Button(
              onClick = { onSave(saveName.trim()); saveName = "" },
              enabled = canSave && saveName.isNotBlank(),
              modifier = Modifier.fillMaxWidth(),
            ) { Text("Save project") }
            if (!canSave) Text("Load or import timetable data before saving.", color = MaterialTheme.colorScheme.onSurfaceVariant)
          }
        }
      }
    }
    if (!loadError.isNullOrBlank()) {
      item {
        Surface(
          color = MaterialTheme.colorScheme.errorContainer,
          contentColor = MaterialTheme.colorScheme.onErrorContainer,
          shape = MaterialTheme.shapes.medium,
        ) {
          Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("Saved projects are unavailable", style = MaterialTheme.typography.titleMedium)
            Text(loadError, style = MaterialTheme.typography.bodyMedium)
            OutlinedButton(onClick = onRetry) { Text("Retry") }
          }
        }
      }
    } else if (projects.isEmpty()) {
      item {
        EmptyCard(Icons.Rounded.FolderOpen, "No saved projects", "Build or import a schedule, then save it from the timetable.")
      }
    } else {
      items(projects, key = { "${it.tenantId}:${it.name}" }) { project ->
        ProjectRow(
          project = project,
          canWrite = canWrite && project.storage != "legacy",
          onOpen = onOpen,
          onRename = { editing = project; newName = project.name },
          onDelete = { deleting = project },
        )
      }
    }
  }
}

@Composable
private fun ProjectRow(
  project: ProjectSummary,
  canWrite: Boolean,
  onOpen: (ProjectSummary) -> Unit,
  onRename: () -> Unit,
  onDelete: () -> Unit,
) {
  Card(
    Modifier.fillMaxWidth().clickable { onOpen(project) },
    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    shape = MaterialTheme.shapes.medium,
  ) {
    Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
      Icon(Icons.Rounded.FolderOpen, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(28.dp))
      Column(Modifier.weight(1f)) {
        Text(project.name, style = MaterialTheme.typography.titleMedium)
        Text(project.tenantId, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
      }
      Column(horizontalAlignment = Alignment.End) {
        TextButton(onClick = { onOpen(project) }) { Text("Open") }
        if (canWrite) {
          Row {
            TextButton(onClick = onRename) { Text("Rename") }
            TextButton(onClick = onDelete) { Text("Delete") }
          }
        }
      }
    }
  }
}

@Composable
internal fun SettingsScreen(
  state: PlanoraUiState,
  canEditBaseUrl: Boolean,
  themeMode: ThemeMode,
  onThemeMode: (ThemeMode) -> Unit,
  onSaveBaseUrl: (String) -> Unit,
  onTutorial: () -> Unit,
  onLogout: () -> Unit,
) {
  val uriHandler = LocalUriHandler.current
  var server by remember(state.apiBaseUrl) { mutableStateOf(state.apiBaseUrl) }
  LazyColumn(
    Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background),
    contentPadding = PaddingValues(16.dp),
    verticalArrangement = Arrangement.spacedBy(16.dp),
  ) {
    item { SectionTitle("Settings", "Your account, hosted connection, appearance, and help.") }
    item {
      SettingsCard("Account", Icons.Rounded.People) {
        val principal = state.principal
        if (principal == null) {
          Text("No account details are available.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
          Text(principal.displayName.ifBlank { principal.userId }, style = MaterialTheme.typography.titleMedium)
          DetailLine("Signed-in account", principal.userId)
          DetailLine("University workspace", principal.tenantId)
          DetailLine("Role", principal.role.replace('_', ' ').replaceFirstChar { it.uppercase() })
        }
      }
    }
    item {
      SettingsCard("Connection", Icons.Rounded.CloudDone) {
        if (canEditBaseUrl) {
          OutlinedTextField(
            value = server,
            onValueChange = { server = it },
            label = { Text("Planora server") },
            supportingText = { Text("HTTPS is required outside local development.") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
          )
          OutlinedButton(onClick = { onSaveBaseUrl(server) }, modifier = Modifier.fillMaxWidth()) {
            Text("Save server address")
          }
        } else {
          ConnectedEndpoint(state.apiBaseUrl)
        }
      }
    }
    item {
      SettingsCard("Appearance", Icons.Rounded.SettingsBrightness) {
        Text("Use the system setting or choose a fixed appearance.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        Row(
          Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
          horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
          ThemeMode.entries.forEach { mode ->
            val icon = when (mode) {
              ThemeMode.SYSTEM -> Icons.Rounded.SettingsBrightness
              ThemeMode.LIGHT -> Icons.Rounded.LightMode
              ThemeMode.DARK -> Icons.Rounded.DarkMode
            }
            FilterChip(
              selected = themeMode == mode,
              onClick = { onThemeMode(mode) },
              label = { Text(mode.name.lowercase().replaceFirstChar { it.uppercase() }) },
              leadingIcon = { Icon(icon, contentDescription = null, modifier = Modifier.size(18.dp)) },
            )
          }
        }
      }
    }
    item {
      SettingsCard("Help", Icons.Rounded.Lightbulb) {
        Text("Replay the plain-language walkthrough at any time.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedButton(onClick = onTutorial, modifier = Modifier.fillMaxWidth()) { Text("Open the Planora guide") }
      }
    }
    item {
      SettingsCard("About", Icons.AutoMirrored.Rounded.MenuBook) {
        DetailLine("App version", BuildConfig.VERSION_NAME)
        DetailLine("Contract", state.catalog?.contractVersion?.ifBlank { "Unavailable" } ?: "Unavailable")
        DetailLine("Backend", state.catalog?.backendId?.ifBlank { "Unavailable" } ?: "Unavailable")
        if (BuildConfig.APP_WEB_URL.isNotBlank()) {
          OutlinedButton(
            onClick = { uriHandler.openUri(BuildConfig.APP_WEB_URL) },
            modifier = Modifier.fillMaxWidth(),
          ) {
            Text("Open Planora on the web")
          }
        }
      }
    }
    item { TextButton(onClick = onLogout, modifier = Modifier.fillMaxWidth()) { Text("Sign out") } }
  }
}

@Composable
private fun SettingsCard(title: String, icon: ImageVector, content: @Composable ColumnScope.() -> Unit) {
  Card(
    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    shape = MaterialTheme.shapes.large,
  ) {
    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
      Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(9.dp)) {
        Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(21.dp))
        Text(title, style = MaterialTheme.typography.titleLarge)
      }
      content()
    }
  }
}

private data class TutorialPage(val id: String, val title: String, val body: String, val icon: ImageVector)

private val tutorialPages = listOf(
  TutorialPage("bring-in", "Bring in your timetable", "Open the Spring 2023 example or import your university data.", Icons.Rounded.ImportExport),
  TutorialPage("check-essentials", "Check the essentials", "Confirm the term, rooms, people, courses, and student groups.", Icons.Rounded.Groups),
  TutorialPage("build-draft", "Build a draft", "Choose Fast, Balanced, or Maximum quality and let Planora place events.", Icons.Rounded.AutoAwesome),
  TutorialPage("review-repair", "Review and repair", "Open a flagged event, understand the issue, and apply a suggested move.", Icons.Rounded.CheckCircle),
  TutorialPage("validate-publish", "Validate and share", "Confirm there are no hard conflicts, then save or export the timetable.", Icons.Rounded.Publish),
)

@Composable
internal fun TutorialScreen(
  page: Int,
  steps: List<TutorialStep> = emptyList(),
  onPrevious: () -> Unit,
  onNext: () -> Unit,
  onFinish: () -> Unit,
) {
  val pages = steps.takeIf { it.isNotEmpty() }?.mapIndexed { index, step ->
    TutorialPage(step.id, step.title, step.body, tutorialPages.getOrElse(index) { tutorialPages.last() }.icon)
  } ?: tutorialPages
  val safePage = page.coerceIn(pages.indices)
  val item = pages[safePage]
  Column(
    Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).safeDrawingPadding()
      .padding(16.dp).verticalScroll(rememberScrollState()),
    verticalArrangement = Arrangement.spacedBy(16.dp),
  ) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
      Image(
        painter = painterResource(R.drawable.planora_elephant),
        contentDescription = null,
        modifier = Modifier.size(48.dp),
      )
      Column {
        Text("Planora guide", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.titleMedium)
        Text(
          "Step ${safePage + 1} of ${pages.size}",
          color = MaterialTheme.colorScheme.onSurfaceVariant,
          style = MaterialTheme.typography.bodySmall,
        )
      }
    }
    MotionAwareContent(targetState = item, label = "tutorial step") { pageItem ->
      Surface(
        color = MaterialTheme.colorScheme.surface,
        shape = MaterialTheme.shapes.extraLarge,
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        modifier = Modifier.fillMaxWidth().heightIn(min = 340.dp),
      ) {
        Column(
          Modifier.padding(22.dp),
          horizontalAlignment = Alignment.CenterHorizontally,
          verticalArrangement = Arrangement.Center,
        ) {
          Surface(color = MaterialTheme.colorScheme.primaryContainer, shape = MaterialTheme.shapes.extraLarge) {
            Icon(
              pageItem.icon,
              contentDescription = null,
              tint = MaterialTheme.colorScheme.primary,
              modifier = Modifier.padding(22.dp).size(62.dp),
            )
          }
          Spacer(Modifier.height(24.dp))
          Text(
            pageItem.title,
            style = MaterialTheme.typography.headlineLarge,
            textAlign = TextAlign.Center,
            modifier = Modifier.semantics { heading() },
          )
          Spacer(Modifier.height(14.dp))
          Text(
            pageItem.body,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyLarge,
            textAlign = TextAlign.Center,
          )
        }
      }
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
      if (safePage > 0) {
        OutlinedButton(onClick = onPrevious, modifier = Modifier.weight(1f).height(52.dp)) {
          Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = null)
          Spacer(Modifier.width(6.dp))
          Text("Back")
        }
      }
      Button(
        onClick = if (safePage == pages.lastIndex) onFinish else onNext,
        modifier = Modifier.weight(1f).height(52.dp),
      ) {
        Text(if (safePage == pages.lastIndex) "Open Planora" else "Next")
        Spacer(Modifier.width(6.dp))
        Icon(if (safePage == pages.lastIndex) Icons.Rounded.Check else Icons.AutoMirrored.Rounded.ArrowForward, contentDescription = null)
      }
    }
    if (safePage < pages.lastIndex) {
      TextButton(onClick = onFinish, modifier = Modifier.align(Alignment.CenterHorizontally)) { Text("Skip for now") }
    }
  }
}

@Composable
private fun EmptySchedule() {
  Box(Modifier.fillMaxSize().padding(22.dp), contentAlignment = Alignment.Center) {
    EmptyCard(Icons.Rounded.CalendarMonth, "No schedule open", "Start a demo, load the Spring 2023 profile, import a file, or open a saved project from Home.")
  }
}

@Composable
private fun EmptyCard(icon: ImageVector, title: String, body: String) {
  Card(
    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    shape = MaterialTheme.shapes.large,
  ) {
    Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
      Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(44.dp))
      Text(title, style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center)
      Text(body, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
    }
  }
}

@Composable
private fun SectionTitle(title: String, body: String) {
  Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
    Text(title, style = MaterialTheme.typography.headlineSmall, modifier = Modifier.semantics { heading() })
    Text(body, color = MaterialTheme.colorScheme.onSurfaceVariant)
  }
}

private fun dayLabel(day: String): String = when (day.uppercase()) {
  "MON" -> "Monday"
  "TUE" -> "Tuesday"
  "WED" -> "Wednesday"
  "THU" -> "Thursday"
  "FRI" -> "Friday"
  "SAT" -> "Saturday"
  "SUN" -> "Sunday"
  else -> day.lowercase().replaceFirstChar { it.uppercase() }
}

private fun slotNumberLabel(slot: Int): String = "Slot ${slot.coerceAtLeast(0) + 1}"

private fun slotRangeLabel(slot: Int, duration: Int): String {
  val start = slot.coerceAtLeast(0) + 1
  val end = start + duration.coerceAtLeast(1) - 1
  return if (start == end) "Slot $start" else "Slots $start–$end"
}

private fun durationLabel(duration: Int): String {
  val safeDuration = duration.coerceAtLeast(1)
  return "$safeDuration slot${if (safeDuration == 1) "" else "s"}"
}

private fun workspaceSummary(workspace: ScheduleWorkspace): String {
  if (workspace.events.isEmpty()) return "No draft built yet"
  val duration = workspace.events.sumOf { it.duration.coerceAtLeast(1) }
  val validation = when (workspace.validationState) {
    ValidationState.NOT_VALIDATED -> "not validated"
    ValidationState.VALID -> "validated"
    ValidationState.INVALID -> "${workspace.hardConflicts.size} hard conflict${if (workspace.hardConflicts.size == 1) "" else "s"}"
  }
  return "${workspace.events.size} activities · ${durationLabel(duration)} scheduled · $validation"
}

@Composable
private fun ConnectedEndpoint(endpoint: String) {
  Surface(
    color = MaterialTheme.colorScheme.surfaceContainerLow,
    shape = MaterialTheme.shapes.medium,
    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    modifier = Modifier.fillMaxWidth().semantics { stateDescription = "Connected" },
  ) {
    Row(
      Modifier.padding(12.dp),
      verticalAlignment = Alignment.CenterVertically,
      horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
      Icon(Icons.Rounded.CloudDone, contentDescription = null, tint = MaterialTheme.planoraColors.success)
      Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text("Connected to hosted Planora", style = MaterialTheme.typography.titleSmall)
        Text(
          endpoint.ifBlank { "Managed production endpoint" },
          color = MaterialTheme.colorScheme.onSurfaceVariant,
          style = MaterialTheme.typography.bodySmall,
          maxLines = 2,
          overflow = TextOverflow.Ellipsis,
        )
      }
    }
  }
}

@Composable
private fun JobProgressPanel(job: JobStatus, onCancel: () -> Unit) {
  val trackingFailed = job.status == "tracking_error"
  Surface(
    color = MaterialTheme.colorScheme.primaryContainer,
    contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
    shape = MaterialTheme.shapes.medium,
    modifier = Modifier.fillMaxWidth().semantics {
      stateDescription = if (job.progress == null) job.message
      else "${job.message}, ${(job.progress.coerceIn(0f, 1f) * 100).toInt()} percent"
    },
  ) {
    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
      Text(job.message.ifBlank { "Improving the timetable" }, style = MaterialTheme.typography.titleSmall)
      if (job.progress == null) {
        LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
      } else {
        LinearProgressIndicator(progress = { job.progress.coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
      }
      OutlinedButton(onClick = onCancel, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) {
        Icon(Icons.Rounded.Cancel, contentDescription = null)
        Spacer(Modifier.width(7.dp))
        Text(if (trackingFailed) "Stop tracking and close schedule" else "Cancel improvement")
      }
    }
  }
}

private fun plainConflict(value: String): String = value
  .replace('_', ' ')
  .replace("activity", "class", ignoreCase = true)
  .trim()

internal fun conflictMentionsActivity(conflict: String, activityId: Int): Boolean =
  Regex("(?i)\\bA$activityId\\b").containsMatchIn(conflict)
