package com.planora.mobile.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowForward
import androidx.compose.material.icons.rounded.AccountCircle
import androidx.compose.material.icons.rounded.AdminPanelSettings
import androidx.compose.material.icons.rounded.Analytics
import androidx.compose.material.icons.rounded.CloudDone
import androidx.compose.material.icons.rounded.CalendarMonth
import androidx.compose.material.icons.rounded.DataObject
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Email
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.Group
import androidx.compose.material.icons.rounded.Insights
import androidx.compose.material.icons.rounded.Key
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.rounded.School
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import com.planora.mobile.domain.AccessSnapshot
import com.planora.mobile.domain.AccountSnapshot
import com.planora.mobile.domain.AdminSnapshot
import com.planora.mobile.domain.CatalogItem
import com.planora.mobile.domain.DataRow
import com.planora.mobile.domain.Principal
import com.planora.mobile.domain.MoveTarget
import com.planora.mobile.domain.ScheduleWorkspace
import com.planora.mobile.domain.SolverSettings
import java.text.DateFormat
import java.util.Date

private data class ToolLink(
  val destination: Destination,
  val title: String,
  val body: String,
  val icon: ImageVector,
  val visible: (Principal) -> Boolean = { true },
)

private val toolLinks = listOf(
  ToolLink(Destination.DATA, "Data and scenarios", "Open a preset or import your university CSV.", Icons.Rounded.DataObject),
  ToolLink(Destination.ADVANCED, "Advanced solver", "Use specialist engine, room, and improvement controls.", Icons.Rounded.Tune),
  ToolLink(Destination.INSIGHTS, "Fairness and utilization", "Compare staff, group, and room load.", Icons.Rounded.Insights),
  ToolLink(Destination.ACCOUNT, "Account and organizations", "Groups, invite codes, passwords, and sessions.", Icons.Rounded.AccountCircle),
  ToolLink(Destination.PLATFORM, "Platform parity", "Inspect the shared backend capability manifest.", Icons.Rounded.CloudDone),
  ToolLink(Destination.ACCESS, "Users and invites", "Manage groups, roles, memberships, and invite codes.", Icons.Rounded.Group) {
    "access:manage" in it.permissions
  },
  ToolLink(Destination.ADMIN, "Global administration", "Runtime, analytics, audit exports, and email delivery.", Icons.Rounded.AdminPanelSettings) {
    it.isGlobalAdmin
  },
  ToolLink(Destination.SETTINGS, "App settings", "Appearance, connection, help, and sign out.", Icons.Rounded.Settings),
)

@Composable
internal fun MoveTargetsSheet(
  eventTitle: String,
  targets: List<MoveTarget>,
  onMove: (MoveTarget) -> Unit,
  onCancel: () -> Unit,
) {
  val allowed = targets.filter { it.allowed }
  LazyColumn(
    Modifier.fillMaxWidth().heightIn(max = 620.dp),
    contentPadding = PaddingValues(start = 20.dp, end = 20.dp, bottom = 32.dp),
    verticalArrangement = Arrangement.spacedBy(10.dp),
  ) {
    item { FeatureHeader("Move $eventTitle", "Only placements accepted by the hosted constraint engine are selectable.") }
    if (allowed.isEmpty()) {
      item { Text("No safe alternatives are available for this class.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
    } else {
      items(allowed, key = { "${it.week}:${it.day}:${it.slot}:${it.roomId}:${it.staffId}" }) { target ->
        Card(
          modifier = Modifier.fillMaxWidth().clickable { onMove(target) },
          colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
          border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        ) {
          Row(
            Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
          ) {
            Icon(Icons.Rounded.CalendarMonth, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            Column(Modifier.weight(1f)) {
              Text("Week ${target.week} · ${target.day} · slot ${target.slot + 1}", fontWeight = FontWeight.SemiBold)
              Text(
                target.explanation.ifBlank { "Safe placement confirmed by Planora" },
                color = MaterialTheme.colorScheme.onSurfaceVariant,
              )
            }
            Text("Move", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.SemiBold)
          }
        }
      }
    }
    item { TextButton(onClick = onCancel, modifier = Modifier.fillMaxWidth()) { Text("Cancel") } }
  }
}

@Composable
internal fun ToolsScreen(principal: Principal, onNavigate: (Destination) -> Unit) {
  LazyColumn(
    Modifier.fillMaxSize(),
    contentPadding = PaddingValues(16.dp),
    verticalArrangement = Arrangement.spacedBy(12.dp),
  ) {
    item { FeatureHeader("Tools", "Everything available in the web workspace, adapted for Android.") }
    items(toolLinks.filter { it.visible(principal) }, key = { it.destination.name }) { item ->
      Card(
        modifier = Modifier.fillMaxWidth().clickable { onNavigate(item.destination) },
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
      ) {
        Row(
          Modifier.padding(16.dp),
          verticalAlignment = Alignment.CenterVertically,
          horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
          Icon(item.icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(30.dp))
          Column(Modifier.weight(1f)) {
            Text(item.title, style = MaterialTheme.typography.titleMedium)
            Text(item.body, color = MaterialTheme.colorScheme.onSurfaceVariant)
          }
          Icon(Icons.AutoMirrored.Rounded.ArrowForward, contentDescription = null)
        }
      }
    }
  }
}

@Composable
internal fun DataScreen(
  state: PlanoraUiState,
  onScenario: (CatalogItem) -> Unit,
  onImport: (Map<String, String>) -> Unit,
  onMode: (String) -> Unit,
) {
  var fieldMapText by remember {
    mutableStateOf("week=week, day=day, slot=slot, course=course, group=group, room=room, kind=kind, lecturer=lecturer, ta=ta")
  }
  val fieldMap = fieldMapText.split(',').mapNotNull { part ->
    val values = part.split('=', limit = 2).map(String::trim)
    values.takeIf { it.size == 2 && it.all(String::isNotBlank) }?.let { it[0] to it[1] }
  }.toMap()
  LazyColumn(
    Modifier.fillMaxSize(),
    contentPadding = PaddingValues(16.dp),
    verticalArrangement = Arrangement.spacedBy(14.dp),
  ) {
    item { FeatureHeader("Data workspace", "Start with a server preset or bring the timetable you already maintain.") }
    state.workspace?.let { workspace ->
      item {
        FeatureCard("Loaded timetable") {
          FactRow("Activities", workspace.events.size.toString())
          FactRow("Courses", workspace.courses.size.toString())
          FactRow("Rooms", workspace.rooms.size.toString())
          FactRow("Staff", workspace.staff.size.toString())
        }
      }
    }
    item { Text("Choose timetable data", style = MaterialTheme.typography.titleLarge) }
    items(state.catalog?.scenarios.orEmpty(), key = { it.id }) { scenario ->
      Card(
        modifier = Modifier.fillMaxWidth().clickable(
          enabled = scenario.id != "import" || state.principal?.canWriteSchedule == true,
        ) { if (scenario.id == "import") onImport(fieldMap) else onScenario(scenario) },
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
      ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
          Text(scenario.label, style = MaterialTheme.typography.titleMedium)
          Text(scenario.description, color = MaterialTheme.colorScheme.onSurfaceVariant)
          Text(
            if (scenario.id == "import") "Choose CSV" else "Open scenario",
            color = MaterialTheme.colorScheme.primary,
            fontWeight = FontWeight.SemiBold,
          )
        }
      }
    }
    item {
      FeatureCard("CSV column mapping") {
        Text("Match Planora fields to your CSV headers. The defaults fit the web app's import format.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedTextField(
          value = fieldMapText,
          onValueChange = { fieldMapText = it },
          label = { Text("field=column pairs") },
          minLines = 3,
          modifier = Modifier.fillMaxWidth(),
        )
        Button(
          onClick = { onImport(fieldMap) },
          enabled = state.principal?.canWriteSchedule == true && fieldMap.keys.containsAll(listOf("week", "day", "slot", "course")),
          modifier = Modifier.fillMaxWidth(),
        ) { Text("Choose CSV file") }
      }
    }
    item { Text("Default planning approach", style = MaterialTheme.typography.titleLarge) }
    item {
      Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        state.catalog?.modes.orEmpty().forEach { mode ->
          FilterChip(
            selected = state.selectedModeId == mode.id,
            onClick = { onMode(mode.id) },
            label = { Text(mode.label) },
          )
        }
      }
    }
  }
}

@Composable
internal fun AdvancedScreen(
  settings: SolverSettings,
  overridesEnabled: Boolean,
  onChange: (SolverSettings) -> Unit,
  onUseDefaults: () -> Unit,
) {
  LazyColumn(
    Modifier.fillMaxSize(),
    contentPadding = PaddingValues(16.dp),
    verticalArrangement = Arrangement.spacedBy(14.dp),
  ) {
    item { FeatureHeader("Advanced", "Specialist controls for research, verification, or measured institutional needs.") }
    item {
      FeatureCard(if (overridesEnabled) "Specialist overrides active" else "Mode defaults active") {
        Text(
          if (overridesEnabled) "These values override the server-owned mode for the next solve or improvement."
          else "Fast, Balanced, or Maximum quality is controlled by the shared backend.",
          color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (overridesEnabled) OutlinedButton(onClick = onUseDefaults) { Text("Use mode defaults") }
      }
    }
    item {
      FeatureCard("Engine and room strategy") {
        ChoiceRow("Room mode", listOf("greedy", "partitioned", "cp_rooms", "decomposed"), settings.roomMode) {
          onChange(settings.copy(roomMode = it))
        }
        ChoiceRow("Profile", listOf("university_fast", "balanced", "quality_first", "fairness_first", "research_adaptive"), settings.profile) {
          onChange(settings.copy(profile = it))
        }
        NumberSetting("Time limit seconds", settings.timeLimitSeconds, 1..3600) { onChange(settings.copy(timeLimitSeconds = it)) }
        NumberSetting("Workers", settings.workers, 1..64) { onChange(settings.copy(workers = it)) }
        ToggleSetting("Use CP objective", settings.useObjective) { onChange(settings.copy(useObjective = it)) }
        ToggleSetting("Force same weekly pattern", settings.forceRepeatWeeklyPattern) {
          onChange(settings.copy(forceRepeatWeeklyPattern = it))
        }
      }
    }
    item {
      FeatureCard("Improvement budget") {
        NumberSetting("Iterations", settings.improveIterations, 1..200000) { onChange(settings.copy(improveIterations = it)) }
        NumberSetting("Maximum seconds", settings.improveSeconds, 1..3600) { onChange(settings.copy(improveSeconds = it)) }
        NumberSetting("Progress cadence", settings.progressEvery, 1..10000) { onChange(settings.copy(progressEvery = it)) }
      }
    }
  }
}

@Composable
private fun ChoiceRow(label: String, values: List<String>, selected: String, onSelect: (String) -> Unit) {
  Text(label, style = MaterialTheme.typography.labelLarge)
  Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
    values.forEach { value ->
      FilterChip(selected = selected == value, onClick = { onSelect(value) }, label = { Text(value.replace('_', ' ')) })
    }
  }
}

@Composable
private fun NumberSetting(label: String, value: Int, range: IntRange, onChange: (Int) -> Unit) {
  OutlinedTextField(
    value = value.toString(),
    onValueChange = { raw -> raw.toIntOrNull()?.coerceIn(range)?.let(onChange) },
    label = { Text(label) },
    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
    singleLine = true,
    modifier = Modifier.fillMaxWidth(),
  )
}

@Composable
private fun ToggleSetting(label: String, checked: Boolean, onChecked: (Boolean) -> Unit) {
  Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
    Text(label, Modifier.weight(1f))
    Switch(checked = checked, onCheckedChange = onChecked)
  }
}

@Composable
internal fun AccountScreen(
  principal: Principal,
  account: AccountSnapshot,
  onRefresh: () -> Unit,
  onJoinInvite: (String) -> Unit,
  onSwitchOrganization: (String) -> Unit,
  onChangePassword: (String, String) -> Unit,
  onRevokeSessions: () -> Unit,
) {
  var invite by remember { mutableStateOf("") }
  var currentPassword by remember { mutableStateOf("") }
  var newPassword by remember { mutableStateOf("") }
  LazyColumn(
    Modifier.fillMaxSize(),
    contentPadding = PaddingValues(16.dp),
    verticalArrangement = Arrangement.spacedBy(14.dp),
  ) {
    item { FeatureHeader("My account", "Organizations, groups, security, and active sessions.") }
    item {
      FeatureCard("Profile") {
        FactRow("Email / user", principal.userId)
        FactRow("Organization", principal.tenantId)
        FactRow("Role", principal.role.replace('_', ' '))
        FactRow("Groups", principal.groups.joinToString().ifBlank { "None" })
        OutlinedButton(onClick = onRefresh, modifier = Modifier.fillMaxWidth()) {
          Icon(Icons.Rounded.Refresh, contentDescription = null)
          Text("Refresh account")
        }
      }
    }
    item {
      FeatureCard("Organizations") {
        if (account.organizations.isEmpty()) Text("No linked organizations yet.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        account.organizations.forEach { organization ->
          Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
              Text(organization.displayName, fontWeight = FontWeight.SemiBold)
              Text("${organization.tenantId} · ${organization.role} · ${organization.groupCount} groups", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            TextButton(
              enabled = !organization.active && organization.enabled,
              onClick = { onSwitchOrganization(organization.tenantId) },
            ) { Text(if (organization.active) "Active" else "Switch") }
          }
        }
      }
    }
    item {
      FeatureCard("Join another group") {
        OutlinedTextField(invite, { invite = it }, label = { Text("Invite code") }, modifier = Modifier.fillMaxWidth())
        Button(
          onClick = { onJoinInvite(invite.trim()); invite = "" },
          enabled = invite.trim().length >= 8,
          modifier = Modifier.fillMaxWidth(),
        ) { Text("Join group") }
      }
    }
    item {
      FeatureCard("Security") {
        OutlinedTextField(
          currentPassword,
          { currentPassword = it },
          label = { Text("Current password") },
          visualTransformation = PasswordVisualTransformation(),
          modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
          newPassword,
          { newPassword = it },
          label = { Text("New password · at least 10 characters") },
          visualTransformation = PasswordVisualTransformation(),
          modifier = Modifier.fillMaxWidth(),
        )
        Button(
          onClick = {
            onChangePassword(currentPassword, newPassword)
            currentPassword = ""
            newPassword = ""
          },
          enabled = currentPassword.isNotBlank() && newPassword.length >= 10,
          modifier = Modifier.fillMaxWidth(),
        ) { Text("Change password") }
        OutlinedButton(onClick = onRevokeSessions, modifier = Modifier.fillMaxWidth()) { Text("Revoke other sessions") }
      }
    }
    item { Text("Active sessions", style = MaterialTheme.typography.titleLarge) }
    if (account.sessions.isEmpty()) item { Text("No session rows available.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
    items(account.sessions, key = { it.sessionId }) { session ->
      FeatureCard(session.sessionId.take(12).ifBlank { "Session" }) {
        FactRow("Status", if (session.active) "Active" else "Revoked or expired")
        FactRow("Device", if (session.current) "This device" else "Other session")
        FactRow("Last seen", DateFormat.getDateTimeInstance().format(Date(session.lastSeenAt * 1000)))
      }
    }
  }
}

@Composable
internal fun InsightsScreen(workspace: ScheduleWorkspace?) {
  val staff = remember(workspace) { workspace?.events.orEmpty().groupingBy { it.staff }.eachCount().entries.sortedByDescending { it.value } }
  val groups = remember(workspace) { workspace?.events.orEmpty().flatMap { it.groups }.groupingBy { it }.eachCount().entries.sortedByDescending { it.value } }
  val usedRooms = remember(workspace) { workspace?.events.orEmpty().map { it.room }.filterNot { it == "Room pending" }.toSet().size }
  LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
    item { FeatureHeader("Fairness and utilization", "Workload totals expose imbalances that a single penalty can hide.") }
    if (workspace == null || workspace.events.isEmpty()) {
      item { FeatureCard("No schedule analytics yet") { Text("Load a scenario and run the solver first.") } }
    } else {
      item {
        FeatureCard("Current draft") {
          FactRow("Scheduled activities", workspace.events.size.toString())
          FactRow("Staff load spread", spread(staff.map { it.value }).toString())
          FactRow("Group load spread", spread(groups.map { it.value }).toString())
          FactRow("Rooms used", "$usedRooms / ${workspace.rooms.size}")
        }
      }
      item { Text("Staff workload", style = MaterialTheme.typography.titleLarge) }
      items(staff.take(20), key = { it.key }) { FactCard(it.key, "${it.value} scheduled activities") }
      item { Text("Student-group workload", style = MaterialTheme.typography.titleLarge) }
      items(groups.take(20), key = { it.key }) { FactCard(it.key, "${it.value} scheduled activities") }
    }
  }
}

private fun spread(values: List<Int>): Int = (values.maxOrNull() ?: 0) - (values.minOrNull() ?: 0)

@Composable
internal fun PlatformScreen(parity: DataRow?, onRefresh: () -> Unit) {
  LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
    item { FeatureHeader("Platform parity", "The capability manifest shared by web, desktop, and Android.") }
    item { OutlinedButton(onClick = onRefresh, modifier = Modifier.fillMaxWidth()) { Text("Refresh platform manifest") } }
    if (parity == null) item { Text("No platform manifest loaded.") }
    else items(parity.values.entries.toList(), key = { it.key }) { (key, value) -> FactCard(key.replace('_', ' '), value) }
  }
}

@Composable
internal fun AccessScreen(
  principal: Principal,
  snapshot: AccessSnapshot?,
  onRefresh: () -> Unit,
  onChange: (Map<String, Any?>) -> Unit,
) {
  var tenantId by remember(principal.tenantId) { mutableStateOf(principal.tenantId) }
  var userId by remember { mutableStateOf("") }
  var groupId by remember { mutableStateOf("") }
  var groupName by remember { mutableStateOf("") }
  var role by remember { mutableStateOf("student") }
  var staffId by remember { mutableStateOf("") }
  var studentGroupId by remember { mutableStateOf("") }
  var scopeType by remember { mutableStateOf("tenant") }
  var scopeId by remember { mutableStateOf("*") }
  var inviteId by remember { mutableStateOf("") }
  var inviteCode by remember { mutableStateOf("") }
  var inviteLabel by remember { mutableStateOf("") }
  var deleteUser by remember { mutableStateOf<String?>(null) }
  if (deleteUser != null) {
    AlertDialog(
      onDismissRequest = { deleteUser = null },
      title = { Text("Delete account?") },
      text = { Text("This permanently removes the account, sessions, memberships, and authentication tokens. Audit history remains.") },
      confirmButton = {
        TextButton(onClick = {
          onChange(mapOf("action" to "delete_user", "user_id" to deleteUser, "tenant_id" to tenantId))
          deleteUser = null
        }) { Text("Delete") }
      },
      dismissButton = { TextButton(onClick = { deleteUser = null }) { Text("Cancel") } },
    )
  }
  LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
    item { FeatureHeader("Users and invites", "Manage the same tenant-scoped access controls as the web app.") }
    item { OutlinedButton(onClick = onRefresh, modifier = Modifier.fillMaxWidth()) { Text("Refresh directory") } }
    item {
      FeatureCard("Organization and role") {
        if (principal.isGlobalAdmin) Field("Organization", tenantId) { tenantId = it }
        Field("User ID", userId) { userId = it }
        ChoiceRow("Role", listOf("student", "ta", "professor", "uni_admin") + if (principal.isGlobalAdmin) listOf("admin") else emptyList(), role) { role = it }
        Button(onClick = { onChange(mapOf("action" to "set_role", "user_id" to userId, "role" to role, "tenant_id" to tenantId)) }, enabled = userId.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text("Assign role") }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
          OutlinedButton(onClick = { onChange(mapOf("action" to "set_disabled", "user_id" to userId, "disabled" to true, "tenant_id" to tenantId)) }, enabled = userId.isNotBlank(), modifier = Modifier.weight(1f)) { Text("Disable") }
          OutlinedButton(onClick = { onChange(mapOf("action" to "set_disabled", "user_id" to userId, "disabled" to false, "tenant_id" to tenantId)) }, enabled = userId.isNotBlank(), modifier = Modifier.weight(1f)) { Text("Enable") }
        }
        if (principal.isGlobalAdmin) OutlinedButton(onClick = { deleteUser = userId }, enabled = userId.isNotBlank() && userId != principal.userId, modifier = Modifier.fillMaxWidth()) {
          Icon(Icons.Rounded.Delete, contentDescription = null)
          Text("Delete user")
        }
      }
    }
    item {
      FeatureCard("Groups and membership") {
        Field("New group name", groupName) { groupName = it }
        Button(onClick = { onChange(mapOf("action" to "create_group", "name" to groupName, "tenant_id" to tenantId)); groupName = "" }, enabled = groupName.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text("Create group") }
        Field("Group ID", groupId) { groupId = it }
        Button(onClick = { onChange(mapOf("action" to "set_membership", "user_id" to userId, "group_id" to groupId, "enabled" to true, "tenant_id" to tenantId)) }, enabled = userId.isNotBlank() && groupId.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text("Add member") }
        Field("Staff ID", staffId) { staffId = it }
        Field("Student group ID", studentGroupId) { studentGroupId = it }
        OutlinedButton(onClick = { onChange(mapOf("action" to "link_schedule_identity", "user_id" to userId, "staff_id" to staffId, "student_group_id" to studentGroupId, "tenant_id" to tenantId)) }, enabled = userId.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text("Link schedule identity") }
      }
    }
    item {
      FeatureCard("Scoped group role") {
        Field("Scope type", scopeType) { scopeType = it }
        Field("Scope ID", scopeId) { scopeId = it }
        Button(onClick = { onChange(mapOf("action" to "bind_role", "principal_type" to "group", "principal_id" to groupId, "role" to role, "scope_type" to scopeType, "scope_id" to if (scopeType == "tenant") "*" else scopeId, "tenant_id" to tenantId)) }, enabled = groupId.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text("Bind group role") }
      }
    }
    item {
      FeatureCard("Invite codes") {
        Field("Label", inviteLabel) { inviteLabel = it }
        Field("Code · blank creates one", inviteCode) { inviteCode = it }
        Button(onClick = { onChange(mapOf("action" to "create_invite", "group_id" to groupId, "role" to role, "label" to inviteLabel, "code" to inviteCode, "tenant_id" to tenantId)) }, enabled = groupId.isNotBlank(), modifier = Modifier.fillMaxWidth()) { Text("Create invite") }
        Field("Existing invite ID", inviteId) { inviteId = it }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
          OutlinedButton(onClick = { onChange(mapOf("action" to "rotate_invite", "invite_id" to inviteId, "code" to inviteCode, "label" to inviteLabel, "tenant_id" to tenantId)) }, enabled = inviteId.isNotBlank(), modifier = Modifier.weight(1f)) { Text("Rotate") }
          OutlinedButton(onClick = { onChange(mapOf("action" to "set_invite_disabled", "invite_id" to inviteId, "disabled" to true, "tenant_id" to tenantId)) }, enabled = inviteId.isNotBlank(), modifier = Modifier.weight(1f)) { Text("Disable") }
        }
        snapshot?.newInviteCode?.takeIf { it.isNotBlank() }?.let { Text("New invite code: $it", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold) }
      }
    }
    item { Text("Directory", style = MaterialTheme.typography.titleLarge) }
    items(snapshot?.accountTenants.orEmpty(), key = { "${it["tenant_id"]}:${it["user_id"]}" }) { row ->
      FactCard(row["display_name"].ifBlank { row["user_id"] }, "${row["role"]} · ${row["tenant_id"]} · ${if (row["disabled"] == "1") "disabled" else "active"}")
    }
    item {
      Text(
        "${snapshot?.groups?.size ?: 0} groups · ${snapshot?.memberships?.size ?: 0} memberships · ${snapshot?.roleBindings?.size ?: 0} scoped roles · ${snapshot?.inviteCodes?.size ?: 0} invites",
        color = MaterialTheme.colorScheme.onSurfaceVariant,
      )
    }
  }
}

@Composable
internal fun AdminScreen(
  snapshot: AdminSnapshot?,
  onRefresh: (Map<String, String>) -> Unit,
  onEmailTest: (String) -> Unit,
  onExport: (String, Map<String, String>) -> Unit,
) {
  var days by remember { mutableStateOf("30") }
  var tenant by remember { mutableStateOf("") }
  var event by remember { mutableStateOf("") }
  var path by remember { mutableStateOf("") }
  var action by remember { mutableStateOf("") }
  var user by remember { mutableStateOf("") }
  var email by remember { mutableStateOf("") }
  val filters = mapOf("days" to days, "tenant_id" to tenant, "event_name" to event, "path" to path, "action" to action, "user_id" to user).filterValues { it.isNotBlank() }
  LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
    item { FeatureHeader("Global administration", "Runtime health, consented analytics, audit events, and email delivery.") }
    item {
      FeatureCard("System summary") {
        FactRow("API", snapshot?.system?.get("ok")?.ifBlank { "unknown" } ?: "unknown")
        FactRow("Database", snapshot?.system?.get("database")?.ifBlank { "n/a" } ?: "n/a")
        FactRow("Runtime", snapshot?.status?.get("api")?.ifBlank { "n/a" } ?: "n/a")
        FactRow("Analytics events", snapshot?.analytics?.get("events")?.ifBlank { "0" } ?: "0")
        FactRow("Visitors", snapshot?.analytics?.get("visitors")?.ifBlank { "0" } ?: "0")
      }
    }
    item {
      FeatureCard("Filters and exports") {
        Field("Days", days) { days = it.filter(Char::isDigit) }
        Field("Tenant", tenant) { tenant = it }
        Field("Event", event) { event = it }
        Field("Path", path) { path = it }
        Field("Audit action", action) { action = it }
        Field("Audit user", user) { user = it }
        Button(onClick = { onRefresh(filters) }, modifier = Modifier.fillMaxWidth()) { Text("Apply filters") }
        OutlinedButton(onClick = { onExport("analytics", filters) }, modifier = Modifier.fillMaxWidth()) { Text("Export analytics CSV") }
        OutlinedButton(onClick = { onExport("audit", filters) }, modifier = Modifier.fillMaxWidth()) { Text("Export audit CSV") }
      }
    }
    item {
      FeatureCard("Email deliverability") {
        Field("Recipient", email) { email = it }
        Button(onClick = { onEmailTest(email) }, enabled = email.contains('@'), modifier = Modifier.fillMaxWidth()) {
          Icon(Icons.Rounded.Email, contentDescription = null)
          Text("Send test email")
        }
      }
    }
    item { Text("Recent audit events", style = MaterialTheme.typography.titleLarge) }
    if (snapshot?.auditEvents.isNullOrEmpty()) item { Text("No audit events in this filter.") }
    items(snapshot?.auditEvents.orEmpty(), key = { it["id"] }) { row ->
      FactCard(row["action"].ifBlank { "Audit event" }, "${row["tenant_id"]} · ${row["user_id"]}")
    }
  }
}

@Composable
private fun FeatureHeader(title: String, body: String) {
  Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
    Text(title, style = MaterialTheme.typography.headlineLarge, modifier = Modifier.semantics { heading() })
    Text(body, color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyLarge)
  }
}

@Composable
private fun FeatureCard(title: String, content: @Composable ColumnScope.() -> Unit) {
  Card(
    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    modifier = Modifier.fillMaxWidth(),
  ) {
    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
      Text(title, style = MaterialTheme.typography.titleLarge)
      content()
    }
  }
}

@Composable
private fun FactRow(label: String, value: String) {
  Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
    Text(label, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
    Text(value, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1.3f))
  }
}

@Composable
private fun FactCard(title: String, body: String) {
  Card(
    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    modifier = Modifier.fillMaxWidth(),
  ) {
    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
      Text(title, fontWeight = FontWeight.SemiBold)
      Text(body, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
  }
}

@Composable
private fun Field(label: String, value: String, onChange: (String) -> Unit) {
  OutlinedTextField(value, onChange, label = { Text(label) }, singleLine = true, modifier = Modifier.fillMaxWidth())
}
