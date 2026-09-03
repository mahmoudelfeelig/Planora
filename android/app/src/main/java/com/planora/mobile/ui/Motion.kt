package com.planora.mobile.ui

import android.database.ContentObserver
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.animation.core.tween
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext

@Composable
internal fun rememberPlanoraMotionEnabled(): Boolean {
  val resolver = LocalContext.current.contentResolver
  val scaleSettings = listOf(
    Settings.Global.ANIMATOR_DURATION_SCALE,
    Settings.Global.TRANSITION_ANIMATION_SCALE,
    Settings.Global.WINDOW_ANIMATION_SCALE,
  )
  fun animationsEnabled(): Boolean = runCatching {
    scaleSettings.all { setting -> Settings.Global.getFloat(resolver, setting, 1f) > 0f }
  }.getOrDefault(true)

  var enabled by remember(resolver) { mutableStateOf(animationsEnabled()) }
  DisposableEffect(resolver) {
    val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
      override fun onChange(selfChange: Boolean) {
        enabled = animationsEnabled()
      }
    }
    scaleSettings.forEach { setting ->
      resolver.registerContentObserver(Settings.Global.getUriFor(setting), false, observer)
    }
    onDispose { resolver.unregisterContentObserver(observer) }
  }
  return enabled
}

@Composable
internal fun <T> MotionAwareContent(
  targetState: T,
  label: String,
  content: @Composable (T) -> Unit,
) {
  if (!rememberPlanoraMotionEnabled()) {
    content(targetState)
    return
  }
  AnimatedContent(
    targetState = targetState,
    transitionSpec = {
      fadeIn(tween(durationMillis = 170)) togetherWith fadeOut(tween(durationMillis = 90))
    },
    label = label,
  ) { value ->
    content(value)
  }
}
