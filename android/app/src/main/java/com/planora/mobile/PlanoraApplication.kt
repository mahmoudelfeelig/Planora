package com.planora.mobile

import android.app.Application
import com.planora.mobile.data.ApiSettingsStore
import com.planora.mobile.data.EncryptedTokenStore
import com.planora.mobile.data.RetrofitPlanoraGateway
import com.planora.mobile.domain.PlanoraGateway

class PlanoraApplication : Application() {
  lateinit var gateway: PlanoraGateway
    private set

  override fun onCreate() {
    super.onCreate()
    gateway = RetrofitPlanoraGateway(
      ApiSettingsStore(applicationContext),
      EncryptedTokenStore(applicationContext),
    )
  }
}
