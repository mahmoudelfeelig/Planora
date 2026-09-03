package com.planora.mobile.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.core.content.edit
import com.planora.mobile.BuildConfig
import java.nio.ByteBuffer
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class ApiSettingsStore(context: Context) {
  private val preferences = context.getSharedPreferences("planora_api", Context.MODE_PRIVATE)

  fun baseUrl(): String {
    val stored = preferences.getString("base_url", null)
    if (!BuildConfig.CAN_EDIT_API_BASE_URL && stored != null) {
      preferences.edit { remove("base_url") }
    }
    return effectiveApiBaseUrl(
      canEdit = BuildConfig.CAN_EDIT_API_BASE_URL,
      stored = stored,
      fallback = BuildConfig.API_BASE_URL,
    )
  }

  fun setBaseUrl(value: String): String {
    require(BuildConfig.CAN_EDIT_API_BASE_URL) {
      "This production build uses the hosted Planora server and cannot change it."
    }
    val normalized = BaseUrlNormalizer.normalize(value, BuildConfig.API_BASE_URL)
    preferences.edit { putString("base_url", normalized) }
    return normalized
  }
}

internal fun effectiveApiBaseUrl(canEdit: Boolean, stored: String?, fallback: String): String =
  BaseUrlNormalizer.normalize(if (canEdit) stored.orEmpty() else fallback, fallback)

class EncryptedTokenStore(context: Context) {
  private val preferences = context.getSharedPreferences("planora_session", Context.MODE_PRIVATE)

  fun load(origin: String): String {
    val ciphertext = preferences.getString("ciphertext", null) ?: return ""
    val iv = preferences.getString("iv", null) ?: return ""
    return runCatching {
      val cipher = Cipher.getInstance(TRANSFORMATION)
      cipher.init(
        Cipher.DECRYPT_MODE,
        key(),
        GCMParameterSpec(128, Base64.decode(iv, Base64.NO_WRAP)),
      )
      OriginBoundTokenCodec.tokenFor(
        cipher.doFinal(Base64.decode(ciphertext, Base64.NO_WRAP)),
        origin,
      )
    }.getOrDefault("")
  }

  fun save(origin: String, value: String) {
    if (value.isBlank()) {
      clear()
      return
    }
    require(origin.isNotBlank()) { "A valid API origin is required before saving a session." }
    val cipher = Cipher.getInstance(TRANSFORMATION)
    cipher.init(Cipher.ENCRYPT_MODE, key())
    val encrypted = cipher.doFinal(OriginBoundTokenCodec.encode(origin, value))
    preferences.edit {
      putString("ciphertext", Base64.encodeToString(encrypted, Base64.NO_WRAP))
      putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
    }
  }

  fun clear() {
    preferences.edit { clear() }
  }

  private fun key(): SecretKey {
    val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
    return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").run {
      init(
        KeyGenParameterSpec.Builder(
          KEY_ALIAS,
          KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
          .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
          .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
          .setRandomizedEncryptionRequired(true)
          .build(),
      )
      generateKey()
    }
  }

  private companion object {
    const val KEY_ALIAS = "planora_android_session_v1"
    const val TRANSFORMATION = "AES/GCM/NoPadding"
  }
}

internal data class OriginBoundToken(
  val origin: String,
  val token: String,
)

internal object OriginBoundTokenCodec {
  private val magic = byteArrayOf(0x50, 0x4c, 0x4e, 0x52, 0x01)

  fun encode(origin: String, token: String): ByteArray {
    val originBytes = origin.toByteArray(Charsets.UTF_8)
    val tokenBytes = token.toByteArray(Charsets.UTF_8)
    require(originBytes.isNotEmpty() && tokenBytes.isNotEmpty())
    return ByteBuffer.allocate(magic.size + Int.SIZE_BYTES + originBytes.size + tokenBytes.size)
      .put(magic)
      .putInt(originBytes.size)
      .put(originBytes)
      .put(tokenBytes)
      .array()
  }

  fun decode(encoded: ByteArray): OriginBoundToken? = runCatching {
    val buffer = ByteBuffer.wrap(encoded)
    val actualMagic = ByteArray(magic.size)
    if (buffer.remaining() < magic.size + Int.SIZE_BYTES) return@runCatching null
    buffer.get(actualMagic)
    if (!actualMagic.contentEquals(magic)) return@runCatching null
    val originSize = buffer.int
    if (originSize <= 0 || originSize >= buffer.remaining()) return@runCatching null
    val originBytes = ByteArray(originSize)
    buffer.get(originBytes)
    val tokenBytes = ByteArray(buffer.remaining())
    buffer.get(tokenBytes)
    OriginBoundToken(
      origin = String(originBytes, Charsets.UTF_8),
      token = String(tokenBytes, Charsets.UTF_8),
    )
  }.getOrNull()

  fun tokenFor(encoded: ByteArray, expectedOrigin: String): String =
    decode(encoded)?.takeIf { it.origin == expectedOrigin }?.token.orEmpty()
}
