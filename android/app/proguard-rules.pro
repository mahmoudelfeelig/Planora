-keepattributes Signature
-keepattributes *Annotation*

# Retrofit reads service method and parameter annotations at runtime.
-keep interface com.planora.mobile.data.PlanoraApi { *; }

# Gson reflects over the API DTO field names. Keep this deliberately narrow to
# the data boundary so the rest of the release app can still be optimized.
-keep class com.planora.mobile.data.** { *; }
