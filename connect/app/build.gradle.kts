plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
val nativeProofAar = providers.gradleProperty("novaNativeProofAar").orNull
val directoryProfile = providers.gradleProperty("novaDirectoryProfile").orNull
val distributionCode = providers.gradleProperty("novaVersionCode").orElse("9").get().toInt()
require(distributionCode >= 9) { "Distribution version codes must not go backwards" }
android {
    namespace = "com.novacinema.connect"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.novacinema.connect.poc"; minSdk = 26; targetSdk = 35
        versionCode = distributionCode; versionName = "0.9-m4-lan"
        testInstrumentationRunner = "com.novacinema.connect.DevicePairingInstrumentation"
    }
    if (nativeProofAar != null) {
        defaultConfig {
            testInstrumentationRunner = "com.novacinema.connect.NativeEngineSmokeInstrumentation"
            ndk { abiFilters.addAll(listOf("arm64-v8a", "armeabi-v7a", "x86_64")) }
        }
        sourceSets["androidTest"].java.srcDir("../native-proof/src/androidTest/kotlin")
        sourceSets["debug"].java.srcDir("../native-proof/src/debug/kotlin")
        sourceSets["debug"].manifest.srcFile("../native-proof/src/debug/AndroidManifest.xml")
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    buildTypes {
        debug { resValue("string", "app_name", "NOVA Cinema · Lab") }
        release {
            isMinifyEnabled = false
            isDebuggable = false
            resValue("string", "app_name", "NOVA Cinema")
        }
    }
}
// Keep the historical debug package for fixtures. Distribution has a stable
// identity and is signed offline; no private signing material enters Gradle/CI.
androidComponents {
    onVariants(selector().withBuildType("release")) { variant ->
        variant.applicationId.set("com.novacinema.cinema")
    }
}
dependencyLocking { lockAllConfigurations() }
android.sourceSets["main"].java.srcDir("../core/src/main/kotlin")
if(directoryProfile!=null) {
    val profile=file(directoryProfile)
    require(profile.isFile && profile.length() in 1..16384) { "A public Directory deployment profile is required" }
    val generated=layout.buildDirectory.dir("generated/novaDirectoryAssets")
    val prepare=tasks.register<Copy>("prepareDirectoryProfile") {
        from(profile);into(generated);rename { "nova-directory.json" }
        doFirst {
            val value=groovy.json.JsonSlurper().parseText(profile.readText()) as? Map<*,*> ?: error("Invalid public profile")
            require(value.keys==setOf("version","purpose","origin","certificate_pem","public_key") &&
                value["purpose"]=="nova-directory-bootstrap" && !profile.readText().contains("PRIVATE KEY")) { "Only public Directory trust material may be packaged" }
        }
    }
    android.sourceSets["main"].assets.srcDir(generated)
    tasks.named("preBuild").configure { dependsOn(prepare) }
}
dependencies {
    implementation("androidx.media3:media3-exoplayer:1.9.4")
    implementation("androidx.media3:media3-ui:1.9.4")
    implementation("org.bouncycastle:bcprov-jdk15to18:1.86")
    implementation("org.conscrypt:conscrypt-android:2.7.0")
    implementation("com.wireguard.android:tunnel:1.0.20260102")
    // Compile-only research gate; normal builds keep unimplemented providers disabled.
    nativeProofAar?.let { aar ->
        require(file(aar).isFile) { "Native proof AAR was not built" }
        implementation(files(aar))
    }
}
