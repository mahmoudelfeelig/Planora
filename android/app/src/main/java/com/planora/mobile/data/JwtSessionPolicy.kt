package com.planora.mobile.data

import com.google.gson.JsonParser
import java.util.Base64

internal enum class JwtLifetime {
  EXPIRED,
  REFRESH,
  VALID,
  UNKNOWN,
}

internal object JwtSessionPolicy {
  private const val REFRESH_WINDOW_SECONDS = 15 * 60L

  fun classify(
    token: String,
    nowEpochSeconds: Long,
    refreshWindowSeconds: Long = REFRESH_WINDOW_SECONDS,
  ): JwtLifetime {
    val expiresAt = expiryEpochSeconds(token) ?: return JwtLifetime.UNKNOWN
    if (expiresAt <= nowEpochSeconds) return JwtLifetime.EXPIRED
    return if (expiresAt - nowEpochSeconds <= refreshWindowSeconds.coerceAtLeast(0L)) {
      JwtLifetime.REFRESH
    } else {
      JwtLifetime.VALID
    }
  }

  fun expiryEpochSeconds(token: String): Long? = runCatching {
    val parts = token.split('.')
    if (parts.size < 2 || parts[1].isBlank()) return@runCatching null
    val payload = String(Base64.getUrlDecoder().decode(parts[1]), Charsets.UTF_8)
    val parsed = JsonParser.parseString(payload)
    val expires = parsed.takeIf { it.isJsonObject }?.asJsonObject?.get("exp")
      ?: return@runCatching null
    if (!expires.isJsonPrimitive || !expires.asJsonPrimitive.isNumber) return@runCatching null
    expires.asLong
  }.getOrNull()
}
