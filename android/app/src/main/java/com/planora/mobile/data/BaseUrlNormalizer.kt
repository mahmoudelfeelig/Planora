package com.planora.mobile.data

import java.net.URI

object BaseUrlNormalizer {
  fun normalize(raw: String, fallback: String): String {
    return normalizeCandidate(raw) ?: normalizeCandidate(fallback)
      ?: "http://10.0.2.2:8787"
  }

  private fun normalizeCandidate(raw: String): String? {
    val trimmed = raw.trim()
    if (trimmed.isEmpty() || trimmed.startsWith('/') || trimmed.startsWith('\\')) return null
    val authority = trimmed.substringBefore('/')
    val hostWithoutScheme = authority.substringBefore(':').lowercase()
    val withScheme = if ("://" in trimmed) trimmed else {
      if (isLocal(hostWithoutScheme)) "http://$trimmed" else "https://$trimmed"
    }
    val uri = runCatching { URI(withScheme) }.getOrNull() ?: return null
    val scheme = uri.scheme?.lowercase() ?: return null
    val host = uri.host?.lowercase() ?: return null
    if (scheme !in setOf("http", "https")) return null
    if (scheme == "http" && !isLocal(host)) return null
    if (uri.userInfo != null || uri.query != null || uri.fragment != null) return null
    val port = if (uri.port > 0) ":${uri.port}" else ""
    val path = uri.path?.trim('/').orEmpty()
    return buildString {
      append(scheme)
      append("://")
      append(if (host.contains(':')) "[$host]" else host)
      append(port)
      if (path.isNotEmpty()) append("/$path")
    }
  }

  private fun isLocal(host: String): Boolean =
    host == "localhost" || host == "::1" || host == "10.0.2.2" || host.startsWith("127.")
}

internal object ApiOrigin {
  fun fromBaseUrl(baseUrl: String): String? {
    val uri = runCatching { URI(baseUrl.trim()) }.getOrNull() ?: return null
    val scheme = uri.scheme?.lowercase() ?: return null
    val host = uri.host?.lowercase() ?: return null
    if (scheme !in setOf("http", "https")) return null
    val port = when {
      uri.port < 0 -> ""
      scheme == "http" && uri.port == 80 -> ""
      scheme == "https" && uri.port == 443 -> ""
      else -> ":${uri.port}"
    }
    return "$scheme://${if (host.contains(':')) "[$host]" else host}$port"
  }
}
