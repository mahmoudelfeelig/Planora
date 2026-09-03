package com.planora.mobile.data

import com.planora.mobile.domain.ProjectSummary

internal object ProjectTenantPolicy {
  fun visibleToActiveTenant(
    activeTenantId: String,
    projects: List<ProjectSummary>,
  ): List<ProjectSummary> {
    if (activeTenantId.isBlank()) return emptyList()
    return projects.filter { it.tenantId == activeTenantId }
  }

  fun requireOpenAllowed(activeTenantId: String, projectTenantId: String) {
    require(activeTenantId.isNotBlank() && projectTenantId == activeTenantId) {
      "The Android app can open projects only from your active university."
    }
  }
}
