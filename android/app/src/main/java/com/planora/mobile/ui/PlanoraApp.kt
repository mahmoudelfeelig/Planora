package com.planora.mobile.ui

import android.content.Context
import android.content.ContextWrapper
import android.net.Uri
import android.os.Build
import android.provider.OpenableColumns
import android.app.Activity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.BackHandler
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.Logout
import androidx.compose.material.icons.rounded.CalendarMonth
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.FolderOpen
import androidx.compose.material.icons.rounded.Home
import androidx.compose.material.icons.rounded.Apps
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.core.view.WindowCompat
import com.planora.mobile.R
import com.planora.mobile.domain.ExportedSchedule
import com.planora.mobile.domain.MoveTarget
import com.planora.mobile.ui.theme.PlanoraTheme
import com.planora.mobile.ui.theme.ThemeMode
import com.planora.mobile.ui.theme.planoraColors
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private val primaryDestinations = listOf(
  Destination.HOME,
  Destination.SCHEDULE,
  Destination.REVIEW,
  Destination.PROJECTS,
  Destination.TOOLS,
)

@Composable
fun PlanoraRoot(viewModel: PlanoraViewModel) {
  val state by viewModel.uiState.collectAsStateWithLifecycle()
  PlanoraTheme(themeMode = state.themeMode) {
    PlanoraSystemBars(state.themeMode)
    PlanoraContent(viewModel, state)
  }
}

@Composable
private fun PlanoraContent(viewModel: PlanoraViewModel, state: PlanoraUiState) {
  val context = LocalContext.current
  val scope = rememberCoroutineScope()
  var exportToWrite by remember { mutableStateOf<ExportedSchedule?>(null) }
  var exportGeneration by remember { mutableStateOf<Long?>(null) }
  var pendingImportGeneration by remember { mutableStateOf<Long?>(null) }
  BackHandler(enabled = state.destination == Destination.TUTORIAL) {
    if (state.tutorialPage > 0) viewModel.tutorialPrevious() else viewModel.finishTutorial()
  }
  val importLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
    val generation = pendingImportGeneration
    pendingImportGeneration = null
    if (uri != null && generation != null && viewModel.isAuthenticatedGeneration(generation)) {
      scope.launch {
        try {
          val (name, content) = withContext(Dispatchers.IO) { readText(context, uri) }
          currentCoroutineContext().ensureActive()
          viewModel.importCsv(name, content, generation)
        } catch (error: CancellationException) {
          throw error
        } catch (error: Exception) {
          viewModel.reportError(
            error.message ?: "Planora could not read that file.",
            generation,
          )
        }
      }
    }
  }
  val exportLauncher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { uri: Uri? ->
    val exported = exportToWrite
    val generation = exportGeneration
    if (uri == null || exported == null || generation == null) {
      exportToWrite = null
      exportGeneration = null
      if (generation != null) viewModel.exportHandled(saved = false, expectedGeneration = generation)
    } else if (!viewModel.isAuthenticatedGeneration(generation)) {
      exportToWrite = null
      exportGeneration = null
    } else {
      scope.launch {
        var failure: Exception? = null
        val saved = try {
          withContext(Dispatchers.IO) {
            context.contentResolver.openOutputStream(uri, "wt")?.bufferedWriter()?.use {
              it.write(exported.content)
            } ?: error("The selected location could not be opened.")
          }
          currentCoroutineContext().ensureActive()
          true
        } catch (error: CancellationException) {
          throw error
        } catch (error: Exception) {
          failure = error
          false
        }
        exportToWrite = null
        exportGeneration = null
        viewModel.exportHandled(saved, generation)
        failure?.let {
          viewModel.reportError(it.message ?: "Planora could not save the export.", generation)
        }
      }
    }
  }

  LaunchedEffect(state.pendingExport, exportToWrite) {
    state.pendingExport?.let { exported ->
      if (exportToWrite == null) {
        viewModel.captureAuthenticatedGeneration()?.let { generation ->
          exportToWrite = exported
          exportGeneration = generation
          exportLauncher.launch(exported.filename)
        }
      }
    }
  }

  Box(Modifier.fillMaxSize()) {
    when {
      state.initializing -> LoadingScreen()
      state.destination == Destination.TUTORIAL -> TutorialScreen(
        page = state.tutorialPage,
        steps = state.catalog?.tutorial.orEmpty(),
        onPrevious = viewModel::tutorialPrevious,
        onNext = viewModel::tutorialNext,
        onFinish = viewModel::finishTutorial,
      )
      !state.authenticated -> LoginScreen(
        baseUrl = state.apiBaseUrl,
        authConfig = state.authConfig,
        authStage = state.authStage,
        canEditBaseUrl = state.canEditBaseUrl,
        canRetrySession = state.canRetrySession,
        busy = state.busy,
        message = state.message,
        messageIsError = state.isError,
        onLogin = viewModel::login,
        onRegister = viewModel::register,
        onVerify = viewModel::verifyEmail,
        onForgotPassword = viewModel::forgotPassword,
        onResetPassword = viewModel::resetPassword,
        onAuthStage = viewModel::chooseAuthStage,
        onRetrySession = viewModel::retrySession,
        onBaseUrlSave = viewModel::updateBaseUrl,
        onOpenTutorial = { viewModel.openTutorial(Destination.HOME) },
      )
      else -> PlanoraShell(
        state = state,
        viewModel = viewModel,
        onImport = {
          if (state.principal?.canWriteSchedule == true) {
            viewModel.captureAuthenticatedGeneration()?.let { generation ->
              pendingImportGeneration = generation
              importLauncher.launch(
                arrayOf(
                  "text/csv",
                  "text/plain",
                  "text/comma-separated-values",
                  "application/csv",
                  "application/vnd.ms-excel",
                  "application/octet-stream",
                ),
              )
            }
          } else {
            viewModel.reportError("Your role can view schedules but cannot import timetable data.")
          }
        },
      )
    }
    if (state.busy) BusyOverlay()
  }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PlanoraShell(
  state: PlanoraUiState,
  viewModel: PlanoraViewModel,
  onImport: () -> Unit,
) {
  val snackbar = remember { SnackbarHostState() }
  BackHandler(enabled = state.destination != Destination.HOME && state.destination != Destination.TUTORIAL) {
    viewModel.navigate(Destination.HOME)
  }
  LaunchedEffect(state.message) {
    state.message?.let {
      snackbar.showSnackbar(it)
      viewModel.clearMessage()
    }
  }

  if (state.destination == Destination.TUTORIAL) {
    TutorialScreen(
      page = state.tutorialPage,
      steps = state.catalog?.tutorial.orEmpty(),
      onPrevious = viewModel::tutorialPrevious,
      onNext = viewModel::tutorialNext,
      onFinish = viewModel::finishTutorial,
    )
    return
  }

  BoxWithConstraints(Modifier.fillMaxSize()) {
    val useNavigationRail = maxWidth >= 600.dp && maxHeight >= 520.dp
    val threePane = maxWidth >= 1200.dp && maxHeight >= 600.dp
    Row(Modifier.fillMaxSize()) {
      if (useNavigationRail) {
        DesktopRail(
          selected = state.destination,
          onSelect = viewModel::navigate,
          onSettings = { viewModel.navigate(Destination.SETTINGS) },
        )
      }
      Scaffold(
        modifier = Modifier.weight(1f),
        containerColor = MaterialTheme.colorScheme.background,
        topBar = {
          PlanoraTopBar(
            state = state,
            onSettings = { viewModel.navigate(Destination.SETTINGS) },
            onLogout = viewModel::logout,
          )
        },
        bottomBar = {
          if (!useNavigationRail) {
            NavigationBar(containerColor = MaterialTheme.colorScheme.surface) {
              primaryDestinations.forEach { destination ->
                NavigationBarItem(
                  modifier = Modifier.testTag("nav-${destination.name.lowercase()}"),
                  selected = state.destination == destination,
                  onClick = { viewModel.navigate(destination) },
                  icon = { DestinationIcon(destination) },
                  label = { Text(destination.label) },
                )
              }
            }
          }
        },
        snackbarHost = { SnackbarHost(snackbar) },
      ) { padding ->
        Box(Modifier.fillMaxSize().padding(padding)) {
          when (state.destination) {
            Destination.HOME -> HomeScreen(
              state = state,
              onScenario = { item -> if (item.id == "import") onImport() else viewModel.createScenario(item) },
              onMode = viewModel::chooseMode,
              onOpenProject = viewModel::openProject,
              onOpenTutorial = { viewModel.openTutorial(Destination.HOME) },
              onOpenSchedule = { viewModel.navigate(Destination.SCHEDULE) },
            )
            Destination.SCHEDULE -> ScheduleScreen(
              state = state,
              expanded = threePane,
              onWeek = viewModel::chooseWeek,
              onDay = viewModel::chooseDay,
              onEvent = viewModel::selectEvent,
              onMode = viewModel::chooseMode,
              onSolve = viewModel::solve,
              onValidate = viewModel::validate,
              onImprove = viewModel::improve,
              onCancelImprove = viewModel::cancelImprove,
              onOpenReview = { viewModel.navigate(Destination.REVIEW) },
              onSave = viewModel::saveProject,
              onExport = viewModel::exportCsv,
              onPreviewMoves = viewModel::previewMoves,
            )
            Destination.REVIEW -> ReviewScreen(
              state = state,
              onImprove = viewModel::improve,
              onCancelImprove = viewModel::cancelImprove,
              onValidate = viewModel::validate,
              onNavigate = viewModel::navigate,
            )
            Destination.PROJECTS -> ProjectsScreen(
              projects = state.projects,
              loadError = state.projectsLoadError,
              canWrite = state.principal?.canWriteSchedule == true,
              onRetry = viewModel::refreshProjects,
              onOpen = viewModel::openProject,
              onRename = viewModel::renameProject,
              onDelete = viewModel::deleteProject,
            )
            Destination.TOOLS -> state.principal?.let { ToolsScreen(it, viewModel::navigate) }
            Destination.DATA -> DataScreen(
              state = state,
              onScenario = viewModel::createScenario,
              onImport = onImport,
              onMode = viewModel::chooseMode,
            )
            Destination.INSIGHTS -> InsightsScreen(state.workspace)
            Destination.ADVANCED -> AdvancedScreen(
              settings = state.solverSettings,
              overridesEnabled = state.advancedOverridesEnabled,
              onChange = viewModel::updateSolverSettings,
              onUseDefaults = viewModel::useModeDefaults,
            )
            Destination.ACCOUNT -> state.principal?.let {
              AccountScreen(
                principal = it,
                account = state.account,
                onRefresh = viewModel::refreshAccount,
                onJoinInvite = viewModel::joinInvite,
                onSwitchOrganization = viewModel::switchOrganization,
                onChangePassword = viewModel::changePassword,
                onRevokeSessions = viewModel::revokeOtherSessions,
              )
            }
            Destination.PLATFORM -> PlatformScreen(state.parity, viewModel::refreshParity)
            Destination.ACCESS -> state.principal?.let {
              AccessScreen(it, state.access, viewModel::refreshAccess, viewModel::applyAccessChange)
            }
            Destination.ADMIN -> AdminScreen(
              snapshot = state.admin,
              onRefresh = viewModel::refreshAdmin,
              onEmailTest = viewModel::sendTestEmail,
              onExport = viewModel::exportAdminCsv,
            )
            Destination.SETTINGS -> SettingsScreen(
              state = state,
              canEditBaseUrl = state.canEditBaseUrl,
              themeMode = state.themeMode,
              onThemeMode = viewModel::chooseTheme,
              onSaveBaseUrl = viewModel::updateBaseUrl,
              onTutorial = { viewModel.openTutorial(Destination.SETTINGS) },
              onLogout = viewModel::logout,
            )
            Destination.TUTORIAL -> Unit
          }
        }
      }
    }

    if (!threePane && state.selectedEvent != null && state.moveTargets.isEmpty() && state.destination == Destination.SCHEDULE) {
      ModalBottomSheet(onDismissRequest = { viewModel.selectEvent(null) }) {
        EventInspector(
          event = state.selectedEvent,
          conflicts = state.workspace?.hardConflicts.orEmpty(),
          validationState = state.workspace?.validationState,
          onImprove = viewModel::improve,
          onCancelImprove = viewModel::cancelImprove,
          onOpenReview = { viewModel.navigate(Destination.REVIEW) },
          canImprove = state.principal?.canRunSolver == true,
          runningJob = state.runningJob,
          onPreviewMoves = viewModel::previewMoves,
          modifier = Modifier
            .fillMaxWidth()
            .heightIn(max = 460.dp)
            .padding(horizontal = 20.dp, vertical = 8.dp),
        )
        Spacer(Modifier.height(28.dp))
      }
    }
    if (state.moveTargets.isNotEmpty() && state.heldEvent != null && state.destination == Destination.SCHEDULE) {
      ModalBottomSheet(onDismissRequest = viewModel::releaseMove) {
        MoveTargetsSheet(
          eventTitle = state.heldEvent.title,
          targets = state.moveTargets,
          onMove = viewModel::moveEvent,
          onCancel = viewModel::releaseMove,
        )
      }
    }
  }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PlanoraTopBar(
  state: PlanoraUiState,
  onSettings: () -> Unit,
  onLogout: () -> Unit,
) {
  Column {
    TopAppBar(
      colors = TopAppBarDefaults.topAppBarColors(
        containerColor = MaterialTheme.colorScheme.surface,
        titleContentColor = MaterialTheme.colorScheme.onSurface,
      ),
      title = {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
          Image(
            painter = painterResource(R.drawable.planora_elephant),
            contentDescription = "Planora elephant logo",
            modifier = Modifier.size(34.dp).clip(MaterialTheme.shapes.small),
          )
          Column {
            Text("Planora", style = MaterialTheme.typography.titleMedium)
            Text(
              state.workspace?.projectName ?: state.principal?.tenantId.orEmpty(),
              style = MaterialTheme.typography.bodyMedium,
              color = MaterialTheme.colorScheme.onSurfaceVariant,
              maxLines = 1,
              overflow = TextOverflow.Ellipsis,
            )
          }
        }
      },
      actions = {
        IconButton(onClick = onSettings) {
          Icon(Icons.Rounded.Settings, contentDescription = "Settings")
        }
        IconButton(onClick = onLogout) {
          Icon(Icons.AutoMirrored.Rounded.Logout, contentDescription = "Sign out")
        }
      },
    )
    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
  }
}

@Composable
private fun DesktopRail(
  selected: Destination,
  onSelect: (Destination) -> Unit,
  onSettings: () -> Unit,
) {
  Column(
    modifier = Modifier
      .windowInsetsPadding(
        WindowInsets.safeDrawing.only(WindowInsetsSides.Start + WindowInsetsSides.Vertical),
      )
      .width(82.dp).fillMaxHeight()
      .background(MaterialTheme.planoraColors.sidebar)
      .padding(vertical = 18.dp),
    horizontalAlignment = Alignment.CenterHorizontally,
    verticalArrangement = Arrangement.spacedBy(12.dp),
  ) {
    Surface(color = MaterialTheme.colorScheme.surface, shape = MaterialTheme.shapes.small) {
      Image(
        painter = painterResource(R.drawable.planora_elephant),
        contentDescription = "Planora",
        modifier = Modifier.size(44.dp),
      )
    }
    Spacer(Modifier.height(8.dp))
    primaryDestinations.forEach { destination ->
      RailItem(destination, selected == destination) { onSelect(destination) }
    }
    Spacer(Modifier.weight(1f))
    RailItem(Destination.SETTINGS, selected == Destination.SETTINGS, onSettings)
  }
}

@Composable
private fun RailItem(destination: Destination, selected: Boolean, onClick: () -> Unit) {
  Column(
    modifier = Modifier
      .width(70.dp)
      .clip(MaterialTheme.shapes.medium)
      .background(if (selected) MaterialTheme.planoraColors.sidebarActive else Color.Transparent)
      .clickable(onClick = onClick)
      .padding(vertical = 10.dp),
    horizontalAlignment = Alignment.CenterHorizontally,
  ) {
    DestinationIcon(destination, tint = MaterialTheme.planoraColors.sidebarContent)
    Text(
      destination.label,
      color = MaterialTheme.planoraColors.sidebarContent,
      style = MaterialTheme.typography.labelSmall,
    )
  }
}

@Composable
private fun DestinationIcon(destination: Destination, tint: Color = Color.Unspecified) {
  val icon = when (destination) {
    Destination.HOME -> Icons.Rounded.Home
    Destination.SCHEDULE -> Icons.Rounded.CalendarMonth
    Destination.REVIEW -> Icons.Rounded.CheckCircle
    Destination.PROJECTS -> Icons.Rounded.FolderOpen
    Destination.TOOLS -> Icons.Rounded.Apps
    Destination.DATA -> Icons.Rounded.Apps
    Destination.INSIGHTS -> Icons.Rounded.CheckCircle
    Destination.ADVANCED -> Icons.Rounded.Settings
    Destination.ACCOUNT -> Icons.Rounded.Home
    Destination.PLATFORM -> Icons.Rounded.CheckCircle
    Destination.ACCESS -> Icons.Rounded.Home
    Destination.ADMIN -> Icons.Rounded.Settings
    Destination.SETTINGS -> Icons.Rounded.Settings
    Destination.TUTORIAL -> Icons.Rounded.CheckCircle
  }
  Icon(
    imageVector = icon,
    contentDescription = null,
    tint = if (tint == Color.Unspecified) LocalContentColor.current else tint,
  )
}

@Composable
private fun LoadingScreen() {
  Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background), contentAlignment = Alignment.Center) {
    Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(18.dp)) {
      Image(
        painter = painterResource(R.drawable.planora_elephant),
        contentDescription = "Planora",
        modifier = Modifier.size(88.dp),
      )
      CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
      Text("Opening your academic workspace")
    }
  }
}

@Composable
private fun BusyOverlay() {
  Box(
    Modifier.fillMaxSize()
      .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.72f))
      .pointerInput(Unit) {
        awaitPointerEventScope {
          while (true) awaitPointerEvent().changes.forEach { it.consume() }
        }
      }
      .semantics { contentDescription = "Planora is working" },
    contentAlignment = Alignment.Center,
  ) {
    CircularProgressIndicator()
  }
}

@Composable
private fun PlanoraSystemBars(themeMode: ThemeMode) {
  val systemDark = isSystemInDarkTheme()
  val dark = when (themeMode) {
    ThemeMode.SYSTEM -> systemDark
    ThemeMode.LIGHT -> false
    ThemeMode.DARK -> true
  }
  val view = LocalView.current
  val activity = LocalContext.current.findActivity()
  SideEffect {
    activity?.window?.let { window ->
      if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
        window.isNavigationBarContrastEnforced = false
      }
      WindowCompat.getInsetsController(window, view).apply {
        isAppearanceLightStatusBars = !dark
        isAppearanceLightNavigationBars = !dark
      }
    }
  }
}

private fun Context.findActivity(): Activity? {
  var current: Context? = this
  while (current is ContextWrapper) {
    if (current is Activity) return current
    current = current.baseContext
  }
  return current as? Activity
}

private fun readText(context: Context, uri: Uri): Pair<String, String> {
  context.contentResolver.openAssetFileDescriptor(uri, "r")?.use { descriptor ->
    if (descriptor.length > MAX_IMPORT_BYTES) {
      error("That file is larger than the 5 MB import limit.")
    }
  }
  val content = context.contentResolver.openInputStream(uri)?.bufferedReader()?.use { reader ->
    val output = StringBuilder()
    val buffer = CharArray(8_192)
    while (true) {
      val read = reader.read(buffer)
      if (read < 0) break
      output.append(buffer, 0, read)
      if (output.length > MAX_IMPORT_BYTES) error("That file is larger than the 5 MB import limit.")
    }
    output.toString()
  } ?: error("The selected file could not be opened.")
  require(content.isNotBlank()) { "The selected file is empty." }
  val name = context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
    ?.use { cursor ->
      if (cursor.moveToFirst()) cursor.getString(0) else null
    }
    ?.takeIf { it.isNotBlank() }
    ?: uri.lastPathSegment?.substringAfterLast('/')
    ?: "schedule.csv"
  return name to content
}

private const val MAX_IMPORT_BYTES = 5 * 1024 * 1024
