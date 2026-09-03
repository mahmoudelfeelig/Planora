package com.planora.mobile.ui

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ConflictAttributionTest {
  @Test
  fun matchesOnlyExplicitActivityTokens() {
    val conflict = "Staff overlap at week 1 MON slot 2 (A2, A3)"

    assertFalse(conflictMentionsActivity(conflict, 1))
    assertTrue(conflictMentionsActivity(conflict, 2))
    assertTrue(conflictMentionsActivity(conflict, 3))
    assertFalse(conflictMentionsActivity(conflict, 23))
  }
}
