plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
val nativeProofAar = providers.gradleProperty("novaNativeProofAar").orNull
val directoryProfile = providers.gradleProperty("novaDirectoryProfile").orNull
val wireGuardProof = providers.gradleProperty("novaWireGuardProof").orNull == "true"
val tailscaleProof = providers.gradleProperty("novaTailscaleProof").orNull == "true"
require(!wireGuardProof || nativeProofAar == null) { "Network and combined-runtime proofs are separate variants" }
require(!tailscaleProof || (nativeProofAar != null && !wireGuardProof)) { "Tailscale requires the pinned combined AAR" }
val distributionCode = providers.gradleProperty("novaVersionCode").orElse("9").get().toInt()
require(distributionCode >= 9) { "Distribution version codes must not go backwards" }
android {
    namespace = "com.novacinema.connect"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.novacinema.connect.poc"; minSdk = 26; targetSdk = 35
        versionCode = distributionCode; versionName = providers.gradleProperty("novaVersionName").orElse("0.9-m4-lan").get()
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
    if (wireGuardProof) {
        defaultConfig { testInstrumentationRunner = "com.novacinema.connect.WireGuardNetworkInstrumentation" }
        sourceSets["androidTest"].java.srcDir("../wireguard-proof/src/androidTest/kotlin")
        sourceSets["debug"].java.srcDir("../wireguard-proof/src/debug/kotlin")
        sourceSets["debug"].manifest.srcFile("../wireguard-proof/src/debug/AndroidManifest.xml")
    }
    if (tailscaleProof) {
        defaultConfig { testInstrumentationRunner = "com.novacinema.connect.TailscaleNetworkInstrumentation" }
        sourceSets["debug"].java.srcDir("../tailscale-native/src/main/kotlin")
        sourceSets["debug"].java.srcDir("../tailscale-native/src/debug/kotlin")
        sourceSets["debug"].manifest.srcFile("../tailscale-native/src/debug/AndroidManifest.xml")
        sourceSets["androidTest"].java.srcDir("../tailscale-native/src/androidTest/kotlin")
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
if (tailscaleProof) {
    val policyClasses = layout.buildDirectory.dir("tailscalePolicyChecks")
    val compilePolicy = tasks.register<JavaCompile>("compileTailscalePolicyChecks") {
        dependsOn("compileDebugKotlin")
        source(fileTree("../tailscale-native/src/policyTest/java") { include("**/*.java") })
        classpath = files(layout.buildDirectory.dir("tmp/kotlin-classes/debug")) + configurations.getByName("debugRuntimeClasspath")
        destinationDirectory.set(policyClasses)
        sourceCompatibility = "17"; targetCompatibility = "17"
    }
    tasks.register<JavaExec>("verifyTailscalePolicy") {
        dependsOn(compilePolicy)
        classpath = files(policyClasses, layout.buildDirectory.dir("tmp/kotlin-classes/debug")) +
            configurations.getByName("debugRuntimeClasspath")
        mainClass.set("com.novacinema.connect.TailscalePolicyChecks")
    }
}
