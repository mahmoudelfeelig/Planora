package com.planora.mobile

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.viewmodel.compose.viewModel
import com.planora.mobile.ui.PlanoraRoot
import com.planora.mobile.ui.PlanoraViewModel

class MainActivity : ComponentActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    enableEdgeToEdge()
    val application = application as PlanoraApplication
    setContent {
      val model: PlanoraViewModel = viewModel(factory = PlanoraViewModel.factory(application.gateway, this))
      PlanoraRoot(model)
    }
  }
}
