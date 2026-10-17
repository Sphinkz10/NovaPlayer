plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
val nativeProofAar = providers.gradleProperty("novaNativeProofAar").orNull
android {
    namespace = "com.novacinema.connect"
    compileSdk = 35
    defaultConfig { applicationId = "com.novacinema.connect.poc"; minSdk = 26; targetSdk = 35; versionCode = 4; versionName = "0.4-phase1" }
    if (nativeProofAar != null) {
        defaultConfig {
            testInstrumentationRunner = "com.novacinema.connect.NativeEngineSmokeInstrumentation"
            ndk { abiFilters.addAll(listOf("arm64-v8a", "armeabi-v7a", "x86_64")) }
        }
        sourceSets["androidTest"].java.srcDir("../native-proof/src/androidTest/kotlin")
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    buildTypes { release { isMinifyEnabled = false } }
}
dependencyLocking { lockAllConfigurations() }
android.sourceSets["main"].java.srcDir("../core/src/main/kotlin")
dependencies {
    implementation("com.wireguard.android:tunnel:1.0.20260102")
    // Compile-only research gate; normal builds keep unimplemented providers disabled.
    nativeProofAar?.let { aar ->
        require(file(aar).isFile) { "Native proof AAR was not built" }
        implementation(files(aar))
    }
}
