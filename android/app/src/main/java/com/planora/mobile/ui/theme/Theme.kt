package com.planora.mobile.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

enum class ThemeMode(val storageValue: String) {
  SYSTEM("system"),
  LIGHT("light"),
  DARK("dark");

  companion object {
    fun fromStorage(value: String?): ThemeMode = entries.firstOrNull { it.storageValue == value } ?: SYSTEM
  }
}

// Stable aliases retained for shell code while screen content uses the active palette.
val PlanoraNavy = Color(0xFF17497E)
val PlanoraNavyDark = Color(0xFF0C3158)
val PlanoraSidebarActive = Color(0xFF1E527E)
val PlanoraPaper = Color(0xFFEEF2F6)
val PlanoraPanel = Color(0xFFFFFFFF)
val PlanoraPanelRaised = Color(0xFFF7F9FC)
val PlanoraPanelMuted = Color(0xFFEDF2F7)
val PlanoraInk = Color(0xFF142033)
val PlanoraTextSoft = Color(0xFF31455D)
val PlanoraMuted = Color(0xFF53667D)
val PlanoraLine = Color(0xFFD0D9E4)
val PlanoraLineStrong = Color(0xFF7B8DA1)
val PlanoraBlueSoft = Color(0xFFE2EDF8)
val PlanoraRed = Color(0xFFA52B37)
val PlanoraGreen = Color(0xFF176B4C)
val PlanoraGreenSoft = Color(0xFFE1F1E9)
val PlanoraWarning = Color(0xFF8A4B08)
val PlanoraWarningSoft = Color(0xFFFFF0D7)
val CourseBlue = Color(0xFFDCE9F8)
val CourseMint = Color(0xFFDFF0E9)
val CourseAmber = Color(0xFFF9EBC8)
val CourseLavender = Color(0xFFEEE3F6)
val CourseCoral = Color(0xFFF7E3DA)

@Immutable
data class PlanoraCourseColors(
  val container: Color,
  val outline: Color,
  val accent: Color,
  val content: Color,
)

@Immutable
data class PlanoraExtendedColors(
  val sidebar: Color,
  val sidebarActive: Color,
  val sidebarContent: Color,
  val sidebarMuted: Color,
  val success: Color,
  val successContainer: Color,
  val warning: Color,
  val warningContainer: Color,
  val danger: Color,
  val dangerContainer: Color,
  val focus: Color,
  val courseTones: List<PlanoraCourseColors>,
)

private val LightExtendedColors = PlanoraExtendedColors(
  sidebar = Color(0xFF0C3158),
  sidebarActive = Color(0xFF1E527E),
  sidebarContent = Color(0xFFF8FBFF),
  sidebarMuted = Color(0xFFC6D8EA),
  success = Color(0xFF176B4C),
  successContainer = Color(0xFFE1F1E9),
  warning = Color(0xFF8A4B08),
  warningContainer = Color(0xFFFFF0D7),
  danger = Color(0xFFA52B37),
  dangerContainer = Color(0xFFF9E2E5),
  focus = Color(0xFF2875BD),
  courseTones = listOf(
    PlanoraCourseColors(Color(0xFFDCE9F8), Color(0xFF94B2D5), Color(0xFF2D689F), Color(0xFF153553)),
    PlanoraCourseColors(Color(0xFFDFF0E9), Color(0xFF9CC6B6), Color(0xFF307B61), Color(0xFF183F34)),
    PlanoraCourseColors(Color(0xFFF9EBC8), Color(0xFFD9B875), Color(0xFF9A650C), Color(0xFF4A350E)),
    PlanoraCourseColors(Color(0xFFEEE3F6), Color(0xFFC5ADDB), Color(0xFF76519C), Color(0xFF402B57)),
    PlanoraCourseColors(Color(0xFFF7E3DA), Color(0xFFDAA997), Color(0xFFA15337), Color(0xFF4F2B20)),
    PlanoraCourseColors(Color(0xFFDCEFF1), Color(0xFF95C6CC), Color(0xFF397A82), Color(0xFF1E4449)),
  ),
)

private val DarkExtendedColors = PlanoraExtendedColors(
  sidebar = Color(0xFF061B32),
  sidebarActive = Color(0xFF18507F),
  sidebarContent = Color(0xFFF5F9FD),
  sidebarMuted = Color(0xFFBFD1E2),
  success = Color(0xFF7BD3AC),
  successContainer = Color(0xFF183B31),
  warning = Color(0xFFF0BF76),
  warningContainer = Color(0xFF49351A),
  danger = Color(0xFFFF9CA6),
  dangerContainer = Color(0xFF4E252D),
  focus = Color(0xFF95C7F3),
  courseTones = listOf(
    PlanoraCourseColors(Color(0xFF284968), Color(0xFF6593C2), Color(0xFFA4CFF5), Color(0xFFF5FAFF)),
    PlanoraCourseColors(Color(0xFF245543), Color(0xFF5DA88A), Color(0xFF94DFBD), Color(0xFFF1FFF9)),
    PlanoraCourseColors(Color(0xFF614926), Color(0xFFB78A43), Color(0xFFFFD080), Color(0xFFFFF9EB)),
    PlanoraCourseColors(Color(0xFF4B3961), Color(0xFF9A78BD), Color(0xFFD5B2F6), Color(0xFFFCF8FF)),
    PlanoraCourseColors(Color(0xFF5D3C31), Color(0xFFB5745C), Color(0xFFFFB195), Color(0xFFFFF8F5)),
    PlanoraCourseColors(Color(0xFF285158), Color(0xFF5F9FA8), Color(0xFFA2DCE2), Color(0xFFF3FEFF)),
  ),
)

private val LocalPlanoraExtendedColors = staticCompositionLocalOf { LightExtendedColors }

val MaterialTheme.planoraColors: PlanoraExtendedColors
  @Composable
  @ReadOnlyComposable
  get() = LocalPlanoraExtendedColors.current

private val LightColors = lightColorScheme(
  primary = Color(0xFF17497E),
  onPrimary = Color.White,
  primaryContainer = Color(0xFFE2EDF8),
  onPrimaryContainer = Color(0xFF0F3868),
  inversePrimary = Color(0xFF78ADDF),
  secondary = Color(0xFF31455D),
  onSecondary = Color.White,
  secondaryContainer = Color(0xFFEDF2F7),
  onSecondaryContainer = Color(0xFF142033),
  tertiary = Color(0xFF17497E),
  onTertiary = Color.White,
  tertiaryContainer = Color(0xFFE2EDF8),
  onTertiaryContainer = Color(0xFF0F3868),
  background = Color(0xFFEEF2F6),
  onBackground = Color(0xFF142033),
  surface = Color.White,
  onSurface = Color(0xFF142033),
  surfaceVariant = Color(0xFFEDF2F7),
  onSurfaceVariant = Color(0xFF31455D),
  surfaceTint = Color(0xFF17497E),
  inverseSurface = Color(0xFF142033),
  inverseOnSurface = Color(0xFFF0F5FB),
  error = Color(0xFFA52B37),
  onError = Color.White,
  errorContainer = Color(0xFFF9E2E5),
  onErrorContainer = Color(0xFF7B202A),
  outline = Color(0xFF7B8DA1),
  outlineVariant = Color(0xFFD0D9E4),
  scrim = Color(0xFF09131F),
  surfaceBright = Color.White,
  surfaceDim = Color(0xFFE2E8EF),
  surfaceContainerLowest = Color.White,
  surfaceContainerLow = Color(0xFFF7F9FC),
  surfaceContainer = Color(0xFFF2F5F8),
  surfaceContainerHigh = Color(0xFFEDF2F7),
  surfaceContainerHighest = Color(0xFFE5EBF1),
)

private val DarkColors = darkColorScheme(
  primary = Color(0xFF78ADDF),
  onPrimary = Color(0xFF081522),
  primaryContainer = Color(0xFF203C59),
  onPrimaryContainer = Color(0xFFD4DEEA),
  inversePrimary = Color(0xFF17497E),
  secondary = Color(0xFFAEBED0),
  onSecondary = Color(0xFF09131F),
  secondaryContainer = Color(0xFF1B2B3E),
  onSecondaryContainer = Color(0xFFF0F5FB),
  tertiary = Color(0xFF78ADDF),
  onTertiary = Color(0xFF081522),
  tertiaryContainer = Color(0xFF203C59),
  onTertiaryContainer = Color(0xFFD4DEEA),
  background = Color(0xFF09131F),
  onBackground = Color(0xFFF0F5FB),
  surface = Color(0xFF111D2B),
  onSurface = Color(0xFFF0F5FB),
  surfaceVariant = Color(0xFF1B2B3E),
  onSurfaceVariant = Color(0xFFD4DEEA),
  surfaceTint = Color(0xFF78ADDF),
  inverseSurface = Color(0xFFF0F5FB),
  inverseOnSurface = Color(0xFF142033),
  error = Color(0xFFFF9CA6),
  onError = Color(0xFF3B1119),
  errorContainer = Color(0xFF4E252D),
  onErrorContainer = Color(0xFFFFDADD),
  outline = Color(0xFF6A7F96),
  outlineVariant = Color(0xFF34485F),
  scrim = Color.Black,
  surfaceBright = Color(0xFF1B2B3E),
  surfaceDim = Color(0xFF09131F),
  surfaceContainerLowest = Color(0xFF07111C),
  surfaceContainerLow = Color(0xFF111D2B),
  surfaceContainer = Color(0xFF172536),
  surfaceContainerHigh = Color(0xFF1B2B3E),
  surfaceContainerHighest = Color(0xFF23364A),
)

private val PlanoraShapes = Shapes(
  extraSmall = RoundedCornerShape(4.dp),
  small = RoundedCornerShape(6.dp),
  medium = RoundedCornerShape(8.dp),
  large = RoundedCornerShape(12.dp),
  extraLarge = RoundedCornerShape(20.dp),
)

private val PlanoraTypography = Typography(
  displayLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold, fontSize = 44.sp, lineHeight = 52.sp),
  displayMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold, fontSize = 38.sp, lineHeight = 46.sp),
  displaySmall = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold, fontSize = 32.sp, lineHeight = 40.sp),
  headlineLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold, fontSize = 28.sp, lineHeight = 34.sp, letterSpacing = (-0.2).sp),
  headlineMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold, fontSize = 24.sp, lineHeight = 30.sp),
  headlineSmall = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold, fontSize = 22.sp, lineHeight = 28.sp),
  titleLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Bold, fontSize = 20.sp, lineHeight = 26.sp),
  titleMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, lineHeight = 22.sp),
  titleSmall = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, lineHeight = 20.sp),
  bodyLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Normal, fontSize = 16.sp, lineHeight = 24.sp),
  bodyMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Normal, fontSize = 14.sp, lineHeight = 20.sp),
  bodySmall = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Normal, fontSize = 12.sp, lineHeight = 16.sp),
  labelLarge = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, lineHeight = 20.sp),
  labelMedium = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.SemiBold, fontSize = 12.sp, lineHeight = 16.sp),
  labelSmall = TextStyle(fontFamily = FontFamily.SansSerif, fontWeight = FontWeight.Medium, fontSize = 11.sp, lineHeight = 15.sp),
)

@Composable
fun PlanoraTheme(
  themeMode: ThemeMode = ThemeMode.SYSTEM,
  content: @Composable () -> Unit,
) {
  val darkTheme = when (themeMode) {
    ThemeMode.SYSTEM -> isSystemInDarkTheme()
    ThemeMode.LIGHT -> false
    ThemeMode.DARK -> true
  }
  CompositionLocalProvider(
    LocalPlanoraExtendedColors provides if (darkTheme) DarkExtendedColors else LightExtendedColors,
  ) {
    MaterialTheme(
      colorScheme = if (darkTheme) DarkColors else LightColors,
      typography = PlanoraTypography,
      shapes = PlanoraShapes,
      content = content,
    )
  }
}
