plugins {
  id("com.android.application")
  id("org.jetbrains.kotlin.plugin.compose")
}

fun String.asBuildConfigString(): String =
  "\"${replace("\\", "\\\\").replace("\"", "\\\"")}\""

fun externalSigningValue(name: String) =
  providers.gradleProperty(name).orElse(providers.environmentVariable(name))

val productionApiBaseUrl = "https://planora.elfeel.me/api"
val appWebUrl = "https://planora.elfeel.me"
val debugApiBaseUrl = providers.gradleProperty("PLANORA_API_BASE_URL")
  .orElse(productionApiBaseUrl)
  .get()
  .trim()
  .trimEnd('/')
  .ifBlank { productionApiBaseUrl }

val releaseStoreFilePath = externalSigningValue("PLANORA_RELEASE_STORE_FILE").orNull
  ?.trim()
  ?.takeIf(String::isNotEmpty)
val releaseStorePassword = externalSigningValue("PLANORA_RELEASE_STORE_PASSWORD").orNull
  ?.takeIf(String::isNotEmpty)
val releaseKeyAlias = externalSigningValue("PLANORA_RELEASE_KEY_ALIAS").orNull
  ?.takeIf(String::isNotEmpty)
val releaseKeyPassword = externalSigningValue("PLANORA_RELEASE_KEY_PASSWORD").orNull
  ?.takeIf(String::isNotEmpty)
val hasReleaseSigning = listOf(
  releaseStoreFilePath,
  releaseStorePassword,
  releaseKeyAlias,
  releaseKeyPassword,
).all { it != null }
val hasPartialReleaseSigning = listOf(
  releaseStoreFilePath,
  releaseStorePassword,
  releaseKeyAlias,
  releaseKeyPassword,
).any { it != null } && !hasReleaseSigning

require(!hasPartialReleaseSigning) {
  "Release signing requires PLANORA_RELEASE_STORE_FILE, " +
    "PLANORA_RELEASE_STORE_PASSWORD, PLANORA_RELEASE_KEY_ALIAS, and " +
    "PLANORA_RELEASE_KEY_PASSWORD together."
}

android {
  namespace = "com.planora.mobile"
  compileSdk = 36

  defaultConfig {
    applicationId = "com.planora.mobile"
    minSdk = 26
    targetSdk = 36
    versionCode = 1
    versionName = "1.0.0"
    testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

    buildConfigField("String", "UI_CONTRACT_VERSION", "\"planora.ui.v1\"")
    buildConfigField("String", "APP_WEB_URL", appWebUrl.asBuildConfigString())
  }

  signingConfigs {
    if (hasReleaseSigning) {
      create("release") {
        storeFile = file(requireNotNull(releaseStoreFilePath))
        storePassword = releaseStorePassword
        keyAlias = releaseKeyAlias
        keyPassword = releaseKeyPassword
      }
    }
  }

  buildTypes {
    getByName("debug") {
      buildConfigField("String", "API_BASE_URL", debugApiBaseUrl.asBuildConfigString())
      buildConfigField("boolean", "CAN_EDIT_API_BASE_URL", "true")
    }

    getByName("release") {
      buildConfigField("String", "API_BASE_URL", productionApiBaseUrl.asBuildConfigString())
      buildConfigField("boolean", "CAN_EDIT_API_BASE_URL", "false")
      isMinifyEnabled = true
      isShrinkResources = true
      if (hasReleaseSigning) {
        signingConfig = signingConfigs.getByName("release")
      }
      proguardFiles(
        getDefaultProguardFile("proguard-android-optimize.txt"),
        "proguard-rules.pro",
      )
    }
  }

  compileOptions {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
  }

  buildFeatures {
    compose = true
    buildConfig = true
  }

  packaging.resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
}

dependencies {
  val composeBom = platform("androidx.compose:compose-bom:2024.10.01")

  implementation("androidx.core:core-ktx:1.15.0")
  implementation("androidx.activity:activity-compose:1.9.3")
  implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
  implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
  implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

  implementation(composeBom)
  androidTestImplementation(composeBom)
  implementation("androidx.compose.ui:ui")
  implementation("androidx.compose.ui:ui-tooling-preview")
  implementation("androidx.compose.animation:animation")
  implementation("androidx.compose.material3:material3")
  implementation("androidx.compose.material:material-icons-extended")

  implementation("com.squareup.retrofit2:retrofit:2.11.0")
  implementation("com.squareup.retrofit2:converter-gson:2.11.0")
  implementation("com.squareup.okhttp3:okhttp:4.12.0")
  implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

  testImplementation("junit:junit:4.13.2")
  androidTestImplementation("androidx.test.ext:junit:1.2.1")
  androidTestImplementation("androidx.compose.ui:ui-test-junit4")
  debugImplementation("androidx.compose.ui:ui-tooling")
  debugImplementation("androidx.compose.ui:ui-test-manifest")
}
